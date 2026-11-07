# T069: narrow the selftest product's exports lists back to the clean module (T055 deviation)

Repo: `Mivr/c-rigor-gate`. Branch `task/T069`. Read `AGENTS.md` ("Working efficiently"), `selftest/grade.sh`,
`products/selftest/policy.toml`, and `docs/product-checks.md` (exports).
T055 widened `products/selftest/policy.toml` `exports` for core and util with symbols that only some red-case or
step edits add: `core_marker`, `core_slow`, `core_stop`, `core_sum_ff`, `util_fact` and `util_long` (and T041 added
`core_pos`). That happened because `selftest/grade.sh` shares one policy across all steps. As a result, the
selftest product no longer catches an accidental export of those names in the clean case.

## Requirement
1. `products/selftest/policy.toml` `exports` lists exactly what the clean selftest module exports.
2. A `grade.sh` step whose edit adds a symbol grades against a **scratch copy** of the product inputs, with
   that step's symbol added. T041's `ta-*` steps already work this way; reuse its helper, or extract one shared
   helper.
3. A new red property step in `grade.sh`: the clean module plus an unlisted exported function fails `symbols` with
   `unexpected-export`. This pins that the narrowing works.
4. Every existing step keeps its expected result.

## Allowed paths
`products/selftest/policy.toml`, `selftest/grade.sh`, `selftest/grade_product/**`, `docs/grade.md` (the selftest
section).
**In flight in parallel:** T064 (`rules/mutate.bzl`, `mutate/**`, `mutants_*`, `selftest/mutate.sh`). Do not edit
`plan/backlog.md` or `plan/backlog.d/`.

## Acceptance
```sh
selftest/gate.sh
selftest/grade.sh            # via tools/job, twice in a row
```
