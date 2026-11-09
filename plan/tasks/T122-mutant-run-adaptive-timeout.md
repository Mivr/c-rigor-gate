# T122: adaptive per-run timeout for mutant test runs (the hanging-mutant tail)

Repo: `Mivr/c-rigor-gate`. Branch `task/T122` from main (T121 merged: stop at first failed check, stable names, 3
chunks in flight). Read `mutate/tool.py` (`RUN_TIMEOUT_SECONDS = 180`, the baseline runs), `rules/mutate.bzl`,
`docs/mutate.md`, and T121's commits.

## Why (measured on business-apps T120, 2026-11-09)
Chunk 0 waited more than 80 minutes on two `lk/inventory` mutants that make a test loop forever. Each mutant runs every
dependent test binary (about 175), and each run is killed only after `RUN_TIMEOUT_SECONDS = 180` (ctest kills one test
after 10 s, so a binary with many hanging tests runs until 180 s): up to about 8.7 h for ONE mutant. T121 stops only at
a failed check (to keep killed-assert vs killed-crash identical), so a hang still costs every test binary its timeout.

## Do
1. Replace the fixed 180 s with an adaptive limit per test binary, derived from that binary's BASELINE run in the same
   batch (the unmutated run the tool already does): `limit = clamp(K * baseline_wall, MIN, 180)`; pick K and MIN from
   data (propose K = 20, MIN = 5 s; justify with the fixture and the business-apps baseline times if you can get them
   from a report), and make the per-test ctest timeout follow the same idea if it is set by the tool. A baseline that
   itself times out keeps the old 180 s.
2. A timeout stays a timeout verdict (same class, same reason text shape), so verdicts do not change except that a
   mutant that would have finished between the new limit and 180 s now records a timeout; show that this cannot turn
   a survivor into a kill wrongly (a run that exceeds K x baseline is a hang for a deterministic test), and document
   the rule and its numbers in `docs/mutate.md`.
3. Optional and only if it keeps verdicts identical: once one run of a mutant has TIMED OUT, later runs of that mutant
   get MIN as their limit (a hang is usually in a shared path). If it could change a verdict class, do not do it; say why.
4. Tests in `gate/tests` and a selftest fixture with a mutant that hangs (an infinite loop guarded by the mutation):
   before/after wall time and identical verdicts.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`, `selftest/product_checks.sh`, `selftest/canaries.sh`, `selftest/grade.sh`.

## Allowed paths
`mutate/**`, `gate/**`, `rules/**`, `selftest/**`, `docs/**`, `tools/affected.toml`. NOT `products/**`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T122`. `TMPDIR=/var/tmp/cache/T122/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. Never end your turn while a job you started is running. Commit on `task/T122`; your last message
is the report (the numbers chosen and why, timings, verdict diff).
