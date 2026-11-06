"""Tests of `rigor mutants`: verdicts derived from raw report facts, and every way the gate must fail."""

import json

from tests.helpers import Repo, Signer, TempDirTestCase, read_json, run_rigor

LABEL = "//m:mod_mutants"
H = ["%064x" % n for n in range(1, 40)]  # distinct object hashes
BASE = H[0]


def results(*lines):
    """JSON Lines text of a ctest binary: each line is (status, asserts, reason)."""
    rows = []
    for number, (status, asserts, reason) in enumerate(lines, start=1):
        rows.append(json.dumps({"id": "s/t%d" % number, "status": status, "asserts": asserts, "reason": reason}))
    passed = sum(1 for line in lines if line[0] == "pass")
    rows.append(json.dumps({"summary": {"total": len(lines), "passed": passed}}))
    return "\n".join(rows) + "\n"


PASS = {"rc": 0, "timed_out": False, "results": results(("pass", 2, ""))}
KILLED = {"rc": 1, "timed_out": False,
          "results": results(("fail", 2, "1 of 2 checks failed; first: f.c:3: CHECK(x): 1 != 2"))}
CRASH = {"rc": 1, "timed_out": False, "results": results(("fail", 1, "killed by signal 11"))}
TIMEOUT = {"rc": 1, "timed_out": False, "results": results(("fail", 1, "timeout after 10 s"))}
KILLED_BY_WATCHDOG = {"rc": -9, "timed_out": True, "results": None}


def mutant(number, function="f", operator="relational", status="ok", digest=None, runs=None, line=3):
    return {"id": "%016x" % number, "file": "m/a.c", "begin_offset": number, "end_offset": number + 1,
            "original": "<", "replacement": "<=", "operator": operator, "function": function, "line": line,
            "compile": {"status": status, "hash": "" if status == "unviable" else (digest or H[number])},
            "runs": {"t": KILLED} if runs is None and status == "ok" else (runs or {})}


def report(mutants, functions=("f",), baseline=PASS, original=BASE, label=LABEL, tests=("t",), skipped=()):
    return {
        "schema": 1, "label": label, "tests": list(tests),
        "sources": [{"file": "m/a.c", "sha256": "0" * 64, "functions": [{"name": n, "line": 1} for n in functions],
                     "skipped": list(skipped),
                     "baseline": {"status": "ok", "hash": BASE}, "original": {"status": "ok", "hash": original}}],
        "baseline_runs": {t: baseline for t in tests}, "mutants": mutants,
    }


class MutantsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")
        self.policy = self.tmp / "policy.toml"
        self.write_policy("L3")

    def write_policy(self, level, label=LABEL):
        self.policy.write_text('[module."%s"]\nlevel = "%s"\n' % (label, level), encoding="utf-8")

    def put(self, document, name="mod.json"):
        (self.results / name).write_text(json.dumps(document), encoding="utf-8")

    def grade(self, extra=()):
        out = self.tmp / "out.json"
        outcome = run_rigor(["mutants", "--results", self.results, "--policy", self.policy, "--out", out]
                            + list(extra))
        return outcome, (read_json(out) if out.exists() else None)

    def rules(self, result):
        return sorted(f["rule"] for f in result["findings"])

    def fails_with(self, document, *rules, level="L3"):
        self.write_policy(level)
        self.put(document)
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), sorted(rules), result)
        return result

    # -- green -------------------------------------------------------------------------------
    def test_all_killed_by_a_check_failure_passes(self):
        self.put(report([mutant(1), mutant(2, operator="arithmetic")]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        module = result["metadata"]["modules"][LABEL]
        self.assertEqual((module["total"], module["verdicts"]["killed-assert"]), (2, 2))
        self.assertEqual(module["operators"], {"relational": 1, "arithmetic": 1})
        self.assertEqual(module["survivors"], [])

    def test_result_is_deterministic(self):
        self.put(report([mutant(1), mutant(2, runs={"t": PASS})]))
        first, _ = self.grade()
        data = (self.tmp / "out.json").read_bytes()
        second, _ = self.grade()
        self.assertEqual((first.code, second.code), (1, 1))
        self.assertEqual(data, (self.tmp / "out.json").read_bytes())

    # -- red: survivors ----------------------------------------------------------------------
    def test_a_known_survivor_is_reported_as_a_survivor_with_its_place_and_change(self):
        result = self.fails_with(report([mutant(1), mutant(2, operator="arithmetic", runs={"t": PASS}, line=7)]),
                                 "survived-mutant")
        found = result["findings"][0]
        self.assertEqual((found["id"], found["line"], found["operator"], found["replacement"], found["function"]),
                         ("%016x" % 2, 7, "arithmetic", "<=", "f"))
        self.assertEqual(result["metadata"]["modules"][LABEL]["survivors"][0]["at"], "m/a.c:7")

    def test_a_survivor_in_an_l2_module_is_only_reported(self):
        self.write_policy("L2")
        self.put(report([mutant(1), mutant(2, runs={"t": PASS})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(self.rules(result), ["survivor"])
        self.assertEqual(result["findings"][0]["severity"], "info")

    def test_one_test_passing_is_not_enough_to_kill_but_one_failing_check_is(self):
        two = report([mutant(1, runs={"a": PASS, "b": KILLED}), mutant(2, runs={"a": PASS, "b": PASS})],
                     tests=("a", "b"))
        result = self.fails_with(two, "survived-mutant")
        self.assertEqual(result["findings"][0]["id"], "%016x" % 2)

    def test_a_check_failure_beats_a_crash_for_the_verdict(self):
        both = report([mutant(1, runs={"a": CRASH, "b": KILLED})], tests=("a", "b"))
        self.put(both)
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["killed-assert"], 1)

    # -- red: blind generator ----------------------------------------------------------------
    def test_a_generator_that_found_no_mutants_fails(self):
        self.fails_with(report([]), "no-mutants")

    def test_a_source_with_functions_but_no_mutants_fails_even_if_others_have_some(self):
        document = report([mutant(1)])
        document["sources"].append({"file": "m/b.c", "sha256": "0" * 64, "functions": [{"name": "g", "line": 1}],
                                    "skipped": [], "baseline": {"status": "ok", "hash": BASE},
                                    "original": {"status": "ok", "hash": BASE}})
        self.fails_with(document, "no-mutants")

    def test_a_source_without_functions_needs_no_mutants(self):
        self.put(report([], functions=()))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    def test_everything_unviable_fails(self):
        self.fails_with(report([mutant(1, status="unviable"), mutant(2, status="unviable")]),
                        "all-unviable", "no-assert-kill-function")

    def test_a_function_no_mutant_can_reach_fails_l3_and_is_info_in_l2(self):
        hidden = [{"name": "made_by_macro", "file": "m/a.c", "reason": "macro"},
                  {"name": "inline_fn", "file": "m/a.h", "reason": "header"}]
        result = self.fails_with(report([mutant(1)], skipped=hidden), "unmutated-function", "unmutated-function")
        self.assertEqual(sorted(f["function"] for f in result["findings"]), ["inline_fn", "made_by_macro"])
        self.write_policy("L2")
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual({f["severity"] for f in result["findings"]}, {"info"})

    # -- verdicts ----------------------------------------------------------------------------
    def test_equal_object_to_the_baseline_is_equivalent_and_needs_no_run(self):
        self.put(report([mutant(1), mutant(2, digest=BASE, runs={})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["equivalent"], 1)

    def test_equal_object_to_an_earlier_mutant_is_a_duplicate_of_it(self):
        self.put(report([mutant(1), mutant(2, digest=H[1], runs={})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["duplicate"], 1)

    def test_a_duplicate_of_a_survivor_does_not_hide_it(self):
        result = self.fails_with(report([mutant(1, runs={"t": PASS}), mutant(2, digest=H[1], runs={})]),
                                 "survived-mutant")
        self.assertEqual(result["findings"][0]["id"], "%016x" % 1)

    def test_a_crash_or_a_timeout_kills_but_only_by_crash(self):
        for run in (CRASH, TIMEOUT, KILLED_BY_WATCHDOG, {"rc": 139, "timed_out": False, "results": None}):
            self.fails_with(report([mutant(1, runs={"t": run})]), "crash-only-function")

    def test_a_function_with_one_assert_kill_is_enough_even_if_others_crash(self):
        self.put(report([mutant(1, runs={"t": CRASH}), mutant(2)]))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    def test_a_function_whose_mutants_are_all_equivalent_fails(self):
        self.fails_with(report([mutant(1, digest=BASE, runs={})]), "no-assert-kill-function")

    def test_the_function_rule_does_not_apply_to_l2(self):
        self.write_policy("L2")
        self.put(report([mutant(1, runs={"t": CRASH})]))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    # -- red: unusable facts -----------------------------------------------------------------
    def test_a_live_mutant_without_a_run_fails(self):
        self.fails_with(report([mutant(1), mutant(2, runs={})]), "missing-run")

    def test_results_that_disagree_with_the_exit_status_fail(self):
        self.fails_with(report([mutant(1), mutant(2, runs={"t": dict(PASS, rc=1)})]), "bad-results")
        self.fails_with(report([mutant(1), mutant(2, runs={"t": dict(KILLED, rc=0)})]), "bad-results")

    def test_unparsable_or_skipped_results_fail(self):
        garbage = {"rc": 0, "timed_out": False, "results": "not json\n"}
        skipped = {"rc": 0, "timed_out": False, "results": results(("skip", 1, ""))}
        for run in (garbage, skipped):
            self.fails_with(report([mutant(1), mutant(2, runs={"t": run})]), "bad-results")

    def test_a_run_that_lists_other_tests_than_the_baseline_fails(self):
        other = {"rc": 0, "timed_out": False, "results": results(("pass", 1, ""), ("pass", 1, ""))}
        self.fails_with(report([mutant(1), mutant(2, runs={"t": other})]), "bad-results")

    def test_a_red_baseline_fails(self):
        for baseline in (KILLED, CRASH, dict(PASS, rc=1), {"rc": 0, "timed_out": False, "results": None},
                         {"rc": 0, "timed_out": False, "results": results(("pass", 0, ""))},
                         {"rc": 0, "timed_out": True, "results": PASS["results"]}):
            self.fails_with(report([mutant(1)], baseline=baseline), "baseline-red")

    def test_a_harness_that_does_not_reproduce_the_real_object_fails(self):
        self.fails_with(report([mutant(1)], original=H[30]), "harness-mismatch")

    def test_policy_and_reports_must_match(self):
        self.put(report([mutant(1)], label="//m:other"), "other.json")
        self.put(report([mutant(1)]))
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), ["module-not-in-policy"])
        self.write_policy("L3", label="//m:gone")
        (self.results / "other.json").unlink()
        outcome, result = self.grade()
        self.assertEqual(self.rules(result), ["module-not-in-policy", "policy-module-without-report"])

    # -- exit 2 ------------------------------------------------------------------------------
    def test_malformed_input_is_exit_2(self):
        bad = report([mutant(1)])
        bad["extra"] = 1
        cases = {"extra key": bad, "wrong schema": dict(report([mutant(1)]), schema=2),
                 "bad hash": report([mutant(1, digest="xyz")]),
                 "unknown test": report([mutant(1, runs={"zz": KILLED})])}
        for what, document in cases.items():
            self.put(document)
            outcome, result = self.grade()
            self.assertExit(outcome, 2)
            self.assertEqual(self.rules(result), ["internal-error"], what)

    def test_empty_results_a_stray_file_a_bad_policy_and_two_reports_for_a_label_are_exit_2(self):
        self.assertExit(self.grade()[0], 2)
        self.put(report([mutant(1)]))
        self.put(report([mutant(1)]), "second.json")
        self.assertExit(self.grade()[0], 2)
        (self.results / "second.json").unlink()
        (self.results / "notes.txt").write_text("x", encoding="utf-8")
        self.assertExit(self.grade()[0], 2)
        (self.results / "notes.txt").unlink()
        for text in ('[module."//m:mod_mutants"]\nlevel = "L1"\n', '[module."//m:mod_mutants"]\n',
                     '[global]\nx = 1\n', 'not toml ['):
            self.policy.write_text(text, encoding="utf-8")
            self.assertExit(self.grade()[0], 2)


class ApprovalTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")
        (self.tmp / "policy.toml").write_text('[module."%s"]\nlevel = "L3"\n' % LABEL, encoding="utf-8")
        (self.results / "mod.json").write_text(json.dumps(
            report([mutant(1), mutant(2, runs={"t": PASS})])), encoding="utf-8")
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("a.txt", "1\n")
        self.first = self.repo.commit("first")
        self.repo.write("a.txt", "2\n")
        self.head = self.repo.commit("second")
        self.signer = Signer(self.tmp / "keys")
        self.allowed = self.signer.write_allowed_signers(self.tmp / "allowed_signers")
        self.dir = self.sub("approvals")

    def approve(self, scope, kind="equivalent-mutant", repo_sha=None):
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", "same behaviour",
                             "--repo-sha", repo_sha or self.first, "--key", self.signer.key, "--out", self.dir])
        self.assertExit(outcome, 0)

    def grade(self):
        out = self.tmp / "out.json"
        outcome = run_rigor(["mutants", "--results", self.results, "--policy", self.tmp / "policy.toml",
                             "--out", out, "--approvals", self.dir, "--allowed-signers", self.allowed,
                             "--repo", self.repo.root, "--head", self.head])
        return outcome, read_json(out)

    def test_a_signed_approval_of_the_mutant_id_covers_the_survivor(self):
        self.approve("%016x" % 2)
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(len(result["metadata"]["approvals_used"]), 1)

    def test_an_approval_of_another_id_or_kind_or_a_non_ancestor_does_not(self):
        for kwargs in ({"scope": "%016x" % 3}, {"scope": "%016x" % 2, "kind": "suppression"},
                       {"scope": "%016x" % 2, "repo_sha": "a" * 40}):
            for name in list(self.dir.iterdir()):
                name.unlink()
            self.approve(**kwargs)
            outcome, result = self.grade()
            self.assertExit(outcome, 1)
            self.assertIn("survived-mutant", [f["rule"] for f in result["findings"]])

    def test_an_approval_never_covers_a_missing_run_or_a_crash_only_function(self):
        (self.results / "mod.json").write_text(json.dumps(
            report([mutant(1, runs={"t": CRASH}), mutant(2, runs={})])), encoding="utf-8")
        self.approve("%016x" % 2)
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual(sorted(f["rule"] for f in result["findings"]), ["missing-run"])


if __name__ == "__main__":
    import unittest
    unittest.main()
