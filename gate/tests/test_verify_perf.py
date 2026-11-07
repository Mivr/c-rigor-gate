"""`rigor verify --expect-perf-sha` (R011, B13): next to `--expect-witness-sha`; `none` means no `--perf`."""

import os
import subprocess

from rigor_lib import jsonio, perf_bundle, verdict
from tests.helpers import GATE_DIR, TempDirTestCase, base_env, run_rigor
from tests.test_verdict_inputs import Fixture

FIXTURE = GATE_DIR / "tests" / "fixtures" / "perf" / "selftest"


class VerifyExpectation(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.key = str(self.tmp / "key")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", self.key], check=True,
                       capture_output=True, env=base_env())
        pub = (self.tmp / "key.pub").read_text().split()
        self.signers = self.tmp / "signers"
        self.signers.write_text('signer namespaces="c-rigor-gate-verdict" %s %s\n' % (pub[0], pub[1]))
        self.verdict = self.tmp / "verdict.json"
        self.fixture = Fixture(str(self.tmp))
        self.sha = perf_bundle.digest(perf_bundle.load(str(FIXTURE)))

    def make(self, mutate_core=None):
        core = verdict.build_core(["a"], {"a": {"status": "PASS", "findings": []}})
        core["uncached"] = False
        core["inputs"] = self.fixture.inputs()
        if mutate_core:
            mutate_core(core)
        document = {"core": core, "core_sha256": jsonio.sha256_hex(jsonio.canonical_dumps(core)), "metadata": {}}
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        sig = str(self.verdict) + ".sig"
        if os.path.exists(sig):
            os.unlink(sig)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-n", "c-rigor-gate-verdict", "-f", self.key, str(self.verdict)],
                       check=True, capture_output=True, env=base_env())

    def verify(self, *extra):
        return run_rigor(["verify", "--verdict", self.verdict, "--allowed-signers", self.signers, *extra])

    def assertRejected(self, outcome, text):
        self.assertEqual(outcome.code, 1, outcome.stdout + outcome.stderr)
        self.assertIn(text, outcome.stdout)

    def test_expect_perf_sha_accepts_only_that_bundle(self):
        self.fixture.file_hashes["perf_sha256"] = self.sha
        self.make()
        self.assertEqual(self.verify().code, 0)
        self.assertEqual(self.verify("--expect-perf-sha", self.sha).code, 0)
        self.assertRejected(self.verify("--expect-perf-sha", "e" * 64), "perf_sha256 is %s, expected %s" % (self.sha, "e" * 64))

    def test_none_is_rejected_for_a_grade_with_a_bundle(self):
        self.fixture.file_hashes["perf_sha256"] = self.sha
        self.make()
        self.assertRejected(self.verify("--expect-perf-sha", "none"), "expected none")

    def test_a_grade_without_perf_accepts_none_or_absent_and_rejects_a_sha(self):
        self.fixture.file_hashes["perf_sha256"] = None
        self.make()
        self.assertEqual(self.verify().code, 0)
        self.assertEqual(self.verify("--expect-perf-sha", "none").code, 0)
        self.assertRejected(self.verify("--expect-perf-sha", self.sha), "perf_sha256 is null")

    def test_a_malformed_perf_sha_is_rejected(self):
        def bad(core):
            core["inputs"]["perf_sha256"] = "short"
        self.make(bad)
        self.assertRejected(self.verify(), "perf_sha256 is missing or malformed")

    def test_a_verdict_without_the_perf_key_is_rejected(self):
        self.make(lambda core: core["inputs"].pop("perf_sha256"))
        self.assertRejected(self.verify(), "no well-formed inputs")
