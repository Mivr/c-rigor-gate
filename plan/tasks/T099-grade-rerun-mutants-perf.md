# T099: `rigor grade` re-run into the same `--work` crashes in mutants-perf

Repo: `Mivr/c-rigor-gate`. Branch `task/T099`. Read `AGENTS.md`, `docs/grade.md`, `docs/perf.md`, `docs/mutate.md`
and the code that writes `<work>/mutants-perf/` (grep `mutants-perf` in `gate/rigor_lib/`).

## Bug
`rigor grade ... --work W` a second time into the same `W` fails in the mutants gate with
`[Errno 17] File exists: W/mutants-perf/004.json` (T098, business-apps): the perf-mutant results directory from the
previous run is not emptied, and the writer uses exclusive create.

## Fix
Make every per-run output directory under `--work` that the grade (re)creates start empty on each run, consistently
with how the other per-run directories are handled (find the existing convention and follow it; do not weaken the
exclusive-create safety for files written within one run). Stale files from a previous run must never be read as
results of this run. Add a unit test that runs the affected step twice into the same work dir (fixture-level, no
full product grade) and a regression line in the docs if `docs/grade.md` describes `--work` reuse.

## Acceptance (the orchestrator re-runs it)
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```

## Rules
Edit only `gate/**`, `docs/**`, `selftest/**`. Use `TMPDIR=/var/tmp/cache/T099/tmp`; never write to `/tmp`. Build only
with `tools/buck2`. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs; never search from `/`. Kill only processes you
started, by the pid `tools/job` recorded; never `rm` outside your cache dir. No sleep-poll loops. 2 CPUs, 8 GiB
shared. No network.
