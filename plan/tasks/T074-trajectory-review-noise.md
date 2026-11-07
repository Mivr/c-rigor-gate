# T074: `rigor trajectory` review noise on real transcripts: T011 (39) and T024 (49) reviews (B22 open part)

Repo: `Mivr/c-rigor-gate`. Branch `task/T074`. Read `AGENTS.md`, `docs/trajectory.md`, `plan/backlog.d/B22.md`,
`gate/tests/trajectory_real.sh` (`REVIEW_CAP`) and `gate/rigor_lib/trajectory*.py`.
This is defensive work on our own audit tool. Every `review` finding is read by a human, so noise hides the real ones.
The goal is fewer false reviews on honest transcripts, with every fail-closed case still flagged. Keep every new test
fixture a short, inert one-line command.

## Requirement
1. Run `rigor trajectory` on the staged real transcripts (`/var/tmp/cache/T074/real`, read-only) and classify every
   `path-unresolved` and `cmd-unresolved` review of T011 and T024 by cause: which construct the auditor could not
   resolve (a variable set in an earlier call, a loop variable, a `$(...)` of a known command, a glob, a script
   argument, and so on). Put the table, with counts, in your report.
2. For the top causes, until T011 + T024 together drop by **at least half** (88 to 44 or fewer), model the construct
   precisely where it is safe. For example, values assigned earlier in the same transcript, `for x in a b c` lists of
   literals, or globs under a known directory, each resolved only when every possible value is known. Anything that
   cannot be resolved stays `review`. A construct that could hide a forbidden path must never become allowed.
3. Each modelled construct gets a green test (an honest sequence, fewer findings) and a red twin (the same construct
   reaching a forbidden path or protected file still blocks), in `gate/tests/test_trajectory*.py`.
4. Lower `REVIEW_CAP` in `gate/tests/trajectory_real.sh` to the new counts. No transcript may gain a block, and no
   transcript may lose a block it has today unless your report rules it a false positive with the line and reason.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/trajectory_real.sh` (caps and comments only),
`docs/trajectory.md`, `plan/backlog.d/B22.md`.
**In flight in parallel:** T067 and T070 (mutate and grade_mutants), T073 (the grade pipeline). Do not touch their files.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
selftest/gate.sh
TRAJECTORY_REAL_DIR=/var/tmp/cache/T074/real gate/tests/trajectory_real.sh
```
Report the cause table, the before/after review and block counts per transcript, the new tests and every deviation.
