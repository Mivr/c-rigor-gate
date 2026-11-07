# T077: `rigor trajectory` false blocks: local submodule URLs, and deletes of `*.orig` leftovers (B26 open part)

Repo: `Mivr/c-rigor-gate`. Branch `task/T077`. Read `AGENTS.md`, `docs/trajectory.md` (T027 "local clones", T031
`own-canary-dir`), `plan/backlog.d/B26.md`, `gate/rigor_lib/trajectory_git.py`, `trajectory_writers.py` and
`trajectory_rules.py`. This is defensive work on our own audit tool: fewer false blocks on honest transcripts, with
every fail-closed case still blocked. Keep every new fixture a short, inert one-line command.

## Requirements
1. **Local submodule URL.** The orchestrator tells lanes to run
   `git -c protocol.file.allow=always -c submodule.gate.url=/var/tmp/src/c-rigor-gate submodule update --init gate`
   in a clone of a local source repo inside their scratch dir. Today it blocks as `cmd-git-network` (and reviews
   `git-config-override`). It is local when:
   - every `submodule.<name>.url` the command sets with `-c` is an absolute local path under `/var/tmp/src/`;
   - the command names a submodule set that way;
   - it runs in a worktree or a scratch clone.

   Then it is not network. Treat `protocol.file.allow=always` as harmless only together with such a local URL.
   Red twins:
   - a URL that is `https://`, `ssh://`, `git@...` or `file://` to anywhere else, or a relative path;
   - `submodule update` with no `-c` url (it uses `.gitmodules`, which is GitHub here);
   - `--recursive` (nested submodules use their own `.gitmodules`);
   - `-c` url for a different submodule than the one updated;
   - `submodule update` with `--remote`;
   - `git -c core.sshCommand=...`.
2. **`*.orig` deletes (B26, ruling).** `rm -f <dir>/*.orig`, a glob whose literal suffix cannot match a test or fixture
   file the protected/test rules care about, is not `tamper-test-delete`. A file name ending in `.orig` is a patch
   leftover, never a test. Generalise only as far as "a glob whose fixed extension is outside the set of test-file
   extensions the rule knows"; document that set. Red twins: `*.c`, `*`, `*.or*`, `test_*`, a glob in a directory
   variable that is unknown, and `rm -f x.orig y_test.c` (the second operand still counts).
3. `gate/tests/trajectory_real.sh`: T028 drops its `.orig` block (update its ground truth and comment), and every other
   transcript's blocks are unchanged. Report counts before and after for all staged transcripts.
4. Docs: `docs/trajectory.md`. Mark the B26 open part done in `plan/backlog.d/B26.md`, then run
   `python3 -I tools/backlog_fold.py` and commit `plan/backlog.md` too.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/trajectory_real.sh` (T028 ground truth,
caps and comments), `docs/trajectory.md`, `plan/backlog.d/B26.md`, `plan/backlog.md` (regenerated only).
**In flight in parallel:** T070 (grade_mutants), T073 (grade pipeline), T076 (perf rule). Do not touch their files.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
selftest/gate.sh
TRAJECTORY_REAL_DIR=/var/tmp/cache/T077/real gate/tests/trajectory_real.sh
```
Report the before/after counts, the new tests and every deviation.
