"""Perf kills in `rigor mutants` (T090): a survivor that makes a declared perf target leave its class is `killed-perf`."""

import json
import unittest

from rigor_lib import mutants_perf
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase, read_json, run_rigor
from tests.test_mutants import LABEL, PASS, mutant, report

TARGET = "//m:mod_perf"


def rec(n, instructions, libc=0, **extra):
    base = {"name": "p", "seed": 1, "n": n, "status": "ok", "counter": "perf_event_open", "errno": 0,
            "input_len": n, "instructions": instructions, "libc_bytes": libc, "result": 0}
    base.update(extra)
    return base


FLAT = [rec(1000, 5000), rec(4000, 5000)]
LINEAR = [rec(1000, 5000), rec(4000, 20000)]


def key(number):
    return "%016x" % number


def evidence(baseline=FLAT, mutants=None, target=TARGET, label=LABEL):
    return {"schema": 1, "label": label, "targets": {target: {"baseline": baseline, "mutants": mutants or {}}}}


class PerfKills(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")
        self.perf = self.sub("perf")
        self.policy = self.tmp / "policy.toml"

    def write_policy(self, level="L3", cost_class="O(1)"):
        self.policy.write_text('[module."%s"]\nlevel = "%s"\n[module."%s".perf."%s"]\nclass = "%s"\n'
                               % (LABEL, level, LABEL, TARGET, cost_class), encoding="utf-8")

    def grade(self, document, perf, level="L3", cost_class="O(1)"):
        self.write_policy(level, cost_class)
        (self.results / "mod.json").write_text(json.dumps(document), encoding="utf-8")
        if perf is not None:
            (self.perf / "mod.json").write_text(json.dumps(perf), encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["mutants", "--results", self.results, "--policy", self.policy, "--perf-results", self.perf,
                             "--out", out])
        return outcome, read_json(out)

    def rules(self, result):
        return sorted(f["rule"] for f in result["findings"])

    def test_a_survivor_that_leaves_the_class_is_killed_perf_and_the_gate_passes(self):
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS}, line=9)]),
                                     evidence(mutants={key(2): LINEAR}))
        self.assertEqual(outcome.code, 0, outcome.stderr)
        module = result["metadata"]["modules"][LABEL]
        self.assertEqual((module["verdicts"]["killed-perf"], module["verdicts"]["survived"], module["survivors"]), (1, 0, []))
        (killed,) = module["perf"]["killed"]
        self.assertEqual((killed["id"], killed["target"], killed["class"], killed["counter"], killed["ratio"], killed["at"]),
                         ("%016x" % 2, TARGET, "O(1)", "instructions", "4.000", "m/a.c:9"))

    def test_a_survivor_inside_the_class_stays_a_survivor(self):
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]), evidence(mutants={key(2): FLAT}))
        self.assertEqual(outcome.code, 1)
        self.assertEqual(self.rules(result), ["survived-mutant"])
        self.assertEqual(result["metadata"]["modules"][LABEL]["perf"]["killed"], [])
        self.assertEqual(result["metadata"]["modules"][LABEL]["perf"]["candidates"], 1)

    def test_the_libc_counter_counts_too(self):
        slow = [rec(1000, 5000, 100), rec(4000, 5000, 5000)]
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]), evidence(mutants={key(2): slow}))
        self.assertEqual(outcome.code, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["perf"]["killed"][0]["counter"], "libc_bytes")

    def test_a_linear_class_does_not_kill_a_linear_mutant(self):
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]), evidence(mutants={key(2): LINEAR}),
                                     cost_class="O(n)")
        self.assertEqual((outcome.code, self.rules(result)), (1, ["survived-mutant"]))

    def test_a_timeout_is_a_blown_class_but_a_crash_or_a_failed_link_is_not(self):
        doc = report([mutant(1), mutant(2, runs={"t": PASS}), mutant(3, runs={"t": PASS}), mutant(4, runs={"t": PASS})])
        mutants = {key(2): [rec(1000, 5000), {"n": 4000, "status": "timeout", "input_len": 4000}],
                   key(3): [rec(1000, 5000), {"n": 4000, "status": "crash", "signal": 11, "input_len": 4000}],
                   key(4): [{"marker": "link-failed"}]}
        outcome, result = self.grade(doc, evidence(mutants=mutants))
        self.assertEqual(outcome.code, 1)
        self.assertEqual([f["id"] for f in result["findings"] if f["rule"] == "survived-mutant"],
                         ["%016x" % 3, "%016x" % 4])

    def test_a_killed_perf_mutant_counts_for_the_function_that_had_no_other_kill(self):
        doc = report([mutant(1, runs={"t": PASS})])
        outcome, result = self.grade(doc, evidence(mutants={key(1): LINEAR}))
        self.assertEqual((outcome.code, result["findings"]), (0, []))

    def test_a_duplicate_of_a_perf_killed_mutant_is_not_a_survivor_either(self):
        same = "%064x" % 77
        doc = report([mutant(1), mutant(2, runs={"t": PASS}, digest=same, o0="%064x" % 78),
                          mutant(3, digest=same, o0="%064x" % 78)])
        doc["mutants"][2]["runs"] = {}
        outcome, result = self.grade(doc, evidence(mutants={key(2): LINEAR}))
        self.assertEqual(outcome.code, 0, result)

    def test_an_unavailable_counter_gives_no_verdict_and_is_an_error(self):
        gone = [rec(1000, None, counter="unavailable", errno=1), rec(4000, None, counter="unavailable", errno=1)]
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]), evidence(baseline=gone))
        self.assertEqual(self.rules(result), ["perf-counter-unavailable", "survived-mutant"])
        self.assertEqual(outcome.code, 1)

    def test_no_survivor_needs_no_counts(self):
        gone = [rec(1000, None, counter="unavailable", errno=1), rec(4000, None, counter="unavailable", errno=1)]
        outcome, result = self.grade(report([mutant(1)]), evidence(baseline=gone))
        self.assertEqual((outcome.code, result["findings"]), (0, []))

    def test_a_baseline_outside_its_class_cannot_kill_anything(self):
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]),
                                     evidence(baseline=LINEAR, mutants={key(2): [rec(1000, 5000), rec(4000, 80000)]}))
        self.assertEqual(self.rules(result), ["perf-baseline-bad", "survived-mutant"])

    def test_a_survivor_without_a_perf_record_is_an_error(self):
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]), evidence())
        self.assertEqual(self.rules(result), ["perf-evidence-missing", "survived-mutant"])
        (self.perf / "mod.json").unlink()
        outcome, result = self.grade(report([mutant(1)]), None)
        self.assertEqual(self.rules(result), ["perf-evidence-missing"])

    def test_l2_findings_about_the_baseline_are_info(self):
        gone = [rec(1000, None, counter="unavailable", errno=1), rec(4000, None, counter="unavailable", errno=1)]
        outcome, result = self.grade(report([mutant(1), mutant(2, runs={"t": PASS})]), evidence(baseline=gone), level="L2")
        self.assertEqual(outcome.code, 0)
        self.assertEqual({f["severity"] for f in result["findings"]}, {"info"})

    def test_without_perf_in_the_policy_nothing_is_read_or_changed(self):
        self.policy.write_text('[module."%s"]\nlevel = "L3"\n' % LABEL, encoding="utf-8")
        (self.results / "mod.json").write_text(json.dumps(report([mutant(1), mutant(2, runs={"t": PASS})])), encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["mutants", "--results", self.results, "--policy", self.policy, "--out", out])
        self.assertEqual(outcome.code, 1)
        self.assertNotIn("perf", read_json(out)["metadata"]["modules"][LABEL])


class EvidenceFiles(TempDirTestCase):
    def test_a_well_formed_file_is_read_and_a_missing_directory_is_no_evidence(self):
        d = self.sub("perf")
        (d / "a.json").write_text(json.dumps(evidence(mutants={key(2): LINEAR})), encoding="utf-8")
        loaded = mutants_perf.load_dir(str(d))
        self.assertEqual(loaded[LABEL][TARGET][1][key(2)][1]["instructions"], 20000)
        self.assertEqual(mutants_perf.load_dir(str(self.tmp / "none")), {})
        self.assertEqual(mutants_perf.load_dir(None), {})

    def test_every_defect_is_exit_2(self):
        d = self.sub("perf")
        bad = [{}, dict(evidence(), schema=2), dict(evidence(), extra=1), dict(evidence(), label="x"),
               {"schema": 1, "label": LABEL, "targets": {"x": {}}},
               {"schema": 1, "label": LABEL, "targets": {TARGET: {"baseline": [1], "mutants": {}}}},
               {"schema": 1, "label": LABEL, "targets": {TARGET: {"baseline": [], "mutants": {"k": 3}}}}]
        for document in bad:
            (d / "a.json").write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(InternalError, msg=document):
                mutants_perf.load_dir(str(d))
        (d / "a.json").write_text(json.dumps(evidence()), encoding="utf-8")
        (d / "b.json").write_text(json.dumps(evidence()), encoding="utf-8")
        with self.assertRaises(InternalError):
            mutants_perf.load_dir(str(d))
        (d / "b.json").unlink()
        (d / "note.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(InternalError):
            mutants_perf.load_dir(str(d))


if __name__ == "__main__":
    unittest.main()
