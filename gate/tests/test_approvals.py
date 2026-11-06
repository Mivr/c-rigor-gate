"""Tests for approvals: creation (`rigor approve`) and verification."""

import hashlib
import json
import os
from pathlib import Path
from unittest import mock

from rigor_lib import approvals
from rigor_lib.errors import InternalError
from tests.helpers import Repo, Signer, TempDirTestCase, run_rigor

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
        self.signer = Signer(self.tmp / "keys")
        self.allowed = self.signer.write_allowed_signers(self.tmp / "allowed_signers")
        self.dir = self.sub("approvals")

    def make(self, kind="suppression", scope=SCOPE, reason="because", repo_sha=None,
             signer=None, allowed_out=None):
        signer = signer or self.signer
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", reason,
                             "--repo-sha", repo_sha or self.first, "--key", signer.key,
                             "--out", allowed_out or self.dir])
        self.assertExit(outcome, 0)
        return Path(outcome.stdout.strip())

    def load(self, repo_sha_head=None, allowed=None):
        return approvals.load_approvals(self.dir, self.repo.root, repo_sha_head or self.head,
                                        allowed or self.allowed)

    def put_raw(self, data, sign_with=None, namespace=None, stem=None, sign=True):
        """Write arbitrary bytes as an approval, optionally signed, named by their hash."""
        stem = stem or hashlib.sha256(data).hexdigest()
        path = self.dir / (stem + ".json")
        path.write_bytes(data)
        if sign:
            (sign_with or self.signer).sign_file(path, namespace)
        return path

    def valid_doc(self, **changes):
        doc = {"kind": "suppression", "scope": SCOPE, "reason": "r", "repo_sha": self.first}
        doc.update(changes)
        return doc

    def reasons(self, result):
        return sorted(p["reason"] for p in result.problems)


class ApproveCommandTests(ApprovalCase):
    def test_writes_json_and_signature_named_by_hash(self):
        path = self.make()
        self.assertEqual(path.name, hashlib.sha256(path.read_bytes()).hexdigest() + ".json")
        self.assertTrue(Path(str(path) + ".sig").is_file())

    def test_json_is_canonical_and_complete(self):
        path = self.make(kind="ratchet", scope="r.toml:k", reason="why")
        expected = canonical({"kind": "ratchet", "scope": "r.toml:k", "reason": "why",
                              "repo_sha": self.first})
        self.assertEqual(path.read_bytes(), expected)

    def test_created_approval_verifies(self):
        self.make()
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_output_directory_is_created(self):
        self.make(allowed_out=self.tmp / "new" / "dir")
        self.assertEqual(len(list((self.tmp / "new" / "dir").iterdir())), 2)

    def run_approve(self, **overrides):
        args = {"--kind": "suppression", "--scope": SCOPE, "--reason": "r",
                "--repo-sha": self.first, "--key": self.signer.key, "--out": self.dir}
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

    def test_missing_key_is_exit_2_and_leaves_nothing_behind(self):
        self.assertExit(self.run_approve(**{"--key": self.tmp / "nokey"}), 2)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_missing_ssh_keygen_is_exit_2_and_leaves_nothing_behind(self):
        outcome = run_rigor(["approve", "--kind", "suppression", "--scope", SCOPE,
                             "--reason", "r", "--repo-sha", self.first,
                             "--key", self.signer.key, "--out", self.dir],
                            path=str(self.sub("nobin")))
        self.assertExit(outcome, 2)
        self.assertEqual(list(self.dir.iterdir()), [])


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

    def test_signer_with_other_principal_name_is_accepted(self):
        other = Signer(self.tmp / "k2", name="second", principal="orchestrator")
        allowed = other.write_allowed_signers(self.tmp / "allowed2", [self.signer.allowed_line])
        self.make(signer=other)
        self.assertIsNotNone(self.load(allowed=allowed).covering("suppression", SCOPE))


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
    def test_unsigned_approval(self):
        self.put_raw(canonical(self.valid_doc()), sign=False)
        result = self.load()
        self.assertEqual(self.reasons(result), ["unsigned"])
        self.assertIsNone(result.covering("suppression", SCOPE))

    def test_signature_from_unlisted_key(self):
        attacker = Signer(self.tmp / "evil", name="evil", principal="owner")
        self.put_raw(canonical(self.valid_doc()), sign_with=attacker)
        result = self.load()
        self.assertEqual(self.reasons(result), ["signature-rejected"])
        self.assertIsNone(result.covering("suppression", SCOPE))

    def test_signature_with_wrong_namespace(self):
        self.put_raw(canonical(self.valid_doc()), namespace="git")
        self.assertEqual(self.reasons(self.load()), ["signature-rejected"])

    def test_allowed_signers_entry_limited_to_another_namespace(self):
        limited = Signer(self.tmp / "k3", name="limited", principal="owner", namespaces="other")
        allowed = limited.write_allowed_signers(self.tmp / "allowed3")
        self.put_raw(canonical(self.valid_doc()), sign_with=limited)
        self.assertEqual(self.reasons(self.load(allowed=allowed)), ["signature-rejected"])

    def test_tampered_content_with_old_name(self):
        path = self.make()
        doc = json.loads(path.read_text())
        doc["scope"] = "other:1-nolint"
        path.write_bytes(canonical(doc))
        self.assertEqual(self.reasons(self.load()), ["name-mismatch"])

    def test_tampered_content_renamed_to_its_own_hash(self):
        path = self.make()
        sig = Path(str(path) + ".sig")
        doc = json.loads(path.read_text())
        doc["scope"] = "other:1-nolint"
        data = canonical(doc)
        stem = hashlib.sha256(data).hexdigest()
        path.unlink()
        (self.dir / (stem + ".json")).write_bytes(data)
        sig.rename(self.dir / (stem + ".json.sig"))
        result = self.load()
        self.assertEqual(self.reasons(result), ["signature-rejected"])
        self.assertIsNone(result.covering("suppression", "other:1-nolint"))

    def test_garbage_signature_file(self):
        path = self.put_raw(canonical(self.valid_doc()), sign=False)
        Path(str(path) + ".sig").write_bytes(b"not a signature\n")
        self.assertEqual(self.reasons(self.load()), ["signature-rejected"])

    def test_empty_signature_file(self):
        path = self.put_raw(canonical(self.valid_doc()), sign=False)
        Path(str(path) + ".sig").write_bytes(b"")
        self.assertEqual(self.reasons(self.load()), ["signature-rejected"])

    def test_signature_without_approval(self):
        path = self.make()
        path.unlink()
        self.assertEqual(self.reasons(self.load()), ["orphan-signature"])

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

    def test_signed_but_not_json(self):
        self.put_raw(b"not json\n")
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_signed_but_not_an_object(self):
        self.put_raw(b"[1,2]\n")
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_signed_with_duplicate_keys(self):
        self.put_raw(b'{"kind":"suppression","kind":"ratchet","scope":"s","reason":"r","repo_sha":"%s"}\n'
                     % self.first.encode())
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_signed_with_missing_key(self):
        doc = self.valid_doc()
        del doc["reason"]
        self.put_raw(canonical(doc))
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_signed_with_extra_key(self):
        self.put_raw(canonical(self.valid_doc(extra="x")))
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_signed_with_unknown_kind(self):
        self.put_raw(canonical(self.valid_doc(kind="anything")))
        self.assertEqual(self.reasons(self.load()), ["malformed"])

    def test_signed_with_bad_field_types_or_values(self):
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
    def test_missing_ssh_keygen_is_an_internal_error(self):
        self.make()
        with mock.patch.dict(os.environ, {"PATH": str(self.sub("nobin"))}):
            with self.assertRaises(InternalError):
                self.load()

    def test_missing_allowed_signers_is_an_internal_error(self):
        self.make()
        with self.assertRaises(InternalError):
            self.load(allowed=self.tmp / "missing")

    def test_missing_approvals_directory_is_an_internal_error(self):
        with self.assertRaises(InternalError):
            approvals.load_approvals(self.tmp / "nodir", self.repo.root, self.head, self.allowed)

    def test_approvals_path_that_is_a_file_is_an_internal_error(self):
        plain = self.tmp / "file"
        plain.write_text("x")
        with self.assertRaises(InternalError):
            approvals.load_approvals(plain, self.repo.root, self.head, self.allowed)


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
