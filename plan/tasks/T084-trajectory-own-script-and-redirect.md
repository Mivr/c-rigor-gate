# T084: two `rigor trajectory` false blocks from real transcripts (own scratch script; submodule url + `2>&1`)

Repo: `Mivr/c-rigor-gate`. Branch `task/T084`. **Gate task** (implementer + its own tests). Read `AGENTS.md`,
`docs/trajectory.md` (all of it; in particular "Scripts the transcript never wrote", the file-text model, T052 rulings 6
and 7, and T077's "Local submodule URL"), `gate/rigor_lib/trajectory*.py`, and the existing tests and fixtures.

## The two false blocks
Two real transcripts are staged in `/var/tmp/cache/T084/real/` (read-only for you; no secrets in them):
1. `A060.jsonl`, two `cmd-obfuscated-exec` blocks on `python3 -I gen_pkg.py` (run in the agent's own scratch clone
   `/var/tmp/cache/A060/scratch`, allow-write `/var/tmp/cache/A060`). The script is the agent's own 6-line file that writes
   a scratch `gate-mutants/BUCK` and `PACKAGE`. Find out why its text is unknown to the audit (how it was written, which
   cwd the audit resolves, whether the "local clone the agent made" rule applies to untracked files in that clone) and
   fix the model so that a script whose full text the transcript shows (written by a modelled writer, or read back by
   the agent in full) is audited as code instead of blocked. A script whose text is really unknown stays a block.
2. `T083.jsonl` line 67, two `cmd-git-network` blocks on
   `git -c protocol.file.allow=always -c submodule.gate.url=/var/tmp/src/c-rigor-gate submodule update --init 2>&1`
   and `git -c protocol.file.allow=always submodule update --init --reference /var/tmp/src/c-rigor-gate 2>&1`.
   The first is T077's allowed local form plus a stderr redirect: it must pass (a redirect to stdout/stderr or
   `/dev/null` does not change what git does). The second has no url override, so git would use `.gitmodules` (network):
   it must stay a block, with T077's documented reason.
Run the audit on both transcripts with the arguments in "Acceptance" before and after.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**` (short, inert,
synthetic fixtures modelled on the two cases; do not copy the real transcripts into the repo), `docs/trajectory.md`.

## Acceptance
```sh
gate/rigor trajectory --transcript /var/tmp/cache/T084/real/A060.jsonl --task $'id="A060"\nallowed=["json/src/**"]\nprotected=["json/tests/**","json/*.h","json/BUCK"]\nrole="implementer"' --worktree /var/tmp/wt/annas-c/A060 --allow-write /var/tmp/cache/A060
gate/rigor trajectory --transcript /var/tmp/cache/T084/real/T083.jsonl --task $'id="T083"\nallowed=["products/annas-c/policy.toml"]\nprotected=["gate/**","selftest/**"]\nrole="implementer"' --worktree /var/tmp/wt/c-rigor-gate/T083 --allow-write /var/tmp/cache/T083
python3 -I -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
selftest/trajectory_real.sh   # with TRAJECTORY_REAL_DIR=/var/tmp/cache/T066/real (the ground-truth set must still match)
selftest/gate.sh
```
The A060 run must have no block; the T083 run exactly one block (the `--reference` form). The worktrees named above
may no longer exist: the audit must not depend on them for these two cases (say if it does, and how you ran it).
Report the cause of each false block, the fix, the new tests and fixtures, and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T084/tmp`; never write to `/tmp`. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs (except
`/var/tmp/cache/T066/real` read-only for the selftest). Never kill processes you did not start. No sleep-poll loops
(`tools/job`). 2 CPUs and 8 GiB are shared. Fixtures stay short and inert (no evasion catalogues).
