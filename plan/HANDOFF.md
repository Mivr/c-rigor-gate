# Orchestrator handoff (2026-11-09)

The previous orchestrator session ran out of budget. State of the gate work:

- `main` = `1830128` (T117 merged).
- **In flight** (agents may have stopped; check the branch, relaunch from its spec if incomplete):
  - `task/T116` (worktree `/var/tmp/wt/c-rigor-gate/T116`): business-apps config refresh 3 (`products/business-apps/**`
    only). It started before business-apps merged posixio, checkconfig, the wire K1-K3 change and the notices keys, so
    it does not cover them. Validate per `plan/tasks/T116-business-apps-config-refresh-3.md`, re-run its acceptance,
    merge.
  - T117 is MERGED (`1830128`): the opt-in `X11` system library and `c_embed(nul = True)`, verified by an orchestrator
    re-run of the full acceptance. It also edited `gate/rigor_lib/{bin2c,buckfiles,facts_data}.py`, needed but not in
    its spec's allowed paths (reviewed, no bypass).
- **Next gate task:** business-apps config refresh 4, after T116: layout, policy and expected tests for the
  business-apps modules merged since T116 started (checkconfig, posixio, lvhost, lkui/input, uiloop, the posix_fs
  split exports, e2eclock at L3), the signed approvals, and the RAM budget for the first kiosk binary. The product side
  keeps its own handoff with the full list.

Rules for gate agents are unchanged (see `AGENTS.md` and any recent `plan/tasks/T11*.md`): TMPDIR in the task cache,
output to files, never `rm`, never the Agent tool, no stash/merge/push, kill only your own buck2d by pid, one build at a
time, no network except Buck2's pinned downloads.
