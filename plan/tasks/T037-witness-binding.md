# T037: bind the witness into the verdict (P002 step 2, backlog B27)

Repo: `Mivr/c-rigor-gate`. Branch `task/T037`. The contract is the section "### T037" of `plan/P002-witness-grading.md`
(allowed paths, requirements, acceptance), read with the rest of that design and the library T036 merged
(`gate/rigor_lib/witness_bundle.py`, `witness_scope.py`, `stub_judge.py`, `docs/witness.md`). Read `AGENTS.md` first,
including "Working efficiently" if present.
**In flight in parallel:** T030 (`grade_build.py`, `toolchains/**`), T032 (`grade_steps.py`, `grade_pipeline.py`,
`grade_checks.py`, `grade_tree.py`, `grade_policy.py`, `gate/order.txt`, `selftest/grade.sh`), T033 (`facts_*`),
T034 (`rules/mutate.bzl`, `mutate/**`), T035 (`mutate/gen.py`), T042 (`tools/job`, `trajectory_*`, `AGENTS.md`),
T043 (`selftest/gate.sh`), T044 (`tools/affected*`, `tools/validate.sh`). Touch none of them. Do not edit
`plan/backlog.md`.
**Owner decision 4 (the `witness-equivalent-mutant` approval kind) is not yet confirmed:** implement it as P002
recommends, keep it in one clearly separated place in `approvals.py`, and say in the report exactly which lines to
drop if the owner rejects it.

## Acceptance
As in the P002 section, plus:
```sh
selftest/gate.sh
selftest/grade.sh
```
