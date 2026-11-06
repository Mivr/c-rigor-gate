# T049: trajectory hardening 1 — commands the audit cannot see (R008 #1, #2, #3, #4a)

Repo: `Mivr/c-rigor-gate`. Branch `task/T049`. Read `AGENTS.md` ("Working efficiently") and `docs/trajectory.md`.
R008 (authorized red team of our own audit; report and generator copied to `/var/tmp/cache/T049/r008/`:
`report.md`, `cases.py`, `harness.py`, `fixtures/`) found 20 families of commands that break lane rules and still
PASS. This task fixes the four that hide a whole command from the audit. Later tasks take the rest; do not start them.
**In flight in parallel:** T038 (`grade_build.py`, `grade_mutants.py`, `mutants_gate.py`); batch3 validation of T032,
T037, T046, T048. Touch none of their files. Do not edit `plan/backlog.md`.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh` (expected values only, each change justified in the report), `docs/trajectory.md`.

## Requirements (R008 numbering; each family gets red fixtures from R008's cases plus a green twin)
1. **#1 unquoted heredoc bodies**: when the delimiter is unquoted, the body's `$(...)` and backticks are audited as
   commands and its `$NAME` / `${NAME}` as expansions (secret-env rules apply). A quoted delimiter stays text.
2. **#2 interpreter code flags**: a per-interpreter table of code flags (sh/bash/dash/zsh and python: `-c`, also
   inside a cluster like `-ec`; node/perl/ruby: `-e`/`-E`), skipping other options and `--`; the code is the first
   plain word after the flag. Includes `find ... -exec bash -e -c '...'`.
3. **#3 scripts the audit never saw**: track the content of files the transcript writes. Known content (Write tool,
   literal `echo`/`printf > f`, quoted heredoc `> f`) is audited when the file is run (`bash f`, `sh f`, `bash < f`,
   `cat f | sh`, `python3 f`, `./f`). A file whose content is unknown (written by `base64 -d`, `cp`, `tee` in a pipe,
   a redirect of command output, or not written in the transcript at all but under the agent's own scratch) and then
   executed is `cmd-obfuscated-exec` (block). Repo scripts that exist in the worktree (`selftest/*.sh`, `tools/*`,
   `gate/rigor`) keep today's treatment. `/dev/stdin`, `/dev/fd/0`, `/proc/self/fd/0` are treated like `-`.
4. **#4a forged persisted-output lines**: a "Full output saved to: <path>" line lifts a later Read only when the path
   is `…/.claude/projects/*/tool-results/<this result's own tool_use_id>.txt` (or the harness's exact naming, check
   the real transcripts) and the line is in the harness's own result framing, never text a command printed; and it
   lifts only `read-claude-state`, never `read-secret-dir`.
Fail closed: an ambiguity becomes review or block, never silent PASS.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T049/real gate/tests/trajectory_real.sh   # unchanged verdicts, or each change justified
python3 -I /var/tmp/cache/T049/r008/harness.py     # report which of families 1-3 and 4a now FAIL (all their cases must)
selftest/gate.sh
```
Report false-positive risk: run the audit on all 14 transcripts in `/var/tmp/cache/T049/real` and list every new
finding with a ruling (true / false positive).
