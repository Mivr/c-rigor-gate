# Gate `layering`: the architecture contract (T087, P001 G4, P002 section 7.1)

A monorepo of generic library modules (`lib/<tier>/<module>/`) and apps (`apps/<app>/<layer>/<module>/`) needs its
module boundaries enforced mechanically. Buck2 `visibility` is product-owned and an agent can widen it, so the
contract is gate-owned: `products/<product>/architecture.toml`, next to `product.toml` and `policy.toml`, read like
them (copied into the grade's `inputs/` snapshot, never from the product repository).

The gate sits right after `symbols` in `gate/order.txt` and reads the same facts (one build, shared with `symbols`):
for every module its direct `deps` and the `undefined` symbols of its units, and every dep's exports.

## No contract: PASS with info `no-architecture`
A product without `architecture.toml` has no layering to judge: the gate is PASS with the info finding
`no-architecture`, before any facts are looked at. (The task text said NOT_RUN. A NOT_RUN fails the verdict, so every
product without a contract, annas-c and the whole canary pack included, would fail; `tests-stub` has the same
`not-applicable` precedent.) With a contract, the gate compiles, so it is NOT_RUN unless `toolchain` and `assemble`
passed, like `symbols`.

## The contract
```toml
[layers]
order = ["lib-base", "lib-ds", "app-domain", "app-root"]   # bottom to top

[layer."lib-base"]                                  # one table per layer, exactly the names in `order`
modules = ["//lib/base/core:core", "//lib/base/fmt:*", "//lib/ds/**"]

[testkit]                                           # optional: non-c_test targets only tests may use
modules = ["//lib/base/core:testkit"]

[composition]                                       # optional: modules that may hold `composition` edges
modules = ["//apps/a/root:root"]

[[edge]]                                            # every allowed dependency edge
from = "app-domain"                                 # a layer name, or an exact module label
to = "lib-base"
kind = "data"                                       # data | pure | port | composition
[[edge]]
from = "app-domain"
to = "lib-ds"
kind = "port"
symbols = ["ds_init"]                               # port only, and required: the target symbols the edge may reference
```
Module entries: an exact label `//pkg:name`, a package glob `//pkg:*`, or a tree glob `//pkg/**` (the package and every
package below). Layers must not overlap (two layers listing one module is exit 2). Edge endpoints with `//` are
module labels, anything else must be a layer name. A fixture: `gate/tests/fixtures/layering/good.toml`.

Edge kinds:
* `data`: the target's header only (types and constants). The source may reference **no symbol the target defines**.
  The facts do not say which defined symbols are functions (a const table and a function are both `T`/`R` exports), so
  the rule is on every defined symbol: it fails closed.
* `pure`: calls the target's functions. No symbol restriction.
* `port`: modelled as `data` plus an explicit list (the spec's fallback): the source may reference only the target's
  symbols named in the edge's `symbols` (a port table getter, `*_init` constructors, exported data). A `port` edge
  needs a non-empty list and no other kind may have one.
* `composition`: constructs concrete adapters; no symbol restriction, allowed only from modules matched by
  `[composition] modules`.

When several edges allow one dependency, the most permissive satisfied one wins.

## Findings (all errors)
| rule | meaning |
|---|---|
| `ungoverned-module` | a graded module that no layer lists (`target`). Its edges are not judged. |
| `undeclared-edge` | a direct dep that no edge allows (`target`, `dep`, `from_layer`, `to_layer`). A production module that depends on a `c_test` or `[testkit]` target is one (`to_layer = testkit`). Edges inside one layer must be declared too. |
| `upward-edge` | a dep on a higher layer, declared or not. A layer-to-layer upward edge in the contract is exit 2 at load; an upward edge written between module labels is found here. |
| `edge-kind-violation` | a `data` or `port` edge whose source references a target symbol outside the edge's list (`symbol`, `unit`), or a `composition` edge from a module not in `[composition]` (`reason = composition-not-permitted`). |
| `contract-stale` | a module label or glob (layers, testkit, composition, edge endpoints) that matches no module (`entry`, `where`). |

Exempt: `c_test` targets and `[testkit]` modules as sources of edges (they may depend on anything); the policy's
`trusted` modules and gate-owned third-party libraries are outside the contract (`symbols` judges them). Only direct
`deps` are edges; a reference to a symbol of a transitive dep is the `symbols` gate's `undeclared-symbol`.

## Canaries
`layering-undeclared-edge`, `layering-data-edge-calls`, `layering-ungoverned-module` (each its own `architecture.toml`
over the base product; `control` has none and stays green). Unit tests: `gate/tests/test_layering.py`.

## Known limits
* The verdict's `inputs` do not yet bind a hash of `architecture.toml` (that needs a new key in
  `verdict_inputs.SHA_KEYS`, outside T087's paths); the file is snapshotted and read from the copy.
* `data` cannot tell a function from const data (see above).
