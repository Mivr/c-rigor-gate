"""The `tests-stub` gate and the role-aware `tests-<mode>` gates of `rigor grade` (T041, P002 Q2), without Buck2.

`stub_judge` itself is tested in `test_stub_judge.py`; here the wiring: the role, NOT_RUN, the input files and
the head's results of both modes. `selftest/grade.sh` runs the same cases for real.
"""

import json
from types import SimpleNamespace

from rigor_lib import grade_pipeline, grade_steps, stub_judge, verdict
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase


def line(test_id, status, reason=None, asserts=1):
    record = {"id": test_id, "status": status, "asserts": asserts}
    if reason is not None:
        record["reason"] = reason
    return json.dumps(record)


class Setup(TempDirTestCase):
    def grading(self, role="test-author", expected=("s/old", "s/new"), previous=("s/old",), built=True):
        product = self.sub("p")
        (product / "expected-tests.json").write_text(json.dumps({"ids": list(expected)}), encoding="utf-8")
        if previous is not None:
            (product / "expected-tests.previous.json").write_text(json.dumps({"ids": list(previous)}),
                                                                  encoding="utf-8")
        task = self.tmp / "task.toml"
        text = 'id = "t"\nallowed = ["**"]\n' + ('role = "%s"\n' % role if role is not None else "")
        task.write_text(text, encoding="utf-8")
        args = SimpleNamespace(task=str(task), product=str(product / "product.toml"), approvals=None)
        dirs = {mode: str(self.sub("results-" + mode)) for mode in stub_judge.MODES} if built else {}
        return SimpleNamespace(args=args, built=dirs, src="", head="h")

    def results(self, g, mode, lines):
        total = len(lines)
        passed = sum(1 for item in lines if json.loads(item)["status"] == "pass")
        text = "\n".join(lines + [json.dumps({"summary": {"total": total, "passed": passed}})]) + "\n"
        with open(g.built[mode] + "/core.jsonl", "w", encoding="utf-8") as handle:
            handle.write(text)


class Registration(Setup):
    def test_tests_stub_runs_right_after_the_head_tests(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("tests-san") + 1], "tests-stub")
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt")), ids)


class TestsStub(Setup):
    def test_other_roles_are_not_applicable_whatever_the_build_did(self):
        for role in (None, "implementer", "audit"):
            for built in (True, False):
                with self.subTest(role=role, built=built):
                    result = grade_steps.tests_stub_gate(self.grading(role=role, previous=None, built=built))
                    self.assertEqual(result.gate, "tests-stub")
                    self.assertEqual(result.status, "PASS")
                    self.assertEqual([(f["rule"], f["severity"], f["role"]) for f in result.findings],
                                     [("not-applicable", "info", role or "implementer")])

    def test_role_test_author_is_not_run_without_clean_results_of_both_modes(self):
        self.assertIsNone(grade_steps.tests_stub_gate(self.grading(built=False)))
        g = self.grading()
        del g.built["san"]
        self.assertIsNone(grade_steps.tests_stub_gate(g))

    def test_role_test_author_without_the_previous_list_is_exit_2(self):
        g = self.grading(previous=None)
        with self.assertRaisesRegex(InternalError, "expected-tests.previous.json"):
            grade_steps.tests_stub_gate(g)

    def test_new_tests_that_fail_on_the_stubs_in_both_modes_pass(self):
        g = self.grading()
        self.results(g, "release", [line("s/old", "pass"), line("s/new", "fail", "1 of 2 checks failed", 2)])
        self.results(g, "san", [line("s/old", "fail", "killed by signal 6"),
                                line("s/new", "fail", "timeout after 10 s", 0)])
        result = grade_steps.tests_stub_gate(g)
        self.assertEqual(result.status, "PASS")
        self.assertEqual([(f["rule"], f["mode"]) for f in result.findings], [("stub-timeout", "san")])
        self.assertEqual(result.metadata["new_ids"], ["s/new"])
        self.assertEqual(result.metadata["fail_kinds"]["release"]["check"], 1)
        self.assertEqual(result.metadata["fail_kinds"]["san"]["timeout"], 1)
        self.assertEqual(result.metadata["role"], "test-author")

    def test_a_new_test_that_passes_on_the_stub_in_one_mode_fails(self):
        for passing in stub_judge.MODES:
            with self.subTest(mode=passing):
                g = self.grading()
                for mode in stub_judge.MODES:
                    status = "pass" if mode == passing else "fail"
                    self.results(g, mode, [line("s/old", "pass"), line("s/new", status, None, 1)])
                result = grade_steps.tests_stub_gate(g)
                self.assertEqual(result.status, "FAIL")
                self.assertEqual([(f["rule"], f["id"], f["mode"]) for f in result.findings],
                                 [("test-passes-on-stub", "s/new", passing)])

    def test_no_new_ids_and_a_missing_new_id_fail(self):
        g = self.grading(expected=("s/old",))
        self.results(g, "release", [line("s/old", "fail", "1 of 1 checks failed")])
        self.results(g, "san", [line("s/old", "fail", "1 of 1 checks failed")])
        self.assertEqual([f["rule"] for f in grade_steps.tests_stub_gate(g).findings], ["no-new-tests"])
        g = self.grading()
        self.results(g, "release", [line("s/old", "pass")])
        self.results(g, "san", [line("s/new", "fail", "1 of 1 checks failed")])
        self.assertEqual([(f["rule"], f["mode"]) for f in grade_steps.tests_stub_gate(g).findings],
                         [("missing-test", "release")])


class TestsModes(Setup):
    """`tests-<mode>`: role test-author judges presence, not status; the other roles judge both."""

    def judge(self, role):
        g = self.grading(role=role, previous=("s/old",))
        for mode in stub_judge.MODES:
            self.results(g, mode, [line("s/old", "fail", "1 of 1 checks failed"),
                                   line("s/new", "fail", "no checks executed", 0)])
        return {mode: grade_steps.tests_gate_for(mode)(g) for mode in stub_judge.MODES}

    def test_role_test_author_leaves_statuses_unjudged(self):
        for mode, result in self.judge("test-author").items():
            self.assertEqual(result.gate, "tests-" + mode)
            self.assertEqual(result.status, "PASS", result.findings)
            self.assertIs(result.metadata["statuses_judged"], False)

    def test_other_roles_judge_statuses(self):
        for role in ("implementer", "audit"):
            for mode, result in self.judge(role).items():
                self.assertEqual(result.status, "FAIL")
                self.assertEqual(sorted({f["rule"] for f in result.findings}), ["no-assertions", "test-not-pass"])
                self.assertNotIn("statuses_judged", result.metadata)

    def test_role_test_author_still_needs_every_expected_id(self):
        g = self.grading(previous=("s/old",))
        for mode in stub_judge.MODES:
            self.results(g, mode, [line("s/old", "fail", "1 of 1 checks failed")])
        for mode in stub_judge.MODES:
            result = grade_steps.tests_gate_for(mode)(g)
            self.assertEqual([(f["rule"], f["id"]) for f in result.findings], [("missing-test", "s/new")])
