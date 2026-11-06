"""Tests for `rigor tests` (expected-test-ID list, assertion check, test-count ratchet)."""

import json
from pathlib import Path

from tests.helpers import Repo, Signer, TempDirTestCase, read_json, run_rigor


def test_line(test_id, status="pass", asserts=1):
    return json.dumps({"id": test_id, "status": status, "asserts": asserts})


def summary_line(total, passed):
    return json.dumps({"summary": {"total": total, "passed": passed}})


class ResultsCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")

    def write_expected(self, ids, name="expected.json"):
        path = self.tmp / name
        path.write_text(json.dumps({"ids": ids}), encoding="utf-8")
        return path

    def write_file(self, lines, name="a.jsonl"):
        (self.results / name).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))

    def write_good(self, ids, name="a.jsonl"):
        lines = [test_line(i) for i in ids] + [summary_line(len(ids), len(ids))]
        self.write_file(lines, name)

    def grade(self, expected, extra=()):
        out = self.tmp / "out.json"
        outcome = run_rigor(["tests", "--results", self.results, "--expected", expected,
                             "--out", out] + list(extra))
        return outcome, (read_json(out) if out.exists() else None)

    def rules(self, result):
        return sorted((f["rule"], f.get("id") or f.get("file")) for f in result["findings"])

    def reasons_of(self, result):
        return sorted(f["reason"] for f in result["findings"] if f["rule"] == "malformed-line")

    def assertRules(self, expected_path, expected_rules, code=1, extra=()):
        outcome, result = self.grade(expected_path, extra)
        self.assertExit(outcome, code)
        self.assertEqual(self.rules(result), sorted(expected_rules))
        return result


class TestsGateGreenTests(ResultsCase):
    def test_all_expected_pass(self):
        self.write_good(["s/one", "s/two"])
        outcome, result = self.grade(self.write_expected(["s/one", "s/two"]))
        self.assertExit(outcome, 0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["findings"], [])

    def test_expected_order_does_not_matter(self):
        self.write_good(["s/one", "s/two"])
        self.assertRules(self.write_expected(["s/two", "s/one"]), [], code=0)

    def test_results_split_over_several_files(self):
        self.write_good(["s/one"], "a.jsonl")
        self.write_good(["t/two"], "b.jsonl")
        self.assertRules(self.write_expected(["s/one", "t/two"]), [], code=0)

    def test_unexpected_passing_test_is_info_only(self):
        self.write_good(["s/one", "s/extra"])
        result = self.assertRules(self.write_expected(["s/one"]), [("unexpected-test", "s/extra")],
                                  code=0)
        self.assertEqual(result["findings"][0]["severity"], "info")
        self.assertEqual(result["status"], "PASS")

    def test_unexpected_skipped_test_is_info_only(self):
        self.write_file([test_line("s/one"), test_line("s/extra", "skip", 0), summary_line(2, 1)])
        self.assertRules(self.write_expected(["s/one"]), [("unexpected-test", "s/extra")], code=0)

    def test_non_jsonl_files_in_results_dir_are_ignored(self):
        self.write_good(["s/one"])
        (self.results / "notes.txt").write_text("hello")
        self.assertRules(self.write_expected(["s/one"]), [], code=0)

    def test_previous_equal_or_smaller_is_fine(self):
        self.write_good(["s/one", "s/two"])
        expected = self.write_expected(["s/one", "s/two"])
        for ids in (["s/one", "s/two"], ["s/one"], ["s/one", "s/two"][::-1]):
            previous = self.write_expected(ids, "prev.json")
            self.assertRules(expected, [], code=0, extra=["--previous", previous])

    def test_findings_are_identical_on_rerun(self):
        self.write_good(["s/b", "s/a"])
        expected = self.write_expected(["s/zz", "s/yy"])
        _, first = self.grade(expected)
        _, second = self.grade(expected)
        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(len(first["findings"]), 4)


class TestsGateRedTests(ResultsCase):
    def test_missing_expected_test(self):
        self.write_good(["s/one"])
        self.assertRules(self.write_expected(["s/one", "s/two"]), [("missing-test", "s/two")])

    def test_duplicate_within_one_file(self):
        self.write_file([test_line("s/one"), test_line("s/one"), summary_line(2, 2)])
        self.assertRules(self.write_expected(["s/one"]), [("duplicate-test", "s/one")])

    def test_duplicate_across_files(self):
        self.write_good(["s/one"], "a.jsonl")
        self.write_good(["s/one"], "b.jsonl")
        self.assertRules(self.write_expected(["s/one"]), [("duplicate-test", "s/one")])

    def test_duplicate_unexpected_test(self):
        self.write_file([test_line("s/one"), test_line("s/x"), test_line("s/x"), summary_line(3, 3)])
        self.assertRules(self.write_expected(["s/one"]), [("duplicate-test", "s/x")])

    def test_failed_expected_test(self):
        self.write_file([test_line("s/one", "fail"), summary_line(1, 0)])
        self.assertRules(self.write_expected(["s/one"]), [("test-not-pass", "s/one")])

    def test_skipped_expected_test(self):
        self.write_file([test_line("s/one", "skip", 0), summary_line(1, 0)])
        self.assertRules(self.write_expected(["s/one"]),
                         [("test-not-pass", "s/one"), ("no-assertions", "s/one")])

    def test_zero_assertions(self):
        self.write_file([test_line("s/one", "pass", 0), summary_line(1, 1)])
        self.assertRules(self.write_expected(["s/one"]), [("no-assertions", "s/one")])

    def test_unexpected_failing_test(self):
        self.write_file([test_line("s/one"), test_line("s/bad", "fail"), summary_line(2, 1)])
        self.assertRules(self.write_expected(["s/one"]), [("unexpected-failing-test", "s/bad")])

    def test_empty_results_directory(self):
        self.assertRules(self.write_expected(["s/one"]),
                         [("no-results", None), ("missing-test", "s/one")])

    def test_results_directory_without_jsonl_files(self):
        (self.results / "notes.txt").write_text("x")
        self.assertRules(self.write_expected(["s/one"]),
                         [("no-results", None), ("missing-test", "s/one")])

    def test_empty_jsonl_file(self):
        (self.results / "a.jsonl").write_bytes(b"")
        self.assertRules(self.write_expected(["s/one"]),
                         [("missing-summary", "a.jsonl"), ("missing-test", "s/one")])

    def test_empty_expected_list(self):
        self.write_good(["s/one"])
        self.assertRules(self.write_expected([]), [("expected-empty", None),
                                                    ("unexpected-test", "s/one")])

    def test_file_without_summary(self):
        self.write_file([test_line("s/one")])
        self.assertRules(self.write_expected(["s/one"]), [("missing-summary", "a.jsonl")])

    def test_summary_total_disagrees(self):
        self.write_file([test_line("s/one"), summary_line(2, 1)])
        self.assertRules(self.write_expected(["s/one"]), [("summary-mismatch", "a.jsonl")])

    def test_summary_passed_disagrees(self):
        self.write_file([test_line("s/one"), summary_line(1, 0)])
        self.assertRules(self.write_expected(["s/one"]), [("summary-mismatch", "a.jsonl")])

    def test_summary_counts_a_hidden_failure(self):
        self.write_file([test_line("s/one"), test_line("s/two", "fail"), summary_line(2, 2)])
        outcome, result = self.grade(self.write_expected(["s/one", "s/two"]))
        self.assertExit(outcome, 1)
        self.assertIn(("summary-mismatch", "a.jsonl"), self.rules(result))
        self.assertIn(("test-not-pass", "s/two"), self.rules(result))

    def test_two_summaries(self):
        self.write_file([test_line("s/one"), summary_line(1, 1), summary_line(1, 1)])
        outcome, result = self.grade(self.write_expected(["s/one"]))
        self.assertExit(outcome, 1)
        self.assertEqual(self.reasons_of(result), ["second-summary"])

    def test_test_line_after_summary(self):
        self.write_file([test_line("s/one"), summary_line(1, 1), test_line("s/two")])
        outcome, result = self.grade(self.write_expected(["s/one", "s/two"]))
        self.assertExit(outcome, 1)
        reasons = [f.get("reason") for f in result["findings"]]
        self.assertIn("line-after-summary", reasons)
        self.assertIn(("missing-test", "s/two"), self.rules(result))

    def test_summary_in_one_file_does_not_excuse_another(self):
        self.write_good(["s/one"], "a.jsonl")
        self.write_file([test_line("s/two")], "b.jsonl")
        self.assertRules(self.write_expected(["s/one", "s/two"]), [("missing-summary", "b.jsonl")])


class TestsGateMalformedLineTests(ResultsCase):
    BAD_LINES = {
        "not-json": ["{not json", "", "  ", "nan"],
        "not-object": ["[1]", '"text"', "null", "5"],
        "test-keys": ['{"id":"s/one","status":"pass"}',
                      '{"id":"s/one","status":"pass","asserts":1,"extra":1}',
                      '{"status":"pass","asserts":1}'],
        "bad-id": ['{"id":"noslash","status":"pass","asserts":1}',
                   '{"id":"a/b/c","status":"pass","asserts":1}',
                   '{"id":"a b/c","status":"pass","asserts":1}',
                   '{"id":"/c","status":"pass","asserts":1}',
                   '{"id":"a/","status":"pass","asserts":1}',
                   '{"id":5,"status":"pass","asserts":1}'],
        "bad-status": ['{"id":"s/o","status":"PASS","asserts":1}',
                       '{"id":"s/o","status":"ok","asserts":1}',
                       '{"id":"s/o","status":true,"asserts":1}'],
        "bad-asserts": ['{"id":"s/o","status":"pass","asserts":-1}',
                        '{"id":"s/o","status":"pass","asserts":1.5}',
                        '{"id":"s/o","status":"pass","asserts":"1"}',
                        '{"id":"s/o","status":"pass","asserts":true}',
                        '{"id":"s/o","status":"pass","asserts":null}'],
        "summary-keys": ['{"summary":{"total":1,"passed":1},"id":"s/o"}'],
        "bad-summary": ['{"summary":5}', '{"summary":{"total":1}}',
                        '{"summary":{"total":1,"passed":1,"x":1}}',
                        '{"summary":{"total":"1","passed":1}}',
                        '{"summary":{"total":true,"passed":1}}',
                        '{"summary":{"total":-1,"passed":0}}'],
    }

    def test_each_malformed_line_is_reported_with_its_reason_and_number(self):
        expected = self.write_expected(["s/one"])
        for reason, lines in self.BAD_LINES.items():
            for bad in lines:
                with self.subTest(reason=reason, line=bad):
                    self.write_file([test_line("s/one"), bad, summary_line(1, 1)])
                    outcome, result = self.grade(expected)
                    self.assertExit(outcome, 1)
                    found = [f for f in result["findings"] if f["rule"] == "malformed-line"]
                    self.assertEqual([(f["line"], f["reason"]) for f in found], [(2, reason)])

    def test_duplicate_keys_inside_a_line(self):
        self.write_file(['{"id":"s/one","status":"fail","status":"pass","asserts":1}',
                         summary_line(1, 1)])
        outcome, result = self.grade(self.write_expected(["s/one"]))
        self.assertExit(outcome, 1)
        self.assertEqual(self.reasons_of(result), ["not-json"])

    def test_nan_in_a_line(self):
        self.write_file(['{"id":"s/one","status":"pass","asserts":NaN}', summary_line(1, 1)])
        outcome, result = self.grade(self.write_expected(["s/one"]))
        self.assertExit(outcome, 1)
        self.assertEqual(self.reasons_of(result), ["not-json"])

    def test_invalid_utf8_in_a_line(self):
        (self.results / "a.jsonl").write_bytes(
            test_line("s/one").encode() + b"\n" + b'{"id":"s/\xff"}\n' + summary_line(1, 1).encode() + b"\n")
        outcome, result = self.grade(self.write_expected(["s/one"]))
        self.assertExit(outcome, 1)
        self.assertEqual(self.reasons_of(result), ["not-json"])

    def test_file_without_trailing_newline_is_accepted(self):
        (self.results / "a.jsonl").write_bytes(
            (test_line("s/one") + "\n" + summary_line(1, 1)).encode())
        self.assertRules(self.write_expected(["s/one"]), [], code=0)

    def test_blank_line_in_the_middle_is_malformed(self):
        (self.results / "a.jsonl").write_bytes(
            (test_line("s/one") + "\n\n" + summary_line(1, 1) + "\n").encode())
        outcome, _ = self.grade(self.write_expected(["s/one"]))
        self.assertExit(outcome, 1)


class TestsGateRatchetTests(ResultsCase):
    def setUp(self):
        super().setUp()
        self.write_good(["s/one"])
        self.expected = self.write_expected(["s/one"])
        self.previous = self.write_expected(["s/one", "s/old"], "prev.json")
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("a.txt", "1\n")
        self.first = self.repo.commit("first")
        self.repo.write("a.txt", "2\n")
        self.head = self.repo.commit("second")
        self.signer = Signer(self.tmp / "keys")
        self.allowed = self.signer.write_allowed_signers(self.tmp / "allowed_signers")
        self.dir = self.sub("approvals")

    def approve(self, scope, kind="test-removal", signer=None, repo_sha=None):
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", "ok",
                             "--repo-sha", repo_sha or self.first, "--key",
                             (signer or self.signer).key, "--out", self.dir])
        self.assertExit(outcome, 0)

    def approval_args(self):
        return ["--approvals", self.dir, "--allowed-signers", self.allowed,
                "--repo", self.repo.root, "--head", self.head]

    def test_removed_test_without_approval_fails(self):
        self.assertRules(self.expected, [("test-removed", "s/old")],
                         extra=["--previous", self.previous])

    def test_removed_test_with_valid_approval_passes(self):
        self.approve("s/old")
        outcome, result = self.grade(self.expected, ["--previous", self.previous]
                                     + self.approval_args())
        self.assertExit(outcome, 0)
        self.assertEqual(len(result["metadata"]["approvals_used"]), 1)

    def test_approval_for_another_test_does_not_cover(self):
        self.approve("s/other")
        outcome, result = self.grade(self.expected, ["--previous", self.previous]
                                     + self.approval_args())
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("test-removed", "s/old")])

    def test_approval_of_another_kind_does_not_cover(self):
        self.approve("s/old", kind="ratchet")
        outcome, _ = self.grade(self.expected, ["--previous", self.previous] + self.approval_args())
        self.assertExit(outcome, 1)

    def test_approval_from_non_ancestor_does_not_cover(self):
        self.approve("s/old", repo_sha="a" * 40)
        outcome, _ = self.grade(self.expected, ["--previous", self.previous] + self.approval_args())
        self.assertExit(outcome, 1)

    def test_forged_approval_fails_even_if_nothing_removed(self):
        (self.dir / "junk.txt").write_text("x")
        outcome, result = self.grade(self.expected, self.approval_args())
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("forged-approval", "junk.txt")])

    def test_unlisted_signer_does_not_cover_and_is_forged(self):
        self.approve("s/old", signer=Signer(self.tmp / "evil", name="evil"))
        outcome, result = self.grade(self.expected, ["--previous", self.previous]
                                     + self.approval_args())
        self.assertExit(outcome, 1)
        self.assertEqual(sorted(r for r, _ in self.rules(result)),
                         ["forged-approval", "test-removed"])

    def test_approvals_without_repo_and_head_is_exit_2(self):
        outcome, _ = self.grade(self.expected, ["--approvals", self.dir,
                                                "--allowed-signers", self.allowed])
        self.assertExit(outcome, 2)

    def test_missing_ssh_keygen_with_approvals_is_exit_2(self):
        self.approve("s/old")
        outcome = run_rigor(["tests", "--results", self.results, "--expected", self.expected,
                             "--previous", self.previous] + self.approval_args(),
                            path=str(self.sub("nobin")))
        self.assertExit(outcome, 2)


class TestsGateErrorTests(ResultsCase):
    def run_gate(self, expected, results=None, previous=None):
        args = ["tests", "--results", results or self.results, "--expected", expected]
        if previous is not None:
            args += ["--previous", previous]
        return run_rigor(args)

    def test_missing_results_directory_is_exit_2(self):
        expected = self.write_expected(["s/one"])
        self.assertExit(self.run_gate(expected, results=self.tmp / "nope"), 2)

    def test_results_path_that_is_a_file_is_exit_2(self):
        expected = self.write_expected(["s/one"])
        plain = self.tmp / "plain"
        plain.write_text("x")
        self.assertExit(self.run_gate(expected, results=plain), 2)

    def test_missing_expected_file_is_exit_2(self):
        self.write_good(["s/one"])
        self.assertExit(self.run_gate(self.tmp / "nope.json"), 2)

    def test_missing_previous_file_is_exit_2(self):
        self.write_good(["s/one"])
        self.assertExit(self.run_gate(self.write_expected(["s/one"]), previous=self.tmp / "no"), 2)

    def test_malformed_expected_lists_are_exit_2(self):
        self.write_good(["s/one"])
        bad_documents = ["not json", "[]", "{}", '{"ids": "s/one"}', '{"ids": [1]}',
                         '{"ids": ["noslash"]}', '{"ids": ["s/one", "s/one"]}',
                         '{"ids": ["s/one"], "extra": 1}', '{"ids": ["s/one"], "ids": []}']
        for text in bad_documents:
            with self.subTest(text=text):
                path = self.tmp / "bad.json"
                path.write_text(text)
                self.assertExit(self.run_gate(path), 2)

    def test_malformed_previous_list_is_exit_2(self):
        self.write_good(["s/one"])
        path = self.tmp / "bad.json"
        path.write_text('{"ids": "x"}')
        self.assertExit(self.run_gate(self.write_expected(["s/one"]), previous=path), 2)

    def test_internal_error_replaces_stale_out_with_fail(self):
        out = self.tmp / "tests.json"
        out.write_text('{"status":"PASS"}')
        run_rigor(["tests", "--results", self.tmp / "nope", "--expected",
                   self.write_expected(["s/one"]), "--out", out])
        self.assertEqual(read_json(out)["status"], "FAIL")
        self.assertEqual(read_json(out)["gate"], "tests")
