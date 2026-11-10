"""THE gate list of `rigor grade`. To add a gate, add one row; nothing else registers gates.

Rows run in this order. A step is `function(grading) -> GateResult | None`; its result file is
`<id>.json`, and `None` means "did not run" (the verdict shows NOT_RUN, which fails). The ids
here must equal, in the same order, the lines of `gate/order.txt` (a test checks that).
Any exception inside a step is an internal error: the step is recorded as FAIL and the
remaining steps do not run. Every gate that compiles is wrapped in `needs_toolchain`: it runs only
after the `toolchain` gate passed (grade_toolchain), otherwise it is NOT_RUN.
"""

from rigor_lib import grade_build, grade_checks, grade_fuzz, grade_mutants, grade_sanmodes, grade_steps
from rigor_lib import grade_structure
from rigor_lib import grade_toolchain, grade_witness, perf_gate


def _compiling(gate_id, step):
    """The row of a gate that compiles: it runs only once `toolchain` passed (grade_toolchain)."""
    return gate_id, grade_toolchain.needs_toolchain(gate_id, step)


GATES = (
    ("clone", grade_steps.clone_gate),
    ("contract", grade_steps.contract_gate),
    ("suppressions", grade_steps.suppressions_gate),
    ("assemble", grade_steps.assemble_gate),
    ("toolchain", grade_toolchain.toolchain_gate),
    ("buckfiles", grade_checks.buckfiles_gate),
    _compiling("semantic-suppressions", grade_checks.semantic_gate),
    _compiling("symbols", grade_checks.symbols_gate),
    ("layering", grade_checks.layering_gate),  # compiles only with an architecture.toml (it wraps itself)
    _compiling("build", grade_build.build_gate),
    _compiling("structure", grade_structure.structure_gate),
    _compiling("mode-divergence", grade_structure.modes_gate),
    ("tests-release", grade_steps.tests_gate_for("release")),
    ("tests-san", grade_steps.tests_gate_for("san")),
    ("tests-stub", grade_steps.tests_stub_gate),
    # They build their own results (the subset of targets the mode has) and need the toolchain like any compiling gate.
    _compiling("tests-msan", grade_sanmodes.sanitizer_tests_gate("msan")),
    _compiling("tests-tsan", grade_sanmodes.sanitizer_tests_gate("tsan")),
    # `fuzz` builds in the fuzz platform, only after `build` and both test gates passed (grade_fuzz.REQUIRED).
    _compiling("fuzz", grade_fuzz.fuzz_gate_step),
    # `perf` builds, but only after `build` and both test gates passed (perf_gate.REQUIRED), which already need the toolchain.
    ("perf", perf_gate.perf_gate),
    _compiling("mutants", grade_mutants.mutants_gate),
    _compiling("witness-tests", grade_witness.witness_tests_gate),
    _compiling("mutants-witness", grade_witness.mutants_witness_gate),
)
