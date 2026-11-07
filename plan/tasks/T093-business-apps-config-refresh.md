# T093: refresh `products/business-apps` for the modules merged after T092

Repo: `Mivr/c-rigor-gate`. Branch `task/T093`. Read `plan/tasks/T092-business-apps-lib-config.md` (the precedent: same
method, same rules), `AGENTS.md`, `docs/products.md`, `docs/grade.md`, `docs/product-checks.md`, `docs/layering.md`
and `products/business-apps/` as T092 left it. The product is `Mivr/business-apps`, local clone
`/var/tmp/src/business-apps` (**read-only for you**: clone it into `/var/tmp/cache/T093/biz-clone` and grade the clone).

## Why
Since T092 cloned, business-apps `main` gained `lib/ds/dset`, `lib/fmt/fmt`, `lib/rt/ev`, `lib/rt/fsm`, `lib/fmt/jdom`,
`lib/fmt/jw`, `lib/fmt/jutf8`, `lib/rt/tlog`, `lib/fmt/mbrtu` (level **L4**: the relay safety core depends on it),
`lib/rt/elog`, and possibly the http/url split (`lib/fmt/{httpdef,url,httpreq,httpchunk,httpresp}`; `httpdef` is
header-only, a data module) by the time you clone. Take every module on `main` when you clone and list them. The
config grades only T092's eight modules, so a whole-repo grade of `main` reports them as ungraded.

## Build
Same four files and rules as T092 steps 1-5: policy entries (level, `impl`, exact exports from the facts, minimal
allows, no allocator), expected ids add-only with `gate/tools/expected.py add` from real release+san results, the
`architecture.toml` edges the new graph needs (fewest named `[[edge]]` declarations; `data` edges to header-only
modules as `docs/layering.md` defines), and `[layout] include` covering exactly the module dirs on `main`. Run the
whole-repo grade of the clone until PASS or until only real product defects remain (list them: gate, rule, module,
excerpt; never edit product code). If the grade needs mutant approvals, list the exact mutant ids with file:line and
mutation; do not sign anything. If `httpresp` exceeds a structure or mutant budget, report it as a product finding.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary (gates, statuses, finding counts) in the report.

## Rules
Use `TMPDIR=/var/tmp/cache/T093/tmp`; never write to `/tmp` (the harness scratchpad under `/tmp` included). Build only
with `gate/tools/buck2`, never host compilers. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill
processes you did not start (your own `tools/job` jobs are yours); never `buck2 kill` outside your scratch. No
sleep-poll loops (`tools/job`). Only one grade at a time in your lane. 2 CPUs and 8 GiB are shared.
