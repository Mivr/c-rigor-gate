"""THE gate list of `rigor grade`. To add a gate, add one row; nothing else registers gates.

Rows run in this order. A step is `function(grading) -> GateResult | None`; its result file is
`<id>.json`, and `None` means "did not run" (the verdict shows NOT_RUN, which fails). The ids
here must equal, in the same order, the lines of `gate/order.txt` (a test checks that).
Any exception inside a step is an internal error: the step is recorded as FAIL and the
remaining steps do not run.
"""

from rigor_lib import grade_build, grade_checks, grade_mutants, grade_steps, grade_structure
from rigor_lib import grade_witness

GATES = (
    ("clone", grade_steps.clone_gate),
    ("contract", grade_steps.contract_gate),
    ("suppressions", grade_steps.suppressions_gate),
    ("assemble", grade_steps.assemble_gate),
    ("buckfiles", grade_checks.buckfiles_gate),
    ("semantic-suppressions", grade_checks.semantic_gate),
    ("symbols", grade_checks.symbols_gate),
    ("build", grade_build.build_gate),
    ("structure", grade_structure.structure_gate),
    ("mode-divergence", grade_structure.modes_gate),
    ("tests-release", grade_steps.tests_gate_for("release")),
    ("tests-san", grade_steps.tests_gate_for("san")),
    ("mutants", grade_mutants.mutants_gate),
    ("witness-tests", grade_witness.witness_tests_gate),
    ("mutants-witness", grade_witness.mutants_witness_gate),
)
