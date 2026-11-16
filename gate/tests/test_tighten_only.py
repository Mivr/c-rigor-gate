"""The tighten-only rule of the ledger in `load_approvals` (T132). U30 removed the signer roles that lived here."""

import argparse

from rigor_lib import approval_args, approvals, ledger
from rigor_lib.errors import InternalError
from tests.test_approvals import ApprovalCase


class LedgerCase(ApprovalCase):
    def load_with(self, ledger_dir=None):
        return approvals.load_approvals(self.dir, self.repo.root, self.head, ledger_dir)


class TightenOnlyRuleTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger = self.sub("ledger")

    def claim(self, path, at):
        approval = approvals.load_approvals(self.dir, self.repo.root, self.head)
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

    def test_the_ledger_flag_reaches_load_from_args(self):
        parser = argparse.ArgumentParser()
        approval_args.add_approval_arguments(parser, True)
        args = parser.parse_args(["--approvals", str(self.dir), "--repo", str(self.repo.root),
                                  "--head", self.head, "--ledger", str(self.ledger)])
        self.claim(self.make(scope="a"), 1)
        ledger.append(str(self.ledger), "tighten-only-on", "x", "", 2)
        self.claim(self.make(scope="b"), 3)
        self.assertEqual(self.reasons(approval_args.load_from_args(args)), ["tighten-only"])

    def test_signer_options_are_gone(self):
        parser = argparse.ArgumentParser()
        approval_args.add_approval_arguments(parser, True)
        for option in ("--allowed-signers", "--signer-roles"):
            with self.assertRaises(SystemExit):
                parser.parse_args([option, "x"])
