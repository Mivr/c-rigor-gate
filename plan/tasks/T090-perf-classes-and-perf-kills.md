# T090: perf gate judging (complexity classes) and perf-killed mutants (P002 G30)

Repo: `Mivr/c-rigor-gate`. Branch `task/T090`. Read `AGENTS.md`, `docs/perf.md` (the `c_perf` rule, records,
determinism, the perf bundle), `docs/mutate.md`, `docs/grade.md`, `rules/perf.bzl`, `rules/mutate.bzl`,
`gate/rigor_lib/perf_bundle.py`, `mutants_verdict.py`, `mutants_report.py`, `grade_mutants.py`.

## Why
`c_perf` produces deterministic instruction and libc-byte counts at sizes `[n, 4n]` but nothing judges them. Two needs:
1. **Complexity classes.** A product declares, per `c_perf` target, the class its operation must have; the gate fails
   when the counts grow faster.
2. **Perf-killed mutants.** In `Mivr/business-apps`, a hash map's hash function (`lib/ds/fmap`) can be replaced by
   `return 0` and every functional test still passes, because the map stays correct, only O(n) per operation. Such a
   mutant is not equivalent: it breaks the module's complexity promise. The mutants gate must count a mutant as
   killed when it makes a declared perf target leave its class.

## Build
1. **Policy:** in `products/<p>/policy.toml`, per module: `[module."//x:y".perf."//x:y_perf"] class = "O(1)" | "O(log n)"
   | "O(n)" | "O(n log n)"` (document the exact shape you choose). Judging on the `instructions` and `libc_bytes` of the
   size pair `(n, 4n)` (use the first and last sizes if more are given):
   - `O(1)`: ratio <= 1.10; `O(log n)`: `count(4n) - count(n)` <= a fixed additive constant you derive and document
     (for example `max(64, 0.10 * count(n))`), or ratio <= 1.5, whichever you can justify from measurements;
     `O(n)`: ratio <= 4.4; `O(n log n)`: ratio <= 4.4 * log2(4n)/log2(n) * 1.1. Use both counters; either exceeding
     fails. Measure the fixtures and say how much headroom each threshold has.
   - Findings: `perf-class-exceeded` (error, names target, class, both counts and the ratio), `perf-counter-unavailable`
     (error in a decisive grade: no verdict without counts), `perf-record-bad` (status not ok).
2. **Gate:** a `perf` gate in `gate/order.txt` after the test gates, reading the perf bundle the grade already builds
   (T080). Products without perf entries: PASS with info `no-perf-targets`.
3. **Perf kills:** `c_mutants` gains an optional `perf = [":x_perf", ...]` attribute (the module's `c_perf` targets).
   For a mutant that survives every functional test, the mutant build also runs those perf targets; a mutant whose perf
   counts leave the declared class is `killed-perf` (a new outcome, counted as killed; report it separately, and keep
   `crash-kill-ratio` logic unaffected). Keep the cost bounded: perf runs only for functional survivors, and say what a
   survivor costs.
4. **Canaries / fixtures:** a fixture module with an O(1) operation whose mutant is O(n) (for example a lookup table
   index replaced by a scan) and no functional test that notices: the mutant is `killed-perf`; a canary
   `perf-class-exceeded` (an O(n^2) driver declared O(n)): red; `control` green.
5. Docs: `docs/perf.md` (judging section), `docs/mutate.md` (`killed-perf`), `docs/grade.md` row.

## Allowed paths
`rules/perf.bzl`, `rules/mutate.bzl`, `ctest/perf.*` (only if needed), `gate/rigor_lib/perf*.py`,
`gate/rigor_lib/mutants_*.py`, `gate/rigor_lib/grade_mutants.py`, `gate/rigor_lib/grade_pipeline.py`,
`gate/rigor_lib/grade_checks.py`, `gate/rigor_lib/facts_policy.py` (the perf policy table only), `gate/order.txt`,
`gate/tests/test_*perf*.py`, `gate/tests/test_*mutant*.py`, `gate/tests/fixtures/perf/**`, `gate/tests/fixtures/mutate/**`
(new fixtures only), `selftest/perf.sh` (add cases only), `canaries/perf-*/**`, `docs/perf.md`, `docs/mutate.md`,
`docs/grade.md`, `tools/affected.toml` (rules for new paths only).

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/perf.sh
selftest/mutate.sh
selftest/canaries.sh --only control --only perf-class-exceeded
selftest/grade.sh
```
Report the change, the policy shape, the thresholds with measured headroom, the `killed-perf` fixture result, the
cost per survivor, and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T090/tmp`; never write to `/tmp`. Build only with `gate/tools/buck2`, never host compilers.
No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill processes you did not start; never
`buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
