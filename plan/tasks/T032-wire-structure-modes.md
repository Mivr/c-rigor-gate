# T032: `rigor grade` runs the `structure` gate (T011) and the release/san `mode-divergence` check (T023)

Repo: `Mivr/c-rigor-gate`. Branch `task/T032`. Read `AGENTS.md`, `docs/grade.md`, `docs/structure.md` (incl. T011's
deviations 5 and 6: the grader must write the `c_structure` targets, skip header-only modules, and give test modules facts
or filter the policy), `docs/product-checks.md` ("Modes", T023: query `c_san_facts`), `gate/order.txt`,
`gate/rigor_lib/grade_mutants.py` (how the grader already writes a generated `c_mutants` package), `grade_steps.py`,
`grade_pipeline.py`, `grade_checks.py`, `buckfiles.py`. **T021 (verdict binding: `grade.py`, `grade_context.py`,
`verdict*.py`, `approvals.py`), T028 (`mutate/**`, `mutants_*.py`), T030 (`toolchains/**`, `grade_build.py`) and T033
(`facts_symbols.py`, `facts_policy.py`) run in parallel**: don't touch their files.

## Allowed paths
`gate/rigor_lib/grade_steps.py`, `grade_pipeline.py`, `grade_checks.py`, `grade_tree.py`, `grade_policy.py`, a new
`gate/rigor_lib/grade_structure.py`, `gate/rigor_lib/buckfiles.py` (only `TEST_DERIVED` += `_facts_san`, and the
generated package's name if needed), `gate/order.txt`, `rules/structure.bzl` (only if the generated targets need it),
`gate/tests/test_grade*.py`, `gate/tests/test_buckfiles*.py`, `selftest/grade.sh`, `selftest/grade_product/**`,
`canaries/structure-length/expect.json`, `canaries/structure-recursion/expect.json`, a new `canaries/mode-divergent/`,
`products/annas-c/**` (policy levels only, if needed), `docs/grade.md`, `plan/backlog.md` (mark B1, B2 wired; B3 wired).

## Requirements
1. Two new gates in `gate/order.txt` after `symbols`/`build` (say where and why): `structure` (from a generated
   `c_structure` package, like `c_mutants`; header-only modules skipped; test and fuzz modules have facts and are
   ungraded, as T011 designed) and `mode-divergence` (`rigor facts --modes` over the release facts and the
   `c_san_facts` twins). Both cached like every other build step; `--uncached` covers them.
2. Fail closed: a module with no structure facts, a missing san twin, a schema mismatch is exit 2 or a finding, never a pass.
3. `canaries/structure-length` and `structure-recursion` become live (drop `pending`; expected gate/rule as they now fail),
   and a new `mode-divergent` canary (code under `__has_feature(address_sanitizer)`) fails in `mode-divergence`.
4. `selftest/grade.sh` gains a red step per new gate and keeps every existing step green; cold/warm action counts reported.
5. Report the annas-c effect (information only, scratch clone in your cache, with `products/annas-c`): findings per new
   gate on annas-c main.

## Acceptance
```sh
selftest/grade.sh
selftest/gate.sh
selftest/canaries.sh
```
