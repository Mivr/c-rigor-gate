"""Tests for the claim ledger: chain verification, tampering, claims, debt cap, tighten-only."""

import hashlib
import shutil
from pathlib import Path

from rigor_lib import ledger
from tests.helpers import TempDirTestCase, run_rigor

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ledger" / "known"
FIXTURE_HEAD = "560e0e4a7d9176489cba3dbadb61456f96796b6c7dbf07fe1e749a53181c83c3"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def claim_subject(kind="equivalent-mutant", scope="m1", sha=SHA_A):
    return ledger.make_subject(kind, scope, sha)


class LedgerCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.dir = self.sub("ledger")

    def add(self, kind, subject, evidence="", at=1):
        return ledger.append(str(self.dir), kind, subject, evidence, at)

    def file1(self):
        return self.dir / "000001.jsonl"

    def lines(self):
        return self.file1().read_bytes().splitlines(keepends=True)

    def fill(self):
        self.add("claim", claim_subject(), at=10)
        self.add("claim", claim_subject(scope="m2", sha=SHA_B), at=11)
        self.add("ratchet", "ram:core", at=12)

    def assertTampered(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.verify(str(self.dir))
        out = run_rigor(["ledger", "verify", "--ledger", self.dir])
        self.assertExit(out, 1)


class FixtureTests(TempDirTestCase):
    def test_known_head(self):
        self.assertEqual(ledger.verify(str(FIXTURE)), FIXTURE_HEAD)
        self.assertEqual(ledger.head(str(FIXTURE)), FIXTURE_HEAD)

    def test_cli_prints_head_and_checks_expected_head(self):
        out = run_rigor(["ledger", "verify", "--ledger", FIXTURE, "--head", FIXTURE_HEAD])
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), FIXTURE_HEAD)
        self.assertExit(run_rigor(["ledger", "verify", "--ledger", FIXTURE, "--head", SHA_A]), 1)

    def test_fixture_claims(self):
        subjects = [e["subject"] for e in ledger.standing_claims(str(FIXTURE))]
        self.assertEqual(subjects, ["suppression:src/a.c:3-x:" + SHA_B])


class VerifyTests(LedgerCase):
    def test_empty_ledger_head_is_zeros(self):
        self.assertEqual(ledger.verify(str(self.dir)), "0" * 64)

    def test_append_chains_and_head_moves(self):
        first = self.add("claim", claim_subject())
        second = self.add("ratchet", "ram:core")
        self.assertNotEqual(first, second)
        self.assertEqual(ledger.verify(str(self.dir)), second)
        self.assertEqual(ledger.verify(str(self.dir), first), second)  # growth is not truncation

    def test_edited_entry(self):
        self.fill()
        self.file1().write_bytes(self.file1().read_bytes().replace(b'"at":11', b'"at":12'))
        self.assertTampered()

    def test_edited_last_entry_changes_head(self):
        self.fill()
        before = ledger.head(str(self.dir))
        self.file1().write_bytes(self.file1().read_bytes().replace(b'"at":12', b'"at":13'))
        self.assertNotEqual(ledger.head(str(self.dir)), before)  # no later entry notices; the bound head does
        with self.assertRaises(ledger.LedgerError):
            ledger.verify(str(self.dir), before)

    def test_non_canonical_entry(self):
        self.fill()
        lines = self.lines()
        lines[0] = lines[0].replace(b",", b", ", 1)
        self.file1().write_bytes(b"".join(lines))
        self.assertTampered()

    def test_gap(self):
        self.fill()
        lines = self.lines()
        self.file1().write_bytes(lines[0] + lines[2])
        self.assertTampered()

    def test_reorder(self):
        self.fill()
        lines = self.lines()
        self.file1().write_bytes(lines[1] + lines[0] + lines[2])
        self.assertTampered()

    def test_duplicate_seq(self):
        self.fill()
        lines = self.lines()
        self.file1().write_bytes(lines[0] + lines[1] + lines[1])
        self.assertTampered()

    def test_stray_file(self):
        self.fill()
        (self.dir / "notes.txt").write_text("x")
        self.assertTampered()

    def test_missing_first_file(self):
        self.fill()
        self.file1().rename(self.dir / "000002.jsonl")
        self.assertTampered()

    def test_truncation_against_head(self):
        self.fill()
        old_head = ledger.head(str(self.dir))
        self.file1().write_bytes(b"".join(self.lines()[:2]))
        ledger.verify(str(self.dir))  # a truncated chain is still a chain ...
        with self.assertRaises(ledger.LedgerError):  # ... but not the one the head names
            ledger.verify(str(self.dir), old_head)
        self.assertExit(run_rigor(["ledger", "verify", "--ledger", self.dir, "--head", old_head]), 1)

    def test_missing_trailing_newline_and_empty_file(self):
        self.fill()
        self.file1().write_bytes(self.file1().read_bytes().rstrip(b"\n"))
        self.assertTampered()
        self.file1().write_bytes(b"")
        self.assertTampered()

    def test_unknown_kind_and_bad_fields(self):
        self.fill()
        for old, new in ((b'"kind":"ratchet"', b'"kind":"nope"'), (b'"at":12', b'"at":-1'),
                         (b'"at":12', b'"at":true'), (b'"evidence":""', b'"evidence":"zz"')):
            data = self.file1().read_bytes()
            self.file1().write_bytes(data.replace(old, new, 1))
            self.assertTampered()
            self.file1().write_bytes(data)

    def test_extra_key_and_garbage(self):
        self.fill()
        data = self.file1().read_bytes()
        self.file1().write_bytes(data + b"not json\n")
        self.assertTampered()
        self.file1().write_bytes(data + b'{"a":1}\n')
        self.assertTampered()

    def test_append_after_tamper_is_refused(self):
        self.fill()
        self.file1().write_bytes(self.file1().read_bytes().replace(b'"at":11', b'"at":12'))
        before = self.file1().read_bytes()
        with self.assertRaises(ledger.LedgerError):
            self.add("ratchet", "ram:core")
        out = run_rigor(["ledger", "append", "--ledger", self.dir, "--kind", "ratchet",
                         "--subject", "x", "--at", 5])
        self.assertExit(out, 2)
        self.assertEqual(self.file1().read_bytes(), before)

    def test_rollover_to_a_second_file(self):
        self.assertEqual(ledger.ENTRIES_PER_FILE, 1000)
        original = ledger.ENTRIES_PER_FILE
        ledger.ENTRIES_PER_FILE = 2
        try:
            self.fill()
        finally:
            ledger.ENTRIES_PER_FILE = original
        self.assertTrue((self.dir / "000002.jsonl").is_file())
        self.assertEqual(len(ledger.read_entries(str(self.dir))[0]), 3)


class AppendCliTests(LedgerCase):
    def test_cli_append_hashes_evidence(self):
        evidence = self.tmp / "ev.txt"
        evidence.write_bytes(b"proof\n")
        subject = claim_subject()
        for kind, extra in (("claim", []), ("revocation", ["--evidence", evidence])):
            out = run_rigor(["ledger", "append", "--ledger", self.dir, "--kind", kind,
                             "--subject", subject, "--at", 7] + extra)
            self.assertExit(out, 0)
        entries = ledger.read_entries(str(self.dir))[0]
        self.assertEqual(entries[1]["evidence"], hashlib.sha256(b"proof\n").hexdigest())
        self.assertEqual(entries[1]["at"], 7)
        self.assertEqual(out.stdout.strip(), ledger.head(str(self.dir)))

    def test_cli_creates_missing_directory(self):
        target = self.tmp / "new" / "l"
        out = run_rigor(["ledger", "append", "--ledger", target, "--kind", "ratchet", "--subject", "s",
                         "--at", 1])
        self.assertExit(out, 0)
        self.assertTrue((target / "000001.jsonl").is_file())


class ClaimTests(LedgerCase):
    def test_standing_claims_sorted_and_revocation(self):
        self.add("claim", claim_subject(scope="m2", sha=SHA_B))
        self.add("claim", claim_subject(scope="m1"))
        self.assertEqual([e["subject"] for e in ledger.standing_claims(str(self.dir))],
                         [claim_subject(scope="m1"), claim_subject(scope="m2", sha=SHA_B)])
        self.add("revocation", claim_subject(scope="m1"), evidence=SHA_C)
        self.assertEqual([e["subject"] for e in ledger.standing_claims(str(self.dir))],
                         [claim_subject(scope="m2", sha=SHA_B)])

    def test_reclaim_after_revocation_stands(self):
        self.add("claim", claim_subject())
        self.add("revocation", claim_subject(), evidence=SHA_C)
        self.add("claim", claim_subject())
        self.assertEqual(len(ledger.standing_claims(str(self.dir))), 1)

    def test_refusals(self):
        with self.assertRaises(ledger.LedgerError):
            self.add("claim", "no-sha-here")
        with self.assertRaises(ledger.LedgerError):
            self.add("revocation", claim_subject(), evidence=SHA_C)  # nothing stands
        self.add("claim", claim_subject())
        with self.assertRaises(ledger.LedgerError):
            self.add("claim", claim_subject())  # already stands
        with self.assertRaises(ledger.LedgerError):
            self.add("revocation", claim_subject())  # no refuting evidence
        with self.assertRaises(ledger.LedgerError):
            self.add("bogus", "x")
        with self.assertRaises(ledger.LedgerError):
            self.add("ratchet", "x", at=-1)

    def test_scope_may_contain_colons(self):
        subject = claim_subject("suppression", "src/a.c:3-nolint")
        self.assertEqual(ledger.split_subject(subject), ("suppression", "src/a.c:3-nolint", SHA_A))
        self.assertIsNone(ledger.split_subject("suppression:x:short"))

    def test_claims_command(self):
        self.add("claim", claim_subject(scope="m2", sha=SHA_B), at=3)
        self.add("claim", claim_subject(scope="m1"), at=4)
        out = run_rigor(["ledger", "claims", "--ledger", self.dir])
        self.assertExit(out, 0)
        subjects = [line.split("\t")[0] for line in out.stdout.splitlines()]
        self.assertEqual(subjects, sorted(subjects))
        self.assertEqual(len(subjects), 2)


class DebtTests(LedgerCase):
    def test_default_constant(self):
        self.assertEqual(ledger.DEFAULT_CAP_PPM, 20000)

    def test_cap_boundaries(self):
        cases = [(0, 0, False), (1, 0, False), (2, 0, True), (0, 1, False), (1, 1, False), (2, 1, True),
                 (1, 49, False), (2, 49, True), (1, 50, False), (2, 50, True), (2, 99, True),
                 (2, 100, False), (3, 100, True), (10, 500, False), (11, 500, True)]
        for count, mutants, expected in cases:
            self.assertEqual(ledger.over_cap(count, mutants), expected, (count, mutants))

    def test_other_cap(self):
        self.assertFalse(ledger.over_cap(5, 100, 50000))
        self.assertTrue(ledger.over_cap(6, 100, 50000))
        self.assertTrue(ledger.over_cap(1, 1000, 0) is True)
        self.assertTrue(ledger.over_cap(1, 10, 0) is False)  # a small module may hold one

    def test_debt_counts_per_module_and_only_equivalent_mutants(self):
        self.add("claim", claim_subject(scope="m1"))
        self.add("claim", claim_subject(scope="m2", sha=SHA_B))
        self.add("claim", claim_subject(scope="m9", sha=SHA_C))  # on no known module
        self.add("claim", claim_subject("suppression", "m1", SHA_C))
        self.add("claim", claim_subject(scope="m3", sha=SHA_C))
        self.add("revocation", claim_subject(scope="m3", sha=SHA_C), evidence=SHA_A)
        standing = ledger.standing_claims(str(self.dir))
        counts = ledger.debt(standing, {"a": {"m1", "m2", "m3"}, "b": {"m4"}})
        self.assertEqual(counts, {"a": 2, "b": 0})


class TightenOnlyTests(LedgerCase):
    def test_switch(self):
        self.assertFalse(ledger.tighten_only(str(self.dir)))
        self.add("tighten-only-on", "canary passed")
        self.assertTrue(ledger.tighten_only(str(self.dir)))
        self.assertEqual(ledger.tighten_only_since(str(self.dir)), 1)
        self.add("tighten-only-off", "fixed by T1")
        self.assertFalse(ledger.tighten_only(str(self.dir)))
        self.add("tighten-only-on", "again")
        self.assertEqual(ledger.tighten_only_since(str(self.dir)), 3)

    def test_copy_of_fixture_can_be_extended(self):
        copy = self.tmp / "copy"
        shutil.copytree(FIXTURE, copy)
        head = ledger.append(str(copy), "ratchet", "x", "", 200)
        self.assertEqual(ledger.verify(str(copy), FIXTURE_HEAD), head)
