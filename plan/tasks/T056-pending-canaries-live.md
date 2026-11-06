# T056: make the four PENDING canaries live

Repo: `Mivr/c-rigor-gate`. Branch `task/T056`. Read `AGENTS.md` first (including "Working efficiently").
Source: batch4 validation (orchestrator, 2026-11-06). `selftest/canaries.sh` reports 47 canaries with 43 live and
4 **pending**, i.e. the assembled gate does **not** catch these cheats today:

```
PENDING generator-attribute: failing gates/rules differ; exit 0, expected 1; overall PASS
PENDING structure-length: failing gates/rules differ; exit 0, expected 1; overall PASS
PENDING structure-recursion: failing gates/rules differ; exit 0, expected 1; overall PASS
PENDING ungraded-path: failing gates/rules differ; NOT_RUN gates differ: got ['mutants']
```

B1/B2 say the `structure` gate was wired into `rigor grade` by T032, and B19 says T017 fixed the
trailing-attribute generator drop. Either the gate is wrong or the canary does not really exercise it.

**In flight in parallel:** batch5 is being validated: T038 (`grade_build.py`, `grade_mutants.py`,
`mutants_gate.py`), T051 (`mutants_*`, `mutate/tool.py`, `rules/mutate.bzl`, `selftest/mutate.sh`),
T053 (`selftest/grade.sh`), T054 (`grade_steps.py`, `suppressions.py`). T052 is editing `trajectory_*`;
T055 is editing `grade_policy.py`, `grade_checks.py`, `facts_symbols.py`. Touch none of them; if the root cause
is in one of them, stop and report the diagnosis instead of editing. Do not edit `plan/backlog.md` or
`plan/backlog.d/`.

## Allowed paths
- `canaries/generator-attribute/**`, `canaries/structure-length/**`, `canaries/structure-recursion/**`,
  `canaries/ungraded-path/**`;
- `gate/rigor_lib/grade_structure.py`, `structure.py`, `structure_*.py`, `grade_tree.py`, `buckfiles.py`;
- `rules/structure.bzl`, `mutate/gen.py`;
- matching `gate/tests/test_*.py` files (new or existing);
- `docs/canaries.md`, `docs/structure.md`, `docs/grade.md`.

## Requirements
1. **Diagnose each of the four first**, and record for each: what the canary's edit produces, what each gate
   reports for it (the per-gate status and findings from its graded run), and why that differs from
   `expect.json`. Classify each one as **gate bug** (the cheat really passes) or **canary bug** (the fixture
   does not contain the cheat it names, or `expect.json` is out of date after T032/T046/T050).
2. Gate bug: fix the gate, with a unit test that fails before the fix. Canary bug: fix the fixture so it really
   contains the named cheat, and keep its `expect.json` exactly as strict (same gate and rule). Never weaken an
   expectation: no removing a rule, no adding `NOT_RUN` gates, and no marking a canary pending to make it pass.
   `ungraded-path` is the one exception: if `mutants` legitimately cannot run on an ungraded path, say why, and
   the `NOT_RUN` list may then include it.
3. At the end, all four are **live**, and `selftest/canaries.sh` reports 0 pending and 0 live misses.

## Acceptance
```sh
selftest/gate.sh
TMPDIR=/var/tmp/cache/T056/tmp selftest/canaries.sh --only generator-attribute --only structure-length \
  --only structure-recursion --only ungraded-path
TMPDIR=/var/tmp/cache/T056/tmp selftest/canaries.sh      # full pack once at the end, via tools/job
```
Commit work in progress before running canaries (the runner refuses a dirty checkout). Report the diagnosis
table, the fixes, the acceptance tails, and every deviation.
