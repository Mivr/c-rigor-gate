# T116: refresh `products/business-apps` (fontdata, uikit fonts, lvrender policy, new test ids, test removal, approvals)

Repo: `Mivr/c-rigor-gate`. Branch `task/T116`. Use the same method, rules and four files as T111 and T113. Read
`plan/tasks/T111-business-apps-config-refresh.md` and `plan/tasks/T113-business-apps-config-refresh-2.md` first. The
differences are below.

- **Product.** `Mivr/business-apps`, local clone `/var/tmp/src/business-apps` (main at `068dcbe` or later; gate pointer
  362854e). It is read-only for you: clone it into `/var/tmp/cache/T116/biz-clone` exactly as T111 did, and grade the
  clone.
- **Modules.** Cover every module on `main` when you clone. These are new or changed since T113; check and list them:
  - `lib/ui/fontdata`: a `c_embed` of `LiberationSans-Regular.ttf` plus `LICENSE-OFL.txt`. `product.toml` layout must
    include the `.ttf` and the licence. Give the policy whatever the gate needs for a data-only module.
  - `lib/ui/uikit`: fonts, a new dep on fontdata, and new tests.
  - `lib/ui/lvrender`: give it an LVGL policy if T113 did not. It is the second module allowed to use
    `gate//third_party/lvgl:lvgl`; nothing else may.
  - `apps/lockers/lkrx/{boot,fold_status,catalog,codes,sync,shift,visit,fold_core}`: L267, L269, L271 and L274.
  - `apps/lockers/lkapp/wire`: L266.
- **Not on main yet, do NOT add:** `apps/lockers/lk/preflight`, `apps/lockers/lkapp/posixio`, and the L273 wire tests.
- **Expected ids.** Add-only, taken from real release and san results. One sanctioned removal:
  `visit_outcome/the_rollback_undo_never_says_pending`. The test was renamed in L216, and its signed `test-removal`
  approval is in the staged approvals. Remove that id from `expected-tests.json` by a manual edit, as `docs/grade.md`
  describes.
- **Approvals.** Grade with `--approvals /var/tmp/cache/T116/approvals`. This is a read-only copy of the orchestrator's
  signed approvals: 145 `.json` files, each with its `.json.sig`. Never write or edit approvals. Report matched,
  rejected and unused approvals; with signatures present, none should be rejected as `unsigned`.
- **Mutants.** T115 merged, so the gate now builds `c_mutants` in chunks of 12 with one retry, and the mutants gate
  should complete. Report:
  - every uncovered L3 or L4 survivor id (file:line, mutation);
  - L2 survivor counts per module, as info;
  - any `mutants-build-failed`.
- **Report.** Give the whole-repo grade verdict per gate, and product findings. Never edit product code.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary in the report.

## Rules
- As T111, with `TMPDIR=/var/tmp/cache/T116/tmp` and your cache dir `/var/tmp/cache/T116`.
- Never `rm`; never `buck2 kill`; kill only your own buck2d, by pid. Use `pgrep -f '^buck2d\['` plus a cwd check, never
  `pgrep -f buck2d`.
- Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache
  dirs. Never search from `/` or `/var/tmp`. Never print the environment.
- Redirect every output to a file and read it; never pipe into `tail` or `head`.
- One grade at a time. Use `--deadline 14400`. No network.
