"""T037 (P002 Q3): the `witness-equivalent-mutant` approval kind, apart from `equivalent-mutant`.

Owner decision 4 is not confirmed yet. If the owner rejects the kind, delete this file together with
the marked block in gate/rigor_lib/approvals.py.
"""

from rigor_lib import approvals
from tests.test_approvals import ApprovalCase

MUTANT_ID = "core/core.c:3:core_add:arith:0"


class WitnessEquivalentMutantKind(ApprovalCase):
    def test_the_kind_is_known_and_distinct(self):
        self.assertEqual(approvals.KIND_WITNESS_EQUIVALENT_MUTANT, "witness-equivalent-mutant")
        self.assertIn(approvals.KIND_WITNESS_EQUIVALENT_MUTANT, approvals.KINDS)
        self.assertIn(approvals.KIND_EQUIVALENT_MUTANT, approvals.KINDS)
        self.assertEqual(len(set(approvals.KINDS)), len(approvals.KINDS))

    def test_rigor_approve_writes_one_that_verifies(self):
        self.make(kind="witness-equivalent-mutant", scope=MUTANT_ID)
        result = self.load()
        self.assertEqual(result.problems, [])
        self.assertIsNotNone(result.covering("witness-equivalent-mutant", MUTANT_ID))

    def test_a_witness_approval_never_covers_the_implementers_mutant(self):
        self.make(kind="witness-equivalent-mutant", scope=MUTANT_ID)
        self.assertIsNone(self.load().covering(approvals.KIND_EQUIVALENT_MUTANT, MUTANT_ID))

    def test_an_implementer_approval_never_covers_the_witness_mutant(self):
        self.make(kind="equivalent-mutant", scope=MUTANT_ID)
        result = self.load()
        self.assertIsNotNone(result.covering(approvals.KIND_EQUIVALENT_MUTANT, MUTANT_ID))
        self.assertIsNone(result.covering(approvals.KIND_WITNESS_EQUIVALENT_MUTANT, MUTANT_ID))
