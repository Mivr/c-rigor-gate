# T005: `rigor grade`, the end-to-end grading pipeline

Repo: `Mivr/c-rigor-gate`. Branch `task/T005`. Read `AGENTS.md`, `plan/phase1.md` (section "Grading tree"),
`docs/toolchain.md`, `docs/ctest.md`, `docs/gate.md` first. T004 (facts, buckfiles) runs in parallel; it will add
its gates to the pipeline afterwards, so leave a clear single place (the gate list) where gates are registered.

## Goal
One command that grades a product change and produces a verdict nobody but the gate influenced:
```
gate/rigor grade --product-repo R --base B --head H --task TASK.toml --product products/<p>/product.toml \
                 [--approvals DIR] [--sign-key KEY] --work DIR --out verdict.json
```

## Allowed paths
`gate/**` (new modules and tests; existing gates untouched except registering in the CLI), `products/**`,
`selftest/grade.sh`, `docs/grade.md`.

## Pipeline (fixed order; each step writes a gate result; any exception = exit 2 and FAIL)
1. **clone**: `git clone --no-local --no-hardlinks` R into `<work>/src` with the hardened git environment from
   `gitrun` (no replace objects, no grafts, no fsmonitor, no hooks, no global config); resolve B and H there;
   check out H detached. All later git gates read this clone, never R.
2. **contract**, **suppressions**: run in-process against the clone with TASK.toml and the approvals.
3. **assemble**: build `<work>/tree/` from scratch:
   - `gate/` = `git archive` of the gate repo at the commit `rigor` itself is running from (record its sha;
     refuse to run if the gate checkout has uncommitted changes to tracked files);
   - product files copied from the clone only if they match `product.toml` `[layout] include` globs and none of
     `[layout] exclude` (always excluded, whatever the product says: `.buckconfig`, `.buckroot`, `*.bzl`,
     `tools/**`, `toolchains/**`, `prelude/**`, `gate/**`, `.git*`);
   - a gate-generated `.buckconfig` (cells: root = tree, gate = tree/gate, toolchains = tree/gate/toolchains,
     prelude bundled; RE settings as in the gate's own `.buckconfig`).
   Record a manifest (path, sha256) of every file copied into the tree in the gate metadata.
4. **build**: in the tree, `tools/buck2`-equivalent (the gate's pinned binary check) builds every `*_results`
   target in `release` and `san` platforms, with `--build-report`. Any build failure: FAIL with the failing
   targets. Kill the grading daemon at the end (`buck2 kill` in the tree) so daemons don't pile up.
5. **tests-release**, **tests-san**: copy the results artifacts into per-mode dirs and run the `tests` gate
   with `products/<p>/expected-tests.json` (gate-owned) and, if present, `expected-tests.previous.json`.
6. **verdict**: `verdict` over the fixed order file `gate/order.txt`
   (`clone contract suppressions assemble build tests-release tests-san` for now; T004 adds its ids).
   With `--sign-key`, also write `verdict.json.sig` (`ssh-keygen -Y sign -n c-rigor-gate-verdict`).

`product.toml`:
```toml
name = "annas-c"
[layout]
include = ["core/**", "json/**", ...]   # product source dirs, BUCK files included
exclude = []
```

## Self-test `selftest/grade.sh`
Creates a throwaway product git repo from a template under `selftest/grade_product/` (a two-module C product
using the gate macros and ctest), a matching `products/selftest/` policy, and runs `rigor grade`:
- clean change: overall PASS; second run on the same head: PASS with 0 executed build actions (report the warm
  wall time);
- red cases, each must give FAIL in the right gate and nowhere else: path outside contract; added `NOLINT`;
  product ships its own `.buckconfig` disabling `-Werror` plus a warning (must still fail `build`, proving the
  product's config is ignored); product ships a `tools/buck2`; a failing test; a test removed from the source
  while still expected; an expected test missing because its BUCK target was deleted; a heap overflow that only
  `san` catches;
- the verdict `core_sha256` is identical across two runs of the same inputs.

## Acceptance
```sh
selftest/grade.sh      # twice, exit 0
selftest/gate.sh       # still green
```
Report the gate results for every case, warm/cold wall times, and deviations.
