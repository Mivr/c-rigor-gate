# T072: `rigor trajectory` path tracking: unresolvable `cd`, piped heredoc writes, moved clones (B21, B23 open parts)

Repo: `Mivr/c-rigor-gate`. Branch `task/T072`. Read `AGENTS.md`, `docs/trajectory.md`, `plan/backlog.d/B21.md`, `B23.md`
and `gate/rigor_lib/trajectory_shell.py`, `trajectory_paths.py`, `trajectory_writers.py`, `trajectory_git.py`.
This is defensive work on our own audit tool: it makes the auditor **more precise** about where a command runs and
what a file contains, so honest transcripts get fewer false reviews and the audit's verdicts can be trusted.
Keep every test fixture a short, inert one-line command (`cd`, `cat`, `git clone` of a local path); no payloads.

## Requirements
1. **Unresolvable `cd`** (B21): today a `cd` to a target the auditor cannot resolve (an unknown variable, a substitution)
   keeps the previous directory, so later relative paths are judged against the wrong place. After such a `cd`, the cwd
   is **unknown** until a resolvable `cd` (or the scope ends: `( ... )`, a new Bash call). Relative paths under an unknown
   cwd are `path-unresolved` (review), never resolved against the stale directory and never silently allowed.
2. **Piped heredoc writes** (B21): `cat <<EOF | tee f` (and `tee -a`) is remembered as the text of `f`, as
   `cat <<EOF > f` is today (T020), so a later run of `f` is audited as written.
3. **Moved clones** (B23): a clone proven local by T027 stays proven when its directory is moved or copied with `mv` or
   `cp -r` within the declared scratch dirs, and the proof follows a symlink to it that the transcript itself
   created there. Anything else (a move out of scratch, a symlink from elsewhere, an edit of `.git/config` in between)
   loses the proof, as today.
4. Each item gets a green test (fewer findings on an honest command sequence) and a red twin (the fail-closed case
   above), in `gate/tests/test_trajectory*.py`. `gate/tests/trajectory_real.sh` must not gain a block on any real
   transcript.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `docs/trajectory.md`.
**In flight in parallel:** T071 (`grade_*`, `approvals*`, `verdict_inputs.py`), T069 (selftest grade).

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
selftest/gate.sh
TRAJECTORY_REAL_DIR=/var/tmp/cache/T072/real gate/tests/trajectory_real.sh   # real transcripts staged by the orchestrator
```
Report the per-transcript block and review counts before and after, the new tests and every deviation.
