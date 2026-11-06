"""Tests for `rigor ratchet`."""

from tests.helpers import Repo, Signer, TempDirTestCase, read_json, run_rigor

SPEC = """
[max_mutants]
direction = "down"

[min_tests]
direction = "up"

[open_issues]
direction = "shrink"
"""

OLD = """
max_mutants = 10
min_tests = 50
open_issues = ["a", "b"]
"""


class RatchetCase(TempDirTestCase):
    def grade(self, new_text, old_text=OLD, spec_text=SPEC, extra=(), new_name="n.toml"):
        old = self.tmp / "o.toml"
        new = self.tmp / new_name
        spec = self.tmp / "s.toml"
        old.write_text(old_text, encoding="utf-8")
        new.write_text(new_text, encoding="utf-8")
        spec.write_text(spec_text, encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["ratchet", "--old", old, "--new", new, "--spec", spec,
                             "--out", out] + list(extra))
        return outcome, (read_json(out) if out.exists() else None)

    def rules(self, result):
        return sorted((f["rule"], f.get("key")) for f in result["findings"])

    def assertRules(self, new_text, expected, code, **kw):
        outcome, result = self.grade(new_text, **kw)
        self.assertExit(outcome, code)
        self.assertEqual(self.rules(result), sorted(expected))
        return result


class RatchetGreenTests(RatchetCase):
    def test_unchanged(self):
        self.assertRules(OLD, [], 0)

    def test_every_key_moves_the_right_way(self):
        new = 'max_mutants = 3\nmin_tests = 80\nopen_issues = ["a"]\n'
        self.assertRules(new, [], 0)

    def test_shrink_to_empty(self):
        self.assertRules('max_mutants = 10\nmin_tests = 50\nopen_issues = []\n', [], 0)

    def test_shrink_ignores_order(self):
        self.assertRules('max_mutants = 10\nmin_tests = 50\nopen_issues = ["b", "a"]\n', [], 0)

    def test_floats_and_ints_compare(self):
        old = 'max_mutants = 10.5\nmin_tests = 50\nopen_issues = []\n'
        new = 'max_mutants = 10\nmin_tests = 50.25\nopen_issues = []\n'
        self.assertRules(new, [], 0, old_text=old)

    def test_new_key_without_baseline_is_info_only(self):
        old = 'max_mutants = 10\nmin_tests = 50\n'
        result = self.assertRules(OLD, [("new-key", "open_issues")], 0, old_text=old)
        self.assertEqual(result["findings"][0]["severity"], "info")

    def test_findings_are_identical_on_rerun(self):
        new = 'max_mutants = 11\nmin_tests = 49\nopen_issues = ["a", "b", "c"]\n'
        _, first = self.grade(new)
        _, second = self.grade(new)
        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(len(first["findings"]), 3)


class RatchetRedTests(RatchetCase):
    def test_down_key_went_up(self):
        result = self.assertRules('max_mutants = 11\nmin_tests = 50\nopen_issues = ["a", "b"]\n',
                                  [("ratchet-regressed", "max_mutants")], 1)
        self.assertEqual((result["findings"][0]["old"], result["findings"][0]["new"]), (10, 11))

    def test_up_key_went_down(self):
        self.assertRules('max_mutants = 10\nmin_tests = 49\nopen_issues = ["a", "b"]\n',
                         [("ratchet-regressed", "min_tests")], 1)

    def test_float_regression(self):
        self.assertRules('max_mutants = 10.0001\nmin_tests = 50\nopen_issues = ["a", "b"]\n',
                         [("ratchet-regressed", "max_mutants")], 1)

    def test_shrink_key_grew_and_names_the_additions(self):
        result = self.assertRules('max_mutants = 10\nmin_tests = 50\nopen_issues = ["z", "a", "b", "c"]\n',
                                  [("ratchet-regressed", "open_issues")], 1)
        self.assertEqual(result["findings"][0]["added"], ["c", "z"])

    def test_shrink_key_swapped_an_element(self):
        self.assertRules('max_mutants = 10\nmin_tests = 50\nopen_issues = ["a", "x"]\n',
                         [("ratchet-regressed", "open_issues")], 1)

    def test_key_missing_from_new(self):
        self.assertRules('max_mutants = 10\nmin_tests = 50\n', [("missing-key", "open_issues")], 1)

    def test_key_missing_from_both_old_and_new(self):
        self.assertRules('max_mutants = 10\nmin_tests = 50\n',
                         [("missing-key", "open_issues")], 1,
                         old_text='max_mutants = 10\nmin_tests = 50\n')

    def test_key_in_new_not_in_spec(self):
        self.assertRules(OLD + "sneaky = 1\n", [("unspecified-key", "sneaky")], 1)

    def test_table_in_new_not_in_spec(self):
        self.assertRules(OLD + "[sneaky]\nx = 1\n", [("unspecified-key", "sneaky")], 1)

    def test_wrong_value_types_are_bad_values(self):
        cases = ['max_mutants = "3"', "max_mutants = true", 'max_mutants = ["a"]',
                 "max_mutants = nan", "max_mutants = inf", "max_mutants = 1979-05-27",
                 "max_mutants = { a = 1 }"]
        for line in cases:
            with self.subTest(line=line):
                new = line + '\nmin_tests = 50\nopen_issues = ["a", "b"]\n'
                outcome, result = self.grade(new)
                self.assertExit(outcome, 1)
                self.assertEqual(self.rules(result), [("bad-value", "max_mutants")])
                self.assertEqual(result["findings"][0]["side"], "new")

    def test_wrong_shrink_values_are_bad_values(self):
        for line in ('open_issues = 3', 'open_issues = "a"', 'open_issues = [1]',
                     'open_issues = ["a", "a"]', 'open_issues = [["a"]]'):
            with self.subTest(line=line):
                outcome, result = self.grade('max_mutants = 10\nmin_tests = 50\n' + line + "\n")
                self.assertExit(outcome, 1)
                self.assertEqual(self.rules(result), [("bad-value", "open_issues")])

    def test_bad_value_in_old_is_reported_on_the_old_side(self):
        old = 'max_mutants = "x"\nmin_tests = 50\nopen_issues = ["a", "b"]\n'
        outcome, result = self.grade(OLD, old_text=old)
        self.assertExit(outcome, 1)
        self.assertEqual([(f["rule"], f["side"]) for f in result["findings"]],
                         [("bad-value", "old")])

    def test_integer_where_a_set_is_expected(self):
        outcome, result = self.grade('max_mutants = 10\nmin_tests = 50\nopen_issues = 0\n')
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("bad-value", "open_issues")])


class RatchetApprovalTests(RatchetCase):
    REGRESSED = 'max_mutants = 11\nmin_tests = 50\nopen_issues = ["a", "b"]\n'

    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("a.txt", "1\n")
        self.first = self.repo.commit("first")
        self.repo.write("a.txt", "2\n")
        self.head = self.repo.commit("second")
        self.signer = Signer(self.tmp / "keys")
        self.allowed = self.signer.write_allowed_signers(self.tmp / "allowed_signers")
        self.dir = self.sub("approvals")

    def approve(self, scope, kind="ratchet", signer=None, repo_sha=None):
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", "ok",
                             "--repo-sha", repo_sha or self.first, "--key",
                             (signer or self.signer).key, "--out", self.dir])
        self.assertExit(outcome, 0)

    def approval_args(self):
        return ["--approvals", self.dir, "--allowed-signers", self.allowed,
                "--repo", self.repo.root, "--head", self.head]

    def grade_approved(self, new_text=REGRESSED):
        return self.grade(new_text, extra=self.approval_args())

    def test_exact_scope_covers_the_regression(self):
        self.approve("n.toml:max_mutants")
        outcome, result = self.grade_approved()
        self.assertExit(outcome, 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["metadata"]["approvals_used"]), 1)

    def test_scope_uses_the_file_name_of_new(self):
        self.approve("n.toml:max_mutants")
        outcome, _ = self.grade(self.REGRESSED, extra=self.approval_args(), new_name="other.toml")
        self.assertExit(outcome, 1)

    def test_other_key_does_not_cover(self):
        self.approve("n.toml:min_tests")
        outcome, _ = self.grade_approved()
        self.assertExit(outcome, 1)

    def test_other_kind_does_not_cover(self):
        self.approve("n.toml:max_mutants", kind="suppression")
        outcome, _ = self.grade_approved()
        self.assertExit(outcome, 1)

    def test_non_ancestor_does_not_cover(self):
        self.approve("n.toml:max_mutants", repo_sha="a" * 40)
        outcome, _ = self.grade_approved()
        self.assertExit(outcome, 1)

    def test_unlisted_signer_is_forged_and_does_not_cover(self):
        self.approve("n.toml:max_mutants", signer=Signer(self.tmp / "evil", name="evil"))
        outcome, result = self.grade_approved()
        self.assertExit(outcome, 1)
        self.assertEqual(sorted(r for r, _ in self.rules(result)),
                         ["forged-approval", "ratchet-regressed"])

    def test_approval_does_not_excuse_a_missing_key(self):
        self.approve("n.toml:open_issues")
        outcome, result = self.grade_approved('max_mutants = 10\nmin_tests = 50\n')
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("missing-key", "open_issues")])

    def test_approval_does_not_excuse_an_unspecified_key(self):
        self.approve("n.toml:sneaky")
        outcome, _ = self.grade_approved(OLD + "sneaky = 1\n")
        self.assertExit(outcome, 1)

    def test_forged_approval_fails_a_clean_ratchet(self):
        (self.dir / "junk.txt").write_text("x")
        outcome, result = self.grade_approved(OLD)
        self.assertExit(outcome, 1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["forged-approval"])

    def test_approvals_without_repo_and_head_is_exit_2(self):
        outcome, _ = self.grade(self.REGRESSED, extra=["--approvals", self.dir,
                                                       "--allowed-signers", self.allowed])
        self.assertExit(outcome, 2)

    def test_missing_ssh_keygen_with_approvals_is_exit_2(self):
        self.approve("n.toml:max_mutants")
        self.grade(self.REGRESSED)  # leaves o.toml, n.toml, s.toml in place
        outcome = run_rigor(["ratchet", "--old", self.tmp / "o.toml", "--new", self.tmp / "n.toml",
                             "--spec", self.tmp / "s.toml"] + self.approval_args(),
                            path=str(self.sub("nobin")))
        self.assertExit(outcome, 2)


class RatchetErrorTests(RatchetCase):
    def test_malformed_toml_in_any_file_is_exit_2(self):
        bad = "this is = = not toml"
        outcome, _ = self.grade(bad)
        self.assertExit(outcome, 2)
        outcome, _ = self.grade(OLD, old_text=bad)
        self.assertExit(outcome, 2)
        outcome, _ = self.grade(OLD, spec_text=bad)
        self.assertExit(outcome, 2)

    def test_missing_files_are_exit_2(self):
        for missing in ("o.toml", "n.toml", "s.toml"):
            for name in ("o.toml", "n.toml", "s.toml"):
                (self.tmp / name).write_text(OLD if name != "s.toml" else SPEC)
            (self.tmp / missing).unlink()
            outcome = run_rigor(["ratchet", "--old", self.tmp / "o.toml", "--new",
                                 self.tmp / "n.toml", "--spec", self.tmp / "s.toml"])
            self.assertExit(outcome, 2)

    def test_bad_specs_are_exit_2(self):
        specs = ["", '[k]\n', '[k]\ndirection = "sideways"\n', '[k]\ndirection = 1\n',
                 '[k]\ndirection = "down"\nextra = 1\n', 'k = "down"\n', '[k]\n[k.sub]\n']
        for spec in specs:
            with self.subTest(spec=spec):
                outcome, _ = self.grade(OLD, spec_text=spec)
                self.assertExit(outcome, 2)

    def test_internal_error_writes_fail_result(self):
        outcome, result = self.grade(OLD, spec_text="")
        self.assertExit(outcome, 2)
        self.assertEqual((result["gate"], result["status"]), ("ratchet", "FAIL"))
