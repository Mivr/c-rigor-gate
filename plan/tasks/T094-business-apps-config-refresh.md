# T094: refresh `products/business-apps` for the modules merged after T093

Repo: `Mivr/c-rigor-gate`. Branch `task/T094`. Read `plan/tasks/T092-business-apps-lib-config.md` and
`plan/tasks/T093-business-apps-config-refresh.md` (the precedents: same method, same rules), `AGENTS.md`, `docs/products.md`, `docs/grade.md`, `docs/product-checks.md`, `docs/layering.md`
and `products/business-apps/` as T092 left it. The product is `Mivr/business-apps`, local clone
`/var/tmp/src/business-apps` (**read-only for you**: clone it into `/var/tmp/cache/T094/biz-clone` and grade the clone).

## Why
Since T093 cloned (which covered the http split, `sel`, `blob`, `ports` and `mbrtu`), business-apps `main` changed
`blob_init` to take a `blob_storage_t` (L051) and gained `lib/fmt/i18n`, `lib/fmt/kv`, `lib/rt/mbox` (the only osal-seam user
besides simhost and the composition root, design S7), `lib/fmt/jpull`, `lib/sim/simclock`, `lib/sim/simrng`,
`lib/sim/trace`, `lib/io/portfakes`, `lib/io/posix_clock` and `lib/io/posix_rand` (L2 syscall adapters), the
`fsm` `report(rep, value)` change (L048), the `httpredir` dead-branch removal, and direct `httpchunk`/`jutf8` tests
(L050). Take every module on `main` when you clone and list them, with their level per `docs/design.md` (sim cores
L3, syscall adapters L2, ports L1). Also take T093's finding list and say which findings the merged changes closed.

## Build
Same four files and rules as T092 steps 1-5: policy entries (level, `impl`, exact exports from the facts, minimal
allows, no allocator), expected ids add-only with `gate/tools/expected.py add` from real release+san results, the
`architecture.toml` edges the new graph needs (fewest named `[[edge]]` declarations; `data` edges to header-only
modules as `docs/layering.md` defines), and `[layout] include` covering exactly the module dirs on `main`. Run the
whole-repo grade of the clone until PASS or until only real product defects remain (list them: gate, rule, module,
excerpt; never edit product code). If the grade needs mutant approvals, list the exact mutant ids with file:line and
mutation; do not sign anything. If any module exceeds a structure or mutant budget, report it as a product finding. The real-libc seam tables of the L2 adapters call `clock_gettime` and `getrandom`: give exactly the allows they need, nothing broader.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary (gates, statuses, finding counts) in the report.

## Rules
Use `TMPDIR=/var/tmp/cache/T094/tmp`; never write to `/tmp` (the harness scratchpad under `/tmp` included). Build only
with `gate/tools/buck2`, never host compilers. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill
processes you did not start (your own `tools/job` jobs are yours); never `buck2 kill` outside your scratch. No
sleep-poll loops (`tools/job`). Only one grade at a time in your lane. 2 CPUs and 8 GiB are shared.
