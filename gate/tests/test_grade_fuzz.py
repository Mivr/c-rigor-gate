"""The `fuzz` step of `rigor grade` (T129): collection of the run outputs into the layout `rigor fuzz` reads, the skip
rules, the transport retry, and the judge run in process."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_fuzz, grade_mutants, grade_pipeline, verdict
from rigor_lib.errors import InternalError
from tests import test_fuzz_gate_helpers as h
from tests.helpers import GATE_DIR, TempDirTestCase

LABEL = "root//p:fz"
SUBS = ("verdict", "report", "crash", "stats", "replayed")


class Registration(unittest.TestCase):
    def test_it_is_registered_after_tests_stub_and_needs_the_toolchain(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("tests-stub") + 1], "fuzz")
        step = dict(grade_pipeline.GATES)["fuzz"]
        self.assertTrue(getattr(step, "needs_toolchain", False))
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt")), ids)

    def test_labels(self):
        self.assertEqual(grade_fuzz.facts_label(LABEL), "//p:fz")


class Collect(TempDirTestCase):
    def tree_with_outputs(self, missing=None):
        tree = self.sub("tree")
        outputs = {}
        for name in SUBS:
            path = tree / "buck-out" / "art" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
            outputs[name] = ["buck-out/art/" + name]
        if missing:
            del outputs[missing]
        return str(tree), outputs

    def test_a_built_target_gets_its_five_files_and_an_index(self):
        tree, outputs = self.tree_with_outputs()
        directory = str(self.tmp / "fuzz")
        failed, index = grade_fuzz.collect(tree, [LABEL], {LABEL: {"success": "SUCCESS", "outputs": outputs}}, directory)
        self.assertEqual((failed, index), ([], {"//p:fz": "t000"}))
        self.assertEqual(sorted(os.listdir(directory)),
                         ["index.json", "t000.crash", "t000.replayed", "t000.report", "t000.stats.json", "t000.verdict"])
        self.assertEqual(json.loads((self.tmp / "fuzz" / "index.json").read_text()), {"//p:fz": "t000"})

    def test_a_missing_output_or_a_failed_build_is_a_failure_of_that_target_only(self):
        tree, outputs = self.tree_with_outputs(missing="stats")
        results = {LABEL: {"success": "SUCCESS", "outputs": outputs}, "root//p:gone": {"success": "FAIL"}}
        failed, index = grade_fuzz.collect(tree, [LABEL, "root//p:gone", "root//p:none"], results, str(self.tmp / "fuzz"))
        self.assertEqual((failed, index), ([LABEL, "root//p:gone", "root//p:none"], {}))

    def test_an_output_outside_buck_out_is_exit_2(self):
        tree, outputs = self.tree_with_outputs()
        outputs["verdict"] = ["../elsewhere"]
        with self.assertRaises(InternalError):
            grade_fuzz.collect(tree, [LABEL], {LABEL: {"success": "SUCCESS", "outputs": outputs}}, str(self.tmp / "fuzz"))


class Step(TempDirTestCase):
    POLICY_NONE = '[global]\ndeny = []\n[module."//p:parse"]\nlevel = "L3"\n'
    POLICY_FUZZ = '[global]\ndeny = []\n[module."//p:parse"]\nlevel = "L3"\nprofile = ["parser"]\n'

    def grading(self, policy_text, status=None, role="implementer"):
        product = self.sub("product") / "product.toml"
        (self.sub("product") / "policy.toml").write_text(policy_text, encoding="utf-8")
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\nrole = "%s"\n' % role, encoding="utf-8")
        args = SimpleNamespace(product=str(product), uncached=False, task=str(task))
        done = {k: "PASS" for k in grade_fuzz.REQUIRED}
        done.update(status or {})
        return SimpleNamespace(args=args, work=str(self.sub("work")), tree=str(self.sub("tree")), status=done,
                               facts=None)

    def test_it_does_not_run_unless_the_tree_built_and_every_test_passed(self):
        for gate in grade_fuzz.REQUIRED:
            with mock.patch.object(grade_fuzz, "_step") as step:
                self.assertIsNone(grade_fuzz.fuzz_gate_step(self.grading(self.POLICY_NONE, {gate: "FAIL"})), gate)
                step.assert_not_called()

    def test_test_author_is_not_applicable(self):
        result = grade_fuzz.fuzz_gate_step(self.grading(self.POLICY_FUZZ, role="test-author"))
        self.assertEqual((result.status, result.findings[0]["rule"], result.findings[0]["severity"]),
                         ("PASS", "not-applicable", "info"))

    def test_no_targets_and_nothing_required_passes_with_info(self):
        with mock.patch.object(grade_fuzz.grade_build, "run_buck", return_value=(0, "", "")):
            result = grade_fuzz.fuzz_gate_step(self.grading(self.POLICY_NONE))
        self.assertEqual((result.status, [f["rule"] for f in result.findings]), ("PASS", ["no-fuzz-targets"]))

    def test_a_required_module_without_a_target_is_fuzz_missing(self):
        g = self.grading(self.POLICY_FUZZ)
        facts = SimpleNamespace(directory=str(h.default_facts(self.tmp / "facts", with_target=False)))
        with mock.patch.object(grade_fuzz.grade_build, "run_buck", return_value=(0, "", "")), \
                mock.patch.object(grade_fuzz.grade_checks, "build_facts", return_value=facts), \
                mock.patch.object(grade_fuzz.grade_context, "kill_daemon"):
            result = grade_fuzz.fuzz_gate_step(g)
        self.assertEqual([f["rule"] for f in result.findings], ["fuzz-missing"])

    def test_facts_that_did_not_build_is_not_run(self):
        with mock.patch.object(grade_fuzz.grade_build, "run_buck", return_value=(0, "", "")), \
                mock.patch.object(grade_fuzz.grade_checks, "build_facts", return_value="query failed"), \
                mock.patch.object(grade_fuzz.grade_context, "kill_daemon"):
            self.assertIsNone(grade_fuzz.fuzz_gate_step(self.grading(self.POLICY_FUZZ)))


class MutantsLayout(unittest.TestCase):
    """The libFuzzer binary of a `c_fuzz` is no module for the mutants gate (no `level-missing`); a product binary is."""

    def layout(self, sim=()):
        def fake_buck(tree, args):
            query = args[1]
            if query.startswith("kind(ctest_results"):
                return 0, "{}", ""
            if query.startswith("kind('^(cxx_library"):
                return 0, json.dumps({"root//p:fz__bin": {"deps": []}, "root//p:tool": {"deps": []}}), ""
            if query == "kind(cxx_binary, //...)":
                return 0, "root//p:fz__bin\nroot//p:tool\n" + "".join("%s\n" % b for b in sim), ""
            if query == "kind(fuzz_run, //...)":
                self.assertEqual(args[2:], ["--output-format", "json", "--output-attribute", "^binary$"])
                return 0, json.dumps({"root//p:fz": {"binary": "root//p:fz__bin"}}), ""
            if query == "kind(sim_run, //...)":   # T2G1: the binary behind a `c_sim` is no module either
                self.assertEqual(args[2:], ["--output-format", "json", "--output-attribute", "^binary$"])
                return 0, json.dumps({"root//p:s__shard0": {"binary": "root//p:s__bin"}}), ""
            raise AssertionError(args)
        run = SimpleNamespace(tree="t")
        with mock.patch.object(grade_mutants.grade_build, "run_buck", side_effect=fake_buck):
            return grade_mutants.read_layout(run)

    def test_the_fuzz_binary_is_left_out_and_another_binary_stays(self):
        self.assertEqual(self.layout().binaries, frozenset({"//p:tool"}))

    def test_the_sim_binary_is_left_out_too(self):
        self.assertEqual(self.layout(sim=["root//p:s__bin"]).binaries, frozenset({"//p:tool"}))


class Retry(TempDirTestCase):
    def grading(self):
        return SimpleNamespace(args=SimpleNamespace(uncached=True), work=str(self.sub("work")), tree=str(self.sub("tree")))

    def run_with(self, replies, report_ok):
        calls = []

        def fake_buck(tree, args):
            calls.append(args)
            return replies.pop(0)
        results = {LABEL: {"success": "SUCCESS" if report_ok else "FAIL"}}
        with mock.patch.object(grade_fuzz.grade_build, "run_buck", side_effect=fake_buck), \
                mock.patch.object(grade_fuzz.grade_build, "action_counts", return_value=(2, 1)), \
                mock.patch.object(grade_fuzz.grade_build, "read_report", return_value=results):
            out = grade_fuzz.build_targets(self.grading(), [LABEL])
        return out, calls

    def test_a_transport_failure_with_an_unbuilt_target_is_retried_once(self):
        (results, code, _, executed, cached), calls = self.run_with(
            [(1, "", "h2 protocol error"), (1, "", "h2 protocol error")], False)
        self.assertEqual((code, executed, cached, len(calls)), (1, 4, 2, 2))
        self.assertIn("--no-remote-cache", calls[0])
        self.assertIn("toolchains//:linux_fuzz", calls[0])

    def test_any_other_failure_is_not_retried(self):
        _, calls = self.run_with([(1, "", "error: compile failed")], False)
        self.assertEqual(len(calls), 1)

    def test_a_clean_build_is_one_call(self):
        _, calls = self.run_with([(0, "", "")], True)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
