# T007: integrate product checks into `rigor grade`; register annas-c as a graded product

Repo: `Mivr/c-rigor-gate`. Branch `task/T007`. Read `AGENTS.md`, `plan/phase1.md`, `docs/grade.md`,
`docs/product-checks.md`, `docs/ctest.md`. T006 (mutation) runs in parallel: don't touch `mutate/**`, `rules/**`,
or its new gate module; keep your gate-list change to the single `GATES` table and `gate/order.txt`.

## Allowed paths
`gate/rigor_lib/grade*.py`, `gate/order.txt`, `gate/tests/test_grade.py`, `products/**`, `policy/**`,
`gate/tools/**` (new), `selftest/grade.sh`, `selftest/grade_product/**`, `docs/grade.md`.

## 1. Pipeline
Add the T004 gates to `rigor grade`, after `assemble` and before `build`:
- `buckfiles` over the assembled product part of the tree;
- `semantic-suppressions` and `symbols`: build every `*_facts` target (release), collect the facts dir, run them
  with `products/<p>/policy.toml` and the toolchain's `libc_symbols`.
The policy path comes from the gate-owned product dir, never from the product.
Update `gate/order.txt`, the selftest product's policy, and add red cases to `selftest/grade.sh`: a product
calling `kill` (symbols FAIL), a product with a spliced `#line` + `optnone` (semantic FAIL), a BUCK with
`native.cxx_library` (buckfiles FAIL). Each must fail only in its gate.

## 2. Expected-test maintenance tool
`gate/tools/expected.py add --product P --results DIR...`: merges the test ids found in result files into
`products/<P>/expected-tests.json` (sorted, add-only; it refuses to remove ids, which needs a signed
`test-removal` approval and a manual edit). Unit-tested.

## 3. Register annas-c
`products/annas-c/product.toml` (layout include `core/**`, `url/**`, `fsname/**`, `json/**`, `html/**`,
`ports/**`, `annas/**`, `adapters/**`, `cli/**`, `mcp/**`), `products/annas-c/policy.toml` (modules
`//core:core`, `//url:url`, `//fsname:fsname` with the smallest `allow` lists that their current code needs;
tests get the same deny list), and `products/annas-c/expected-tests.json` generated with the tool from the
current annas-c `main` results. A product clone is available read-only at `/var/tmp/src/annas-c` (read it;
do not commit there). Note: annas-c `main` currently has `url` and `fsname` as **stubs** (an implementer task is
running), so their tests fail today: register their ids anyway, and expect the grade to FAIL only in
`tests-*` for those ids.

## 4. Grade annas-c
Run `gate/rigor grade` on annas-c `main` (cached and once `--uncached`) with a task contract
`products/annas-c/tasks/whole-repo.toml` that allows everything under the layout. Report the full verdict.
`core` must pass every gate; any `symbols` or `semantic-suppressions` finding in `core` is reported, not fixed
(you cannot change annas-c).

## Acceptance
```sh
selftest/grade.sh     # twice, exit 0
selftest/gate.sh
gate/rigor grade ... annas-c main ...   # verdict reported verbatim
```
