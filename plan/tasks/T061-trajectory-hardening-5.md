# T061: trajectory hardening 5: writers, directory targets, symlinks (R008 #16-#18)

Repo: `Mivr/c-rigor-gate`. Branch `task/T061`. Read `AGENTS.md` ("Working efficiently") and `docs/trajectory.md`.
R008 report, generator and fixtures: `/var/tmp/cache/T061/r008/` (`harness.py` already points at your worktree).
T049 fixed families 1-3 and 4a, T052 fixed 4b/4c and 5-8, T057 fixed 9-14, and T060 fixed #15. This task takes
#16, #17, #18 of the R008 report's ranked table, plus the side finding in #18 (a false positive). T062 takes the rest afterwards.
Real transcripts for `trajectory_real.sh` are in `/var/tmp/cache/T061/real/` (the same 14 that T052 used).

**In flight in parallel:** T059 (`products/annas-c/**`) and T039 (`grade_*`,
`witness*`). Touch none of their files.
Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh` (expected values only, each change justified), `docs/trajectory.md`.

## Requirements (R008 numbering; each family gets its R008 red cases plus green twins)
Implement each family's "fix" column of `report.md` as written, one commit per family, fail closed as in T049.
- **#16 writers the audit does not model:** write-mode literals in inline code; `-o`/`--output` for compilers and
  `sort`; `tar -x -C/-f`, `unzip -d`, `--target-directory=`, `gawk -i inplace`; and `patch`, `git apply`,
  `git clean` and `xargs <writer>` as `write-unresolved`. Green twins: `cc -o /var/tmp/cache/T061/x`,
  `git apply` inside the worktree of a patch the agent wrote (the diff is reviewed), and `sort -o` into scratch.
- **#17 copying into a directory target, and `find -exec ... {}`**, as the report says.
- **#18 symlinks created in the transcript:** a virtual link table, resolved independently of the disk. Also fix
  the side finding: `ln -s ../policy src/p` must resolve `../policy` against the link's directory.

## Orchestrator rulings (from T060's notes)
1. Real agents run `tools/buck2 kill` / `gate/tools/buck2 kill` in their own worktree, scratch trees and grade dirs
   (T008, T013, T022, including T022's `cd $d` over a glob of its own grade dirs). These stay green.
2. Write fixtures as short, inert one-line command strings, as the existing `test_trajectory_cases.py` entries do.
   Do not write long prose descriptions of attacks; the R008 report is the reference. You only teach the checker
   to classify them.
3. T060 (merged) covered #15. Its notes are in `/var/tmp/cache/<this task>/t060-notes.md`, with helper scripts
   in `tools/` there (`realdiff.py`, `regen.py`, `try.py`, `grepcmd.py`): reuse them.
4. T043 line 128 (`ls test_*.py | ... | xargs rm` inside its own `gate/tests`) is a write **inside the
   worktree's allowed paths**. `xargs <writer>` with unknown targets is `write-unresolved` (review), not a block,
   when the cwd is the agent's own worktree. Update T043's expected reviews if `trajectory_real.sh` lists it.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T061/real gate/tests/trajectory_real.sh
python3 -I /var/tmp/cache/T061/r008/harness.py     # every case of  #1-#18 must FAIL (only the controls pass)
selftest/gate.sh
```
Report any new findings on the 14 real transcripts, with your ruling (true or false positive) for each. Keep
false positives on real agent behaviour at zero. Report every deviation.
