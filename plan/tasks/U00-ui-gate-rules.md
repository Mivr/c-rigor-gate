# U-series: the UI gate (P004), common rules for every U task

The U tasks implement `plan/P004-visual-gate.md`. `U<NN>` is P004 §9's `T1xx.<NN>`. T1xx.01 is done:
`plan/metrics/ui-probe-2026-11-13.md` (read its sections 1, 3 and 8 before any U task; its numbers override P004's
estimates). The orchestrator of the U series is a cloud session; its integration branch is `claude/sharp-tesla-joqj8k`,
not `main`.

## Layout fixed for the whole series (do not invent another)
- Gate C code: `ui/lvprobe/` (target `gate//ui/lvprobe:lvprobe`), `ui/model/` (`gate//ui/model:model`, the header
  `ui/model/model.h` and the probe main). One `BUCK` per directory. Macros in `rules/ui.bzl`.
- Gate Python: `gate/rigor_lib/ui_*.py`, tests `gate/tests/test_ui_*.py`. Stdlib only.
- Selftest: `selftest/ui.sh` and its product tree `selftest/ui_product/`. Docs: `docs/ui-<topic>.md`, one per task.
- Gate headers must not use product types. `core_buf_t` in P004's sketch is a product type: use a gate-owned
  `(char *buf, size_t cap, size_t *len)` triple or a gate struct.
- Gate C follows the product C rules of `AGENTS.md` (C17 through `gate//rules`, static memory, no recursion, functions
  <= 50 lines, files <= 500 lines, every return value checked). LVGL is `gate//third_party/lvgl`.

## This machine (development profile, `docs/toolchain.md` "Local execution")
- There is no farm here. Your worktree already has `.buckconfig.local` and `tools/buck2.local`; do not edit, print the
  need for, or commit them. Every action runs on this 4-CPU host: build only the targets you need, one build at a
  time, and never `//...`.
- `ssh-keygen` is not installed: about 149 signing tests of `gate/tests` error with `FileNotFoundError: 'ssh-keygen'`.
  That is the baseline, not your bug. Report the count before and after your change; anything else must pass.
- The first build in a fresh worktree downloads the toolchain (about 4 minutes). Use `tools/job` for it.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/U<NN>` (given in your prompt). `TMPDIR=/var/tmp/cache/U<NN>/tmp`; never `/tmp`.
Long runs via `tools/job`. Redirect every output to a file and read it by range. Never `rm` outside your cache
directory. No stash, merge, rebase or push. **Never use the Agent tool.** Never read other worktrees, other cache
directories, `/var/tmp/cache/boot*`, `~/.ssh` or any `*-hidden` repo; you may read `/home/user/business-apps` and
`/home/user/club-apps` (read only) where the task says so. Do not print the environment. Kill only your own buck2d by
pid. No network except Buck2's pinned downloads. No installs. Never weaken, skip or special-case a check; if a check
is wrong say so in the report. Never end your turn while a job you started is running. Commit on `task/U<NN>` with
clear messages. Your last message is the report: what works, the exact commands and their real output (trimmed), what
does not work, every deviation from the contract, and anything you could not do. An honest "blocked" is fine; "done"
for something not done is the worst outcome. If you are 45 minutes in without a passing acceptance step, stop and
report.
