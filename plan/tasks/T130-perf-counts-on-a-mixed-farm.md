# T130: perf counts on a farm with more than one CPU model (backlog B35)

Repo: `Mivr/c-rigor-gate`. Branch `task/T130` from main. Read `plan/backlog.d/B35.md`, `docs/perf.md` in full
("Determinism", "libc bulk bytes", "Judging"), `ctest/perf.h`, `ctest/perf.c`, `rules/perf.bzl`,
`gate/rigor_lib/perf_judge.py`, `perf_gate.py`, `perf_bundle.py`, `mutants_perf.py`, `selftest/perf.sh`.

## Why (measured 2026-11-10)
`selftest/perf.sh` fails on main, 3 runs of 3: `quad: counts differ between cold runs`, 342312029 retired
instructions against 342312028. The farm now runs gate actions on three workers with two CPU families (two Xeon E5 v4
hosts and one Zen 4 host). `tools/validate.sh` selects `perf` for every change under `rules/**` or `toolchains/**`,
so every such validation is red. The product `perf` gate and the `killed-perf` mutant verdict read the same counts.

## Do
1. **Find the cause, with numbers.** Run the same perf binary uncached enough times to see every worker (record, in
   metadata only, the CPU model string of the machine that ran it). Answer: is the count constant per CPU model? Is
   the difference always one instruction, or does it grow with `n`? Which part of the measured window differs (the
   enable/disable edges of the counter, a microcoded or `rep`-prefixed instruction, an interrupt or signal landing in
   the window, kernel or hypervisor time leaking in)? Put the table in `docs/perf.md`.
2. **Fix it, in this order of preference.**
   1. Remove the cause so the count is identical on every worker (counter attributes such as `exclude_kernel`,
      `exclude_hv`, `exclude_idle`, pinning the thread for the window, moving the enable/disable edges, taking the
      count from a read inside the window). Prefer this if it works.
   2. Otherwise a **stated bound**: two runs agree when their counts differ by at most a bound you derive from the
      measurements and write down (an absolute number of instructions, or absolute plus a tiny relative term). The
      complexity-class judgement works on ratios between sizes and must not change. Show, with the mutate selftest and
      the perf canary, that no `killed-perf` verdict and no `perf-class-exceeded` finding changes.
   Either way: findings stay byte-identical on rerun (anything that can vary lives in metadata only; check where the
   counts are written today and fix it if they are in findings), no retry, no sleep, and nothing that depends on which
   worker ran the action.
3. **Tests.** Unit tests for the agreement rule (equal; inside the bound; outside the bound; a real class change).
   `selftest/perf.sh` passes five times in a row with uncached runs. If you chose the bound, add a selftest case with
   two synthetic records one instruction apart (agree) and one far apart (differ).
4. Close the backlog item: edit `plan/backlog.d/B35.md` (what was found, what was done) and run
   `python3 -I tools/backlog_fold.py`.

## Not in this task
Any worker or farm setting (you cannot change them, and the gate must not depend on them); `products/**`; the
judgement of complexity classes; `gate/rigor_lib/grade*.py` unless a count is written into findings there.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/perf.sh` five times in a row; `selftest/mutate.sh`;
`selftest/grade.sh`; `selftest/canaries.sh --jobs 8`; `python3 -I tools/affected.py --check`.

## Allowed paths
`ctest/perf.h`, `ctest/perf.c`, `rules/perf.bzl`, `gate/rigor_lib/perf_*.py`, `gate/rigor_lib/mutants_perf.py`,
`gate/tests/test_perf*.py`, `selftest/perf.sh`, `selftest/perf*/**`, `canaries/perf-*/**`, `docs/perf.md`,
`plan/backlog.d/B35.md`, `plan/backlog.md` (through the fold tool only), `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T130`. `TMPDIR=/var/tmp/cache/T130/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. The RE farm is shared: measure what you need once, not in a loop. No network except Buck2's
pinned downloads. Never end your turn while a job you started is running. Commit on `task/T130`; your last message is
the report (the cause, the numbers, what you changed, every deviation).
