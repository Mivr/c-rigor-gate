# T058: content-bound mutant ids (B18) and per-level baseline findings (T050 follow-up)

Repo: `Mivr/c-rigor-gate`. Branch `task/T058`. Read `AGENTS.md` ("Working efficiently"), `docs/mutate.md`,
`docs/grade.md` (approvals), and `plan/backlog.d/B18.md`.

**In flight in parallel:** batch6 is being validated: T052 (`trajectory*`) and T055 (`grade_policy.py`,
`grade_checks.py`, `facts_*`). T039 (`grade_*`, `witness*`) starts after it. T057 (`trajectory*`).
Touch none of their files. Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`mutate/gen.py`, `gate/rigor_lib/mutants_gate.py`, `gate/rigor_lib/mutants_verdict.py`,
`gate/rigor_lib/approvals.py`, `gate/rigor_lib/approve.py`, `gate/tests/test_mutants*.py`,
`gate/tests/test_approv*.py`, `gate/tests/test_mutate_gen*.py`, `gate/tests/test_mutants_gen*.py`,
`selftest/mutate.sh`, `docs/mutate.md`, `docs/grade.md` (the approvals section only), and a new canary
`canaries/approval-drift/`.

## Part 1: the baseline findings see the level (T050 deviation 1)
`mutants_gate.module_findings` calls `mutants_verdict.baseline_findings(report)` without the module level, so the
`no-mutable-token` severity by level from T050 never reaches `rigor grade`. Pass the level. Then flip the
expectation in `gate/tests/test_mutants.py` (`test_a_function_with_the_reason_no_mutable_token_...`) so that L3
gives an error and L2 gives info, as `docs/mutate.md` states. Write a red test first: it fails on `main` and
passes after the change.

## Part 2: approval ids cannot drift (B18, R001 R6)
Today `gen.assign_ids` hashes the file, the group (function, operator, original, replacement) and the **ordinal**
among equal mutations in the function. After a refactor, an `equivalent-mutant` approval can silently cover a
different mutation that now has the same ordinal.
1. Bind the id to the **content**: the mutated token's text, plus a hash of the enclosing function's body
   (normalised for whitespace and comments only). The ordinal remains as a tie-break only among byte-identical
   candidates within that same body.
2. Any change to the function body changes every id in that function, so an old approval no longer matches
   anything. It must then be reported as a stale or unused approval, exactly as an approval for a missing id is
   today. Fail closed: no fuzzy matching.
3. Ids stay unique per module, stable across runs and machines, and independent of the absolute path of the
   checkout. Pin all three with tests.
4. Mutant verdict caches keyed on ids are expected to go cold once. Say so in `docs/mutate.md`.
5. Canary `approval-drift`: the base has an approved equivalent mutant in a function. The edit changes that
   function's body so the same ordinal now names a behaviour-changing mutant with no test. Expected: `mutants`
   FAIL (`survived-mutant` and the stale-approval rule), and the old approval does not apply.
   If the canary needs a signed approval, use the throwaway selftest signing setup that `selftest/grade.sh` or
   `gate/tests/test_approvals.py` already uses. If the canary format cannot carry a signed approval, make it a
   `selftest/mutate.sh` step instead and say why.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutants*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutate_gen*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_approv*.py'
selftest/mutate.sh
selftest/gate.sh
TMPDIR=/var/tmp/cache/T058/tmp selftest/canaries.sh --only approval-drift   # then the full pack once, via tools/job
```
Report the red test for part 1, the old and new id formula, the full-pack result, and every deviation.
