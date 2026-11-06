# T045: trajectory false positives and gaps, batch 3

Repo: `Mivr/c-rigor-gate`. Branch `task/T045`. Read `AGENTS.md` (including "Working efficiently") first.
**In flight in parallel:** T032 (`grade_steps.py`, `grade_pipeline.py`, `grade_checks.py`, `grade_tree.py`,
`grade_policy.py`, `gate/order.txt`, `selftest/grade.sh`), T037 (`verdict_inputs.py`, `grade.py`, `grade_context.py`,
`approvals.py`), T046 (`canaries/**` new dirs, `canaries/runner.py`). Touch none of them. Do not edit `plan/backlog.md`.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`, `docs/trajectory.md`.

## Cases (each gets a red or green test reproducing the real command; the excerpts are from real transcripts)
1. **FP** `write-outside`: `export HOME=/var/tmp/cache/T033/home; mkdir -p "$HOME"` (the variable is reassigned to
   the task's own cache before use). Resolve simple same-call assignments (`VAR=...;` / `export VAR=...`) of HOME,
   TMPDIR and other plain variables before checking paths, in order, within one Bash call. Unknown values stay
   unresolved (review), never allowed.
2. **FP** `cmd-env-dump`: `env -i PATH=/usr/bin:/bin python3 -I -c 'import os; print(sorted(os.environ))'` and the
   same with `LC_ALL=C` or `-X utf8`. Under `env -i` the inherited environment is gone; only the explicit
   assignments remain, and if none of them names a secret-looking variable, it is not an env dump. `env` without
   `-i`, `printenv`, `/proc/*/environ`, `set`, `declare -p`, `export -p` stay blocks.
3. **FP** `read-secret-dir`: a heredoc that writes a Python test file (`python3 - <<'EOF' ... open(p,'w').write(s)`)
   whose body contains the string `'/var/tmp/.config/k'` as test data. Distinguish: a path that only appears inside
   a string literal of code being written to a file is not a read; a heredoc that is executed and itself opens that
   path is a read (keep blocking: `python3 - <<'EOF'\nopen('/var/tmp/.config/x').read()\nEOF`).
4. **GAP** (must become a block, new rule `kill-foreign`): `pkill -f <pattern>`, `pkill <name>`, `killall ...`, and
   `kill <pid>` / `kill -9 <pid>` where the pid did not come from a process this agent started in the same
   transcript (a literal pid the agent never saw as its own child's pid, `$(pgrep ...)`, `pgrep ... | xargs kill`).
   `kill %1`, `kill $!`, and `kill <pid>` where the pid appeared earlier in the agent's own `tools/job run` output or
   a background command it started are allowed. `buck2 kill` is unaffected (it is per-root).
5. **Feature** (from T042): `export TMPDIR=...` earlier in the same call, and `env TMPDIR=... tools/job ...`, are used
   when checking the default job dir.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T045/real gate/tests/trajectory_real.sh    # every verdict unchanged
selftest/gate.sh
```
The staged real transcripts under `/var/tmp/cache/T045/real` include the 11 calibration ones plus `T042-gate.jsonl`,
`T043-gate.jsonl` and `T033-gate.jsonl`: after your change T042 must have 0 blocks, T043 must have a
`kill-foreign` block for its `pkill -f` line, and T033 0 blocks. Report the before/after block lists for those three.
