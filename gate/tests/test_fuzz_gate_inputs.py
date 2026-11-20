"""`rigor fuzz` fails closed: every malformed or unexpected input is exit 2."""

import json

from tests import test_fuzz_gate_helpers as h
from tests.helpers import TempDirTestCase, run_rigor


class FuzzGateInputTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.policy = h.policy_file(self.tmp / "policy.toml")
        self.facts = h.default_facts(self.tmp / "facts")
        self.results = h.passing_results(self.tmp / "results")

    def run_gate(self, regressions=None):
        args = ["fuzz", "--results", self.results, "--policy", self.policy, "--facts", self.facts]
        if regressions is not None:
            args += ["--regressions", regressions]
        return run_rigor(args)

    def test_the_baseline_passes(self):
        self.assertExit(self.run_gate(), 0)

    def test_a_stray_file_in_the_results(self):
        (self.results / "stray.txt").write_text("x")
        self.assertExit(self.run_gate(), 2)

    def test_a_missing_index(self):
        (self.results / "index.json").unlink()
        self.assertExit(self.run_gate(), 2)

    def test_an_indexed_run_without_its_files(self):
        (self.results / "fz.report").unlink()
        (self.results / "fz.verdict").unlink()
        self.assertExit(self.run_gate(), 2)

    def test_stats_with_an_unknown_key(self):
        stats = h.stats_doc()
        stats["wall_seconds"] = 3
        (self.results / "fz.stats.json").write_text(json.dumps(stats))
        self.assertExit(self.run_gate(), 2)

    def test_stats_with_a_missing_key_a_bad_phase_or_a_bad_type(self):
        for mutate in (lambda s: s.pop("phase"), lambda s: s.update(phase="x"), lambda s: s.update(runs_done="1"),
                       lambda s: s.update(runs_done=True), lambda s: s.update(reproducer_sha256="zz"),
                       lambda s: s.update(replayed=5)):
            with self.subTest(mutate=mutate):
                stats = h.stats_doc()
                mutate(stats)
                (self.results / "fz.stats.json").write_text(json.dumps(stats))
                self.assertExit(self.run_gate(), 2)

    def test_a_bad_verdict(self):
        (self.results / "fz.verdict").write_text("passed\n")
        self.assertExit(self.run_gate(), 2)

    def test_a_pass_with_a_reproducer_is_inconsistent(self):
        (self.results / "fz.stats.json").write_text(json.dumps(h.stats_doc(sha=h.SHA_A)))
        self.assertExit(self.run_gate(), 2)

    def test_a_crash_file_that_does_not_match_the_stats(self):
        (self.results / "fz.crash").write_bytes(b"not empty")
        self.assertExit(self.run_gate(), 2)

    def test_a_replayed_list_of_the_wrong_length(self):
        (self.results / "fz.replayed").write_text(h.SHA_A + "\n")
        self.assertExit(self.run_gate(), 2)

    def test_a_result_for_a_target_that_is_not_in_the_facts(self):
        h.write_run(self.results, "other", "//p:other", h.stats_doc())
        self.assertExit(self.run_gate(), 2)

    def test_a_policy_module_without_facts(self):
        h.policy_file(self.policy, '[module."//p:nothing"]\nfuzz = true\n')
        self.assertExit(self.run_gate(), 2)

    def test_malformed_policy_values(self):
        for text in ('[module."%s"]\nfuzz = "yes"\n', '[module."%s"]\nfuzz = true\nfuzz_runs = 0\n',
                     '[module."%s"]\nfuzz = true\nfuzz_runs = 99999999\n', '[module."%s"]\nfuzz_runs = 10\n',
                     '[module."%s"\n'):
            with self.subTest(text=text):
                h.policy_file(self.policy, text % h.LIB if "%s" in text else text)
                self.assertExit(self.run_gate(), 2)

    def test_malformed_regressions(self):
        reg = self.tmp / "reg.json"
        for text in ("[]", '{"//p:fz": "x"}', '{"//p:fz": ["abc"]}', '{"//p:fz": ["%s", "%s"]}' % (h.SHA_A, h.SHA_A),
                     '{"bad label": []}', "{not json"):
            with self.subTest(text=text):
                reg.write_text(text)
                self.assertExit(self.run_gate(reg), 2)

    def test_a_missing_regressions_file(self):
        self.assertExit(self.run_gate(self.tmp / "nope.json"), 2)

    def test_an_empty_or_extra_facts_dir(self):
        self.facts = self.tmp / "empty"
        self.facts.mkdir()
        self.assertExit(self.run_gate(), 2)
        (self.tmp / "facts" / "notes.txt").write_text("x")
        self.facts = self.tmp / "facts"
        self.assertExit(self.run_gate(), 2)

    def test_an_unknown_option_and_missing_required_options(self):
        self.assertExit(run_rigor(["fuzz", "--bogus"]), 2)
        self.assertExit(run_rigor(["fuzz"]), 2)
