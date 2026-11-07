"""The witness gates of `rigor grade` (T039) without Buck2: scope, tree assembly, renames, redaction and reuse.

`selftest/grade.sh` runs them for real; here the build, the layout query and the mutants run are replaced.
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import approvals, grade_context, grade_steps, grade_witness, jsonio, product_layout
from rigor_lib import witness_bundle
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from tests.helpers import Repo, TempDirTestCase

POLICY = ('[module."//core:core"]\nlevel = "L3"\nimpl = ["core/core.c"]\n'
          '[module."//util:util"]\nlevel = "L2"\nimpl = ["util/util.c"]\n')
BUILD_CONFIG = b"[buck2_re_client]\nengine_address = a\n\n[http]\n  x = 1\n"
SHA = "0123456789abcdef0123456789abcdef01234567"


def bundle(files, modules=("//core:core",), product="p"):
    entries = {label: witness_bundle.ModuleEntry(label, "A001", SHA) for label in modules}
    items = tuple(sorted((witness_bundle.WitnessFile(p, d) for p, d in files.items()), key=lambda f: f.path))
    return witness_bundle.Bundle(product, entries, items, "0" * 64)


def layout():
    from rigor_lib import grade_mutants
    return grade_mutants.Layout(
        frozenset({"//core:core", "//util:util"}), frozenset(), frozenset({"//core:t", "//util:t"}),
        {"//core:core": (), "//util:util": ("//core:core",), "//core:t": ("//core:core",),
         "//util:t": ("//util:util",)})


class AssembledTree(TempDirTestCase):
    """`grade_steps.assemble_tree` with and without an overlay, over a real clone."""

    def setUp(self):
        super().setUp()
        repo = Repo(self.sub("src"))
        repo.write("core/BUCK", "b\n")
        repo.write("core/core.c", "head core\n")
        repo.write("core/core_test.c", "test\n")
        repo.write("util/util.c", "head util\n")
        self.head = repo.commit()
        config = 'name = "p"\n[layout]\ninclude = ["core/**", "util/**"]\n'
        (self.tmp / "product.toml").write_text(config, encoding="utf-8")
        self.g = SimpleNamespace(src=str(repo.root), head=self.head, gate_sha="g",
                                 product=product_layout.load_product(str(self.tmp / "product.toml")))
        self.patch = mock.patch("rigor_lib.grade_tree.copy_gate",
                                return_value=({"gate/x": "0" * 64}, BUILD_CONFIG))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def read(self, tree, path):
        return (self.tmp / tree / path).read_text(encoding="utf-8")

    def test_the_head_tree_is_what_assemble_always_made(self):
        found, manifest, full = grade_steps.assemble_tree(self.g, str(self.tmp / "head"))
        self.assertEqual(sorted(manifest), ["core/BUCK", "core/core.c", "core/core_test.c", "util/util.c"])
        self.assertEqual(self.read("head", "core/core.c"), "head core\n")
        self.assertEqual([f["rule"] for f in found], ["product-manifest"])
        self.assertIn(".buckconfig", full)

    def test_the_witness_replaces_only_the_impl_paths_of_the_listed_modules(self):
        witness = bundle({"core/core.c": b"witness core\n"})
        modules = {"//core:core": ["core/core.c"], "//util:util": ["util/util.c"]}
        _, manifest, _ = grade_steps.assemble_tree(self.g, str(self.tmp / "w"), (witness, modules))
        self.assertEqual(self.read("w", "core/core.c"), "witness core\n")
        self.assertEqual(self.read("w", "util/util.c"), "head util\n")   # not listed by the bundle: the head's
        self.assertEqual(self.read("w", "core/core_test.c"), "test\n")
        self.assertEqual(sorted(manifest), ["core/BUCK", "core/core.c", "core/core_test.c", "util/util.c"])

    def test_a_witness_equal_to_the_head_gives_the_head_manifest(self):
        _, head, _ = grade_steps.assemble_tree(self.g, str(self.tmp / "head"))
        witness = bundle({"core/core.c": b"head core\n"})
        _, same, _ = grade_steps.assemble_tree(self.g, str(self.tmp / "w"),
                                               (witness, {"//core:core": ["core/core.c"]}))
        self.assertEqual(head, same)

    def test_a_witness_file_the_layout_would_not_copy_is_exit_2(self):
        witness = bundle({"core/core.c": b"x\n", "elsewhere/core.c": b"y\n"})
        with self.assertRaises(InternalError):
            grade_steps.assemble_tree(self.g, str(self.tmp / "w"),
                                      (witness, {"//core:core": ["core/core.c", "elsewhere/core.c"]}))


class Setup(TempDirTestCase):
    def grading(self, witness=None, status=None, role="implementer"):
        work = self.sub("work")
        self.sub("work/results")
        (self.tmp / "task.toml").write_text('id = "t"\nallowed = ["**"]\nrole = "%s"\n' % role, encoding="utf-8")
        (self.sub("p") / "policy.toml").write_text(POLICY, encoding="utf-8")
        (self.tmp / "p" / "expected-tests.json").write_text('{"ids": ["a"]}', encoding="utf-8")
        args = SimpleNamespace(task=str(self.tmp / "task.toml"), product=str(self.tmp / "p" / "product.toml"),
                               uncached=False, approvals=None)
        done = {"assemble": "PASS", "buckfiles": "PASS"}
        done.update(status or {})
        return SimpleNamespace(args=args, work=str(work), tree=str(work / "tree"), results=str(work / "results"),
                               src="", base="b", head="h", witness=witness, status=done, built={})

    def patches(self, changed=("core/core_test.c",)):
        return (mock.patch.object(grade_witness, "_head_layout", return_value=layout()),
                mock.patch.object(grade_witness, "_changed_paths", return_value=list(changed)),
                mock.patch("rigor_lib.grade_context.kill_daemon"))


class WitnessTests(Setup):
    def run_gate(self, g, changed=("core/core_test.c",)):
        one, two, kill = self.patches(changed)
        with one, two, kill as killed:
            result = grade_witness.witness_tests_gate(g)
        return result, killed

    def test_it_waits_for_a_trustworthy_layout(self):
        for gate in ("assemble", "buckfiles"):
            for value in ("FAIL", None):
                self.assertIsNone(grade_witness.witness_tests_gate(self.grading(status={gate: value})))

    def test_role_test_author_needs_the_previous_expected_list_before_any_build(self):
        g = self.grading(role="test-author")
        with self.assertRaisesRegex(InternalError, "expected-tests.previous.json"):
            grade_steps.check_witness_inputs(g)
        (self.tmp / "p" / "expected-tests.previous.json").write_text('{"ids": []}', encoding="utf-8")
        grade_steps.check_witness_inputs(g)   # the T039 refusal of the role is gone
        for role in ("implementer", "audit"):
            grade_steps.check_witness_inputs(self.grading(role=role))   # no previous list needed

    def test_role_test_author_judges_the_stubbed_module_against_its_witness(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}), role="test-author")
        with mock.patch.object(grade_witness, "_build_and_judge", return_value="built") as build:
            result, _ = self.run_gate(g, changed=("core/core.c",))   # a stub: impl only
        self.assertEqual(result, "built")
        self.assertEqual(build.call_args.args[2], ["//core:core"])
        self.assertEqual(g.witness_state.judged, ["//core:core"])

    def test_role_test_author_with_nothing_in_scope_is_no_new_tests(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}), role="test-author")
        with mock.patch.object(grade_steps, "assemble_tree") as tree:
            result, _ = self.run_gate(g, changed=("README",))
        tree.assert_not_called()
        self.assertEqual(result.status, "FAIL")
        self.assertEqual([(f["rule"], f["severity"]) for f in result.findings if f["severity"] == "error"],
                         [("no-new-tests", "error")])
        self.assertEqual(result.metadata["scope"], [])

    def test_role_test_author_without_a_bundle_entry_is_witness_missing_even_at_l2(self):
        for witness in (None, bundle({"core/core.c": b"x"})):
            g = self.grading(witness=witness, role="test-author")
            with mock.patch.object(grade_steps, "assemble_tree") as tree:
                result, _ = self.run_gate(g, changed=("util/util.c",))   # the L2 module was stubbed
            tree.assert_not_called()
            self.assertEqual(result.status, "FAIL")
            self.assertEqual([(f["rule"], f["severity"], f["module"]) for f in result.findings
                              if f["rule"] == "witness-missing"], [("witness-missing", "error", "//util:util")])

    def test_nothing_in_scope_is_a_pass_that_builds_nothing(self):
        g = self.grading()
        with mock.patch.object(grade_steps, "assemble_tree") as tree:
            result, _ = self.run_gate(g, changed=("core/core.c",))   # a pure impl change
        tree.assert_not_called()
        self.assertEqual(result.status, "PASS")
        self.assertEqual([f["rule"] for f in result.findings], ["witness-scope"])
        self.assertEqual(result.metadata["scope"], [])
        self.assertEqual(g.witness_state.judged, [])

    def test_a_module_in_scope_without_a_bundle_entry_is_witness_missing(self):
        g = self.grading(witness=None)
        with mock.patch.object(grade_steps, "assemble_tree") as tree:
            result, _ = self.run_gate(g)
        tree.assert_not_called()
        self.assertEqual(result.status, "FAIL")
        missing = [f for f in result.findings if f["rule"] == "witness-missing"]
        self.assertEqual([(f["module"], f["severity"]) for f in missing], [("//core:core", "error")])

    def test_witness_missing_is_info_at_l2(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}))
        result, _ = self.run_gate(g, changed=("util/util_test.c",))
        self.assertEqual(result.status, "PASS")
        self.assertEqual([(f["rule"], f["severity"], f["module"]) for f in result.findings
                          if f["rule"] == "witness-missing"], [("witness-missing", "info", "//util:util")])

    def test_an_l3_module_without_impl_paths_is_impl_missing(self):
        g = self.grading()
        (self.tmp / "p" / "policy.toml").write_text(POLICY.replace('impl = ["core/core.c"]\n', ""), encoding="utf-8")
        result, _ = self.run_gate(g, changed=("core/core.c",))
        self.assertEqual(result.status, "FAIL")
        self.assertIn(("impl-missing", "//core:core"), [(f["rule"], f.get("module")) for f in result.findings])

    def assembled(self, manifest):
        return mock.patch.object(grade_steps, "assemble_tree", return_value=([], manifest, {}))

    def write_head_manifest(self, g, sha):
        document = {"findings": [finding("product-manifest", "info", sha256=sha)]}
        with open(os.path.join(g.results, "assemble.json"), "wb") as handle:
            handle.write(jsonio.canonical_dumps(document))

    def test_a_witness_equal_to_the_head_reuses_the_head_results_with_zero_actions(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}))
        manifest = {"core/core.c": "a" * 64}
        self.write_head_manifest(g, jsonio.sha256_hex(jsonio.canonical_dumps(manifest)))
        g.built = {"release": "R", "san": "S"}
        verdicts = [GateResult("tests", [finding("test-not-pass", id="t.a", status="fail")], {}),
                    GateResult("tests", [], {})]
        with self.assembled(manifest), mock.patch("rigor_lib.tests_gate.run", side_effect=verdicts) as judge, \
                mock.patch("rigor_lib.grade_build.build_tree") as build:
            result, _ = self.run_gate(g)
        build.assert_not_called()
        self.assertEqual([c.args[0].results for c in judge.call_args_list], ["R", "S"])
        self.assertTrue(g.witness_state.equals_head)
        rules = {(f["rule"], f.get("mode")) for f in result.findings}
        self.assertIn(("witness-test-not-pass", "release"), rules)
        self.assertIn(("witness-equals-head", None), rules)
        self.assertEqual((result.metadata["executed_actions"], result.metadata["cached_actions"]), (0, 0))

    def test_a_different_witness_is_built_in_its_own_tree_and_judged_in_both_modes(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}))
        self.write_head_manifest(g, "f" * 64)
        built = GateResult("build", [], {"executed_actions": 5, "cached_actions": 7, "release": {}, "san": {}})

        def fake_build(run, uncached):
            run.built.update(release="R", san="S")
            return built
        with self.assembled({"core/core.c": "a" * 64}), \
                mock.patch("rigor_lib.grade_build.build_tree", side_effect=fake_build) as build, \
                mock.patch("rigor_lib.tests_gate.run", return_value=GateResult("tests", [], {})) as judge:
            result, killed = self.run_gate(g)
        run = build.call_args.args[0]
        self.assertEqual(run.tree, os.path.join(g.work, grade_context.WITNESS_TREE))
        self.assertEqual(len(judge.call_args_list), 2)
        self.assertEqual(result.status, "PASS")
        self.assertEqual((result.metadata["executed_actions"], result.metadata["cached_actions"]), (5, 7))
        self.assertFalse(g.witness_state.equals_head)
        killed.assert_not_called()   # the witness's daemon lives on for mutants-witness

    def test_a_failed_witness_build_is_witness_build_failed_without_compiler_output(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}))
        self.write_head_manifest(g, "f" * 64)
        built = GateResult("build", [finding("build-failed", mode="release", target="root//core:t_results")],
                           {"executed_actions": 1, "cached_actions": 0, "release": {"stderr_tail": "SECRET LINE"}})
        with self.assembled({"core/core.c": "a" * 64}), \
                mock.patch("rigor_lib.grade_build.build_tree", return_value=built), \
                mock.patch("rigor_lib.tests_gate.run") as judge:
            result, killed = self.run_gate(g)
        judge.assert_not_called()
        self.assertEqual(result.status, "FAIL")
        failed = [f for f in result.findings if f["rule"] == "witness-build-failed"]
        self.assertEqual([(f["mode"], f["kind"]) for f in failed], [("release", "build-failed")])
        self.assertNotIn("SECRET", json.dumps(result.metadata))
        self.assertIn(mock.call(os.path.join(g.work, grade_context.WITNESS_TREE)), killed.call_args_list)


class MutantsWitness(Setup):
    def state(self, g, judged=("//core:core",), equals_head=False):
        from rigor_lib import grade_build
        run = grade_build.TreeRun(os.path.join(g.work, "tree-witness"), os.path.join(g.work, "witness"),
                                  mutants_reports=os.path.join(g.work, "witness", "mutants-reports"))
        lay = layout()
        lay = type(lay)(lay.libs, lay.binaries, lay.tests, lay.deps)
        g.witness_state = grade_witness.State(list(judged), lay, {"//core:core": "L3", "//util:util": "L2"},
                                              run, equals_head)

    def gate(self, g):
        with mock.patch("rigor_lib.grade_context.kill_daemon") as killed:
            result = grade_witness.mutants_witness_gate(g)
        return result, killed

    def test_it_needs_witness_tests_to_pass(self):
        g = self.grading(status={"witness-tests": "FAIL"})
        self.state(g)
        self.assertIsNone(self.gate(g)[0])
        self.assertIsNone(self.gate(self.grading(status={"witness-tests": "PASS"}))[0])   # no state: never ran

    def test_an_empty_scope_is_a_pass(self):
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, judged=())
        result, _ = self.gate(g)
        self.assertEqual((result.status, [f["rule"] for f in result.findings]), ("PASS", ["witness-scope"]))

    SURVIVOR = {"module": "//core:core", "id": "m1", "file": "core/core.c", "line": 3, "function": "f",
                "operator": "op", "original": "a > 0", "replacement": "a >= 0"}

    def write_head_result(self, g, approvals_used=()):
        found = [finding("survivor", "info", **self.SURVIVOR), finding("survived-mutant", **self.SURVIVOR),
                 finding("survived-mutant", **dict(self.SURVIVOR, module="//util:util"))]
        summary = {"total": 3, "verdicts": {}, "operators": {}, "tce": {},
                   "survivors": [{"id": "m1", "at": "core/core.c:3", "operator": "op", "replacement": "a >= 0"}]}
        document = {"findings": found, "metadata": {"modules": {"//core:core": summary, "//util:util": summary},
                                                    "approvals_used": list(approvals_used)}}
        with open(os.path.join(g.results, "mutants.json"), "wb") as handle:
            handle.write(jsonio.canonical_dumps(document))

    def test_a_witness_equal_to_the_head_reuses_the_head_mutants_without_source_text(self):
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, equals_head=True)
        self.write_head_result(g)
        with mock.patch.object(grade_witness.grade_mutants, "write_package") as write:
            result, killed = self.gate(g)
        write.assert_not_called()
        self.assertEqual(result.status, "FAIL")
        rules = sorted((f["rule"], f.get("module")) for f in result.findings)
        self.assertEqual(rules, [("witness-equals-head", None), ("witness-scope", None),
                                 ("witness-survived-mutant", "//core:core"), ("witness-survivor", "//core:core")])
        self.assertNotIn("a >= 0", json.dumps([result.findings, result.metadata]))
        self.assertEqual(list(result.metadata["modules"]), ["//core:core"])
        self.assertEqual((result.metadata["executed_actions"], result.metadata["cached_actions"]), (0, 0))
        killed.assert_called_once_with(g.witness_state.run.tree)

    def test_a_head_result_that_used_an_approval_is_not_reused(self):
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, equals_head=True)
        self.write_head_result(g, approvals_used=["x"])
        with mock.patch.object(grade_witness.grade_mutants, "write_package", return_value="s") as write, \
                mock.patch.object(grade_witness.grade_mutants, "build_reports", return_value=([], {}, [])):
            result, _ = self.gate(g)
        write.assert_called_once()
        self.assertNotIn("witness-equals-head", [f["rule"] for f in result.findings])

    def test_it_mutates_the_witness_with_its_own_approval_kind_and_rule_names(self):
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g)
        judged = [dict(finding("witness-survived-mutant", **self.SURVIVOR))]
        summary = {"total": 1, "survivors": [{"id": "m1", "at": "x:1", "operator": "op", "replacement": "SRC"}]}
        calls = {}

        def fake_judge(grading, run, modules, built, kind, renames):
            calls.update(kind=kind, renames=renames, modules=[m.label for m in modules])
            return judged, {"//core:core": summary}, ["ap"]
        mutants = grade_witness.grade_mutants
        with mock.patch.object(mutants, "write_package", return_value="sha"), \
                mock.patch.object(mutants, "build_reports",
                                  return_value=([], {"executed_actions": 9, "cached_actions": 1,
                                                     "stderr_tail": "SECRET"}, [0])), \
                mock.patch.object(mutants, "judge", side_effect=fake_judge):
            result, _ = self.gate(g)
        self.assertEqual(calls["kind"], approvals.KIND_WITNESS_EQUIVALENT_MUTANT)
        self.assertEqual(calls["renames"], grade_witness.MUTANT_RENAMES)
        self.assertEqual(calls["modules"], ["//core:core"])
        dumped = json.dumps([result.findings, result.metadata])
        for secret in ("SECRET", "SRC", "a >= 0", "a > 0"):
            self.assertNotIn(secret, dumped)
        self.assertEqual(result.metadata["approvals_used"], ["ap"])
        self.assertEqual(result.metadata["executed_actions"], 9)
        self.assertEqual(result.status, "FAIL")


class Redaction(unittest.TestCase):
    def test_a_mutant_finding_loses_the_text_of_the_mutation_only(self):
        item = finding("survived-mutant", module="m", file="f.c", line=1, original="a", replacement="b")
        self.assertEqual(grade_witness.redact_finding(item),
                         finding("survived-mutant", module="m", file="f.c", line=1))

    def test_a_summary_loses_the_replacements_of_its_survivors(self):
        summary = {"total": 2, "survivors": [{"id": "x", "replacement": "r", "at": "f:1"}]}
        self.assertEqual(grade_witness.redact_summary(summary),
                         {"total": 2, "survivors": [{"id": "x", "at": "f:1"}]})


class BundleChecks(Setup):
    def test_a_bundle_for_another_product_or_outside_the_impl_paths_is_exit_2_before_any_build(self):
        g = self.grading(witness=bundle({"core/core.c": b"x"}, product="other"))
        g.product = SimpleNamespace(name="p")
        with self.assertRaises(InternalError):
            grade_steps.check_witness_inputs(g)
        g.witness = bundle({"core/other.c": b"x"}, product="p")
        with self.assertRaises(InternalError):
            grade_steps.check_witness_inputs(g)
        g.witness = bundle({"core/core.c": b"x"}, product="p")
        grade_steps.check_witness_inputs(g)   # a good bundle, and no bundle at all, are fine
        g.witness = None
        grade_steps.check_witness_inputs(g)


if __name__ == "__main__":
    unittest.main()
