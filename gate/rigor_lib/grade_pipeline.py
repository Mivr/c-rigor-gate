"""THE gate list of `rigor grade`. To add a gate, add one row; nothing else registers gates.

Rows run in this order. A step is `function(grading) -> GateResult | None`; its result file is
`<id>.json`, and `None` means "did not run" (the verdict shows NOT_RUN, which fails). The ids
here must equal, in the same order, the lines of `gate/order.txt` (a test checks that).
Any exception inside a step is an internal error: the step is recorded as FAIL and the
remaining steps do not run. Every gate that compiles is wrapped in `needs_toolchain`: it runs only
after the `toolchain` gate passed (grade_toolchain), otherwise it is NOT_RUN.
"""

from rigor_lib import grade_build, grade_checks, grade_decoupling, grade_fuzz, grade_mutants, grade_oracle, grade_sanmodes, grade_sim, grade_steps
from rigor_lib import grade_structure
from rigor_lib import grade_toolchain, grade_witness, perf_gate
from rigor_lib.errors import InternalError


def _compiling(gate_id, step):
    """The row of a gate that compiles: it runs only once `toolchain` passed (grade_toolchain)."""
    return gate_id, grade_toolchain.needs_toolchain(gate_id, step)


# `rigor grade --only a,b` (T2G2, for the historical canaries of T2G8): the selected gates run together with what they need, every
# other gate is left out of the grade and of the verdict's order. The foundation is always needed; the gates below also need the
# tree built and both test gates green (their own NOT_RUN rule); the witness gates need the mutants gate.
FOUNDATION = ("clone", "assemble", "toolchain", "buckfiles")
NEEDS_BUILT = ("build", "tests-release", "tests-san")
_BUILT_USERS = frozenset(NEEDS_BUILT + ("structure", "mode-divergence", "tests-msan", "tests-tsan", "tests-stub", "fuzz", "sim",
                                        "oracle", "perf", "mutants", "witness-tests", "mutants-witness"))
_WITNESS = frozenset(("witness-tests", "mutants-witness"))


def selection(only, ids):
    """The set of gate ids a grade with `--only ONLY` (a list of ids) runs, IDS being every id of the pipeline. An empty or unknown
    selection is an InternalError, so a typo never turns into a grade that judges nothing."""
    unknown = sorted(set(only) - set(ids))
    if not only or unknown or len(set(only)) != len(only):
        raise InternalError("--only: want distinct known gate ids, got %s (unknown: %s)" % (list(only), unknown))
    chosen = set(only) | set(FOUNDATION)
    if chosen & _BUILT_USERS:
        chosen |= set(NEEDS_BUILT)
    if chosen & _WITNESS:
        chosen |= {"mutants"}
    return chosen


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
    ("decoupling", grade_decoupling.decoupling_gate),  # compiles only with a decoupling.toml (it wraps itself)
    _compiling("build", grade_build.build_gate),
    _compiling("structure", grade_structure.structure_gate),
    _compiling("mode-divergence", grade_structure.modes_gate),
    ("tests-release", grade_steps.tests_gate_for("release")),
    ("tests-san", grade_steps.tests_gate_for("san")),
    # They build their own results (the subset of targets the mode has) and need the toolchain like any compiling gate.
    _compiling("tests-msan", grade_sanmodes.sanitizer_tests_gate("msan")),
    _compiling("tests-tsan", grade_sanmodes.sanitizer_tests_gate("tsan")),
    ("tests-stub", grade_steps.tests_stub_gate),
    # `fuzz` builds in the fuzz platform, only after `build` and both test gates passed (grade_fuzz.REQUIRED).
    _compiling("fuzz", grade_fuzz.fuzz_gate_step),
    # `sim` builds in the san and release platforms, after `build` and both test gates passed (grade_sim.REQUIRED).
    _compiling("sim", grade_sim.sim_gate_step),
    # `oracle` replays the hidden Rust traces with the product's replayer built in the san platform, after `build` and both test
    # gates passed (grade_oracle.REQUIRED).
    _compiling("oracle", grade_oracle.oracle_gate_step),
    # `perf` builds, but only after `build` and both test gates passed (perf_gate.REQUIRED), which already need the toolchain.
    ("perf", perf_gate.perf_gate),
    _compiling("mutants", grade_mutants.mutants_gate),
    _compiling("witness-tests", grade_witness.witness_tests_gate),
    _compiling("mutants-witness", grade_witness.mutants_witness_gate),
)
