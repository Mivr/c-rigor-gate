"""THE gate list of `rigor grade`. To add a gate, add one row; nothing else registers gates.

Rows run in this order. A step is `function(grading) -> GateResult | None`; its result file is
`<id>.json`, and `None` means "did not run" (the verdict shows NOT_RUN, which fails). The ids
here must equal, in the same order, the lines of `gate/order.txt` (a test checks that).
Any exception inside a step is an internal error: the step is recorded as FAIL and the
remaining steps do not run.
"""

from rigor_lib import grade_build, grade_steps

GATES = (
    ("clone", grade_steps.clone_gate),
    ("contract", grade_steps.contract_gate),
    ("suppressions", grade_steps.suppressions_gate),
    ("assemble", grade_steps.assemble_gate),
    ("build", grade_build.build_gate),
    ("tests-release", grade_steps.tests_gate_for("release")),
    ("tests-san", grade_steps.tests_gate_for("san")),
)
