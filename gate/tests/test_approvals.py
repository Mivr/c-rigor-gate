"""Tests for approvals: creation (`rigor approve`) and checking (U30: nothing is signed)."""

import hashlib
import json
import os
from pathlib import Path
from unittest import mock

from rigor_lib import approvals
from rigor_lib.errors import InternalError
from rigor_lib import verdict
from tests.helpers import Repo, TempDirTestCase, run_rigor

SCOPE = "src/a.c:3-nolint"


def canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode()


class ApprovalCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("a.txt", "1\n")
        self.first = self.repo.commit("first")
        self.repo.branch("task")
        self.repo.write("a.txt", "2\n")
        self.head = self.repo.commit("second")
        self.dir = self.sub("approvals")

    def make(self, kind="suppression", scope=SCOPE, reason="because", repo_sha=None, out=None):
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", reason,
                             "--repo-sha", repo_sha or self.first, "--out", out or self.dir])
        self.assertExit(outcome, 0)
        return Path(outcome.stdout.strip())

    def load(self, repo_sha_head=None):
        return approvals.load_approvals(self.dir, self.repo.root, repo_sha_head or self.head)

    def put_raw(self, data, stem=None):
        """Write arbitrary bytes as an approval, named by their hash."""
        stem = stem or hashlib.sha256(data).hexdigest()
        path = self.dir / (stem + ".json")
        path.write_bytes(data)
        return path

    def valid_doc(self, **changes):
        doc = {"kind": "suppression", "scope": SCOPE, "reason": "r", "repo_sha": self.first}
        doc.update(changes)
        return doc

    def reasons(self, result):
        return sorted(p["reason"] for p in result.problems)


class ApproveCommandTests(ApprovalCase):
    def test_writes_only_the_json_named_by_hash(self):
        path = self.make()
        self.assertEqual(path.name, hashlib.sha256(path.read_bytes()).hexdigest() + ".json")
        self.assertEqual(list(self.dir.iterdir()), [path])

    def test_json_is_canonical_and_complete(self):
        path = self.make(kind="ratchet", scope="r.toml:k", reason="why")
        expected = canonical({"kind": "ratchet", "scope": "r.toml:k", "reason": "why",
                              "repo_sha": self.first})
        self.assertEqual(path.read_bytes(), expected)

    def test_created_approval_is_valid(self):
        self.make()
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_output_directory_is_created(self):
        self.make(out=self.tmp / "new" / "dir")
        self.assertEqual(len(list((self.tmp / "new" / "dir").iterdir())), 1)

    def run_approve(self, **overrides):
        args = {"--kind": "suppression", "--scope": SCOPE, "--reason": "r",
                "--repo-sha": self.first, "--out": self.dir}
        args.update(overrides)
        flat = [item for pair in args.items() for item in pair]
        return run_rigor(["approve"] + flat)

    def test_unknown_kind_is_exit_2(self):
        self.assertExit(self.run_approve(**{"--kind": "anything"}), 2)

    def test_empty_scope_or_reason_is_exit_2(self):
        self.assertExit(self.run_approve(**{"--scope": ""}), 2)
        self.assertExit(self.run_approve(**{"--reason": ""}), 2)

    def test_bad_repo_sha_is_exit_2(self):
        for sha in ("main", "abc", "A" * 40, "g" * 40):
            self.assertExit(self.run_approve(**{"--repo-sha": sha}), 2)

    def test_a_key_is_refused_and_leaves_nothing_behind(self):
        self.assertExit(self.run_approve(**{"--key": self.tmp / "key"}), 2)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_writing_needs_no_tool_on_the_path(self):
        outcome = run_rigor(["approve", "--kind", "suppression", "--scope", SCOPE, "--reason", "r",
                             "--repo-sha", self.first, "--out", self.dir], path=str(self.sub("nobin")))
        self.assertExit(outcome, 0)
        self.assertEqual(len(list(self.dir.iterdir())), 1)


class ApprovalGreenTests(ApprovalCase):
    def test_covers_only_the_exact_kind_and_scope(self):
        self.make()
        result = self.load()
        self.assertIsNotNone(result.covering("suppression", SCOPE))
        self.assertIsNone(result.covering("suppression", SCOPE + "x"))
        self.assertIsNone(result.covering("suppression", "x" + SCOPE))
        self.assertIsNone(result.covering("test-removal", SCOPE))
        self.assertIsNone(result.covering("ratchet", SCOPE))

    def test_repo_sha_equal_to_head_is_valid(self):
        self.make(repo_sha=self.head)
        self.assertIsNotNone(self.load().covering("suppression", SCOPE))

    def test_empty_directory_needs_no_tools(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.sub("nobin"))}):
            result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNone(result.covering("suppression", SCOPE))

    def test_two_approvals_side_by_side(self):
        self.make(scope="a:1-nolint")
        self.make(scope="b:2-nolint")
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNotNone(result.covering("suppression", "a:1-nolint"))
        self.assertIsNotNone(result.covering("suppression", "b:2-nolint"))

    def test_a_hand_written_canonical_file_is_the_record(self):
        self.put_raw(canonical(self.valid_doc()))
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_every_valid_approval_is_counted_in_force(self):
        self.make(scope="b:2-nolint")
        self.make(scope="a:1-nolint", kind="ratchet")
        block = verdict.approvals_in_force(self.load().valid)
        self.assertEqual(block["count"], 2)
        self.assertEqual(sorted((e["kind"], e["scope"], e["reason"]) for e in block["in_force"]),
                         [("ratchet", "a:1-nolint", "because"), ("suppression", "b:2-nolint", "because")])
        self.assertEqual(sorted(e["stem"] for e in block["in_force"]), [e["stem"] for e in block["in_force"]])


class ApprovalNotApplicableTests(ApprovalCase):
    def test_repo_sha_not_an_ancestor_is_ignored_not_forged(self):
        self.repo.git("checkout", "-q", self.first)
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.write("side.txt", "s\n")
        side = self.repo.commit("side")
        self.make(repo_sha=side)
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNone(result.covering("suppression", SCOPE))

    def test_unknown_repo_sha_is_ignored_not_forged(self):
        self.make(repo_sha="a" * 40)
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNone(result.covering("suppression", SCOPE))

    def test_descendant_of_head_is_not_an_ancestor(self):
        self.repo.write("later.txt", "l\n")
        later = self.repo.commit("later")
        self.make(repo_sha=later)
        self.assertIsNone(self.load(repo_sha_head=self.head).covering("suppression", SCOPE))


class ApprovalForgedTests(ApprovalCase):
    def test_an_approval_bound_to_another_target_covers_nothing_else(self):
        self.put_raw(canonical(self.valid_doc(scope="other:1-nolint")))
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNone(result.covering("suppression", SCOPE))
        self.assertIsNone(result.covering("ratchet", "other:1-nolint"))
        self.assertIsNotNone(result.covering("suppression", "other:1-nolint"))

    def test_tampered_content_with_old_name(self):
        path = self.make()
        doc = json.loads(path.read_text())
        doc["scope"] = "other:1-nolint"
        path.write_bytes(canonical(doc))
        self.assertEqual(self.reasons(self.load()), ["name-mismatch"])

    def test_tampered_content_renamed_to_its_own_hash_is_a_new_approval_and_is_counted(self):
        """U30: nothing signs an approval, so a rewritten one is simply another approval. It covers only its
        own scope (never the one it replaced) and the verdict counts and lists it."""
        path = self.make()
        doc = json.loads(path.read_text())
        doc["scope"] = "other:1-nolint"
        data = canonical(doc)
        stem = hashlib.sha256(data).hexdigest()
        path.unlink()
        (self.dir / (stem + ".json")).write_bytes(data)
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNone(result.covering("suppression", SCOPE))
        self.assertIsNotNone(result.covering("suppression", "other:1-nolint"))
        self.assertEqual(verdict.approvals_in_force(result.valid)["in_force"][0]["stem"], stem)

    def test_a_signature_file_left_beside_an_approval_is_a_problem(self):
        path = self.put_raw(canonical(self.valid_doc()))
        Path(str(path) + ".sig").write_bytes(b"not a signature\n")
        result = self.load()
        self.assertEqual(self.reasons(result), ["signature-file"])
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_an_empty_signature_file_is_a_problem(self):
        path = self.put_raw(canonical(self.valid_doc()))
        Path(str(path) + ".sig").write_bytes(b"")
        self.assertEqual(self.reasons(self.load()), ["signature-file"])

    def test_a_signature_without_approval_is_a_problem(self):
        path = self.make()
        Path(str(path) + ".sig").write_bytes(b"x")
        path.unlink()
        self.assertEqual(self.reasons(self.load()), ["signature-file"])

    def test_unrecognised_file_in_directory(self):
        (self.dir / "notes.txt").write_text("hi")
        self.assertEqual(self.reasons(self.load()), ["unrecognised-file"])

    def test_subdirectory_in_directory(self):
        (self.dir / ("ab" * 32 + ".json")).mkdir()
        self.assertEqual(self.reasons(self.load()), ["unrecognised-file"])

    def test_approval_that_is_a_symlink(self):
        path = self.make()
        real = self.tmp / "elsewhere.json"
        real.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(real)
        self.assertEqual(self.reasons(self.load()), ["unrecognised-file"])

    def test_not_json(self):
        self.put_raw(b"not json\n")
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_not_an_object(self):
        self.put_raw(b"[1,2]\n")
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_with_duplicate_keys(self):
        self.put_raw(b'{"kind":"suppression","kind":"ratchet","scope":"s","reason":"r","repo_sha":"%s"}\n'
                     % self.first.encode())
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_with_missing_key(self):
        doc = self.valid_doc()
        del doc["reason"]
        self.put_raw(canonical(doc))
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_with_extra_key(self):
        self.put_raw(canonical(self.valid_doc(extra="x")))
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_with_unknown_kind(self):
        self.put_raw(canonical(self.valid_doc(kind="anything")))
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_with_bad_field_types_or_values(self):
        for changes in ({"scope": ""}, {"scope": 1}, {"reason": ""}, {"reason": None},
                        {"repo_sha": "main"}, {"repo_sha": "A" * 40}, {"repo_sha": 5}):
            for old in self.dir.iterdir():
                old.unlink()
            self.put_raw(canonical(self.valid_doc(**changes)))
            self.assertEqual(self.reasons(self.load()), ["malformed"], changes)

    def test_forged_does_not_hide_a_good_one(self):
        self.make()
        (self.dir / "junk.txt").write_text("x")
        result = self.load()
        self.assertEqual(self.reasons(result), ["unrecognised-file"])
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_findings_are_forged_approval_errors_naming_the_file(self):
        (self.dir / "junk.txt").write_text("x")
        problem = self.load().problems[0]
        self.assertEqual((problem["rule"], problem["severity"], problem["file"]),
                         ("forged-approval", "error", "junk.txt"))


class ApprovalFailClosedTests(ApprovalCase):
    def test_missing_approvals_directory_is_an_internal_error(self):
        with self.assertRaises(InternalError):
            approvals.load_approvals(self.tmp / "nodir", self.repo.root, self.head)

    def test_approvals_path_that_is_a_file_is_an_internal_error(self):
        plain = self.tmp / "file"
        plain.write_text("x")
        with self.assertRaises(InternalError):
            approvals.load_approvals(plain, self.repo.root, self.head)


class ApprovalHistorySubstitutionTests(ApprovalCase):
    def side_commit(self):
        self.repo.git("checkout", "-q", self.first)
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.write("side.txt", "s\n")
        side = self.repo.commit("side")
        self.repo.git("checkout", "-q", "task")
        return side

    def test_graft_cannot_make_a_non_ancestor_look_like_an_ancestor(self):
        side = self.side_commit()
        self.make(repo_sha=side)
        grafts = self.repo.root / ".git" / "info" / "grafts"
        grafts.parent.mkdir(exist_ok=True)
        grafts.write_text("%s %s %s\n" % (self.head, self.first, side))
        self.assertIsNone(self.load().covering("suppression", SCOPE))

    def test_replace_ref_cannot_make_a_non_ancestor_look_like_an_ancestor(self):
        side = self.side_commit()
        self.make(repo_sha=side)
        self.repo.git("checkout", "-q", "--detach", self.head)
        twin = self.repo.git("commit-tree", self.head + "^{tree}", "-p", self.first, "-p", side,
                             "-m", "twin")
        self.repo.git("replace", self.head, twin)
        self.assertIsNone(self.load().covering("suppression", SCOPE))
