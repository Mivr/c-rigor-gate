"""The `sim` step of `rigor grade` (T2G2): registration, collection of the run outputs into the layout `rigor sim` reads,
the skip rules, the retried build, the salt on the Buck2 command line, and the judge run in process."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_pipeline, grade_sim, verdict
from rigor_lib.errors import InternalError
from tests import test_sim_judge_helpers as h
from tests.helpers import GATE_DIR, TempDirTestCase

LABEL = "root//p:sim"
SAN = ("verdict", "report", "stats", "hashes")


class Registration(unittest.TestCase):
    def test_it_is_registered_after_fuzz_and_needs_the_toolchain(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("fuzz") + 1], "sim")
        self.assertTrue(getattr(dict(grade_pipeline.GATES)["sim"], "needs_toolchain", False))
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt")), ids)


def outputs_in(tree, platform, names):
    result = {}
    for name in names:
        path = tree / "buck-out" / platform / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
        result[name] = ["buck-out/%s/%s" % (platform, name)]
    return result


class Collect(TempDirTestCase):
    def built(self, skip_release=False, label=LABEL, missing=None):
        tree = self.sub("tree")
        san = outputs_in(tree, "san", [n for n in SAN if n != missing])
        release = {} if skip_release else outputs_in(tree, "release", ("hashes",))
        ok = {"success": "SUCCESS"}
        return str(tree), ({label: dict(ok, outputs=san)}, {label: dict(ok, outputs=release)})

    def test_a_built_target_gets_its_files_and_an_index(self):
        tree, built = self.built()
        directory = str(self.tmp / "sim")
        failed, index = grade_sim.collect(tree, [LABEL], built, directory)
        self.assertEqual((failed, index), ([], {"//p:sim": "t000"}))
        self.assertEqual(sorted(os.listdir(directory)), ["index.json", "t000.hashes", "t000.release.hashes", "t000.report",
                                                         "t000.stats.json", "t000.verdict"])
        self.assertEqual((self.tmp / "sim" / "t000.release.hashes").read_text(), "hashes")
        self.assertEqual(json.loads((self.tmp / "sim" / "index.json").read_text()), {"//p:sim": "t000"})

    def test_a_missing_output_in_either_platform_or_a_failed_build_fails_that_target_only(self):
        for case in ({"skip_release": True}, {"missing": "stats"}):
            with self.subTest(case=case):
                tree, built = self.built(**case)
                failed, index = grade_sim.collect(tree, [LABEL, "root//p:none"], built, str(self.tmp / ("o" + "".join(case))))
                self.assertEqual((failed, index), ([LABEL, "root//p:none"], {}))

    def test_a_build_that_failed(self):
        tree, built = self.built()
        built[0][LABEL]["success"] = "FAIL"
        self.assertEqual(grade_sim.collect(tree, [LABEL], built, str(self.tmp / "o"))[0], [LABEL])

    def test_an_output_outside_buck_out_is_exit_2(self):
        tree, built = self.built()
        built[0][LABEL]["outputs"]["verdict"] = ["../elsewhere"]
        with self.assertRaises(InternalError):
            grade_sim.collect(tree, [LABEL], built, str(self.tmp / "o"))


class Step(TempDirTestCase):
    POLICY = '[global]\ndeny = []\n'

    def grading(self, policy_text=POLICY, status=None, role="implementer", salt=None, uncached=False):
        product = self.sub("product") / "product.toml"
        (self.sub("product") / "policy.toml").write_text(policy_text, encoding="utf-8")
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\nrole = "%s"\n' % role, encoding="utf-8")
        if salt is not None:
            (self.sub("work") / "inputs").mkdir(exist_ok=True)
            (self.sub("work") / "inputs" / "sim-salt").write_text(salt)
        args = SimpleNamespace(product=str(product), uncached=uncached, task=str(task))
        done = {k: "PASS" for k in grade_sim.REQUIRED}
        done.update(status or {})
        return SimpleNamespace(args=args, work=str(self.sub("work")), tree=str(self.sub("tree")), status=done, facts=None)

    def test_it_does_not_run_unless_the_tree_built_and_every_test_passed(self):
        for gate in grade_sim.REQUIRED:
            with mock.patch.object(grade_sim, "_step") as step:
                self.assertIsNone(grade_sim.sim_gate_step(self.grading(status={gate: "FAIL"})), gate)
                step.assert_not_called()

    def test_test_author_is_not_applicable(self):
        result = grade_sim.sim_gate_step(self.grading(role="test-author"))
        self.assertEqual((result.status, result.findings[0]["rule"], result.findings[0]["severity"]),
                         ("PASS", "not-applicable", "info"))

    def test_no_targets_and_nothing_required_passes_with_info(self):
        with mock.patch.object(grade_sim.grade_build, "run_buck", return_value=(0, "", "")):
            result = grade_sim.sim_gate_step(self.grading())
        self.assertEqual((result.status, [f["rule"] for f in result.findings], result.metadata), ("PASS", ["no-sim-targets"], {"targets": {}}))

    def test_a_query_that_failed(self):
        with mock.patch.object(grade_sim.grade_build, "run_buck", return_value=(1, "", "boom")):
            result = grade_sim.sim_gate_step(self.grading())
        self.assertEqual(([f["rule"] for f in result.findings], result.metadata["stderr_tail"]), (["query-failed"], "boom"))

    def test_a_required_sim_with_no_target_is_missing(self):
        facts = SimpleNamespace(directory=str(h.facts(self.tmp / "facts", sims=())))
        with mock.patch.object(grade_sim.grade_build, "run_buck", return_value=(0, "", "")), \
                mock.patch.object(grade_sim.grade_checks, "build_facts", return_value=facts):
            result = grade_sim.sim_gate_step(self.grading(self.POLICY + "[sim]\nrequired = true\n"))
        self.assertEqual(([f["rule"] for f in result.findings], result.status), (["sim-missing-target"], "FAIL"))

    def test_facts_that_did_not_build_is_not_run(self):
        with mock.patch.object(grade_sim.grade_build, "run_buck", return_value=(0, "", "")), \
                mock.patch.object(grade_sim.grade_checks, "build_facts", return_value="query failed"):
            self.assertIsNone(grade_sim.sim_gate_step(self.grading(self.POLICY + "[sim]\nrequired = true\n")))

    def test_the_salt_is_a_config_of_both_builds_and_a_target_that_did_not_build_is_reported_once(self):
        facts = SimpleNamespace(directory=str(h.facts(self.tmp / "facts")))
        calls = []

        def fake_buck(tree, args):
            calls.append(args)
            if args[0] == "uquery":
                return 0, LABEL + "\n", ""
            return 1, "", "compile error"

        with mock.patch.object(grade_sim.grade_build, "run_buck", side_effect=fake_buck), \
                mock.patch.object(grade_sim.grade_build, "action_counts", return_value=(3, 4)), \
                mock.patch.object(grade_sim.grade_build, "read_report", return_value={}), \
                mock.patch.object(grade_sim.grade_checks, "build_facts", return_value=facts):
            result = grade_sim.sim_gate_step(self.grading(salt="0102\n", uncached=True))
        builds = [c for c in calls if c[0] == "build"]
        self.assertEqual([c[c.index("--target-platforms") + 1] for c in builds], [grade_sim.SAN, grade_sim.RELEASE])
        for call in builds:
            self.assertIn("--no-remote-cache", call)
            self.assertEqual(call[call.index("-c") + 1], "rigor.sim_salt=0102")
        self.assertEqual([f["rule"] for f in result.findings], ["sim-build-failed"])
        self.assertEqual((result.metadata["executed_actions"], result.metadata["cached_actions"], result.metadata["exit_code"]), (6, 8, 1))

    def test_without_a_salt_no_config_is_passed(self):
        facts = SimpleNamespace(directory=str(h.facts(self.tmp / "facts")))
        calls = []

        def fake_buck(tree, args):
            calls.append(args)
            return (0, LABEL + "\n", "") if args[0] == "uquery" else (1, "", "")

        with mock.patch.object(grade_sim.grade_build, "run_buck", side_effect=fake_buck), \
                mock.patch.object(grade_sim.grade_build, "action_counts", return_value=(0, 0)), \
                mock.patch.object(grade_sim.grade_build, "read_report", return_value={}), \
                mock.patch.object(grade_sim.grade_checks, "build_facts", return_value=facts):
            grade_sim.sim_gate_step(self.grading())
        self.assertTrue(all("-c" not in c and "--no-remote-cache" not in c for c in calls if c[0] == "build"))

    def test_a_transport_failure_is_retried_once(self):
        facts = SimpleNamespace(directory=str(h.facts(self.tmp / "facts")))
        builds = []

        def fake_buck(tree, args):
            if args[0] == "uquery":
                return 0, LABEL + "\n", ""
            builds.append(args)
            return 1, "", "h2 protocol error"

        with mock.patch.object(grade_sim.grade_build, "run_buck", side_effect=fake_buck), \
                mock.patch.object(grade_sim.grade_build, "action_counts", return_value=(0, 0)), \
                mock.patch.object(grade_sim.grade_build, "read_report", return_value={}), \
                mock.patch.object(grade_sim.grade_checks, "build_facts", return_value=facts):
            grade_sim.sim_gate_step(self.grading())
        self.assertEqual(len(builds), 4)   # san and release, each twice
