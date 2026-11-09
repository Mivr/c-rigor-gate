# Orchestrator handoff (2026-11-09)

The previous orchestrator session ran out of budget. State of the gate work:

- `main` = `d74f21a` (T117 and T116 merged). No gate lane in flight.
  - T116 MERGED (`d74f21a`): business-apps config refresh 3. Its whole-repo grade (base = head) passes every gate
    except two **product** findings, to be fixed in business-apps, not here:
    1. `semantic-suppressions` `forbidden-builtin`: `apps/lockers/lkapp/wire/src/host.c` (11, 15, 19) and
       `src/watch.c:10` use `__atomic_load_n` / `__atomic_store_n`; `allow_builtins` covers only trap/unreachable/
       debugtrap. Decide: a product change (C11 `<stdatomic.h>` or a mutex) or a gate rule for atomics.
    2. `mutants` `macro-hidden-code` (L3, not approvable): `lkrx/shift` `put_done` (`src/shift.c:79`) uses
       `LK_BOOK_WAS_UNCERTAIN` from `fold_core.h`.
    Also: 406 L2 survivors (info); 26 unused approvals (24 stale equivalent-mutant ids, 2 test-removal); the
    3600 s per-chunk mutants timeout was hit once on a busy farm (the third run took about 2350 s).
  - T117 MERGED (`1830128`): the opt-in `X11` system library and `c_embed(nul = True)`. It also edited
    `gate/rigor_lib/{bin2c,buckfiles,facts_data}.py`, needed but outside its spec's allowed paths (reviewed, no bypass).
- **Next gate task:** business-apps config refresh 4 (T116 is merged; ready): layout, policy and expected tests for the
  business-apps modules merged since T116 started (checkconfig, posixio, lvhost, lkui/input, uiloop, the posix_fs
  split exports, e2eclock at L3), the signed approvals, and the RAM budget for the first kiosk binary. The product side
  keeps its own handoff with the full list.

Rules for gate agents are unchanged (see `AGENTS.md` and any recent `plan/tasks/T11*.md`): TMPDIR in the task cache,
output to files, never `rm`, never the Agent tool, no stash/merge/push, kill only your own buck2d by pid, one build at a
time, no network except Buck2's pinned downloads.
