# T136: perf counts are comparable only within one CPU model (backlog B35, reopened)

Repo: `Mivr/c-rigor-gate`. Branch `task/T136` from main (T130 merged). Read `plan/backlog.d/B35.md`, `docs/perf.md`
("Determinism", "libc bulk bytes"), `gate/rigor_lib/perf_judge.py` (`count_bound`, `counts_agree`), `ctest/perf.c` (the
`cpu` and `reps` metadata T130 added), `selftest/perf.sh`.

## Why (measured 2026-11-10, after T130)
T130 found a drift of 2 to 4 instructions between executions on one CPU model and gave the selftest's identity check
a bound of `16 + count/2^20`. The selftest still fails now and then: in the validation of T131 it reported
`mmove: instructions differ beyond the bound between cold runs: 4927378 vs 4927410`, a difference of 32 against a
bound of 20. T130 only ever saw runs on one CPU model (`Xeon E5-2690 v4`). The farm has a second family (a Zen 4
host), and `mmove` goes through libc's `memmove`, which glibc dispatches per CPU. The likely cause is that the two
runs landed on different CPU models. That is a hypothesis: prove or refute it first.

## Do
1. **Measure.** Run each selftest fixture uncached until you have at least 5 records from each CPU model the farm
   offers (the `cpu` field tells you which). Table per fixture and size: the counts per CPU model, the spread inside
   one model, the difference between models. Say plainly whether the 32-instruction difference is between models. If
   only one model ever runs these actions, say so and find what else produces a difference of that size.
2. **Fix the comparison, not the bound.** Raw counts are compared only between records with the same `cpu` string,
   with T130's bound. For records from different CPU models the identity check compares what the judge uses: the
   complexity class and the ratios between sizes, within the judge's existing margins. Do not widen `count_bound` to
   cover a cross-model difference. If your measurement shows the same-model drift itself exceeds the bound, derive a
   new bound from the data and state the margin.
3. **Check the verdict path.** Confirm, with a test, that a product perf verdict (`perf-class-exceeded`, and the
   `killed-perf` mutant verdict) never compares raw counts from two different actions: a class is judged from the
   records of one run. If any place does compare across actions, apply the same rule there and report it.
4. **Tests.** Unit tests: same model inside and outside the bound; different models with the same class (agree);
   different models with a different class (differ). `selftest/perf.sh` passes ten times in a row with uncached runs.
5. **Backlog and docs.** `plan/backlog.d/B35.md`: what T130 found, what this task found, what was done; fold with
   `python3 -I tools/backlog_fold.py`. `docs/perf.md`: the table and the rule.

## Not in this task
Any worker or farm setting; the judgement of complexity classes; `products/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/perf.sh` ten times in a row; `selftest/mutate.sh`;
`selftest/grade.sh`; `selftest/canaries.sh --jobs 8`; `python3 -I tools/affected.py --check`.

## Allowed paths
`ctest/perf.h`, `ctest/perf.c`, `rules/perf.bzl`, `gate/rigor_lib/perf_*.py`, `gate/rigor_lib/mutants_perf.py`,
`gate/tests/test_perf*.py`, `selftest/perf.sh`, `selftest/perf*/**`, `docs/perf.md`, `plan/backlog.d/B35.md`,
`plan/backlog.md` (through the fold tool only), `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T136`. `TMPDIR=/var/tmp/cache/T136/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. If you need a throwaway script (a measurement copy of the selftest, for example), write the whole file with
the Write tool or a heredoc so its text is in your transcript; do not derive it with `sed` from another file.
`rigor grade` and the canary runner refuse a dirty checkout: commit before you run them. Commit on `task/T136`; your
last message is the report (the table, the cause, what changed, every deviation).
