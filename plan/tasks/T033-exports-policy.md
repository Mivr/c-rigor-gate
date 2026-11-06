# T033: a gate-owned exports list per module; extra or mutable exported objects are findings (R003 G7, backlog B32)

Repo: `Mivr/c-rigor-gate`. Branch `task/T033`. Read `AGENTS.md`, `docs/product-checks.md` (symbols gate),
`gate/rigor_lib/facts_symbols.py`, `facts_policy.py`, `facts_data.py`, `docs/grade.md`, and R003's G7
(`plan/audits/R003-test-adequacy.md`). **T021, T028, T030 and T032 run in parallel**: don't touch `grade*.py`,
`verdict*.py`, `approvals.py`, `mutate/**`, `mutants_*.py`, `toolchains/**`, `gate/order.txt`.

## Why
R003 S6a: a test author added a writable global hook to the module header; the tests never set it; grade passed L3.
Nothing compares a module's exported symbols with what the spec allows, or flags exported mutable objects.

## Allowed paths
`gate/rigor_lib/facts_symbols.py`, `facts_policy.py`, `facts_data.py` (only if the facts need a field), `cscan.py` or
`rules/facts.bzl` (only if the object's symbol kinds aren't in the facts yet), `gate/tests/test_facts*.py`,
`selftest/product_checks.sh`, `selftest/product_checks_product/**` (or wherever its fixtures live), new `canaries/extra-hook/`,
`products/annas-c/**` (the new policy key for annas-c's modules), `docs/product-checks.md`, `plan/backlog.md` (mark B32).

## Requirements
1. Policy: per module an `exports = [...]` list (the gate-owned allowed set of defined external symbols). At L3 and L2 a
   defined external symbol not in the list is `unexpected-export`; a missing `exports` key at L3 is `exports-missing`
   (fail closed); L1 exempt. Document how a product generates its first list.
2. An exported **mutable object** (defined in a writable data/bss section, not `const`) is `mutable-global-export`, error at
   L3, info at L2, regardless of the list.
3. Red twins in the selftest: an extra function, an extra mutable global, an extra const table (only `unexpected-export`),
   a missing key; green: exact list. The `extra-hook` canary (R003 S6a shape) fails in `symbols`.
4. annas-c: generate `exports` for every module in `products/annas-c` from its headers and report any symbol that is
   exported but not declared in a public header (information only).

## Acceptance
```sh
selftest/product_checks.sh
selftest/gate.sh
selftest/canaries.sh --only extra-hook --only control
```
