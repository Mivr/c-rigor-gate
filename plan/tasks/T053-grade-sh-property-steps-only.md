# T053: `selftest/grade.sh` keeps only its property steps (speed-up R006 #1, step 2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T053`. Read `AGENTS.md` ("Working efficiently": tools/job for long runs).
`grade.sh` takes ~20-33 min under load (batch3: 1969 s). R006 found its red cases duplicate canaries, but it runs
them cold every time (fresh nonce). T046 added the 7 cases canaries lacked. Now grade.sh's red cases (section
"# 2. red cases", every `run_case` line) move out: each must be covered by a canary with the same edit and an
**exact** expectation that includes every rule grade.sh asserts (and the extra greps next to some run_case lines).
**In flight in parallel:** T038 (`grade_build.py`, `grade_mutants.py`, `mutants_gate.py`), T051 (`mutate/**`,
`rules/mutate.bzl`, `mutants_verdict.py`, new steps in `selftest/mutate.sh`), T052 (`trajectory*`). Touch none of
them. Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`selftest/grade.sh`, new `canaries/<id>/` dirs only where no canary covers a case yet, `canaries/runner.py` (only if a
grade.sh extra check such as "the product's tools/buck2 was not executed" or the build.json grep needs a hook),
`gate/tests/test_canaries_runner.py`, `docs/grade.md`, `docs/canaries.md`.

## Requirements
1. For every `run_case` in grade.sh: name the canary that covers it (same edit, possibly with path adaptation;
   expectation contains the asserted rules). Where the edit differs or the canary is missing, add or fix the canary
   (new dirs only; for an existing canary whose edit differs, say so and add a new one rather than change it).
   The extra checks next to run_case lines (`unused-variable` in build.json for buckconfig-hidden; the product's
   `tools/buck2` never executed for product-buck2) must be enforced by the canary pack too.
2. Delete the red-case section from grade.sh. Keep: cold, warm (+ signature, core_sha256), hostile environment,
   uncached, internal error, and every action-count / daemon-leak / verdict-field assertion. Steps that do not
   depend on each other's output after the cold run (warm, hostile, uncached, internal error) run in parallel,
   each in its own work subdir with its own Buck2 daemon; total wall must not exceed the slowest step plus ~10%.
3. `docs/grade.md`: a table mapping every removed case to its canary; `selftest/grade.sh` prints the same mapping
   when it starts, so nobody thinks the cases vanished.
4. `tools/affected.toml` is owned by nobody in flight: if any path you add is unmatched, `affected.py --check` fails;
   fix by adding a rule only if needed (allowed for that purpose).

## Acceptance
```sh
selftest/grade.sh                 # report wall time; before this task it was 1250-1970 s on this host
selftest/canaries.sh              # full pack, 0 live misses; report wall time
python3 -I tools/affected.py --check
selftest/gate.sh
```
