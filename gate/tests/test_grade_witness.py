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
                               uncached=False, approvals=None, allowed_signers="signers")
        done = {"assemble": "PASS", "buckfiles": "PASS"}
        done.update(status or {})
        return SimpleNamespace(args=args, work=str(work), tree=str(work / "tree"), results=str(work / "results"),
                               src="", base="b", head="h", witness=witness, status=done, built={},
                               product_paths=["core/core.c", "core/core_test.c", "util/util.c"])

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

    def write_head_manifest(self, g, sha, files=None):
        """`assemble.json` of the head: the product manifest's sha256 and, per file, [path, sha256] (gate files too)."""
        listed = sorted(dict(files or {}, **{"gate/x": "0" * 64}).items())
        document = {"findings": [finding("product-manifest", "info", sha256=sha)],
                    "metadata": {"manifest": [list(item) for item in listed]}}
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
        self.assertEqual(g.witness_state.same, ())   # the head manifest listed no file here: nothing is called equal
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

    def test_the_modules_whose_witness_is_the_head_s_code_are_noted_for_mutants_witness(self):
        """A bundle with a rewritten core and a copy of the head's util: only util is "equal to the head"."""
        g = self.grading(witness=bundle({"core/core.c": b"x", "util/util.c": b"y"}, ("//core:core", "//util:util")))
        head = {"core/core.c": "c" * 64, "core/core_test.c": "7" * 64, "util/util.c": "b" * 64}
        self.write_head_manifest(g, "f" * 64, head)

        def fake_build(run, uncached):
            run.built.update(release="R", san="S")
            return GateResult("build", [], {"executed_actions": 1, "cached_actions": 0})
        with self.assembled(dict(head, **{"core/core.c": "a" * 64})), \
                mock.patch("rigor_lib.grade_build.build_tree", side_effect=fake_build) as build, \
                mock.patch("rigor_lib.tests_gate.run", return_value=GateResult("tests", [], {})) as judge:
            result, _ = self.run_gate(g, changed=("core/core_test.c", "util/util_test.c"))
        build.assert_called_once()                       # `witness-tests` is unchanged: the whole witness tree is built
        self.assertEqual(len(judge.call_args_list), 2)   # and every expected test judged on it, in both modes
        self.assertEqual(result.metadata["judged"], ["//core:core", "//util:util"])
        self.assertEqual(g.witness_state.same, ("//util:util",))
        self.assertFalse(g.witness_state.equals_head)

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


class EqualToHead(unittest.TestCase):
    """`modules_equal_to_head`: a module is the head's code only when its impl files are the head's, all of them."""
    GLOBS = {"//core:core": ["core/src/*.c"], "//util:util": ["util/util.c"]}
    HEAD = {"core/src/a.c": "1" * 64, "core/src/b.c": "2" * 64, "core/core_test.c": "9" * 64, "util/util.c": "3" * 64}

    def same(self, witness, head=None, globs=None):
        return grade_witness.modules_equal_to_head(self.HEAD if head is None else head, witness, globs or self.GLOBS)

    def test_the_same_paths_with_the_same_bytes_are_equal(self):
        self.assertEqual(self.same(dict(self.HEAD)), ("//core:core", "//util:util"))

    def test_one_differing_byte_makes_that_module_different_and_no_other(self):
        self.assertEqual(self.same(dict(self.HEAD, **{"core/src/b.c": "f" * 64})), ("//util:util",))

    def test_a_file_the_witness_lacks_makes_the_module_different(self):
        witness = {p: s for p, s in self.HEAD.items() if p != "core/src/b.c"}
        self.assertEqual(self.same(witness), ("//util:util",))

    def test_a_file_only_the_witness_has_makes_the_module_different(self):
        self.assertEqual(self.same(dict(self.HEAD, **{"core/src/extra.c": "4" * 64})), ("//util:util",))

    def test_the_same_bytes_under_another_name_are_different(self):
        witness = {"core/src/a.c": "2" * 64, "core/src/b.c": "1" * 64, "util/util.c": "3" * 64}
        self.assertEqual(self.same(witness), ("//util:util",))

    def test_a_module_without_any_file_is_never_equal(self):
        self.assertEqual(self.same({}, head={}), ())

    def test_files_outside_the_impl_paths_do_not_count(self):
        self.assertEqual(self.same(dict(self.HEAD, **{"core/core_test.c": "8" * 64, "new/x.c": "5" * 64})),
                         ("//core:core", "//util:util"))

    def test_only_the_modules_asked_about_are_answered(self):
        self.assertEqual(self.same(dict(self.HEAD), globs={"//util:util": ["util/util.c"]}), ("//util:util",))


class MutantsWitness(Setup):
    def state(self, g, judged=("//core:core",), equals_head=False, same=()):
        from rigor_lib import grade_build
        run = grade_build.TreeRun(os.path.join(g.work, "tree-witness"), os.path.join(g.work, "witness"),
                                  mutants_reports=os.path.join(g.work, "witness", "mutants-reports"))
        lay = layout()
        lay = type(lay)(lay.libs, lay.binaries, lay.tests, lay.deps)
        g.witness_state = grade_witness.State(list(judged), lay, {"//core:core": "L3", "//util:util": "L2"},
                                              run, equals_head, tuple(same))

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

    def write_head_result(self, g, approvals_used=(), modules=("//core:core", "//util:util"), status="FAIL"):
        found = [finding("survivor", "info", **self.SURVIVOR), finding("survived-mutant", **self.SURVIVOR),
                 finding("survived-mutant", **dict(self.SURVIVOR, module="//util:util"))]
        summary = {"total": 3, "verdicts": {}, "operators": {}, "tce": {},
                   "survivors": [{"id": "m1", "at": "core/core.c:3", "operator": "op", "replacement": "a >= 0"}]}
        document = {"findings": found, "metadata": {"modules": {label: summary for label in modules},
                                                    "approvals_used": list(approvals_used)}}
        g.status["mutants"] = status
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

        def fake_judge(grading, run, modules, built, kind, renames, extra_kinds, used_by_kind):
            calls.update(kind=kind, renames=renames, modules=[m.label for m in modules], extra_kinds=extra_kinds)
            used_by_kind[kind] = ["ap"]
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
        self.assertEqual(calls["extra_kinds"], {})   # a module that differs from the head: the witness kind alone
        self.assertEqual(result.metadata["head_approvals_accepted"], [])
        self.assertEqual(result.metadata["approvals_used_by_kind"], {approvals.KIND_WITNESS_EQUIVALENT_MUTANT: ["ap"]})
        dumped = json.dumps([result.findings, result.metadata])
        for secret in ("SECRET", "SRC", "a >= 0", "a > 0"):
            self.assertNotIn(secret, dumped)
        self.assertEqual(result.metadata["approvals_used"], ["ap"])
        self.assertEqual(result.metadata["executed_actions"], 9)
        self.assertEqual(result.status, "FAIL")


    BOTH = ("//core:core", "//util:util")

    def mutated(self, g):
        """Run the gate with the mutants run replaced; returns (result, labels handed to each step)."""
        seen = {}
        mutants = grade_witness.grade_mutants

        def fake_write(run, modules):
            seen["package"] = [m.label for m in modules]
            return "sha"

        def fake_build(run, uncached, modules):
            seen["built"] = [m.label for m in modules]
            return [], {"executed_actions": 4, "cached_actions": 0}, list(range(len(modules)))

        def fake_judge(grading, run, modules, built, kind, renames, extra_kinds, used_by_kind):
            seen["judged"] = [modules[i].label for i in built]
            seen["kind"], seen["extra_kinds"] = kind, extra_kinds
            found = [finding("witness-survived-mutant", **dict(self.SURVIVOR, module=modules[i].label)) for i in built]
            return found, {modules[i].label: {"total": 1, "survivors": []} for i in built}, []
        with mock.patch.object(mutants, "write_package", side_effect=fake_write), \
                mock.patch.object(mutants, "build_reports", side_effect=fake_build), \
                mock.patch.object(mutants, "judge", side_effect=fake_judge):
            result, _ = self.gate(g)
        return result, seen

    def survivors(self, result):
        return [f["module"] for f in result.findings if f["rule"] == "witness-survived-mutant"]

    def skipped(self, result):
        return [(f["module"], f["severity"], f["level"], f["judged_by"]) for f in result.findings
                if f["rule"] == "witness-module-equals-head"]

    def test_a_module_equal_to_the_head_that_the_head_gate_judged_is_not_mutated_again(self):
        """One changed module (core) and one byte-identical copy (util) with a surviving mutant. Before the rule the
        copy's survivor was a `witness-survived-mutant`; now only the changed module is mutated and judged."""
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, judged=self.BOTH)                      # before: nothing is known to be equal
        self.write_head_result(g)
        result, seen = self.mutated(g)
        self.assertEqual((seen["judged"], self.survivors(result)), (list(self.BOTH), list(self.BOTH)))
        self.assertEqual(self.skipped(result), [])

        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, judged=self.BOTH, same=("//util:util",))
        self.write_head_result(g, approvals_used=["head approval of a util mutant"])
        result, seen = self.mutated(g)
        self.assertEqual((seen["package"], seen["built"], seen["judged"]), (["//core:core"],) * 3)
        self.assertEqual(self.survivors(result), ["//core:core"])
        self.assertEqual(self.skipped(result), [("//util:util", "info", "L2", "mutants")])
        self.assertEqual(result.metadata["equal_to_head"], ["//util:util"])
        self.assertEqual(result.metadata["scope"], list(self.BOTH))
        self.assertEqual(list(result.metadata["modules"]), ["//core:core"])
        self.assertEqual(result.metadata["targets"].keys(), {"//core:core"})
        self.assertEqual(result.status, "FAIL")              # the changed module is judged exactly as before
        self.assertEqual((seen["extra_kinds"], result.metadata["head_approvals_accepted"]), ({}, []))

    def test_an_equal_module_is_still_mutated_when_the_head_gate_did_not_judge_it(self):
        """Role test-author: head `mutants` is not applicable (no module summaries). Skipping there would leave the
        module judged by nobody, so a weakened test of an untouched module would pass. Likewise a module whose head
        mutants did not build, a head gate that did not run, and no head result at all."""
        cases = {"not applicable (test-author)": dict(modules=(), status="PASS"),
                 "this module did not build on the head": dict(modules=("//core:core",)),
                 "the head gate did not run": dict(status=None)}
        for name, head in cases.items():
            with self.subTest(name):
                g = self.grading(status={"witness-tests": "PASS"}, role="test-author")
                self.state(g, judged=self.BOTH, same=("//util:util",))
                self.write_head_result(g, **head)
                result, seen = self.mutated(g)
                self.assertEqual(seen["judged"], list(self.BOTH))
                self.assertEqual(self.survivors(result), list(self.BOTH))
                self.assertEqual((self.skipped(result), result.metadata["equal_to_head"]), ([], []))
                # judged here, with the head's approval kind accepted too, for the identical module alone
                self.assertEqual(seen["kind"], approvals.KIND_WITNESS_EQUIVALENT_MUTANT)
                self.assertEqual(seen["extra_kinds"], {"//util:util": (approvals.KIND_EQUIVALENT_MUTANT,)})
                self.assertEqual(result.metadata["head_approvals_accepted"], ["//util:util"])
        g = self.grading(status={"witness-tests": "PASS", "mutants": "PASS"})   # a status, but no result file
        os.unlink(os.path.join(g.results, "mutants.json"))
        self.state(g, judged=self.BOTH, same=("//util:util",))
        result, seen = self.mutated(g)
        self.assertEqual((seen["judged"], self.skipped(result)), (list(self.BOTH), []))

    def test_when_every_module_is_equal_to_the_head_nothing_is_mutated_and_the_gate_says_which(self):
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, judged=self.BOTH, same=self.BOTH)
        self.write_head_result(g)
        with mock.patch.object(grade_witness.grade_mutants, "write_package") as write:
            result, killed = self.gate(g)
        write.assert_not_called()
        self.assertEqual(result.status, "PASS")
        self.assertEqual([m for m, _, _, _ in self.skipped(result)], list(self.BOTH))
        self.assertEqual((result.metadata["modules"], result.metadata["equal_to_head"]), ({}, list(self.BOTH)))
        killed.assert_called_once_with(g.witness_state.run.tree)

    def test_the_whole_tree_reuse_still_comes_first(self):
        g = self.grading(status={"witness-tests": "PASS"})
        self.state(g, equals_head=True, same=("//core:core",))
        self.write_head_result(g)
        result, _ = self.gate(g)
        rules = sorted({f["rule"] for f in result.findings})
        self.assertEqual(rules, ["witness-equals-head", "witness-scope", "witness-survived-mutant", "witness-survivor"])
        self.assertTrue(result.metadata["equals_head"])


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
