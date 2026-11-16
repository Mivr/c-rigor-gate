"""The simulation inputs of a verdict (T2G2): the salt snapshot, the keys bound into `core.inputs`, and what `rigor verify` prints
and expects."""

import os

from rigor_lib import jsonio, sim_policy, verdict_inputs
from rigor_lib.errors import InternalError
from tests.gate_repo_fixture import VerdictCase
from tests.helpers import TempDirTestCase

PUBLIC = "0a0b\n"
HIDDEN = "ffee01\n"


class SaltSnapshot(TempDirTestCase):
    def snapshot(self, hidden=None, public=None):
        public_copy = self.tmp / "sim-salt.public"
        if public is not None:
            public_copy.write_text(public)
        if hidden is not None:
            (self.tmp / "hidden").write_text(hidden)
        destination = self.tmp / "sim-salt"
        if destination.exists():
            destination.unlink()
        sha = verdict_inputs.snapshot_sim_salt(None if hidden is None else str(self.tmp / "hidden"), str(public_copy),
                                               str(destination))
        return sha, destination.read_text() if destination.exists() else None

    def test_the_hidden_salt_wins_and_only_its_hash_is_returned(self):
        sha, text = self.snapshot(hidden=HIDDEN, public=PUBLIC)
        self.assertEqual((sha, text), (jsonio.sha256_hex(bytes.fromhex("ffee01")), "ffee01\n"))

    def test_the_public_salt_is_the_default(self):
        sha, text = self.snapshot(public=PUBLIC)
        self.assertEqual((sha, text), (jsonio.sha256_hex(bytes([10, 11])), "0a0b\n"))

    def test_no_salt_is_null_and_writes_nothing(self):
        self.assertEqual(self.snapshot(), (None, None))

    def test_the_empty_salt_is_a_salt(self):
        sha, text = self.snapshot(hidden="")
        self.assertEqual((sha, text), (jsonio.sha256_hex(b""), "\n"))

    def test_a_bad_hidden_or_public_salt_is_exit_2(self):
        for text in ("XYZ", "abc", "AB", "ab" * 65):
            with self.subTest(text=text), self.assertRaises(InternalError):
                self.snapshot(hidden=text)
            with self.subTest(text=text, kind="public"), self.assertRaises(InternalError):
                self.snapshot(public=text)

    def test_a_hidden_salt_that_is_not_a_regular_file(self):
        (self.tmp / "dir").mkdir()
        with self.assertRaises(InternalError):
            verdict_inputs.snapshot_sim_salt(str(self.tmp / "dir"), str(self.tmp / "none"), str(self.tmp / "out"))
        os.symlink(self.tmp / "dir", self.tmp / "link")
        with self.assertRaises(InternalError):
            verdict_inputs.snapshot_sim_salt(str(self.tmp / "link"), str(self.tmp / "none"), str(self.tmp / "out"))

    def test_a_salt_swap_changes_the_bound_id(self):
        self.assertNotEqual(self.snapshot(hidden=HIDDEN)[0], self.snapshot(hidden="ffee02\n")[0])

    def test_the_id_is_what_the_judge_computes(self):
        _, text = self.snapshot(hidden=HIDDEN)
        (self.tmp / "salt").write_text(text)
        self.assertEqual(sim_policy.load_salt(str(self.tmp / "salt"))[1], self.snapshot(hidden=HIDDEN)[0])


class VerifySim(VerdictCase):
    SPEC = "a" * 64
    SALT = "b" * 64

    def make_sim(self, **inputs):
        self.fixture.file_hashes.update(inputs)
        self.make()

    def no_sim(self):
        self.fixture.file_hashes.update(sim_spec_sha256=None, sim_salt_id=None, sim_regressions_sha256=None)

    def test_the_simulation_inputs_are_printed(self):
        self.fixture.file_hashes.update(sim_spec_sha256=self.SPEC, sim_salt_id=self.SALT)
        self.fixture.sim_digest = "c" * 64
        self.make()
        outcome = self.verify()
        self.assertEqual(outcome.code, 0, outcome.stdout)
        for line in ("sim_spec_sha256 " + self.SPEC, "sim_salt_id " + self.SALT, "sim_seed_digest " + "c" * 64):
            self.assertIn("rigor verify: " + line, outcome.stdout)

    def test_nothing_of_a_simulation_prints_as_none(self):
        self.no_sim()
        self.make()
        self.assertIn("rigor verify: sim_salt_id none", self.verify().stdout)

    def test_a_verdict_graded_with_another_salt_or_spec_is_refused(self):
        self.make_sim(sim_spec_sha256=self.SPEC, sim_salt_id=self.SALT)
        self.assertEqual(self.verify("--expect-sim-salt-id", self.SALT, "--expect-sim-spec-sha", self.SPEC).code, 0)
        self.assertRejected(self.verify("--expect-sim-salt-id", "e" * 64), "sim_salt_id is %s, expected %s" % (self.SALT, "e" * 64))
        self.assertRejected(self.verify("--expect-sim-spec-sha", "e" * 64), "sim_spec_sha256 is %s" % self.SPEC)

    def test_a_verdict_without_a_simulation_does_not_satisfy_an_expected_salt(self):
        self.no_sim()
        self.make()
        self.assertRejected(self.verify("--expect-sim-salt-id", self.SALT), "sim_salt_id is None")

    def test_a_malformed_simulation_input_is_rejected(self):
        self.make(lambda core: core["inputs"].__setitem__("sim_seed_digest", "short"))
        self.assertRejected(self.verify(), "sim_seed_digest is missing or malformed")

    def test_a_verdict_without_the_keys_is_rejected(self):
        self.make(lambda core: core["inputs"].pop("sim_salt_id"))
        self.assertRejected(self.verify(), "no well-formed inputs")
