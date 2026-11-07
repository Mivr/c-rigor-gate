"""The `toolchain` gate (T073, backlog B33 a): is the grader's toolchain the pinned one?

It is a grader-integrity check, not a product check, and it runs before every gate that compiles. In an
`--uncached` grade it verifies the cached toolchain trees against `toolchains/*.manifest` once
(`toolchain_verify.prepare`, in the head tree's daemon, which `semantic-suppressions`, `symbols` and
`build` then reuse). A cached grade trusts the action cache for every action anyway, so nothing is
verified there. Outcomes:

  * PASS, info `toolchain-verified` (each manifest's path and sha256);
  * PASS, info `toolchain-not-verified` (reason `cached grade`);
  * FAIL, error `toolchain-mismatch` (manifest, first differing path, step, buck2 and verifier exit codes);
  * NOT_RUN in an uncached grade without an assembled tree (nothing to run Buck2 in).

`needs_toolchain` wraps the steps of the gates that compile (grade_pipeline): unless `toolchain` passed,
they do not run (NOT_RUN), so no product gate ever reports the grader's toolchain as `build-failed`.
"""

import os

from rigor_lib import grade_build, jsonio, toolchain_verify
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = "toolchain"
CACHED_REASON = "cached grade"


def manifest_hashes(tree):
    """[{path, sha256}] of the manifests in the grading tree: the gate commit's bytes the verifier read."""
    hashes = []
    for name in toolchain_verify.MANIFESTS:
        data = jsonio.read_bytes(os.path.join(tree, "gate", "toolchains", name))
        hashes.append({"path": "toolchains/" + name, "sha256": jsonio.sha256_hex(data)})
    return hashes


def mismatch(failure):
    return finding("toolchain-mismatch", manifest=failure.manifest(), first_difference=failure.first_difference(),
                   step=failure.step, exit_code=failure.code, verifier_exit_code=failure.verifier_exit_code())


def toolchain_gate(g):
    if not g.args.uncached:
        return GateResult(GATE_ID, [finding("toolchain-not-verified", severity=SEVERITY_INFO, reason=CACHED_REASON)],
                          {"verified": False})
    if g.status.get("assemble") != "PASS":
        return None  # no grading tree to run Buck2 in
    failure = toolchain_verify.prepare(grade_build._run_buck, g.tree)
    if failure is not None:
        return GateResult(GATE_ID, [mismatch(failure)], {"verified": False, "stderr_tail": failure.message()})
    return GateResult(GATE_ID, [finding("toolchain-verified", severity=SEVERITY_INFO,
                                        manifests=manifest_hashes(g.tree))], {"verified": True})


def needs_toolchain(gate_id, step):
    """`step` of a gate that compiles, run only once `toolchain` passed; otherwise NOT_RUN (None)."""
    def gated(g):
        status = g.status.get(GATE_ID, "NOT_RUN")
        if status != "PASS":
            print("%-14s not run: gate %s is %s" % (gate_id, GATE_ID, status))
            return None
        return step(g)
    gated.needs_toolchain = True
    return gated
