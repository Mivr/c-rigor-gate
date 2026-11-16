"""`rigor verify` (T021; U30: nothing is signed): what it recomputes, what it requires, what it rejects by name."""

from rigor_lib import jsonio, verdict_inputs
from tests.gate_repo_fixture import VerdictCase, default_product_files, gate_repo
from tests.helpers import Repo, read_json, run_rigor
from tests.test_verdict_inputs import Fixture, HEAD


class Verify(VerdictCase):
    def test_a_consistent_clean_pass_verifies_with_all_expectations(self):
        self.make()
        inputs = self.fixture.inputs()
        outcome = self.verify("--expect-policy-sha", inputs["policy_sha256"], "--expect-task-sha", inputs["task_sha256"])
        self.assertEqual(outcome.code, 0, outcome.stdout + outcome.stderr)
        self.assertIn("OK", outcome.stdout)
        self.assertIn("approvals in force 0", outcome.stdout)

    def test_each_expectation_is_checked_on_its_own(self):
        self.make()
        self.assertRejected(self.verify("--expect-head", "e" * 40), "head is")
        self.assertRejected(self.verify("--expect-gate", "e" * 40), "gate_sha is")
        self.assertRejected(self.verify("--expect-policy-sha", "e" * 64), "policy_sha256 is")
        self.assertRejected(self.verify("--expect-task-sha", "e" * 64), "task_sha256 is")
        self.assertEqual(self.verify().code, 0)

    def test_the_head_and_the_gate_commit_must_be_named(self):
        self.make()
        for dropped in ("--expect-head", "--expect-gate"):
            argv = ["verify", "--verdict", self.verdict, "--gate-repo", self.gate_repo, "--product-dir", self.product,
                    "--expect-head", HEAD, "--expect-gate", self.fixture.gate_sha]
            index = argv.index(dropped)
            outcome = run_rigor(argv[:index] + argv[index + 2:])
            self.assertExit(outcome, 2)
            self.assertIn(dropped, outcome.stderr)

    def test_a_verdict_graded_by_another_gate_commit_is_rejected_by_name(self):
        approved = self.fixture.gate_sha
        repo = Repo(self.gate_repo)
        repo.write("gate/rigor_lib/weakened.py", "# an unmerged branch that weakens a check\n")
        self.fixture.gate_sha = repo.commit("weakened")
        self.make()   # consistent with the weakened commit, which is in the gate object store
        self.assertEqual(self.verify("--expect-gate", self.fixture.gate_sha).code, 0)
        self.assertRejected(self.verify("--expect-gate", approved),
                            "gate_sha is %s, expected %s" % (self.fixture.gate_sha, approved))

    def test_a_verdict_of_the_signing_gate_is_refused_by_name_and_its_signature_ignored(self):
        def legacy(core):
            core["inputs"]["allowed_signers_sha256"] = "5" * 64
        self.make(legacy)
        (self.tmp / "verdict.json.sig").write_bytes(b"-----BEGIN SSH SIGNATURE-----\n")
        self.assertRejected(self.verify(), "written by a gate that signed verdicts")
        for option in ("--allowed-signers", "--signature"):
            self.assertExit(self.verify(option, self.tmp / "verdict.json.sig"), 2)

    def test_a_tampered_file_is_rejected(self):
        self.make()
        document = read_json(self.verdict)
        document["core"]["inputs"]["head"] = "e" * 40
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        self.assertRejected(self.verify(), "core_sha256 does not match")
        self.write(document["core"])   # rehashed: consistent, but about another tree than the one asked about
        self.assertRejected(self.verify(), "head is %s, expected %s" % ("e" * 40, HEAD))

    def test_a_document_whose_hash_does_not_match_its_core(self):
        self.make()
        self.write(read_json(self.verdict)["core"], "0" * 64)
        self.assertRejected(self.verify(), "core_sha256 does not match")

    def test_a_dirty_gate_pass_is_rejected(self):
        self.fixture.gate_clean = False
        self.make()
        self.assertRejected(self.verify(), "gate tree was dirty")

    def test_a_fail_is_rejected(self):
        self.make(lambda core: core.__setitem__("overall", "FAIL"))
        self.assertRejected(self.verify(), "not PASS")

    def test_a_pass_with_a_failed_gate_is_rejected(self):
        self.make(lambda core: core["gates"][0].__setitem__("status", "FAIL"))
        self.assertRejected(self.verify(), "a gate is not")

    def test_a_gate_entry_that_is_not_an_object_is_rejected(self):
        self.make(lambda core: core.__setitem__("gates", ["a"]))
        self.assertRejected(self.verify(), "core.gates is not a list of objects")
        self.make(lambda core: core.__setitem__("gates", {"a": "PASS"}))
        self.assertRejected(self.verify(), "core.gates is not a list of objects")

    def test_a_partial_or_reordered_grade_is_rejected(self):
        self.fixture = Fixture(str(self.tmp / "two"))
        self.gate_repo = gate_repo(self.fixture, ("a", "b"))
        self.make()   # the core lists only `a`: an `--only` grade
        self.assertRejected(self.verify(), "not the gate order of revision")
        self.make(lambda core: core.__setitem__("gates", core["gates"] * 2))
        self.assertRejected(self.verify(), "not the gate order of revision")

    def test_every_gate_owned_input_is_recomputed_from_the_gate_revision(self):
        for key in ("order_sha256", "toolchain_buck_sha256", "llvm_sha256", "sysroot_sha256", "buck2_sha256",
                    "buckconfig_sha256"):
            self.make(lambda core, key=key: core["inputs"].__setitem__(key, "9" * 64))
            self.assertRejected(self.verify(), "%s is %s, but gate revision" % (key, "9" * 64))

    def test_a_gate_sha_that_is_not_a_gate_commit_is_rejected(self):
        self.make(lambda core: core["inputs"].__setitem__("gate_sha", "e" * 40))
        self.assertRejected(self.verify("--expect-gate", "e" * 40), "is not a commit of the gate repository")


class VerifyProductFiles(VerdictCase):
    def test_an_edited_baseline_or_policy_after_the_grade_is_rejected(self):
        self.make()
        for name, key in (("decoupling-baseline.toml", "decoupling_baseline_sha256"), ("policy.toml", "policy_sha256"),
                          ("architecture.toml", "architecture_sha256"), ("ram-budget.toml", "ram_budget_sha256")):
            original = (self.product / name).read_bytes()
            (self.product / name).write_bytes(original + b"# raised\n")
            self.assertRejected(self.verify(), "%s is %s, but %s gives" % (key, self.fixture.file_hashes[key], self.product))
            (self.product / name).write_bytes(original)
        (self.product / "expected-tests.previous.json").unlink()
        self.assertRejected(self.verify(), "expected_tests_previous_sha256 is")
        self.assertEqual(len(default_product_files()), 14)

    def test_a_product_directory_outside_the_gate_checkout_must_be_given(self):
        self.make()
        self.assertRejected(self.verify(product_dir=False), "pass --product-dir")

    def test_a_product_directory_in_the_gate_checkout_is_read_from_the_gate_commit(self):
        files = default_product_files()
        self.fixture = Fixture(str(self.tmp / "in-gate"))
        self.gate_repo = gate_repo(self.fixture, product_dir="products/prod", product_files=files)
        self.fixture.product_dir = "products/prod"
        self.make()   # the scratch product directory holds the same files
        outcome = self.verify(product_dir=False)
        self.assertEqual(outcome.code, 0, outcome.stdout)
        self.assertRejected(self.verify(), "--product-dir must not be given")
        self.fixture.product_dir = "products/other"
        self.make()
        self.assertRejected(self.verify(product_dir=False), "policy_sha256 is")


class VerifyApprovals(VerdictCase):
    ENTRY = {"kind": "ratchet", "scope": "n.toml:k", "reason": "why", "repo_sha": "e" * 40}

    def approvals_dir(self):
        directory = self.sub("approvals")
        data = jsonio.canonical_dumps(dict(self.ENTRY))
        stem = jsonio.sha256_hex(data)
        (directory / (stem + ".json")).write_bytes(data)
        self.fixture.file_hashes["approvals_sha256"] = verdict_inputs.approvals_digest(str(directory))
        return directory, dict(self.ENTRY, stem=stem)

    def test_the_approvals_in_force_are_checked_and_printed(self):
        directory, entry = self.approvals_dir()
        self.make(lambda core: core.__setitem__("approvals", {"count": 1, "in_force": [entry]}))
        outcome = self.verify()
        self.assertEqual(outcome.code, 0, outcome.stdout)
        self.assertIn("approvals in force 1", outcome.stdout)
        self.assertIn("ratchet n.toml:k " + entry["stem"], outcome.stdout)
        for block, text in (({"count": 2, "in_force": [entry]}, "count does not match"),
                            ({"count": 2, "in_force": [entry, entry]}, "without duplicates"),
                            ({"count": 1, "in_force": [dict(entry, kind="owner")]}, "malformed"),
                            ({"count": 1, "in_force": [dict(entry, repo_sha="main")]}, "malformed"),
                            ({"in_force": []}, "no well-formed approvals count")):
            self.make(lambda core, block=block: core.__setitem__("approvals", block))
            self.assertRejected(self.verify(), text)
        self.fixture.file_hashes["approvals_sha256"] = None
        self.make(lambda core: core.__setitem__("approvals", {"count": 1, "in_force": [entry]}))
        self.assertRejected(self.verify(), "no approvals bundle is bound")

    def test_the_approvals_directory_is_recomputed_when_given(self):
        directory, entry = self.approvals_dir()
        self.make(lambda core: core.__setitem__("approvals", {"count": 1, "in_force": [entry]}))
        self.assertEqual(self.verify("--approvals", directory).code, 0)
        self.make(lambda core: core.__setitem__("approvals", {"count": 1, "in_force": [dict(entry, reason="other")]}))
        self.assertRejected(self.verify("--approvals", directory), "with other fields than its file")
        self.make(lambda core: core.__setitem__("approvals", {"count": 1, "in_force": [entry]}))
        (directory / "extra.txt").write_text("x")
        outcome = self.verify("--approvals", directory)
        self.assertRejected(outcome, "approvals_sha256 is")
        (directory / "extra.txt").unlink()
        (directory / (entry["stem"] + ".json")).write_bytes(b"{}\n")
        self.assertRejected(self.verify("--approvals", directory), "its file is not the approval of that hash")


class VerifyInputs(VerdictCase):
    def test_a_verdict_without_inputs_is_rejected(self):
        self.make(lambda core: core.pop("inputs"))
        self.assertRejected(self.verify(), "no well-formed inputs")

    def test_a_null_required_input_is_rejected(self):
        self.make(lambda core: core["inputs"].__setitem__("policy_sha256", None))
        self.assertRejected(self.verify(), "policy_sha256 is missing")

    def test_uncached_flag_must_agree_and_can_be_required(self):
        self.make()
        self.assertRejected(self.verify("--require-uncached"), "not an --uncached")
        self.fixture.uncached = True
        self.make()
        self.assertEqual(self.verify("--require-uncached").code, 0)
        self.make(lambda core: core.__setitem__("uncached", False))
        self.assertRejected(self.verify(), "disagrees")

    def test_expect_witness_sha_accepts_only_that_bundle(self):
        wanted = self.fixture.inputs()["witness_sha256"]
        self.make()
        self.assertEqual(self.verify("--expect-witness-sha", wanted).code, 0)
        self.assertRejected(self.verify("--expect-witness-sha", "e" * 64), "witness_sha256 is %s" % wanted)

    def test_expect_witness_sha_rejects_a_grade_without_a_witness(self):
        self.fixture.file_hashes["witness_sha256"] = None
        self.make()
        self.assertEqual(self.verify().code, 0)
        self.assertRejected(self.verify("--expect-witness-sha", "e" * 64), "witness_sha256 is null")

    def test_a_malformed_witness_sha_is_rejected(self):
        self.make(lambda core: core["inputs"].__setitem__("witness_sha256", "short"))
        self.assertRejected(self.verify(), "witness_sha256 is missing or malformed")

    def test_require_tier_accepts_only_that_tier_and_the_tier_is_always_printed(self):
        self.make()   # a nightly grade
        outcome = self.verify()
        self.assertEqual(outcome.code, 0)
        self.assertIn("tier nightly", outcome.stdout)
        self.assertEqual(self.verify("--require-tier", "nightly").code, 0)
        self.assertRejected(self.verify("--require-tier", "merge"), "tier is nightly, expected merge")
        self.fixture.tier = "merge"
        self.make()
        outcome = self.verify("--require-tier", "nightly")
        self.assertRejected(outcome, "tier is merge, expected nightly")
        self.assertIn("tier merge", outcome.stdout)
        self.assertEqual(self.verify("--require-tier", "merge").code, 0)

    def test_a_tier_edited_in_place_breaks_the_core_hash_and_an_unknown_tier_is_malformed(self):
        self.fixture.tier = "merge"
        self.make()
        document = read_json(self.verdict)
        document["core"]["inputs"]["tier"] = "nightly"
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        self.assertRejected(self.verify("--require-tier", "nightly"), "core_sha256 does not match")
        self.make(lambda core: core["inputs"].__setitem__("tier", "weekly"))
        self.assertRejected(self.verify(), "tier is missing or malformed")

    def test_an_unreadable_verdict_is_an_internal_error(self):
        outcome = run_rigor(["verify", "--verdict", self.tmp / "none.json", "--expect-head", HEAD,
                             "--expect-gate", self.fixture.gate_sha])
        self.assertEqual(outcome.code, 2)
