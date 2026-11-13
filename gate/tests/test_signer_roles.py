"""Tests for signer roles (gate/signer_roles.toml) and the tighten-only rule in `load_approvals`."""

from pathlib import Path

from rigor_lib import approvals, jsonio, ledger
from rigor_lib.errors import InternalError
from tests.helpers import Signer
from tests.test_approvals import SCOPE, ApprovalCase

ROLES_FILE = Path(__file__).resolve().parents[1] / "signer_roles.toml"
ALL_KINDS = {"suppression", "test-removal", "ratchet", "equivalent-mutant", "witness-equivalent-mutant"}


class RolesCase(ApprovalCase):
    def roles(self, text):
        path = self.tmp / "roles.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def load_with(self, roles_path=None, ledger_dir=None):
        return approvals.load_approvals(self.dir, self.repo.root, self.head, self.allowed,
                                        roles_path, ledger_dir)


class RolesFileTests(RolesCase):
    def test_shipped_file_gives_orchestrator_every_kind_that_exists(self):
        roles = approvals.load_roles(str(ROLES_FILE))
        self.assertEqual(roles, {"orchestrator": ALL_KINDS})
        self.assertEqual(ALL_KINDS, set(approvals.KINDS))

    def test_shipped_principal_is_in_allowed_signers(self):
        signers = (ROLES_FILE.parent / "allowed_signers").read_text(encoding="utf-8")
        self.assertIn("orchestrator ", signers)

    def test_malformed_roles_are_internal_errors(self):
        for text in ("[principal.x]\nkinds = [\"nope\"]\n", "[principal.x]\nkinds = \"suppression\"\n",
                     "[principal.x]\nkinds = []\nextra = 1\n", "[other]\na = 1\n", "this is = = bad"):
            with self.assertRaises(InternalError, msg=text):
                approvals.load_roles(self.roles(text))
        with self.assertRaises(InternalError):
            approvals.load_roles(str(self.tmp / "missing.toml"))


class RoleRuleTests(RolesCase):
    def test_listed_kind_counts(self):
        self.make()
        result = self.load_with(self.roles('[principal.owner]\nkinds = ["suppression"]\n'))
        self.assertEqual(result.problems, [])
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_removing_a_kind_turns_its_approvals_into_forged_approval(self):
        self.make(kind="suppression")
        self.make(kind="ratchet", scope="r.toml:k")
        full = self.roles('[principal.owner]\nkinds = ["suppression", "ratchet"]\n')
        self.assertEqual(self.load_with(full).problems, [])
        less = self.roles('[principal.owner]\nkinds = ["suppression"]\n')
        result = self.load_with(less)
        self.assertEqual(self.reasons(result), ["kind-not-allowed-for-signer"])
        self.assertEqual(result.problems[0]["rule"], "forged-approval")
        self.assertIsNone(result.covering("ratchet", "r.toml:k"))
        self.assertIsNotNone(result.covering("suppression", SCOPE))

    def test_unlisted_principal_signs_nothing(self):
        self.make()
        result = self.load_with(self.roles('[principal.someone-else]\nkinds = ["suppression"]\n'))
        self.assertEqual(self.reasons(result), ["kind-not-allowed-for-signer"])
        self.assertEqual(self.load_with(self.roles("")).valid, [])

    def test_two_principals_each_limited_to_their_own_kinds(self):
        second = Signer(self.tmp / "keys2", principal="arbiter")
        allowed = second.write_allowed_signers(self.tmp / "both", [self.signer.allowed_line])
        self.make(kind="suppression")
        self.make(kind="equivalent-mutant", scope="abc", signer=second)
        roles = self.roles('[principal.owner]\nkinds = ["suppression"]\n'
                           '[principal.arbiter]\nkinds = ["equivalent-mutant"]\n')
        result = approvals.load_approvals(self.dir, self.repo.root, self.head, allowed, roles)
        self.assertEqual(result.problems, [])
        self.assertEqual(len(result.valid), 2)
        swapped = self.roles('[principal.owner]\nkinds = ["equivalent-mutant"]\n'
                             '[principal.arbiter]\nkinds = ["suppression"]\n')
        result = approvals.load_approvals(self.dir, self.repo.root, self.head, allowed, swapped)
        self.assertEqual(self.reasons(result), ["kind-not-allowed-for-signer"] * 2)

    def test_without_roles_nothing_changes(self):
        self.make()
        self.assertEqual(self.load_with().problems, [])


class TightenOnlyRuleTests(RolesCase):
    def setUp(self):
        super().setUp()
        self.ledger = self.sub("ledger")

    def claim(self, path, at):
        approval = approvals.load_approvals(self.dir, self.repo.root, self.head, self.allowed)
        stem = path.name[:-len(".json")]
        item = [a for a in approval.valid if a.stem == stem][0]
        subject = ledger.make_subject(item.kind, item.scope, stem)
        ledger.append(str(self.ledger), "claim", subject, "", at)

    def test_claim_after_switch_does_not_count(self):
        old = self.make(scope="old")
        self.claim(old, 1)
        ledger.append(str(self.ledger), "tighten-only-on", "canary passed", "", 2)
        new = self.make(scope="new")
        self.claim(new, 3)
        result = self.load_with(ledger_dir=str(self.ledger))
        self.assertEqual(self.reasons(result), ["tighten-only"])
        self.assertEqual(result.problems[0]["rule"], "forged-approval")
        self.assertIsNotNone(result.covering("suppression", "old"))
        self.assertIsNone(result.covering("suppression", "new"))

    def test_switch_off_again_counts_everything(self):
        self.claim(self.make(scope="a"), 1)
        ledger.append(str(self.ledger), "tighten-only-on", "x", "", 2)
        self.claim(self.make(scope="b"), 3)
        ledger.append(str(self.ledger), "tighten-only-off", "fixed", "", 4)
        result = self.load_with(ledger_dir=str(self.ledger))
        self.assertEqual(result.problems, [])
        self.assertEqual(len(result.valid), 2)

    def test_no_ledger_argument_changes_nothing(self):
        self.claim(self.make(scope="a"), 1)
        ledger.append(str(self.ledger), "tighten-only-on", "x", "", 2)
        self.claim(self.make(scope="b"), 3)
        self.assertEqual(len(self.load_with().valid), 2)

    def test_broken_ledger_is_an_internal_error(self):
        self.make()
        (self.ledger / "junk").write_text("x")
        with self.assertRaises(InternalError):
            self.load_with(ledger_dir=str(self.ledger))

    def test_revocation_and_cli_flags_are_accepted(self):
        # the optional flags reach load_from_args through approval_args
        from rigor_lib import approval_args
        import argparse
        parser = argparse.ArgumentParser()
        approval_args.add_approval_arguments(parser, True)
        args = parser.parse_args(["--approvals", str(self.dir), "--repo", str(self.repo.root),
                                  "--head", self.head, "--allowed-signers", str(self.allowed),
                                  "--signer-roles", self.roles('[principal.x]\nkinds = ["ratchet"]\n'),
                                  "--ledger", str(self.ledger)])
        self.make()
        loaded = approval_args.load_from_args(args)
        self.assertEqual(self.reasons(loaded), ["kind-not-allowed-for-signer"])
        self.assertEqual(jsonio.sha256_hex(b""), jsonio.sha256_hex(b""))
