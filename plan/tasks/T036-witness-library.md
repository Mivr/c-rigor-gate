# T036: witness bundle, impl paths, scope and stub judge, as a pure library (P002 step 1, backlog B27)

Repo: `Mivr/c-rigor-gate`. Branch `task/T036`. The contract is the section "### T036" of `plan/P002-witness-grading.md`
(allowed paths, requirements, acceptance), read with the rest of that design. Read `AGENTS.md` first.
**In flight in parallel:** T021 (`grade.py`, `grade_context.py`, `verdict*`, `approvals.py`), T030 (`grade_build.py`,
`toolchains/**`), T032 (`grade_steps.py`, `grade_pipeline.py`, `grade_checks.py`, `grade_tree.py`, `grade_policy.py`,
`gate/order.txt`, `selftest/grade.sh`), T033 (`facts_*`), T034 (`rules/mutate.bzl`, `mutate/**`), T035 (`mutate/gen.py`).
Touch none of them. Nothing here is wired into `rigor grade` yet (that is T037/T039).

## Acceptance
As in the P002 section, plus:
```sh
selftest/gate.sh
```
