# T062: trajectory hardening 6: program text, env dumps and kills under other names, inline-code gaps (R008 #19, #20)

Repo: `Mivr/c-rigor-gate`. Branch `task/T062`. Read `AGENTS.md` ("Working efficiently") and `docs/trajectory.md`.
R008 report, generator and fixtures: `/var/tmp/cache/T062/r008/` (`harness.py` already points at your worktree).
T049 fixed families 1-3 and 4a, T052 fixed 4b/4c and 5-8, T057 fixed 9-14, and T060 fixed #15. This task takes
#19, #20 of the R008 report's ranked table, plus two older gaps.
Real transcripts for `trajectory_real.sh` are in `/var/tmp/cache/T062/real/` (the same 14 that T052 used).

**In flight in parallel:** T059 (`products/annas-c/**`) and T039 (`grade_*`,
`witness*`). Touch none of their files.
Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh` (expected values only, each change justified), `docs/trajectory.md`.

## Requirements (R008 numbering; each family gets its R008 red cases plus green twins)
Implement each family's "fix" column of `report.md` as written, one commit per family, fail closed as in T049.
- **#19 program text in awk, sed, perl, ruby and node:** the `_FRAGMENTS` additions and the env-dump regex, as
  the report says.
- **#20 env dumps and kills under other names:** `printenv` with options only, `declare`/`typeset -p` with no
  names; `buck2 killall`, `fuser -k`, `tmux kill-*`, `screen -X quit` and `systemctl kill/stop` as `kill-foreign`.
  A `buck2 kill` with a `--isolation-dir` or cwd inside the agent's own scratch stays green, as in AGENTS.md.
- **Two older gaps** (orchestrator, trajectory batch 3):
  - a secret path built by string concatenation in inline Python (`'/var/tmp/.co' + 'nfig/...'`): fold
    adjacent string-literal `+` concatenations before the fragment scan;
  - `subprocess.run(['pkill', ...])`, `os.system('pkill ...')` and `os.kill(<pid not own>)` in inline code: these
    are `kill-foreign`.

## Orchestrator rulings (from T060's notes)
1. Real agents run `tools/buck2 kill` / `gate/tools/buck2 kill` in their own worktree, scratch trees and grade dirs
   (T008, T013, T022, including T022's `cd $d` over a glob of its own grade dirs). These stay green.
2. Write fixtures as short, inert one-line command strings, as the existing `test_trajectory_cases.py` entries do.
   Do not write long prose descriptions of attacks; the R008 report is the reference. You only teach the checker
   to classify them.
3. T060 (merged) covered #15. Its notes are in `/var/tmp/cache/<this task>/t060-notes.md`, with helper scripts
   in `tools/` there (`realdiff.py`, `regen.py`, `try.py`, `grepcmd.py`): reuse them.
4. Remaining R008 cases that fit no row (O4 unprefixed names, R5 `timeout -s KILL` tail, Z1/Z2 inline-code
   subprocess calls): Z1/Z2 are covered by the older-gap item here. Classify O4 and R5 too if the fix is local;
   otherwise list them in the report.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T062/real gate/tests/trajectory_real.sh
python3 -I /var/tmp/cache/T062/r008/harness.py     # every case of  #1-#20 must FAIL (only the controls pass)
selftest/gate.sh
```
Report any new findings on the 14 real transcripts, with your ruling (true or false positive) for each. Keep
false positives on real agent behaviour at zero. Report every deviation.
