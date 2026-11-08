# T103: refresh `products/business-apps` for the modules merged after T101 (first lockers modules), and grade with the approvals

Repo: `Mivr/c-rigor-gate`. Branch `task/T103`. Read `plan/tasks/T101` (the precedent: same method, same rules, same
four files), `AGENTS.md`, `docs/products.md`, `docs/grade.md`, `docs/product-checks.md`, `docs/layering.md`,
`docs/approvals.md` (or wherever `--approvals` is documented), and `products/business-apps/` as T101 left it. The
product is `Mivr/business-apps`, local clone `/var/tmp/src/business-apps` (main at `e45b21c` or later). **It is read-only
for you**: clone it into `/var/tmp/cache/T103/biz-clone` and grade the clone.

## Why
Since T101, business-apps `main` gained:
- `lib/sim/simhost`, `lib/ui/scene`, `lib/ui/scenediff`, `lib/ui/a11y`, `lib/io/tls_stream` (moved from annas-c; gate
  mbedTLS; its pnet transport over posix_net's public API), `posix_net`'s `pnet_wait`, the T097-era grade fixes
  (test-kit statics behind accessors; the simnet accept struct);
- the first **lockers** modules under `apps/lockers/`: `lk/types`, `lk/syncsched`, `lk/code` (more follow:
  include whatever is on `main` when you clone). Their header includes are `"apps/lockers/<dir>/<name>.h"`.

Take every module on `main` when you clone and list them, with their level per `docs/design.md` (lockers modules:
section 4.1; `relay/*` modules are L4). Take only what is on `main`.

## Build
Same four files and rules as T101:
- policy entries: level, `impl`, exact exports from the facts, minimal allows, no allocator;
- expected ids: add-only, with `gate/tools/expected.py add` from real release+san results;
- `architecture.toml`: the edges the new graph needs. The lockers layer is a new layer above `lib/*`: `lk/*`
  modules may depend on `lib/base`, `lib/ds`, `lib/fmt` and on `lk/types` (and on each other only along the design's
  dependency column); nothing in `lib/**` may depend on `apps/**`. Encode that as rules, not as one-off edges, and say
  how you did it;
- `[layout] include`: exactly the module dirs on `main`, `apps/lockers/**` included.

**Approvals:** grade with `--approvals /var/tmp/cache/T103/approvals`, a read-only copy of the orchestrator's signed
equivalent-mutant approvals for business-apps. Never write an approval and never edit those files. Report how the
grade used them: matched ids, approvals the grade rejected and why, unused approvals.

Run the whole-repo grade of the clone until it PASSes, or until only real product defects remain. List those defects
with gate, rule, module and excerpt. Never edit product code. Known open product findings from T101 (do not try to
fix them): the `jstr_decode` (8 params) and `jtok_literal` (7 params) structure findings, pending the jpull split
(L071); the contract `submodule` finding on `gate`. List every surviving mutant id that no approval covers
(file:line, mutation). Report any module over a structure or mutant budget as a product finding. Take T101's finding
list and say which findings the merged changes closed.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary in the report: gates, statuses, finding counts.

## Rules
Use `TMPDIR=/var/tmp/cache/T103/tmp`, and never write to `/tmp`. Build only with `gate/tools/buck2`, never host
compilers. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs, and never search from `/`. Do not print the
environment. Kill only processes you started, by the pid `tools/job` recorded. Run `buck2 kill` only in your clone.
No sleep-poll loops (`tools/job`). Only one grade at a time in your lane. 2 CPUs and 8 GiB, shared. No network.
