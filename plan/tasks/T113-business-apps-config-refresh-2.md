# T113: refresh `products/business-apps` for the modules merged after T111 (uikit + LVGL policy, e2e, posix_listen, runtime, codeshttp, httpreq)

Repo: `Mivr/c-rigor-gate`. Branch `task/T113`. Same method, rules and four files as T111: read
`plan/tasks/T111-business-apps-config-refresh.md` first and follow it, with these differences.

- Product: `Mivr/business-apps`, local clone `/var/tmp/src/business-apps` (main at `690acdc` or later). Read-only for
  you: clone it into `/var/tmp/cache/T113/biz-clone` exactly as T111 did and grade the clone.
- Modules: every module on `main` when you clone. New since T111 (check and list): `lib/ui/uikit`, `lib/io/posix_listen`,
  `apps/lockers/lkapp/e2e`, and changes to `apps/lockers/lkapp/runtime`, `apps/lockers/lkadp/codeshttp` (new tests,
  testkit now PUBLIC), `apps/lockers/lkrx/{view,fold_status}`, `lib/fmt/httpreq`. `lib/ui/lvrender` is NOT on main yet:
  do not add it.
- LVGL: `lib/ui/uikit` is the first module that depends on `gate//third_party/lvgl:lvgl`. Its policy entry lists it as
  an allowed third-party dep (`third_party = [...]` or the key the gate uses; read the docs), and nothing else may use
  it (architecture: only `lib/ui/uikit` and, later, `lib/ui/lvrender` may depend on LVGL). Levels per
  `docs/design.md` (uikit L2, posix_listen per its row, e2e and runtime per their rows).
- Approvals: grade with `--approvals /var/tmp/cache/T113/approvals` (a read-only copy of the orchestrator's signed
  approvals, staged there; two new ones cover httpreq `fold`). Never write or edit approvals. Report matched, rejected
  and unused approvals.
- Expected ids: add-only from real release+san results, as T111.
- Report the whole-repo grade verdict, every uncovered surviving mutant id at L3/L4 (file:line, mutation), L2
  survivor counts per module (info), and product findings (never edit product code).

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary in the report.

## Rules
As T111, with `TMPDIR=/var/tmp/cache/T113/tmp` and your cache dir `/var/tmp/cache/T113`. Never `rm`; never
`buck2 kill`; kill only your own buck2d by pid; never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs; never search from `/` or `/var/tmp`; never print the
environment; redirect every output to a file and read it, never pipe into `tail`/`head`; one grade at a time; no network.
