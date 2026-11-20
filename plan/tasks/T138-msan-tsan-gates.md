# T138: the gates `tests-msan` and `tests-tsan` in `rigor grade` (P003 W5 part 2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T138` from main (T125 merged: the `msan` and `tsan` build modes and their
farm prerequisite). Read P003 §7.1, `docs/toolchain.md` (the two modes), `docs/grade.md` ("The gate list", the
`tests-*` gates, "Verdict determinism"), `docs/product-checks.md` ("Modes": `rigor facts --modes`),
`gate/rigor_lib/grade_pipeline.py`, `grade_context.py` (`MODES`), `grade_steps.py` (`tests_gate_for`), `grade_build.py`,
`grade_structure.py` (`modes_gate`), `facts_modes.py`, `tests_gate.py`, `rules/c.bzl` (`c_test(threads = ...)`, the
msan compatibility rule), `ctest/sanlog.c`, `selftest/sanmodes.sh`, `docs/canaries.md`.

## Why
The grade tests in `release` and `san` only. A read of uninitialised memory and a data race pass both (the
`sanmodes` selftest shows exactly that). T125 landed the two modes; this task makes them part of the verdict.

## Do
1. **Two gates**, after `tests-san` in `GATES` and `gate/order.txt`: `tests-msan` and `tests-tsan`. Each judges the
   results of its mode with the same `tests` rules as `tests-san` (expected ids, fail-closed results, assertion
   counts). NOT_RUN under the same conditions as `tests-san`. In role `test-author` they behave as `tests-san` does.
   - `tests-msan` expects every expected test except those that have no msan results target (a system library beyond
     libc and pthread in the link closure). Each such test is an info finding `msan-not-applicable` with the library
     that causes it; anything else missing is `missing-test` as today.
   - `tests-tsan` expects exactly the tests declared `threads = True`. A product with none passes with info
     `no-threaded-tests`.
2. **The `threads` declaration cannot hide a test or be empty.** From the symbol facts the gate already builds: a
   `c_test` whose own objects reference a thread-creation function (`pthread_create`, `thrd_create`) without
   `threads = True` is the error `threads-undeclared`; a `threads = True` test that references none is
   `threads-vacuous`. Put the two in the gate that owns test facts today, and say which.
3. **Mode divergence.** Code guarded by `__has_feature(memory_sanitizer)`, `__has_feature(thread_sanitizer)` or
   `__SANITIZE_*__` must be visible: extend the `mode-divergence` gate so the facts of the msan and tsan modes are
   compared with release exactly as the san facts are today. Close, in the same way for every mode, the known hole
   that a product macro wrapping `__has_feature` hides the use from the name-based comparison (evaluate on
   preprocessed text per mode; the canary `mode-divergent` shows the trick).
4. **Stable reports.** TSan prints `(pid=N)` and `(tid=N)`; scrub them in the normalizer (`ctest/sanlog.c`) so a
   report is byte-identical across runs, and drop the workaround in `selftest/sanmodes.sh`. Findings must not carry
   anything that varies between runs.
5. **A farm that refuses the call fails clearly.** When results of either mode end with the runtime's start-up CHECK
   (docs/toolchain.md), the gate's finding is `sanitizer-startup` naming the prerequisite, not a list of missing
   tests. It is an error. No retry.
6. **Canaries** (follow `docs/canaries.md`; every existing expectation that lists `tests-san` as NOT_RUN gets the two
   new gates as well, by running the pack, not by guessing): `uninit-read` (red on `tests-msan` only), `data-race`
   (red on `tests-tsan` only), `threads-undeclared`, `threads-vacuous`, `msan-guarded-code` (red on
   `mode-divergence`). The control stays green.
7. **Selftest and cost.** `selftest/grade.sh`: steps for both gates on the selftest product; a second identical grade
   executes zero actions for them. Report the wall time and action count the two gates add to a cold grade of the
   selftest product.
8. **Docs.** `docs/grade.md` (gate list, a row for each gate in the tier table if one exists on your base; both tiers
   run both gates), `docs/toolchain.md`, `docs/product-checks.md`, `docs/canaries.md`.

## Not in this task
`products/**`; the hardened release profile; any change to the `release`, `san`, `cov` or `fuzz` modes; `mutate/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/grade.sh`; `selftest/sanmodes.sh`; `selftest/ctest.sh`;
`selftest/product_checks.sh`; `selftest/canaries.sh --jobs 8`; `selftest/tripwires.sh --jobs 5`;
`python3 -I tools/affected.py --check`. The orchestrator runs the full `tools/validate.sh`.

## Allowed paths
`gate/rigor_lib/grade*.py`, `gate/rigor_lib/tests_gate.py`, `gate/rigor_lib/facts_*.py`, `gate/rigor_lib/cscan.py` (only
for item 3), `gate/order.txt`, `gate/tests/**`, `ctest/sanlog.c`, `ctest/sanlog.h`, `rules/c.bzl`, `rules/ctest.bzl`,
`rules/facts.bzl` (only what the gates need to collect: the modes' facts and results), `canaries/**`, `tripwires/**`
(expectations only), `selftest/grade.sh`, `selftest/grade_product/**`, `selftest/sanmodes.sh`, `selftest/sanmodes/**`,
`selftest/canaries.sh`, `docs/grade.md`, `docs/toolchain.md`, `docs/product-checks.md`, `docs/canaries.md`,
`docs/tripwires.md`, `docs/ctest.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T138`. `TMPDIR=/var/tmp/cache/T138/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. The sandbox you work in does not allow `personality(ADDR_NO_RANDOMIZE)`; the farm does: a sanitizer binary
you run locally can die at start-up, so prove things with results targets on the farm. If you need a throwaway
script, write the whole file with the Write tool or a heredoc so its text is in your transcript. `rigor grade` and
the canary runner refuse a dirty checkout: commit before you run them. Commit on `task/T138`; your last message is
the report (what works, what does not, the added cost, every deviation).
