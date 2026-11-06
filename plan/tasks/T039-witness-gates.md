# T039: the witness gates `witness-tests` and `mutants-witness` (P002, B27 witness half)

Repo: `Mivr/c-rigor-gate`. Branch `task/T039`. Read `AGENTS.md` ("Working efficiently"), `docs/grade.md`,
`docs/witness.md` if present, and **`plan/P002-witness-grading.md` in full**. The contract is P002's
"### T039" section, plus the terms, Q1, Q3, Q5 and "The gate list and the verdict after this design". Follow it
exactly. The prerequisites T032, T033, T034, T036, T037 and T038 are all merged.

Changes since P002 was written:
- **T055** made `rigor grade` hand the symbols gate the whole policy, `level` included, and removed
  `grade_policy.symbol_policy_path`. P002's "drop `impl` from the symbols copy" therefore becomes: the policy
  reader (`facts_policy`) must accept `impl` and ignore it for symbols. `facts_policy.py` is allowed for that one
  key. Also delete `grade_policy.symbol_policy_text`, which is now dead, and its uses in
  `gate/tests/test_grade_mutants.py` (T055 deviation 1).
- T053 cut `selftest/grade.sh` to property steps only. Add your steps in that style; do not re-add red cases that a
  canary already covers.
- The witness bundle snapshots the way T037 binds it: `witness_bundle.py`, `verdict_inputs.py`. Reuse them.

**Allowed paths:** exactly P002's T039 list, plus `gate/rigor_lib/facts_policy.py` (the `impl` key only),
`gate/tests/test_facts*.py`, and the backlog fragment `plan/backlog.d/B27.md` (the witness half only) instead of
`plan/backlog.md`.
**In flight in parallel:** T061/T062 (`trajectory*`), T063 (`structure*`, `grade_structure.py`), T059 (being merged:
`products/annas-c/**`; add your `impl` keys in their own commit so a conflict is trivial). T040 branches from your branch after you report, so keep your
commits clean.

## Acceptance
```sh
selftest/gate.sh
selftest/grade.sh            # via tools/job
```
The canary pack is run from `task/T040` (stacked on yours); you do not need to make it green. In your report,
include P002 T039 requirement 6 (action counts with and without `--witness`) and requirement 8 (the annas-c
effect, from a scratch clone in `/var/tmp/cache/T039`). Report every deviation.
