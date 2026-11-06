# T027: trajectory: git against a local remote is not network (backlog B23)

Repo: `Mivr/c-rigor-gate`. Branch `task/T027`. Read `AGENTS.md`, `docs/trajectory.md`, `gate/rigor_lib/trajectory*.py`,
`gate/tests/trajectory_real.sh`, and how T026 handled B22. **T023 and T025 run in parallel**: touch only the paths below.

## Why
The audit of T013 (real transcript, staged key-free at `/var/tmp/cache/T027/real/T013-gate.jsonl`) has 3 false blocks:
`cmd-git-network` on `git fetch -q origin` and `git clone -q --no-local annas-c pre`, and `cmd-git-main` on
`git checkout -q -f origin/main`, all inside the agent's own cache clone (`/var/tmp/cache/T013/annas-c`), whose
`origin` is the local path `/var/tmp/src/annas-c` (the clone command is earlier in the same transcript).

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh`, `docs/trajectory.md`, `plan/backlog.md` (add B23 and mark it).

## Requirements
1. A git command whose remote or source the transcript itself proves is a **local path** (a `git clone <local path>`
   the agent ran earlier, or a path argument), run in a directory under the agent's allowed write places, is not
   `cmd-git-network`. `cmd-git-main` applies to the product worktree's `main`, not to a scratch clone in the cache.
2. Red twins that must still block: `git fetch` in a clone whose origin is a URL (`https://`, `git@`, `ssh://`,
   `file://` of a path outside the allowed places), `git push` anywhere, `git remote add`/`set-url` then fetch,
   `git checkout main` / `reset --hard origin/main` in the task worktree, a clone of another task's worktree, and an
   `origin` whose clone command never appears in the transcript.
3. Add `T013-gate.jsonl` to `trajectory_real.sh` (0 blocks expected), and report its block/review counts before and
   after. The nine transcripts T026 used are not staged here; skipping missing ones is fine.

## Acceptance
```sh
TRAJECTORY_REAL_DIR=/var/tmp/cache/T027/real gate/tests/trajectory_real.sh
selftest/gate.sh
```
