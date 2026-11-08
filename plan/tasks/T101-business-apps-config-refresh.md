# T101: refresh `products/business-apps` for the modules merged after T098, and grade with the approvals

Repo: `Mivr/c-rigor-gate`. Branch `task/T101`. Read `plan/tasks/T092`, `T093`, `T094` and `T098` (the precedents:
same method, same rules), `AGENTS.md`, `docs/products.md`, `docs/grade.md`, `docs/product-checks.md`,
`docs/layering.md`, `docs/approvals.md` (or wherever `--approvals` is documented), and `products/business-apps/` as
T098 left it. The product is `Mivr/business-apps`, local clone `/var/tmp/src/business-apps`. **It is read-only for
you**: clone it into `/var/tmp/cache/T101/biz-clone` and grade the clone.

## Why
Since T098, business-apps `main` gained:
- the `jdom` split (`jnum`, `jstr`, `jkidx`, `jtok`, `jdom`), the `url` split (`url` + `pct`) and the `rxwire` split
  (`rxwire` + `rxindex`), and the `simfs` split (`simfs` + `simfs_tab`);
- `lib/sim/simnet`, `lib/io/posix_fs`, `lib/io/osal` (pthread via `system_libs`), `lib/rt/rtprio`, `lib/rt/rx`, `lib/fmt/fp`
  (gate mbedTLS) and `lib/io/posix_net` (L2 syscall adapter; real-libc seam over getaddrinfo, socket, connect,
  getsockopt, poll, send, recv, close and clock_gettime: exactly the allows it calls).

Take every module on `main` when you clone and list them, with their level per `docs/design.md`. Some modules
(`simhost`, `scene`, `jpull` split, `tls_stream`) may still be on task branches. Take only what is on `main`.

## Build
Same four files and rules as T092 steps 1-5:
- policy entries: level, `impl`, exact exports from the facts, minimal allows, no allocator;
- expected ids: add-only, with `gate/tools/expected.py add` from real release+san results;
- `architecture.toml`: the edges the new graph needs;
- `[layout] include`: exactly the module dirs on `main`.

**Approvals:** grade with `--approvals /var/tmp/cache/T101/approvals`. That is a copy of the orchestrator's signed
equivalent-mutant approvals for business-apps (`<sha256>.json` + `.json.sig`). It is read-only, so never write an
approval and never edit those files. Report how the grade used them: matched ids, approvals the grade rejected and
why, unused approvals.

Run the whole-repo grade of the clone until it PASSes, or until only real product defects remain. List those defects
with gate, rule, module and excerpt. Never edit product code. List every surviving mutant id that no approval
covers (file:line, mutation). Report any module over a structure or mutant budget as a product finding. Take T098's
finding list and say which findings the merged changes closed.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary in the report: gates, statuses, finding counts.

## Rules
Use `TMPDIR=/var/tmp/cache/T101/tmp`, and never write to `/tmp`. Build only with `gate/tools/buck2`, never host
compilers. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs, and never search from `/`. Do not print the
environment. Kill only processes you started, by the pid `tools/job` recorded. Run `buck2 kill` only in your clone.
No sleep-poll loops (`tools/job`). Only one grade at a time in your lane. 2 CPUs and 8 GiB, shared. No network.
