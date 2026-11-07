# T087: `layering` gate: the architecture contract (P001 G4, P002 section 7.1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T087`. Read `AGENTS.md`, `docs/gate.md`, `docs/grade.md`,
`docs/product-checks.md`, `docs/canaries.md`, `gate/rigor_lib/facts_data.py`, `facts_symbols.py`, `facts_policy.py`,
`grade_pipeline.py`, `gate/order.txt`, and `products/annas-c/`.

## Why
The next product (`Mivr/business-apps`, a monorepo: generic library modules under `lib/<tier>/<module>/` and apps under
`apps/<app>/<layer>/<module>/`) needs its module boundaries enforced mechanically. Buck2 `visibility` is product-owned
and an agent can widen it; the contract must be gate-owned.

## The contract
`products/<product>/architecture.toml`, gate-owned (like `policy.toml`), optional per product (a product without one:
gate `layering` is NOT_RUN with reason `no-architecture`). Shape (refine names if needed, document them):
```toml
[layers]                     # ordered from bottom to top
order = ["lib-base", "lib-ds", "lib-rt", "app-domain", "app-root"]
[layer."lib-base"]
modules = ["//lib/base/core:core", "//lib/base/fmt:*"]   # labels, or a package glob ending in ":*" or "/**"
[[edge]]                      # every allowed dependency edge, by layer or by module
from = "app-domain"           # a layer name or a module label
to = "lib-base"
kind = "pure"                 # data | pure | port | composition
```
Edge kinds: `data` (the target's header only: types and constants, **no function symbol of the target referenced**);
`pure` (calls the target's functions); `port` (uses the target only through a port table: may reference only the
target's exported data symbols and its `*_init`-style constructors the edge lists in `symbols = [...]`, if you need it;
otherwise model `port` as `data` plus an explicit symbol list, and say so); `composition` (constructs concrete
adapters; allowed only from modules the contract lists).

## The gate
- Reads, for every graded module, its facts (`deps` and per-unit `undefined` symbols, already in the facts files) and
  each dep's exports. Findings (all errors, fail closed):
  - `ungoverned-module`: a graded module no layer lists.
  - `undeclared-edge`: a dep (direct `deps` entry) that no edge allows, naming from, to and both layers.
  - `upward-edge`: an edge to a higher layer even if declared (a contract defect: make it an `InternalError`
    at load time instead if you prefer, and say which).
  - `edge-kind-violation`: a `data` edge whose source references a function the target defines (name the symbol
    and unit); a `port` edge beyond its listed symbols.
  - `contract-stale`: a module label or glob in the contract that matches no module (like `stale-include`).
  - Test-only targets (`c_test`, fakes the policy marks `testkit`) are exempt from layering, but their deps are not
    allowed to make a production module depend on them (a production module depending on a testkit is an
    `undeclared-edge`).
- Placed in `gate/order.txt` after `symbols` (same facts), wired into `rigor grade`, documented in
  `docs/layering.md` and linked from `docs/grade.md` / `docs/product-checks.md`.
- Canaries (each red, in `canaries/`, own fixtures, do not edit existing ones): `layering-undeclared-edge`,
  `layering-data-edge-calls`, `layering-ungoverned-module`. Plus `control` stays green.
- Unit tests with green and red fixtures for every finding, and the NOT_RUN case.
- No change to `products/annas-c/`: annas-c has no contract yet (NOT_RUN).

## Allowed paths
`gate/rigor_lib/layering*.py` (new), `gate/rigor_lib/grade_pipeline.py`, `gate/rigor_lib/grade_steps.py`,
`gate/rigor_lib/grade_checks.py` (wiring only), `gate/order.txt`, `gate/rigor_lib/cli.py` (a `rigor layering`
subcommand if useful), `gate/tests/test_*layering*.py`, `gate/tests/fixtures/layering/**`, `canaries/layering-*/**`,
`docs/layering.md`, `docs/grade.md`, `docs/product-checks.md` (links and a row).

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/gate.sh
selftest/canaries.sh --only control --only layering-undeclared-edge --only layering-data-edge-calls --only layering-ungoverned-module
selftest/grade.sh
```
Report the change, the contract format, the tests, the canary table, and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T087/tmp`; never write to `/tmp`. Build only with `gate/tools/buck2`, never host compilers.
No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill processes you did not start; never
`buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
