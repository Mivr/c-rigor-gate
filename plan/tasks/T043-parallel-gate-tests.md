# T043: run the gate's unit tests in parallel (speed-up R006 #3)

Repo: `Mivr/c-rigor-gate`. Branch `task/T043`. Read `AGENTS.md` first.
`selftest/gate.sh` runs ~1000 unittest tests in one process: median ~110 s (61-402 s), and it runs in every
validation and ~190 times a day in agent sessions. The host is idle (median 0.05 of 32 cores).

**In flight in parallel:** T030 (`grade_build.py`, `toolchains/**`), T032 (`grade_steps.py`, `grade_pipeline.py`,
`grade_checks.py`, `grade_tree.py`, `grade_policy.py`, `gate/order.txt`, `selftest/grade.sh`), T033 (`facts_*`),
T034 (`rules/mutate.bzl`, `mutate/**`), T042 (`tools/job`, `trajectory_*`, `AGENTS.md`, `docs/lanes.md`). Touch none
of them. **Do not edit `plan/backlog.md`.**

## Allowed paths
`selftest/gate.sh`, new `gate/tests/run_parallel.py`, new `gate/tests/test_run_parallel.py`, `docs/gate.md` (a short
"Running the tests" note).

## Requirements
1. `gate/tests/run_parallel.py` (stdlib only, run as `python3 -I -B gate/tests/run_parallel.py [--jobs N]`): discovers
   the same tests as `python3 -I -B -m unittest discover -s gate/tests -t gate` (same start dir, top dir, pattern),
   runs each test **module** in its own subprocess (`python3 -I -B -m unittest <module>` from the same cwd and env,
   with a per-module `TMPDIR` under the caller's `TMPDIR`), `--jobs` defaulting to half the CPUs (min 1, max 16).
   Longest modules first (order by a recorded duration file in `$TMPDIR` if present, else by size); this is only a
   scheduling hint, never a skip.
2. Output: one line per finished module (`ok|FAIL module tests seconds`), then on failure the full output of each
   failed module, then a summary `Ran N tests in S s` with N the total actually run.
3. Exit 1 if any module fails or errors, **or if the number of tests run differs from the number discovered**, or if
   a module could not be imported, or produced no test count. Exit 2 on a runner error. A module that hangs is killed
   after `--timeout` (default 900 s) and counts as a failure.
4. `selftest/gate.sh` uses the runner. Keep the Python version check and the final line
   `selftest/gate.sh: all gate tests passed` (the orchestrator greps it). Keep `GATE_SERIAL=1` as a way to run the old
   single-process command.
5. Tests must not depend on running in the same process; if a module fails only in parallel (shared files in `/var/tmp`,
   fixed ports, cwd changes), report it — do not edit other test modules (they are outside your paths). The
   per-module `TMPDIR` should already isolate most of it.

## Acceptance
```sh
python3 -I -B -m unittest gate.tests.test_run_parallel   # from the repo root, -t gate as needed
time GATE_SERIAL=1 selftest/gate.sh    # old path, show N and seconds
time selftest/gate.sh                  # new path: same N, show seconds
selftest/gate.sh; selftest/gate.sh     # twice in a row, both pass
# red: in a scratch copy under /var/tmp/cache/T043, add a failing test to one module and a module with an import
# error; the runner exits 1 and names both; delete a test's discovery (count mismatch) -> exit 1
```
Report both timings and N, the jobs value used, and any test that is order- or process-dependent.
