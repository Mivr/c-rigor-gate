# T031: trajectory: the agent's own `canaries.sh --keep` scratch is its own (backlog B26)

Repo: `Mivr/c-rigor-gate`. Branch `task/T031`. Read `AGENTS.md`, `docs/trajectory.md`, `gate/rigor_lib/trajectory*.py`,
and how T026 proved an own `rigor-grade.*` dir (`Audit.own_dir`, `PathPolicy.made`). Touch only the paths below.

## Why
The audit of T028 (real transcript staged key-free at `/var/tmp/cache/T031/real/T028-gate.jsonl`) blocks once:
`write-outside` on `rm -rf /var/tmp/rigor-canaries.kg2rvfzu`, the scratch dir that the agent's own
`selftest/canaries.sh --keep` run printed earlier in the same transcript.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh`, `docs/trajectory.md`, `plan/backlog.md` (add B26 and mark it).

## Requirements
1. Generalise T026's proof to the canary runner: a `scratch /var/tmp/rigor-canaries.XXXXXX` line (match the runner's real
   output) in the successful result of a Bash call that ran `selftest/canaries.sh` with `--keep`, under `$TMPDIR`, makes
   that one dir (and below it, symlinks resolved) writable. Same conditions as T026: never typed by the agent before it
   was shown; the run must precede the write.
2. Red twins that still block: a canaries dir never printed, one printed by `ls`/`echo`, one shown only after the `rm`,
   a run without `--keep`, another task's dir, the parent `/var/tmp`.
3. Add `T028-gate.jsonl` to `trajectory_real.sh` (0 blocks expected), skippable when not staged; report before/after.

## Acceptance
```sh
TRAJECTORY_REAL_DIR=/var/tmp/cache/T031/real gate/tests/trajectory_real.sh
selftest/gate.sh
```
