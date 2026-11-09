# T129: the `fuzz` gate in `rigor grade`, with canaries (P003 W6 part 2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T129` from main (T126 and T127 merged). Read P003 §7.2 and §4, `docs/fuzz.md`,
`gate/rigor_lib/fuzz_gate.py`, `rules/fuzz.bzl`, `docs/grade.md` ("The gate list", "Mutation testing in the pipeline",
"Verdict determinism and bound inputs"), `gate/rigor_lib/grade_pipeline.py`, `grade_build.py`, `grade_mutants.py`,
`grade_steps.py`, `verdict_inputs.py`, `docs/canaries.md`, `gate/rigor_lib/profiles.py`.

## Why
T126 landed `c_fuzz(corpus, runs)` and the judge `rigor fuzz`, but no grade runs them. This task makes fuzzing part of
the verdict.

## Do
1. **Gate `fuzz`** in `GATES` and `gate/order.txt`, after `tests-stub`. It needs `assemble`, `buckfiles`, `build` and
   both `tests-*` PASS, otherwise NOT_RUN.
   - Targets: every product `c_fuzz` target, found with `buck2 uquery` in the grading tree, built in
     `toolchains//:linux_fuzz`. Collect each target's `verdict`, `report`, `crash`, `stats.json` and `replayed` outputs
     into `<work>/fuzz/` in exactly the layout `rigor fuzz` reads, then judge in process.
   - A build that does not produce a target's outputs is `fuzz-build-failed` for that target (an error). A transport
     failure is retried once, exactly as `grade_build.transport_failure` does for other builds; nothing else is retried.
   - Role `test-author`: PASS with info `not-applicable`, as `mutants` does (the stubs are not fuzzed).
   - A product with no `c_fuzz` target and no module that must be fuzzed: PASS with info `no-fuzz-targets`.
   - The action is deterministic, so the cache answers a repeat grade; `--uncached` behaves as for every other build.
     Metadata: executed and cached action counts, per-target runs and corpus sizes.
2. **Which modules must be fuzzed.** A module with `fuzz = true`, or whose `profile` list contains `parser`
   (`[module."//pkg:name"] profile = [...]`, T127). Teach `fuzz_gate.load_policy` the second rule.
3. **Policy keys everywhere.** Every reader of `policy.toml` must accept `fuzz`, `fuzz_runs` and `profile` (today
   `facts_policy.py` rejects `fuzz` and `fuzz_runs` as unknown keys, so a product policy that uses them breaks the
   `symbols` gate). A unit test loads one policy with all three keys through every reader.
4. **Regression inputs.** An optional gate-owned `products/<p>/fuzz-regressions.json` (`{"<target label>":
   ["<sha256>", ...]}`), snapshotted and bound into `core.inputs` like `expected-tests.json`, and passed to the judge.
5. **Canaries**, each red on the gate `fuzz` and nowhere else unless stated, plus the control staying green:
   `fuzz-crash` (a parser with an out-of-bounds read the budget reaches), `fuzz-missing` (a `parser` module without a
   target), `fuzz-vacuous-harness` (the harness never calls the module), `fuzz-regression-dropped` (the list names an
   input that is not in the corpus). Follow `docs/canaries.md` for the catalogue and the expected-red declarations.
6. **Selftest.** `selftest/grade.sh` gets steps for the gate: a product with a clean fuzz target passes with the gate
   PASS; a second identical grade executes zero fuzz actions. If `selftest/grade_product` has to grow a fuzz target,
   update the expectations that depend on its layout and say which.
7. **Docs.** `docs/grade.md` (the gate list and a "Fuzz in the pipeline" section), `docs/fuzz.md`, `docs/canaries.md`;
   fix the stale lines in `docs/toolchain.md` and `docs/ctest.md` that still place `fuzz_run` in `rules/ctest.bzl`.

## Not in this task
`rules/**` (no rule change should be needed; if one is, stop and report), `products/**`, a nightly campaign, the
`policy-check` gate, `mutate/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/grade.sh`; `selftest/canaries.sh --jobs 8`;
`selftest/tripwires.sh --jobs 5`; `selftest/fuzz.sh`; `selftest/product_checks.sh`;
`python3 -I tools/affected.py --check`. `selftest/perf.sh` fails on main for an unrelated reason (backlog B35): do
not spend time on it.

## Allowed paths
`gate/rigor_lib/grade*.py`, `gate/rigor_lib/fuzz_gate.py`, `gate/rigor_lib/verdict_inputs.py`, the policy readers (key
acceptance only), `gate/order.txt`, `gate/tests/**`, `canaries/**`, `selftest/grade.sh`, `selftest/grade_product/**`,
`selftest/canaries.sh` (only if the runner must learn the new gate), `docs/**`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T129`. `TMPDIR=/var/tmp/cache/T129/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Commit on `task/T129`; your last message is the report (what works, what does not, every deviation).
