# T066: two small fixes: the affected-path map for products/annas-c, and an env-dump false positive

Repo: `Mivr/c-rigor-gate`. Branch `task/T066`. Read `AGENTS.md`, `tools/affected.toml`, `docs/trajectory.md`
(the env-dump rules, by line range).

1. **`tools/affected.toml`:** `products/annas-c/**` maps to `grade` and `canaries`, but no selftest, canary or gate
   test reads that directory (the orchestrator checked with `grep -rln products/annas-c selftest canaries
   gate/tests`). Map it to `gate` only, with a comment. Then add a unit test, or extend the existing affected-map
   test, that **fails** if any selftest or canary file mentions a product directory whose rule does not select it.
   That keeps the narrowing honest.
2. **Trajectory false positive (orchestrator, T062 audit):** an inline Python heredoc that *writes documentation
   text* containing `%ENV`, `ENVIRON` or `printenv` inside a string literal is reported as `cmd-env-dump`.
   Example: `python3 - <<'EOF'` with a line like `new = '''... Perl's %ENV ...'''` that is then written to
   `docs/x.md`. A string literal that is only **data** (assigned, or written to a file) is not program text of perl,
   ruby or awk. Fix it narrowly: the env-dump patterns for perl, ruby and awk apply only to code that is run by
   that interpreter, not to Python string literals. Add a green fixture for the example and keep every red env-dump
   fixture red. `trajectory_real.sh` must keep every verdict.

## Allowed paths
`tools/affected.toml`, `gate/tests/test_affected*.py` (or the existing test of `tools/affected.py`),
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`docs/trajectory.md`.
**In flight in parallel:** T039 (`grade_*`, `witness*`, `selftest/grade.sh`) and T064 (`rules/mutate.bzl`,
`mutate/**`, `mutants_*`). Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_affected*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_trajectory*.py'
TRAJECTORY_REAL_DIR=/var/tmp/cache/T066/real gate/tests/trajectory_real.sh
selftest/gate.sh
```
