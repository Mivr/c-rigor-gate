# T044: affected-selftest map and per-step timing (speed-up R006 #5, #10, #11)

Repo: `Mivr/c-rigor-gate`. Branch `task/T044`. Read `AGENTS.md` first.
The orchestrator validates each branch by re-running selftests. Today it picks them by hand; trajectory-only
changes need only `gate.sh` + `trajectory_real.sh` (2-4 min) while a full run is 14+ min. Five selftests print no timing.

**In flight in parallel:** T030 (`grade_build.py`, `toolchains/**`), T032 (`grade_steps.py`, `grade_pipeline.py`,
`grade_checks.py`, `grade_tree.py`, `grade_policy.py`, `gate/order.txt`, `selftest/grade.sh`), T033 (`facts_*`),
T034 (`rules/mutate.bzl`, `mutate/**`), T042 (`tools/job`, `trajectory_*`, `AGENTS.md`, `docs/lanes.md`),
T043 (`selftest/gate.sh`, `gate/tests/run_parallel.py`). Touch none of them. **Do not edit `plan/backlog.md`.**

## Allowed paths
new `tools/affected.py`, new `tools/affected.toml`, new `gate/tests/test_affected.py`, new `tools/validate.sh`,
`selftest/product_checks.sh`, `selftest/ctest.sh`, `selftest/toolchain.sh`, `selftest/third_party.sh`,
`selftest/fuzz.sh`, `selftest/structure.sh`, `selftest/mutate.sh` (timing lines only: no other change),
new `docs/validation.md`.

## Requirements
1. `tools/affected.toml`: ordered rules `{glob = "...", selftests = [...]}` mapping repo paths to the selftests
   (`gate`, `grade`, `mutate`, `structure`, `product_checks`, `toolchain`, `ctest`, `fuzz`, `third_party`,
   `canaries`, `trajectory_real`) that must run when a matching path changes. Derive it from reading what each
   selftest exercises (imports, rules, products it builds). **Fail closed:** any changed path no rule matches selects
   everything; `rules/**`, `toolchains/**`, `prelude/**`, `.buckconfig`, `tools/buck2*`, `gate/rigor_lib/grade*`,
   `gate/rigor` select everything. `gate` is always selected.
2. `tools/affected.py BASE HEAD` (stdlib, `python3 -I`) prints the selected selftests one per line (stable order) and,
   with `--why`, the rule that selected each. `--check` verifies every tracked file matches at least one rule other
   than a catch-all, and exits 1 listing the unmatched ones (so the map cannot rot silently).
3. `tools/validate.sh [--dry-run] BRANCH`: in the current worktree (the orchestrator's val worktree, already merged
   with main), compute the set against `main`, run the selected selftests (independent ones in parallel, each to its
   own log under `$TMPDIR/validate/`, `canaries.sh` with `--jobs 8`), and print one summary table: selftest, exit,
   seconds, last line. `--dry-run` prints the plan only. It never merges, pushes, or reads agent output.
4. Each listed selftest prints a final `elapsed <S>s` line (the existing last line must stay the last
   human-readable result line the orchestrator greps; put timing before it or on stderr — document which).

## Acceptance
```sh
python3 -I -B -m unittest gate.tests.test_affected
python3 -I tools/affected.py --check
python3 -I tools/affected.py <a trajectory-only commit>^ <same>     # gate, trajectory_real
python3 -I tools/affected.py <a toolchains commit>^ <same>          # everything
python3 -I tools/affected.py main main                              # gate only
tools/validate.sh --dry-run HEAD
selftest/gate.sh
selftest/product_checks.sh; selftest/ctest.sh   # still pass, now with timing
```
Pick the example commits from `git log` and name them in your report.
