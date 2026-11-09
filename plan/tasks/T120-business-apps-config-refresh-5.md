# T120: refresh `products/business-apps` (refresh 5: uiloop, shell_linux, version, the kiosk RAM budget) and the whole-repo grade

Repo: `Mivr/c-rigor-gate`. Branch `task/T120` from main (T119 merged). Same method, rules and four files as T116/T119:
read `plan/tasks/T119-business-apps-config-refresh-4.md` and its merge commit message first. The differences:

- **Product.** `/var/tmp/src/business-apps` main at the L315 merge or later (clone it into `/var/tmp/cache/T120/biz-clone`
  exactly as T119 did; initialise the gate submodule as T119 had to). Cover every module on main and list them.
  New or changed since T119's clone (`46a1c75`):
  - `apps/lockers/lkapp/uiloop` (L2; its BUCK carries a long dep closure; give it exactly what its facts need,
    `third_party = [lvgl]` only if its facts show direct LVGL symbols).
  - `apps/lockers/lkapp/shell_linux`: library `x11` (L1, `system_libs = ["X11"]`, `allow` = the X symbols its facts
    show), library `shell` (L1, `allow_mutable_data = true` for its one static object, `deny_exempt = ["getenv"]` per
    business-apps P290 D10, `allow` for poll/read/write/stat/pthread_sigmask/signalfd/clock_gettime/... exactly as the
    facts show), binaries `lockers` and `lockers_e2e` (L1). `apps/lockers/lkapp/version` (L1, header-only).
  - Changed exports/rules: `lib/ui/lvhost` (`lvh_cfg_t`, kit accessors), `lib/ui/scene` (`scene_snap_view_t`),
    `lib/ui/lvrender` + `lib/ui/uikit` (notice rows, fixed card: `kit_notice_add_row`, `_row_count`, `_row`,
    `_remove_row`, `_set_fixed`, `_is_fixed`), `uiloop` (`uil_redraw`), `codeshttp`/`synchttp` (`plain` port),
    `wire`/`posixio`/`checkconfig` (plain ports), `synchttp` (macros gone), `lib/ui/scene` survivors (L315).
  - **`apps/lockers/lkadp/e2eclock` back to L2** (orchestrator ruling, 2026-11-09): it is an e2e-only decorator around a
    wall port of the same type, so `indirect-cycle-possible` cannot be removed structurally; at L2 it is info. Note the
    reason in a policy comment.
  - **RAM budget** (business-apps decision D15, owner 2026-11-09): a `ram-budget` entry for `lockers` and `lockers_e2e`
    with a ceiling of 30 MB (31457280 bytes) each; report the measured static size of each binary.
- **Expected ids.** Add-only with `gate/tools/expected.py add` from real release+san results. Report any id that
  disappeared (renamed tests); remove one only with a signed `test-removal` approval in the staged approvals.
- **Approvals.** Grade with `--approvals /var/tmp/cache/T120/approvals` (read-only copy, as T119). Never write or edit
  approvals.
- **Grade.** Run the whole-repo grade ONCE with `--deadline 28800`. The farm is otherwise idle for this lane. If a
  mutants chunk still times out, report the chunk, its targets and its wall time; do not loop.
- **Report.** The verdict per gate; every uncovered L3/L4 survivor with its mutant **id**, file:line and mutation (the
  orchestrator signs equivalents from this list; known candidates: synchttp `collect.c:13`, `snap.c:57`,
  `step.c:15/19/27`, and any L315 lists); L2 survivor counts per module; approvals matched/rejected/unused; every
  product finding of the other gates. Never edit product code.

## Allowed paths
`products/business-apps/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py` and `selftest/product_checks.sh` green, plus the grade summary.

## Rules
As T119 (worktree `/var/tmp/wt/c-rigor-gate/T120`, `TMPDIR=/var/tmp/cache/T120/tmp`, cache `/var/tmp/cache/T120`,
long runs via `tools/job`, never `rm`, kill only your own buck2d by pid with a cwd check, never read `/var/tmp/.config`,
`/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs (you MAY read
`/var/tmp/src/business-apps` only to clone it), never search from `/` or `/var/tmp`, never print the environment, never
the Agent tool, no stash/merge/push, redirect output to files and never pipe into tail/head, no network except Buck2's
pinned downloads). Commit on `task/T120`; your last message is the report.
