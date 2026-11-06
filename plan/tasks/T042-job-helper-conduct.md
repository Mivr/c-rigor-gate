# T042: `tools/job` (background jobs without polling) and the agent conduct block

Repo: `Mivr/c-rigor-gate`. Branch `task/T042`. Read `AGENTS.md` first. Source: the R006/R007 speed-up reviews
(orchestrator, 2026-11-06): about 11% of agent turns were spent waiting on background jobs (sleep/`until` loops,
`tail` peeks, Monitor calls that failed schema validation), each poll turn re-reads ~155k tokens of context,
and one lane stalled 59 min on a dead watcher. Several trajectory false positives came from agents putting
scratch under `/var/tmp/rigor-*` instead of their own cache dir.

**In flight in parallel:** T021 (`grade.py`, `grade_context.py`, `verdict*`, `approvals.py`), T030 (`grade_build.py`,
`toolchains/**`), T032 (`grade_steps.py`, `grade_pipeline.py`, `grade_checks.py`, `grade_tree.py`, `grade_policy.py`,
`gate/order.txt`, `selftest/grade.sh`), T033 (`facts_*`), T034 (`rules/mutate.bzl`, `mutate/**`), T035
(`mutate/gen.py`). Touch none of them. **Do not edit `plan/backlog.md`**; put any backlog note in your report.

## Allowed paths
- new `tools/job` (Python 3 stdlib, executable, `#!/usr/bin/env -S python3 -I`) and new `tools/lanes/job_lib.py`
  if you want a module;
- new `gate/tests/test_job.py`;
- `gate/rigor_lib/trajectory_bash.py`, `trajectory_cmds.py`, `trajectory_shell.py` (only for recognising
  `tools/job`), plus new or existing `gate/tests/test_trajectory*.py` cases;
- `AGENTS.md` (a new section "## Working efficiently"; do not change the existing rules' meaning);
- `docs/lanes.md` (a new "Waiting on long jobs" section), `docs/trajectory.md` (the `tools/job` rule).

## Requirements

### 1. Measure the harness first
Agents are Claude Code subagents. A subagent is **not** re-invoked when its background shell finishes (ending
its turn ends the task), so it must wait with a blocking call. Measure, from your own session, and record the
numbers in `docs/lanes.md`: (a) the longest a foreground Bash call can block when `timeout` is set to 600000
(R007 reports the harness moves calls past ~180 s to the background regardless; confirm or refute), (b) what
happens to a foreground call that is auto-backgrounded. Design `wait` around the measured limit.

### 2. `tools/job`
- `tools/job run [--deadline SECONDS] [--dir DIR] NAME -- CMD [ARG...]`: starts CMD detached (new session,
  stdin `/dev/null`, stdout+stderr to `DIR/NAME/log`), with the caller's cwd and environment **unchanged**
  (adds nothing, removes nothing), records argv, start time, pid; on exit writes the exit code and end time;
  at the deadline kills the whole process group and records `killed`. Prints one line: the job name, pid, and the
  argv it is running (so the transcript shows the real command). Refuses an existing running NAME.
- `tools/job wait NAME [--max SECONDS]`: blocks until the job ends or `--max` (default: the measured safe limit
  minus a margin) elapses. Prints exactly one status line while running (`running 312s`), or on completion
  the exit code, wall time and the **last 30 lines of the log with ANSI escapes stripped**, or `KILLED after S s`.
  Exit code: the job's exit code when finished, 124 when still running, 2 on any tool error.
- `tools/job status NAME` (non-blocking, same output as `wait --max 0`), `tools/job list`.
- `DIR` defaults to `$TMPDIR/jobs` when `TMPDIR` is set, else refuses. The resolved DIR must be inside
  `/var/tmp/cache/` (realpath, no symlinks in the path); refuse anything else. No network, no shell string
  evaluation: CMD is executed as an argv, never through `sh -c` unless the caller wrote `sh -c` themselves.
- A job whose runner died (pid gone, no exit record) is reported as `lost`, never as running forever.

### 3. Trajectory
`rigor trajectory` must audit `tools/job run ... -- CMD ARGS` exactly as if `CMD ARGS` had been run directly at
that point (all rules: network, paths, git, tamper, literals), in addition to the `tools/job` call itself.
`wait`/`status`/`list` are read-only commands. Red tests: a wrapped `curl`, a wrapped `rm -rf` outside the
allowed write roots, a wrapped `git push`, `--dir` pointing outside `/var/tmp/cache/<task>` all block; a wrapped
`selftest/gate.sh` passes. `TRAJECTORY_REAL_DIR=/var/tmp/cache/T042/real gate/tests/trajectory_real.sh` must keep
every existing verdict (11 transcripts staged there).

### 4. `AGENTS.md` "## Working efficiently" (short, imperative, numbered)
1. Long commands (> 2 min): `TMPDIR=/var/tmp/cache/<task>/tmp tools/job run ...` then `tools/job wait`; no sleep
   loops, no `tail -f`, no polling a file.
2. Scratch files only under `/var/tmp/cache/<task>/` (set `TMPDIR` there); never `/var/tmp/rigor-*` or `/tmp`.
3. Never `buck2 kill` unless a check needs a cold daemon; a selftest you change must pass twice in a row.
4. Exploratory scripts under `timeout 300`. If you are 45 min in without a passing acceptance step, report
   progress and the blocker instead of continuing silently.
5. Read files by line range and filter command output (`| tail -40`); use the Edit tool for small changes
   instead of rewriting whole files.
6. Do not merge `main` into your branch unless the task says so or a real conflict blocks you.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_job*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T042/real gate/tests/trajectory_real.sh
selftest/gate.sh
# demo, shown in the report:
TMPDIR=/var/tmp/cache/T042/tmp tools/job run --deadline 30 demo -- sh -c 'echo hi; sleep 5; echo done'
TMPDIR=/var/tmp/cache/T042/tmp tools/job wait demo        # exit 0, prints hi/done
TMPDIR=/var/tmp/cache/T042/tmp tools/job run --deadline 2 slow -- sleep 60; tools/job wait slow  # KILLED
```
Report the harness measurements, the wait limit you chose and why, and every deviation.
