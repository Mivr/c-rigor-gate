# T123: one mutants entry point for lanes that builds exactly the grade's mutant actions (shared cache)

Repo: `Mivr/c-rigor-gate`. Branch `task/T123` from main (T121 merged: mutant target names derive from the module label,
so the grade's `mutant_run` action keys are stable across grades). Read `gate/rigor_lib/grade_mutants.py` (how the
grade generates `gate-mutants/BUCK` and its targets), `rules/mutate.bzl`, `docs/mutate.md`, `AGENTS.md`, and the
"Scratch clone ... a hand-written `c_mutants` target in the clone only" instruction business-apps lane specs give today
(example: business-apps `plan/tasks/L312-synchttp-l3-survivors.md`).

## Why (measured, business-apps 2026-11-09)
Mutation testing is 49% of all agent wall time. Every implementer/test-author lane measures its module's mutants in a
private scratch clone with a HAND-WRITTEN `c_mutants` target, whose action keys differ from the grade's; the
whole-repo grade then measures the same mutants again from scratch. The work is done twice.

## Do
1. A command, e.g. `gate/tools/mutants //path/to/module [--level L3]`, run from a product checkout (a lane's worktree,
   no scratch clone needed), that:
   - generates the SAME `gate-mutants` target for that module that the grade generates (same name, same attrs, same
     tests selection and order, same rules), in a location that does not dirty the product tree (or that the grade
     ignores), and builds it with the product's `gate/tools/buck2` on RE;
   - prints the mutant table the lane needs (killed / survived / unviable / unrun, ids, file:line, mutation) and the
     verdict the grade would give at the module's level, using the same verdict code as the grade (`rigor mutants`).
2. Prove the cache sharing: run the command on a fixture module, then grade the fixture: the grade executes ZERO
   `mutant_run` actions for that module (count from the event log), and the per-mutant verdicts are identical.
3. Docs (`docs/mutate.md`): the lane workflow (replace "scratch clone + hand-written c_mutants" with this command) and
   what is shared. Selftest in `selftest/` that proves (2).

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`, `selftest/product_checks.sh`, `selftest/grade.sh` and the new selftest.

## Allowed paths
`gate/**`, `tools/**`, `rules/**`, `selftest/**`, `docs/**`. NOT `products/**`, NOT `mutate/tool.py` (T122 is editing
it; if you truly need a change there, describe it in the report instead).

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T123`. `TMPDIR=/var/tmp/cache/T123/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. Never end your turn while a job you started is running. Commit on `task/T123`; your last
message is the report (design, the cache-sharing proof, the lane workflow).
