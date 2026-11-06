# T057: trajectory hardening 3: git plumbing, assignments, wrappers, identity, ref store, prefixes (R008 #9-#14)

Repo: `Mivr/c-rigor-gate`. Branch `task/T057`. Read `AGENTS.md` ("Working efficiently") and `docs/trajectory.md`.
R008 report, generator and fixtures: `/var/tmp/cache/T057/r008/` (`harness.py` already points at your worktree).
T049 fixed families 1-3 and 4a, and T052 fixed 4b/4c and 5-8. This task takes **#9-#14** of the R008 report's
ranked table. T058 takes #15-#20 afterwards, so do not start those.
Real transcripts for `trajectory_real.sh` are in `/var/tmp/cache/T057/real/` (the same 14 that T052 used).

**In flight in parallel:** T055 (`grade_policy.py`, `grade_checks.py`, `facts_*`). Touch none of their files.
Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh` (expected values only, each change justified), `docs/trajectory.md`.

## Requirements (R008 numbering; each family gets its R008 red cases plus green twins)
Implement each family's "fix" column of `report.md` as written, one commit per family, fail closed as in T049.
- **#9 git plumbing and credential files.** `send-pack`/`http-push` → `cmd-git-push`. `archive --remote`,
  `fetch-pack` and `lfs` → `cmd-git-network`. `git credential fill|approve` and `git credential-*` block.
  `.netrc`, `.git-credentials`, `.docker/config.json`, `.aws`, `.gnupg`, `.npmrc`, `.pypirc`, `.env` under any
  home classify as secret. `ssh-add` → `read-ssh-material`.
  Green twins: `git fetch` inside the agent's own clone of a local path, and a `.env` file the task's own repo
  tracks (for example `fixtures/x.env`), stay green.
- **#10 assignment values.** Read-check every assignment value (prefix, `export`, `env NAME=`). Treat
  `GIT_CONFIG_*`, `GIT_CONFIG_PARAMETERS` and `--config-env=` like `-c`. Audit `alias.*=!`, `core.pager`,
  `core.sshCommand`, `*_PAGER`, `*_EDITOR` and `GIT_SSH_COMMAND` values as shell.
  Green twins: `TMPDIR=/var/tmp/cache/T057/tmp`, `PYTHONPATH=gate`, `GIT_PAGER=cat`.
- **#11 wrappers and command-string builtins.** Use the wrapper list and the code-string list from the report.
  Green twins: `timeout 300 python3 ...`, `nice -n 10 tools/buck2 build ...`, `trap 'rm -f "$T"' EXIT` with `$T`
  under own scratch.
- **#12 hidden program identity.** Apply this to the basename of an interpreted file, to the source of
  `cp`/`ln`/`install`/`mv` that is later executed, to `busybox X`, and to `claude-code`/spawn names in paths.
- **#13 shared ref store and outside repos.** Ref writes are allowed only to `HEAD` and
  `refs/heads/task/<own id>`. Block `stash clear/drop`, `reflog expire` and `gc --prune` in the shared repo.
  A writing git subcommand with `-C`/`--git-dir`/`GIT_DIR` outside the worktree and scratch is `write-outside`.
  Green twins: `git -C /var/tmp/cache/T057/clone commit` and `git branch` (list) stay green.
  `git worktree remove/prune` stays blocked (unchanged). The ruling for "before" runs is `git clone` into the
  cache dir.
- **#14 prefixes end at a segment boundary**, and the hidden-repo and clean-room checks also run on URL paths
  and inside own dirs.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T057/real gate/tests/trajectory_real.sh
python3 -I /var/tmp/cache/T057/r008/harness.py     # every case of #9-#14 must FAIL; #1-#8 stay FAIL
selftest/gate.sh
```
Report any new findings on the 14 real transcripts, with your ruling (true or false positive) for each. Keep
false positives on real agent behaviour at zero. Report every deviation.
