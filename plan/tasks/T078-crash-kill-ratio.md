# T078: `crash-kill-ratio`: a function whose kills are mostly crashes fails at L3 (B31, R003 G6)

Repo: `Mivr/c-rigor-gate`. Branch `task/T078`. Read `AGENTS.md`, `plan/backlog.d/B31.md`, `docs/mutate.md` (verdicts,
`killed-assert`/`killed-crash`), `gate/rigor_lib/mutants_gate.py` (`crash-only-function`, `no-assert-kill-function`) and
`mutants_verdict.py`.

## Problem
`crash-only-function` fires only when **no** mutant of an L3 function is killed by a failed check. One assertion kill
satisfies it. So a test suite that only checks "does not crash" plus one trivial assertion passes L3, while most
behaviour changes are caught only because the mutant happened to crash (R003 G6).

## Requirement
1. **Calibrate first, on real data.** `/var/tmp/cache/T078/annas-mutants-reports/*.json` (read-only) are the 13 per-module
   mutant reports of the orchestrator's annas-c audit grade (T070, all modules built). `annas-mutants-verdict.json` is
   its `mutants` gate result. For every L3 function with at least one killed mutant, compute
   `crash_ratio = killed-crash / (killed-assert + killed-crash)` and the kill count. Report the distribution: a
   histogram, percentiles, and the top 20 functions by ratio with their counts. Choose a threshold and a minimum kill
   count so that honest, well-tested functions pass and the R003 G6 shape fails. Justify both from the data, not from
   intuition. A function with very few kills should not flip on one mutant.
2. Rule `crash-kill-ratio` in `mutants_gate.py`: error at L3 and above, info at L2, for a function whose kills number at
   least `min_kills` and whose `crash_ratio` exceeds the threshold. Fields: module, function, file, assert and crash
   counts, ratio, threshold. Thresholds are constants in one place, documented. `crash-only-function` stays as it is
   (ratio 1.0 is its own rule; do not double-report it).
3. Canary `crash-oracle` (red): a module whose tests check one trivial value per function plus "no crash", so that most
   of its mutants are `killed-crash`. It must fail `mutants` with `crash-kill-ratio` and pass every other gate. A green
   twin (the same module with real assertions) must PASS. New canaries need both `exports` and `impl` policy keys.
4. Report how many annas-c functions the chosen rule flags today (those become annas test tasks; this is expected), and
   list them.

## Allowed paths
`gate/rigor_lib/mutants_gate.py`, `gate/rigor_lib/mutants_verdict.py` (only if the counts must come from there),
`gate/tests/test_mutants*.py`, `canaries/crash-oracle/**`, `canaries/crash-oracle-green/**`, `docs/mutate.md`,
`plan/backlog.d/B31.md` (mark done; then `python3 -I tools/backlog_fold.py` and commit `plan/backlog.md`).
**In flight in parallel:** T070 in validation (`grade_mutants.py`, `rules/mutate.bzl`), T073 (grade pipeline). Do not touch them.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutants*.py'
selftest/gate.sh
TMPDIR=/var/tmp/cache/T078/tmp selftest/canaries.sh      # via tools/job, full pack, 0 misses
```
Report the calibration table, the chosen threshold and min-kill count with the reasoning, the annas-c functions it flags,
the canary results and every deviation.
