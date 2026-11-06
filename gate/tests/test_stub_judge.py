"""The `tests-stub` judgement (P002, Q2): every new expected id fails on the stubs, in release and san."""

import json
import os
import unittest

from rigor_lib import stub_judge as sj
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase

OLD, NEW, NEW2 = "core/old", "core/new", "core/new2"
EXPECTED = {OLD, NEW, NEW2}
PREVIOUS = {OLD}
CHECK = "1 of 2 checks failed; first: core_test.c:10 core_add(1, 1) == 2"


def line(test_id, status="fail", reason=CHECK, asserts=0):
    obj = {"id": test_id, "status": status, "asserts": asserts}
    if reason is not None:
        obj["reason"] = reason
    return obj


def results(*records, name="core_test.jsonl"):
    rows = [json.dumps(r) for r in records]
    passed = sum(1 for r in records if r["status"] == "pass")
    rows.append(json.dumps({"summary": {"total": len(records), "passed": passed}}))
    return [sj.parse_file(name, ("\n".join(rows) + "\n").encode("utf-8"))]


def both(*records):
    return {"release": results(*records), "san": results(*records)}


def rules(result):
    return sorted((f["rule"], f.get("id"), f.get("mode"), f["severity"]) for f in result.findings)


class Green(unittest.TestCase):
    def test_every_new_id_fails_in_both_modes(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(OLD, "pass", None, 3), line(NEW), line(NEW2)))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.gate, "tests-stub")
        self.assertEqual(result.metadata["new_ids"], [NEW, NEW2])
        self.assertEqual(result.metadata["new_count"], 2)
        self.assertEqual(result.metadata["fail_kinds"]["release"],
                         {"check": 2, "crash": 0, "timeout": 0, "no-checks": 0, "other": 0})

    def test_old_ids_are_not_judged(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(OLD, "fail"), line(NEW), line(NEW2)))
        self.assertEqual(result.findings, [])

    def test_unexpected_ids_are_not_judged(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(NEW), line(NEW2), line("core/extra", "pass", None, 1)))
        self.assertEqual(result.findings, [])

    def test_a_timeout_still_fails_on_the_stub_and_is_info(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(NEW, reason="timeout after 10 s"), line(NEW2)))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(rules(result), [("stub-timeout", NEW, "release", "info"), ("stub-timeout", NEW, "san", "info")])
        self.assertEqual(result.metadata["fail_kinds"]["san"]["timeout"], 1)


class Red(unittest.TestCase):
    def test_a_pass_in_release(self):
        result = sj.judge(EXPECTED, PREVIOUS, {"release": results(line(NEW, "pass", None, 2), line(NEW2)),
                                               "san": results(line(NEW), line(NEW2))})
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(rules(result), [("test-passes-on-stub", NEW, "release", "error")])
        self.assertEqual(result.findings[0]["status"], "pass")

    def test_a_pass_in_san_only(self):
        result = sj.judge(EXPECTED, PREVIOUS, {"release": results(line(NEW), line(NEW2)),
                                               "san": results(line(NEW), line(NEW2, "pass", None, 1))})
        self.assertEqual(rules(result), [("test-passes-on-stub", NEW2, "san", "error")])

    def test_a_pass_in_both_modes_is_two_findings(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(NEW, "pass", None, 1), line(NEW2)))
        self.assertEqual(rules(result), [("test-passes-on-stub", NEW, "release", "error"),
                                         ("test-passes-on-stub", NEW, "san", "error")])

    def test_a_skip_is_not_a_fail(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(NEW, "skip", None), line(NEW2)))
        self.assertEqual(rules(result), [("test-passes-on-stub", NEW, "release", "error"),
                                         ("test-passes-on-stub", NEW, "san", "error")])
        self.assertEqual(result.findings[0]["status"], "skip")

    def test_an_id_missing_in_one_mode(self):
        result = sj.judge(EXPECTED, PREVIOUS, {"release": results(line(NEW), line(NEW2)),
                                               "san": results(line(NEW))})
        self.assertEqual(rules(result), [("missing-test", NEW2, "san", "error")])

    def test_an_id_missing_in_both_modes(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(NEW)))
        self.assertEqual(rules(result), [("missing-test", NEW2, "release", "error"),
                                         ("missing-test", NEW2, "san", "error")])

    def test_no_new_tests(self):
        result = sj.judge({OLD}, {OLD}, both(line(OLD)))
        self.assertEqual(rules(result), [("no-new-tests", None, None, "error")])
        self.assertEqual(result.metadata["new_ids"], [])

    def test_only_removals_is_no_new_tests(self):
        result = sj.judge({OLD}, {OLD, NEW}, both(line(OLD)))
        self.assertEqual(rules(result), [("no-new-tests", None, None, "error")])

    def test_a_duplicate_that_passes_once_is_a_pass_on_the_stub(self):
        result = sj.judge(EXPECTED, PREVIOUS, both(line(NEW), line(NEW, "pass", None, 1), line(NEW2)))
        self.assertEqual(rules(result), [("test-passes-on-stub", NEW, "release", "error"),
                                         ("test-passes-on-stub", NEW, "san", "error")])

    def test_a_malformed_line_does_not_count_as_a_fail(self):
        rows = [json.dumps(line(NEW)), '{"id": "core/new2", "status": "fail"}',
                json.dumps({"summary": {"total": 1, "passed": 0}})]
        bad = [sj.parse_file("x.jsonl", ("\n".join(rows) + "\n").encode())]
        result = sj.judge(EXPECTED, PREVIOUS, {"release": bad, "san": results(line(NEW), line(NEW2))})
        self.assertEqual(rules(result), [("missing-test", NEW2, "release", "error")])


class FailKinds(unittest.TestCase):
    CASES = [
        (CHECK, "check"),
        ("3 of 3 checks failed; first: x", "check"),
        ("killed by signal 11", "crash"),
        ("killed by signal 6; AddressSanitizer: heap-buffer-overflow at core/core.c:3 core_add", "crash"),
        ("exited with status 1 before reporting", "crash"),
        ("exited with status 23 before reporting; UndefinedBehaviorSanitizer: x", "crash"),
        ("exited with status 1 after reporting", "crash"),
        ("exited without reporting (exit() or _exit() before the test returned)", "crash"),
        ("invalid report from the test process", "crash"),
        ("sanitizer report in a test that looked passing: LeakSanitizer: detected memory leaks", "crash"),
        ("timeout after 10 s", "timeout"),
        ("no checks executed", "no-checks"),
        ("no checks executed; LeakSanitizer: x", "no-checks"),
        ("something new", "other"),
        ("", "other"),
        ("checks failed", "other"),
        (None, "other"),
    ]

    def test_kinds_from_reason(self):
        for reason, kind in self.CASES:
            self.assertEqual(sj.fail_kind(reason), kind, reason)

    def test_every_kind_counts_as_a_fail_on_the_stub_and_is_counted_per_mode(self):
        for reason, kind in self.CASES:
            result = sj.judge(EXPECTED, PREVIOUS, {"release": results(line(NEW, reason=reason), line(NEW2)),
                                                   "san": results(line(NEW), line(NEW2))})
            self.assertEqual(result.status, "PASS", reason)
            release = result.metadata["fail_kinds"]["release"]
            self.assertEqual(release[kind], 1 + (kind == "check"), reason)
            self.assertEqual(sum(release.values()), 2, reason)
            self.assertEqual(result.metadata["fail_kinds"]["san"]["check"], 2)


class Inputs(TempDirTestCase):
    def test_previous_is_required(self):
        with self.assertRaises(InternalError):
            sj.judge(EXPECTED, None, both(line(NEW)))

    def test_exactly_the_two_modes(self):
        for parsed in ({"release": results(line(NEW))}, dict(both(line(NEW)), asan=[]), [], None):
            with self.assertRaises(InternalError):
                sj.judge(EXPECTED, PREVIOUS, parsed)

    def test_bad_ids(self):
        for expected, previous in (({"bad"}, set()), ({NEW}, {"a b/c"}), ("core/new", set()), ([NEW, NEW], set()),
                                   ({1}, set())):
            with self.assertRaises(InternalError):
                sj.judge(expected, previous, both(line(NEW)))

    def test_results_must_be_parsed_by_this_module(self):
        from rigor_lib import results_parse
        raw = results_parse.parse_file("x.jsonl", b'{"summary": {"total": 0, "passed": 0}}\n')
        for parsed in ({"release": [raw], "san": []}, {"release": "x", "san": []}):
            with self.assertRaises(InternalError):
                sj.judge(EXPECTED, PREVIOUS, parsed)

    def test_reasons_are_read_back_per_line(self):
        parsed = results(line(NEW, reason="timeout after 10 s"), line(NEW2, reason=None))[0]
        self.assertEqual(parsed.reasons, {1: "timeout after 10 s", 2: None})
        self.assertEqual([r.test_id for r in parsed.parsed.records], [NEW, NEW2])

    def test_parse_directory_reads_only_jsonl_files_in_name_order(self):
        directory = self.sub("results")
        (directory / "b.jsonl").write_text(json.dumps(line(NEW2)) + "\n" +
                                           json.dumps({"summary": {"total": 1, "passed": 0}}) + "\n")
        (directory / "a.jsonl").write_text(json.dumps(line(NEW)) + "\n" +
                                           json.dumps({"summary": {"total": 1, "passed": 0}}) + "\n")
        (directory / "c.txt").write_text(json.dumps(line(NEW2, "pass", None, 1)) + "\n")
        os.mkdir(directory / "d.jsonl")
        parsed = sj.parse_directory(str(directory))
        self.assertEqual([p.parsed.name for p in parsed], ["a.jsonl", "b.jsonl"])
        result = sj.judge(EXPECTED, PREVIOUS, {"release": parsed, "san": parsed})
        self.assertEqual(result.findings, [])

    def test_parse_directory_of_a_missing_directory(self):
        with self.assertRaises(InternalError):
            sj.parse_directory(str(self.tmp / "none"))


if __name__ == "__main__":
    unittest.main()
