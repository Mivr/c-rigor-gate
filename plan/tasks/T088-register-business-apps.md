# T088: register `business-apps` as a gate product, with the allocation deny list (P002 G25)

Repo: `Mivr/c-rigor-gate`. Branch `task/T088`. Read `AGENTS.md`, `docs/grade.md`, `docs/product-checks.md`,
`docs/canaries.md`, and `products/annas-c/` (the model). The product is the private monorepo `Mivr/business-apps`
(local clone `/var/tmp/src/business-apps`, read-only for you; `main` has `lib/base/core` only, moved from annas-c `core`).

## Build
1. `products/business-apps/` from the draft in `/var/tmp/cache/T088/draft/` (written by the L000 agent; check every
   field against the annas-c files and `docs/grade.md`):
   - `product.toml`: `name = "business-apps"`, `[layout] include = ["lib/**"]` only (add `apps/**` when the first app
     module lands; a pattern that matches nothing is `stale-include`).
   - `policy.toml`: annas-c's `[global]` deny list **plus the allocation deny list** (G25): `malloc`, `calloc`,
     `realloc`, `free`, `aligned_alloc`, `posix_memalign`, `memalign`, `valloc`, `pvalloc`, `reallocarray`, `strdup`,
     `strndup`, `asprintf`, `vasprintf`, `getline`, `getdelim`, `open_memstream`, `mmap`, `munmap`, `mremap`, `brk`,
     `sbrk` (check the gate's own `ctest` and `canaries/_base` do not need any of them through this product; a trusted
     gate module that does is fine). Module entries for `//lib/base/core:*` exactly as annas-c grades `//core:*`
     (same level, allow lists, exports, `impl` = `lib/base/core/src/**`).
   - `expected-tests.json`: the 131 core test ids of `business-apps` `main` (verify from a build, do not copy blindly).
   - `tasks/whole-repo.toml` as annas-c's.
2. Canary `alloc-deny` (new dir in `canaries/`, do not edit existing ones): the shared base product plus an edit that
   calls `malloc` and `free` in production code, with a policy carrying the G25 list: `symbols` FAIL `denied-symbol`
   for both, every other gate as declared. Plus one for `strdup` (a less obvious allocator) if it costs little.
3. Docs: a short `docs/products.md` row or section listing the registered products (annas-c, business-apps) and what
   G25 adds; link from `README.md`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh --only control --only alloc-deny
# grade business-apps main (no witness: the witness gates may be NOT_RUN; say which)
gate/rigor grade --product-repo <your clone of /var/tmp/src/business-apps under /var/tmp/cache/T088> --base <first commit> --head main \
  --task products/business-apps/tasks/whole-repo.toml --product products/business-apps/product.toml ...
```
Every non-witness gate must PASS on business-apps main. Paste the verdict table. Report every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T088/tmp`; never write to `/tmp`. Build only with `gate/tools/buck2`, never host compilers.
No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs (your draft copy is in your own cache dir). Never kill
processes you did not start; never `buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and
8 GiB are shared.
