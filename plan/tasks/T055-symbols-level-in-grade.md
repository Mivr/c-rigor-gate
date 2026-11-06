# T055: `rigor grade` hands the symbols gate the module level (B32 follow-up)

Repo: `Mivr/c-rigor-gate`. Branch `task/T055`. Read `AGENTS.md` first (including "Working efficiently").
Source: B32's open part (orchestrator, 2026-11-06). T033 added the per-module `exports` check
(`unexpected-export`, `exports-missing`, `mutable-global-export`), but `rigor grade` gives `facts_symbols` a policy
copy **without `level`** (`grade_policy.symbol_policy_text`/`symbol_policy_path`). So in a graded run a module at
L3 with no `exports` key is treated as a legacy table and **not checked at all**. Only `rigor facts` finds it.
`facts_policy` has accepted `level` since T033, so the reason for stripping it is gone.

**In flight in parallel:** batch5 is being validated: T038 (`grade_build.py`, `grade_mutants.py`,
`mutants_gate.py`), T051 (`mutants_*`, `mutate/tool.py`, `rules/mutate.bzl`, `selftest/mutate.sh`),
T053 (`selftest/grade.sh`), T054 (`grade_steps.py`, `suppressions.py`). T052 is editing `trajectory_*`.
Touch none of them. Do not edit `plan/backlog.md` or `plan/backlog.d/`; put backlog notes in your report.

## Allowed paths
- `gate/rigor_lib/grade_policy.py`, `gate/rigor_lib/grade_checks.py`, `gate/rigor_lib/facts_symbols.py`,
  `gate/rigor_lib/facts_policy.py` (only if the reader needs a change);
- `gate/tests/test_grade_policy*.py`, `gate/tests/test_facts_exports*.py`, `gate/tests/test_grade_checks*.py`
  (new or existing);
- a new canary `canaries/exports-missing-l3/` (same file set as the other canaries);
- `docs/product-checks.md`, `docs/grade.md`, `docs/canaries.md`.

## Requirements
1. In a graded run, the symbols gate sees each module's real `level`. The semantic gate and every other
   consumer keep behaving exactly as today (if one of them must not see `level`, keep a stripped copy for it
   only, and say which and why).
2. Semantics, as `docs/product-checks.md` already states them, now hold in `rigor grade` too:
   L1 exempt; L2 missing list = `exports-missing` info; L3 and above missing list = `exports-missing` error,
   so the symbols gate fails. A table with neither `level` nor `exports` stays the legacy, unchecked case.
3. Fail closed: a policy whose `level` is malformed is an internal error, never "unchecked".
4. Remove a helper that becomes dead (`symbol_policy_text`/`symbol_policy_path` if nothing else uses them);
   do not leave a no-op shim.
5. Red tests first: a unit test that fails on today's `main` (graded L3 module, no `exports`, symbols gate
   passes) and passes after your change; L1/L2/legacy cases pinned.
6. Canary `exports-missing-l3`: a product edit that adds a new L3 module without `exports`; expected:
   `symbols` FAIL with `exports-missing`, the other gates as the canary format requires.
7. Check annas-c: clone `/var/tmp/src/annas-c` into your cache dir (read-only source) and run
   `rigor facts` against it. Report every module that would newly fail `exports-missing` under grade. Do not
   edit annas-c.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_*polic*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_facts_exports*.py'
selftest/gate.sh
TMPDIR=/var/tmp/cache/T055/tmp selftest/canaries.sh --only exports-missing-l3 --only extra-hook
```
(Use `tools/job` for anything over 2 minutes.) Report the red test failing on `main`, the acceptance tails,
the annas-c result, and every deviation.
