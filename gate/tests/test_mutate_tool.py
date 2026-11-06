"""Tests of the result normalisation of mutate/tool.py (T034).

What a mutant run stores must be a function of its verdict, not of garbage from uninitialised memory, and
normalising must never change the verdict `rigor mutants` reaches (`mutants_verdict.outcome_of_run`).
"""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from rigor_lib import mutants_verdict

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mutate_tool", HERE.parent.parent / "mutate" / "tool.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def line(test, status, asserts, reason):
    return json.dumps({"id": test, "status": status, "asserts": asserts, "reason": reason}) + "\n"


def results(*lines):
    total = len(lines)
    passed = sum(1 for ln in lines if '"pass"' in ln)
    return "".join(lines) + json.dumps({"summary": {"total": total, "passed": passed}}) + "\n"


def run(rc, text, timed_out=False):
    return SimpleNamespace(rc=rc, timed_out=timed_out, results=text)


def verdict(rc, text, timed_out=False):
    return mutants_verdict.outcome_of_run(run(rc, text, timed_out))


class ReasonTest(unittest.TestCase):
    def test_garbage_values_of_a_failed_check_are_dropped(self):
        a = "2 of 5 checks failed; first: a/b.c:41: CHECK_EQ_I64(f(i), 20): 32770 != 20"
        b = "3 of 5 checks failed; first: a/b.c:41: CHECK_EQ_I64(f(i), 20): -781801958 != 20"
        self.assertEqual(tool.normalise_reason(a), tool.normalise_reason(b))
        self.assertEqual(tool.normalise_reason(a),
                         "0 of 0 checks failed; first: a/b.c:41: CHECK_EQ_I64(f(i), 20)")

    def test_a_check_without_values_and_the_place_are_kept(self):
        self.assertEqual(tool.normalise_reason("1 of 1 checks failed; first: x.c:7: CHECK(p != 0)"),
                         "0 of 0 checks failed; first: x.c:7: CHECK(p != 0)")

    def test_strings_and_addresses_after_the_check_are_dropped(self):
        a = 'CHECK_EQ_STR(s, "ok"): "\\u0001\\u00ff" != "ok" at 0x7ffd1234'
        text = "1 of 1 checks failed; first: x.c:9: " + a
        self.assertEqual(tool.normalise_reason(text), "0 of 0 checks failed; first: x.c:9: CHECK_EQ_STR(s, \"ok\")")

    def test_other_reasons_keep_their_words_and_lose_their_numbers(self):
        self.assertEqual(tool.normalise_reason("killed by signal 11"), "killed by signal #")
        self.assertEqual(tool.normalise_reason("killed by signal 6"), "killed by signal #")
        self.assertEqual(tool.normalise_reason("timeout after 10 s"), "timeout after # s")
        self.assertEqual(tool.normalise_reason("no checks executed"), "no checks executed")

    def test_a_crash_never_becomes_a_check_failure(self):
        for text in ("killed by signal 11", "exited with status 3 before reporting",
                     "exited with status 0 after reporting", "timeout after 10 s", "no checks executed"):
            self.assertIsNone(tool.CHECK_FAILURE.match(tool.normalise_reason(text)), text)

    def test_the_exit_status_keeps_only_what_decides(self):
        self.assertEqual([tool.normalise_rc(rc, False) for rc in (0, 1, 2, 139, -11, -6)], [0, 1, -1, -1, -1, -1])
        self.assertEqual(tool.normalise_rc(-9, True), -9)


class ResultsTest(unittest.TestCase):
    def test_two_runs_that_differ_in_garbage_store_the_same_text(self):
        a = results(line("s/t", "fail", 4, "1 of 4 checks failed; first: k.c:3: CHECK_EQ_I64(g(), 1): 32770 != 1"))
        b = results(line("s/t", "fail", 3, "2 of 3 checks failed; first: k.c:3: CHECK_EQ_I64(g(), 1): -85 != 1"))
        self.assertEqual(tool.normalise_results(a), tool.normalise_results(b))

    def test_verdicts_do_not_change(self):
        cases = [
            (1, results(line("s/t", "fail", 4, "1 of 4 checks failed; first: k.c:3: CHECK(x): 5"))),
            (1, results(line("s/t", "fail", 0, "killed by signal 11"))),
            (1, results(line("s/t", "fail", 0, "timeout after 10 s"))),
            (1, results(line("s/t", "fail", 2, "no checks executed"))),
            (0, results(line("s/t", "pass", 3, ""))),
            (0, results(line("s/t", "skip", 0, ""))),
            (0, results(line("s/t", "fail", 1, ""))),
            (1, results(line("s/t", "pass", 1, ""))),
            (0, "this is not json\n"),
            (0, ""),
            (2, results(line("s/t", "fail", 0, "x"))),
        ]
        for rc, text in cases:
            with self.subTest(rc=rc, text=text):
                before = verdict(rc, text)
                after = verdict(tool.normalise_rc(rc, False), tool.normalise_results(text) if text else text)
                self.assertEqual(before[0], after[0])
                self.assertEqual(before[1], after[1])

    def test_a_timeout_stays_a_crash(self):
        self.assertEqual(verdict(-9, "", True)[0], "crash")
        self.assertEqual(verdict(tool.normalise_rc(-9, True), "", True)[0], "crash")

    def test_a_line_that_does_not_parse_stays_a_line_that_does_not_parse(self):
        text = tool.normalise_results(line("s/t", "pass", 1, "") + "{broken\n")
        self.assertEqual(verdict(0, text)[0], "bad")

    def test_assertion_counts_are_zero_or_one(self):
        out = tool.normalise_results(results(line("s/t", "pass", 7, ""), line("s/u", "fail", 0, "x")))
        counts = [json.loads(ln)["asserts"] for ln in out.splitlines() if '"id"' in ln]
        self.assertEqual(counts, [1, 0])


if __name__ == "__main__":
    unittest.main()
