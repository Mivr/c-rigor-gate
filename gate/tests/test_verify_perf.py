"""`rigor verify --expect-perf-sha` (R011, B13): next to `--expect-witness-sha`; `none` means no `--perf`."""

from rigor_lib import perf_bundle
from tests.gate_repo_fixture import VerdictCase
from tests.helpers import GATE_DIR

FIXTURE = GATE_DIR / "tests" / "fixtures" / "perf" / "selftest"


class VerifyExpectation(VerdictCase):
    def setUp(self):
        super().setUp()
        self.sha = perf_bundle.digest(perf_bundle.load(str(FIXTURE)))

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
