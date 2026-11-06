# T013: the grading layout fails closed (backlog B14); complete the annas-c layout, policy, levels and expected tests

Repo: `Mivr/c-rigor-gate`. Branch `task/T013`. Read `AGENTS.md`, `plan/backlog.md` (B14), `docs/grade.md`,
`docs/product-checks.md`, `docs/mutate.md`, `gate/rigor_lib/product_layout.py`, `grade_tree.py`,
`grade_policy.py`, and `products/annas-c/**`. **In parallel:** T011 (`structure*`, one `cli.py` line), T014
(`cscan.py`, `semantic_table.py`, `facts_*.py`, `rules/c.bzl`), T015 (`trajectory*`, one `cli.py` line), T016
(`rules/ctest.bzl`, `toolchains/**`, `ctest/**`). Touch none of those.

## Why
`[layout].include` is an allow-list. annas-c's `http/`, `app/` and `posix_*/` were never graded, and nothing
said so. A gate that silently grades less than the product is fail-open.

## Allowed paths
`gate/rigor_lib/product_layout.py`, `gate/rigor_lib/grade_tree.py`, `gate/rigor_lib/grade_checks.py`,
`gate/rigor_lib/grade_policy.py`, `gate/tests/test_product_layout*.py`, `gate/tests/test_grade*.py`,
`selftest/grade.sh`, `selftest/grade_product/**`, `products/annas-c/**`, `docs/grade.md`, `plan/backlog.md`
(mark B14).

## Requirements
1. **Coverage rule.** At assembly, every file at the product head that is a `BUCK` file, or has a C or header
   extension (`.c`, `.h`, `.inc`, `.def`, and also any file that a product BUCK names in `srcs` or `headers`), must
   be included by the layout, or excluded by a gate rule (for example `gate/**`, `third_party/**`, always
   excluded). Anything else is a finding `ungraded-path` (fail) naming the path. `exclude` in `product.toml` may
   name only non-code paths (docs, plans, fixtures). An exclude that covers a BUCK or C file is itself a finding
   `excluded-code`. Make `third_party/**` an always-excluded gate path (B12 note).
2. **No silent empty modules.** A layout include glob that matches nothing is a finding `stale-include`. For
   annas-c, drop `html/**`, `adapters/**`, `cli/**` and `mcp/**` or keep them only if they exist.
3. **annas-c**: include `http/**`, `annas/**`, `app/**`, `posix_fs/**`, `posix_env/**`, `posix_clock/**` (and
   `tls_stream/**` only if present at the graded head). Add policy entries with the **smallest** `allow` lists
   their code at the head needs, and levels: core, json, url, fsname, http, annas = L3; ports, app, posix_fs,
   posix_env, posix_clock = L2; testkits and fakes libraries = L1 (or whatever `grade_policy` allows for
   test-support libraries; document it). Regenerate `expected-tests.json` with `gate/tools/expected.py add`.
4. Grade annas-c `main` at the latest commit (`/var/tmp/src/annas-c`, read-only; clone it into
   `/var/tmp/cache/T013/`). Every gate except `mutants` must PASS. Report the `mutants` findings per module as
   information, because they are product work, not this task's.

## Self-test
`selftest/grade.sh`: red cases for an unlisted module directory (`ungraded-path`), a C file hidden under an
excluded docs path (`excluded-code`), a stale include glob, and a third-party copy in the product tree. Green:
the full layout passes.

## Acceptance
```sh
selftest/gate.sh
selftest/grade.sh
gate/tools/rigor grade ... annas-c main   # the exact command and the per-gate statuses
```
