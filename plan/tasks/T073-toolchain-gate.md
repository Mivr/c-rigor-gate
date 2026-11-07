# T073: toolchain verification is its own `toolchain` gate (B33 part a)

Repo: `Mivr/c-rigor-gate`. Branch `task/T073`. Read `AGENTS.md` ("Working efficiently"), `plan/backlog.d/B33.md`,
`docs/grade.md` (gate list, order, verdict), `gate/order.txt`, `gate/rigor_lib/grade_pipeline.py`, `grade_build.py`
(`toolchain_verify.prepare` before the build) and `toolchain_verify.py`.

## Problem
In an `--uncached` grade, `grade_build` verifies the cached toolchain tree against `toolchains/*.manifest` (T030) before
building. A failed verification today surfaces as `build` FAIL (`build-failed`, with a `TOOLCHAIN VERIFICATION FAILED`
stderr tail), so a verdict cannot tell "the product does not compile" from "the grader's toolchain is not the pinned
one". The second is a grader-integrity failure, not a product failure.

## Requirement
1. A new gate `toolchain` in `gate/order.txt`, before `build` (and before any other gate that compiles or links; check
   `structure`, `symbols`, facts and modes for that), and in the pipeline. It runs the verification once per grade.
   Status values:
   - PASS with info `toolchain-verified` (the manifest names and hashes) when verified;
   - PASS with info `toolchain-not-verified` (reason: cached grade) when no verification applies;
   - FAIL with error `toolchain-mismatch` (manifest, first differing path, the verifier's exit code) otherwise.
2. When `toolchain` fails, every gate that would compile is **not run** (the existing not-run mechanism, with a reason
   naming `toolchain`). No product gate reports `build-failed` for it, and the overall verdict is FAIL. Exit codes follow
   the existing rules for a failed gate. Decide whether a grader-integrity failure should rather be exit 2, document
   the choice in `docs/grade.md`, and justify it in your report.
3. `grade_build` no longer verifies by itself; the verification runs at most once per grade, as today.
4. Tests: unit tests for the three outcomes through the pipeline with the verifier faked at its existing seam, and an
   update to every expectation that lists the gate order (selftest steps and canaries `expect.json` that enumerate gates
   or NOT_RUN sets). The canary pack must stay at 0 misses.
5. Verdict format: `toolchain` appears in `core` like every other gate. Document it in `docs/grade.md`.

## Allowed paths
`gate/order.txt`, `gate/rigor_lib/grade_pipeline.py`, `grade_build.py`, `grade_steps.py` (if gates are registered there),
`toolchain_verify.py`, a new `gate/rigor_lib/grade_toolchain.py`, `gate/tests/test_grade*.py`, `gate/tests/test_toolchain*.py`,
`selftest/grade.sh` (expectations only), `canaries/*/expect.json` (gate-list expectations only), `docs/grade.md`,
`plan/backlog.d/B33.md` (mark part a done).
**In flight in parallel:** T070 (`grade_mutants.py`, `selftest/mutate.sh` end, maybe a new canary), T067 (`mutate/tool.py`,
`selftest/mutate.sh`). Do not touch those files.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_grade*.py'
selftest/gate.sh
TMPDIR=/var/tmp/cache/T073/tmp selftest/grade.sh                      # via tools/job
TMPDIR=/var/tmp/cache/T073/tmp selftest/canaries.sh                   # via tools/job, full pack, 0 misses
selftest/toolchain.sh
```
Plus one `--uncached` grade of the selftest product in your cache dir with a deliberately corrupted copy of the
cached toolchain tree. Corrupt only a scratch copy that you point the grade at, never the shared cache. Show `toolchain`
FAIL and the compiling gates not run. If the verifier cannot be pointed at a scratch copy without a code change, use
the unit-test seam instead and say so. Report every deviation.
