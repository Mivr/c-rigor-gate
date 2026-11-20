"""`rigor fuzz`: the findings, on hand-made facts and results."""

import json

from rigor_lib import fuzz_gate
from tests import test_fuzz_gate_helpers as h
from tests.helpers import GATE_DIR, TempDirTestCase, run_rigor


class FuzzGateTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.policy = h.policy_file(self.tmp / "policy.toml")
        self.facts = h.default_facts(self.tmp / "facts")
        self.results = self.tmp / "results"
        self.out = self.tmp / "out.json"

    def empty_results(self):
        self.results.mkdir()
        (self.results / "index.json").write_text("{}")

    def judge(self, code, regressions=None):
        args = ["fuzz", "--results", self.results, "--policy", self.policy, "--facts", self.facts, "--out", self.out]
        if regressions is not None:
            args += ["--regressions", regressions]
        outcome = run_rigor(args)
        self.assertExit(outcome, code)
        return outcome

    def test_a_passing_run_passes_with_the_info_for_an_empty_corpus(self):
        h.passing_results(self.results)
        self.judge(0)
        self.assertEqual(h.rules(self.out), ["fuzz-empty-corpus"])
        self.assertEqual(h.findings(self.out, "fuzz-empty-corpus")[0]["severity"], "info")

    def test_a_replayed_corpus_has_no_info(self):
        h.write_run(self.results, "fz", h.FUZZ, h.stats_doc(corpus_files=1, replayed=1), replayed=[h.SHA_A])
        self.judge(0)
        self.assertEqual(h.rules(self.out), [])

    def test_a_budget_crash(self):
        h.write_run(self.results, "fz", h.FUZZ, h.stats_doc(runs_done=16283, sha=h.SHA_A), verdict="fail rc=1",
                    report=h.CRASH_REPORT)
        self.judge(1)
        (crash,) = h.findings(self.out, "fuzz-crash")
        self.assertEqual((crash["target"], crash["phase"], crash["reproducer_sha256"], crash["top_frame"]),
                         (h.FUZZ, "budget", h.SHA_A, "parse_run p/parse.c:15:22"))

    def test_a_replay_crash(self):
        h.write_run(self.results, "fz", h.FUZZ, h.stats_doc(runs_done=0, corpus_files=2, replayed=1, phase="replay", sha=h.SHA_B),
                    verdict="fail rc=1", report=h.CRASH_REPORT, replayed=[h.SHA_A])
        self.judge(1)
        self.assertEqual(h.findings(self.out, "fuzz-crash")[0]["phase"], "replay")

    def test_a_failure_without_a_frame_has_an_empty_top_frame(self):
        h.write_run(self.results, "fz", h.FUZZ, h.stats_doc(runs_done=0), verdict="fail rc=77", report="fuzz: x\n")
        self.judge(1)
        self.assertEqual(h.findings(self.out, "fuzz-crash")[0]["top_frame"], "")

    def test_a_short_run_without_a_crash(self):
        h.passing_results(self.results, runs_done=199999)
        self.judge(1)
        self.assertIn("fuzz-short", h.rules(self.out))

    def test_the_policy_budget_is_what_a_run_must_reach(self):
        h.policy_file(self.policy, '[module."%s"]\nfuzz = true\nfuzz_runs = 1000\n' % h.LIB)
        h.passing_results(self.results, runs_done=1000)
        self.judge(0)
        h.policy_file(self.policy, '[module."%s"]\nfuzz = true\nfuzz_runs = 1001\n' % h.LIB)
        self.judge(1)

    def test_a_module_without_a_target_is_missing(self):
        h.write_facts(self.tmp / "f2", [h.facts_doc(h.LIB, "c_library", [h.unit(defined=["parse_run"])])])
        self.facts = self.tmp / "f2"
        self.empty_results()
        self.judge(1)
        (missing,) = h.findings(self.out, "fuzz-missing")
        self.assertEqual(missing["module"], h.LIB)

    def test_a_target_whose_harness_calls_nothing(self):
        self.facts = h.default_facts(self.tmp / "f3", calls=False)
        h.passing_results(self.results)
        self.judge(1)
        (nocall,) = h.findings(self.out, "fuzz-harness-no-call")
        self.assertEqual((nocall["target"], nocall["module"]), (h.FUZZ, h.LIB))

    def test_a_required_target_without_results(self):
        self.empty_results()
        self.judge(1)
        self.assertEqual(h.findings(self.out, "fuzz-not-run")[0]["target"], h.FUZZ)

    def test_a_regression_input_that_was_not_replayed(self):
        h.write_run(self.results, "fz", h.FUZZ, h.stats_doc(corpus_files=1, replayed=1), replayed=[h.SHA_A])
        reg = self.tmp / "reg.json"
        reg.write_text(json.dumps({h.FUZZ: [h.SHA_A, h.SHA_B]}))
        self.judge(1, reg)
        (missing,) = h.findings(self.out, "fuzz-regression-missing")
        self.assertEqual((missing["target"], missing["sha256"]), (h.FUZZ, h.SHA_B))

    def test_a_regression_list_for_a_vanished_target_is_missing_too(self):
        h.passing_results(self.results)
        reg = self.tmp / "reg.json"
        reg.write_text(json.dumps({"//p:gone": [h.SHA_A]}))
        self.judge(1, reg)
        self.assertEqual(h.findings(self.out, "fuzz-regression-missing")[0]["target"], "//p:gone")

    def test_findings_are_byte_identical_on_rerun_and_counts_are_metadata(self):
        h.write_run(self.results, "fz", h.FUZZ, h.stats_doc(runs_done=77, sha=h.SHA_A), verdict="fail rc=1", report=h.CRASH_REPORT)
        self.judge(1)
        first = self.out.read_bytes()
        self.judge(1)
        self.assertEqual(first, self.out.read_bytes())
        document = json.loads(first)
        self.assertEqual(document["metadata"]["targets"][h.FUZZ]["runs_done"], 77)
        self.assertNotIn("77", json.dumps(document["findings"]))

    def test_the_budget_constants_match_the_rules(self):
        self.assertEqual(h.default_budget_from_bzl(GATE_DIR.parent), (fuzz_gate.DEFAULT_RUNS, fuzz_gate.MAX_RUNS))
