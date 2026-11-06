"""T021: `grade.write_verdict`, signing policy, and `rigor verify` (throwaway keys, no Buck2)."""

import json
import os
import subprocess
from unittest import mock

from rigor_lib import grade, jsonio, verdict
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, base_env, read_json, run_rigor
from tests.test_verdict_inputs import Fixture, HEAD, GATE


def passing_results(directory, order):
    for gate_id in order:
        doc = {"gate": gate_id, "status": "PASS", "findings": [], "metadata": {}}
        (directory / (gate_id + ".json")).write_text(json.dumps(doc))


class GradeVerdict(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = Fixture(str(self.tmp))
        self.order_bytes = (GATE_DIR / "order.txt").read_bytes()
        self.order = verdict.parse_order(self.order_bytes)
        self.results = self.sub("results")
        self.out = self.tmp / "verdict.json"

    def grading(self, results=True):
        g, documents = self.fixture.grading()
        if results:
            passing_results(self.results, self.order)
            for gate_id in ("clone", "assemble"):
                doc = {"gate": gate_id, "status": "PASS", "findings": [], "metadata": documents[gate_id]["metadata"]}
                (self.results / (gate_id + ".json")).write_text(json.dumps(doc))
        g.order_bytes = self.order_bytes
        g.results = str(self.results)
        g.args.verdict_out = str(self.out)
        return g

    def test_a_pass_binds_the_inputs_and_uncached_stays_top_level(self):
        code = grade.write_verdict(self.grading())
        core = read_json(self.out)["core"]
        self.assertEqual((code, core["overall"]), (0, "PASS"))
        self.assertEqual(core["inputs"], self.fixture.inputs())
        self.assertIs(core["uncached"], False)
        self.assertEqual(core["inputs"]["head"], HEAD)
        self.assertEqual(core["inputs"]["gate_sha"], GATE)

    def test_the_order_bytes_used_are_the_ones_hashed_by_the_caller_not_the_file_now(self):
        g = self.grading()
        g.order_bytes = b"".join((i + "\n").encode() for i in self.order[:-1])
        passing = [name for name in os.listdir(self.results)]
        self.assertTrue(passing)
        grade.write_verdict(g)
        self.assertEqual(len(read_json(self.out)["core"]["gates"]), len(self.order) - 1)

    def test_a_pass_with_an_unbound_input_is_an_internal_error(self):
        g = self.grading()
        meta = json.loads((self.results / "clone.json").read_text())
        del meta["metadata"]["merge_base"]
        (self.results / "clone.json").write_text(json.dumps(meta))
        with self.assertRaises(InternalError):
            grade.write_verdict(g)
        self.assertFalse(self.out.exists())

    def test_a_fail_may_have_null_inputs(self):
        g = self.grading(results=False)
        code = grade.write_verdict(g)
        core = read_json(self.out)["core"]
        self.assertEqual((code, core["overall"]), (1, "FAIL"))
        self.assertIsNone(core["inputs"]["head"])

    def test_a_dirty_gate_is_recorded_unsigned_and_never_verifies(self):
        self.fixture.gate_clean = False
        g = self.grading()
        self.assertEqual(grade.write_verdict(g), 0)
        self.assertIs(read_json(self.out)["core"]["inputs"]["gate_clean"], False)

    def run_grade(self, gate_clean):
        g = self.grading()
        g.gate_clean = gate_clean
        g.args.sign_key = "key"
        with mock.patch.object(grade, "start_grading", return_value=g), \
                mock.patch.object(grade, "run_gates", return_value=None), \
                mock.patch.object(grade.grade_context, "kill_daemon"), \
                mock.patch.object(grade, "sign_verdict") as sign:
            code = grade.run(g.args)
        return code, sign

    def test_signing_only_happens_for_a_clean_gate(self):
        code, sign = self.run_grade(True)
        self.assertEqual(code, 0)
        sign.assert_called_once()
        code, sign = self.run_grade(False)
        self.assertEqual(code, 0)
        sign.assert_not_called()


class Verify(TempDirTestCase):
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

    def make(self, mutate_core=None, namespace="c-rigor-gate-verdict", sign=True, fixture=None):
        fixture = fixture or self.fixture
        core = verdict.build_core(["a"], {"a": {"status": "PASS", "findings": []}})
        core["uncached"] = fixture.uncached
        core["inputs"] = fixture.inputs()
        if mutate_core:
            mutate_core(core)
        document = {"core": core, "core_sha256": jsonio.sha256_hex(jsonio.canonical_dumps(core)),
                    "metadata": {}}
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        if sign:
            self.sign(self.key, namespace)

    def sign(self, key, namespace="c-rigor-gate-verdict"):
        sig = str(self.verdict) + ".sig"
        if os.path.exists(sig):
            os.unlink(sig)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-n", namespace, "-f", key, str(self.verdict)],
                       check=True, capture_output=True, env=base_env())

    def verify(self, *extra):
        return run_rigor(["verify", "--verdict", self.verdict, "--allowed-signers", self.signers, *extra])

    def assertRejected(self, outcome, text):
        self.assertEqual(outcome.code, 1, outcome.stdout + outcome.stderr)
        self.assertIn(text, outcome.stdout)

    def test_a_signed_clean_pass_verifies_with_all_expectations(self):
        self.make()
        inputs = self.fixture.inputs()
        outcome = self.verify("--expect-head", HEAD, "--expect-gate", GATE,
                              "--expect-policy-sha", inputs["policy_sha256"])
        self.assertEqual(outcome.code, 0, outcome.stdout + outcome.stderr)
        self.assertIn("OK", outcome.stdout)

    def test_each_expectation_is_checked_on_its_own(self):
        self.make()
        self.assertRejected(self.verify("--expect-head", "e" * 40), "head is")
        self.assertRejected(self.verify("--expect-gate", "e" * 40), "gate_sha is")
        self.assertRejected(self.verify("--expect-policy-sha", "e" * 64), "policy_sha256 is")
        self.assertEqual(self.verify().code, 0)

    def test_no_signature_wrong_namespace_wrong_key(self):
        self.make(sign=False)
        self.assertRejected(self.verify(), "no signature")
        self.make(namespace="c-rigor-gate")
        self.assertRejected(self.verify(), "signature is not valid")
        other = str(self.tmp / "other")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", other], check=True,
                       capture_output=True, env=base_env())
        self.make()
        self.sign(other)
        self.assertRejected(self.verify(), "signature is not valid")

    def test_a_tampered_file_after_signing_is_rejected(self):
        self.make()
        document = read_json(self.verdict)
        document["core"]["inputs"]["head"] = "e" * 40
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        self.assertRejected(self.verify(), "signature is not valid")

    def test_a_signed_document_whose_hash_does_not_match_its_core(self):
        self.make()
        document = read_json(self.verdict)
        document["core_sha256"] = "0" * 64
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        self.sign(self.key)
        self.assertRejected(self.verify(), "core_sha256 does not match")

    def test_a_signed_dirty_gate_pass_is_rejected(self):
        self.fixture.gate_clean = False
        self.make()
        self.assertRejected(self.verify(), "gate tree was dirty")

    def test_a_signed_fail_is_rejected(self):
        def fail(core):
            core["overall"] = "FAIL"
        self.make(fail)
        self.assertRejected(self.verify(), "not PASS")

    def test_a_verdict_without_inputs_is_rejected(self):
        self.make(lambda core: core.pop("inputs"))
        self.assertRejected(self.verify(), "no well-formed inputs")

    def test_a_null_required_input_is_rejected(self):
        def null(core):
            core["inputs"]["policy_sha256"] = None
        self.make(null)
        self.assertRejected(self.verify(), "policy_sha256 is missing")

    def test_uncached_flag_must_agree_and_can_be_required(self):
        self.make()
        self.assertRejected(self.verify("--require-uncached"), "not an --uncached")
        self.fixture.uncached = True
        self.make()
        self.assertEqual(self.verify("--require-uncached").code, 0)

        def disagree(core):
            core["uncached"] = False
        self.make(disagree)
        self.assertRejected(self.verify(), "disagrees")

    def test_an_unreadable_verdict_is_an_internal_error(self):
        outcome = run_rigor(["verify", "--verdict", self.tmp / "none.json", "--allowed-signers", self.signers])
        self.assertEqual(outcome.code, 2)
