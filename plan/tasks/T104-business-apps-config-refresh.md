# T104: refresh `products/business-apps` for the lockers modules merged after T103, and grade with the approvals

Repo: `Mivr/c-rigor-gate`. Branch `task/T104`. Read `plan/tasks/T103` and `T101` (the precedents: same method, same
rules, same four files), `AGENTS.md`, `docs/products.md`, `docs/grade.md`, `docs/product-checks.md`,
`docs/layering.md`, `docs/approvals.md` (or wherever `--approvals` is documented), the `c_catalog` docs from T105, and
`products/business-apps/` as T103 left it. The product is `Mivr/business-apps`, local clone
`/var/tmp/src/business-apps` (main at `836c9b8` or later). **It is read-only for you**: clone it into
`/var/tmp/cache/T104/biz-clone` (`git clone -q /var/tmp/src/business-apps biz-clone`, then
`git -c protocol.file.allow=always -c submodule.gate.url=/var/tmp/src/c-rigor-gate submodule update --init -q`)
and grade the clone.

## Why
Since T103, business-apps `main` gained many lockers modules under `apps/lockers/` (`lk/*`, `lkadp/*`, `lkapp/*`,
`lkrx/*`, `lksim/*`, `lkui/*`, `relay/*`), a `c_catalog` package (`apps/lockers/lkui/catalog`, generated from
`.pot`/`.po`), and changes to `lib/*` (for example `lib/sim/simfs` read_at/truncate, `lib/base/ports`,
`lib/fmt/jpull` skip_overlong). Take every module on `main` when you clone and list them, with their level per
`docs/design.md` (section 4.1 for lockers; `relay/*` is L4; adapters `lkadp/*` per the design column). Take only what
is on `main`.

## Build
Same four files and rules as T103:
- policy entries: level, `impl`, exact exports from the facts, minimal allows, no allocator. `lkui/catalog` is a
  generated catalog: L1, exports exactly its catalog symbol, its `.pot`/`.po` files in `[layout] include`;
- expected ids: add-only, with `gate/tools/expected.py add` from real release+san results. Remove nothing; if a
  previously expected id no longer exists on `main` (renamed test), report it, do not delete it;
- `architecture.toml`: the edges the new graph needs. Extend T103's lockers layer rules to the new sub-layers
  (`lk` < `lkrx` < `lkui`, adapters `lkadp` over ports, `lkapp` wiring, `relay`, `lksim`) per the design's dependency
  column, as rules rather than one-off edges; nothing in `lib/**` may depend on `apps/**`. Say how you encoded it;
- `[layout] include`: exactly the module dirs on `main`.

**Approvals:** grade with `--approvals /var/tmp/cache/T104/approvals`, a read-only copy of the orchestrator's signed
equivalent-mutant approvals for business-apps (already staged there). Never write an approval and never edit those
files. Report how the grade used them: matched ids, approvals rejected and why, unused approvals.

Run the whole-repo grade of the clone until it PASSes, or until only real product defects remain. List those defects
with gate, rule, module and excerpt. Never edit product code. Known open product findings (do not try to fix them):
those T103 left open (read its merge commit message and report section in the plan file if any). List every surviving
mutant id that no approval covers (file:line, mutation). Report any module over a structure or mutant budget as a
product finding. Take T103's finding list and say which findings the merged changes closed.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary in the report: gates, statuses, finding counts.

## Rules
Use `TMPDIR=/var/tmp/cache/T104/tmp`, and never write to `/tmp`. Build only with `gate/tools/buck2`, never host
compilers. Redirect every build/grade output to a file and read the file; never pipe into `tail` or `head`. Long runs go
through `tools/job run` and `tools/job wait`. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs, and never
search from `/`. Do not print the environment. Never use `rm`; overwrite with `cp -f`. Kill only processes you
started: your own buck2d by pid, found with `readlink /proc/<pid>/cwd` pointing into your worktree or clone. Do NOT
run `buck2 kill` (it kills other lanes' daemons). If your daemon dies from a foreign kill, just re-run. No sleep-poll
loops. Only one grade at a time in your lane. 2 CPUs and 8 GiB, shared. No network.
