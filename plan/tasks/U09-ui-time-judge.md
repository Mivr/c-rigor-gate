# U09: the `ui-time` judge (P004 3.5) and the kiosk's screen-class paths

Repo `Mivr/c-rigor-gate`, branch `task/U09`. Read first: `plan/tasks/U00-ui-gate-rules.md`;
`plan/P004-visual-gate.md` 3.5, 3.10 (dwell, reading-time floor, tick), 4.3 (time words), 6.3; `docs/ui-explore.md`
("Paths and time", the time words `fire-due`, `before-due`, `until-change`, `at`, patches and trace per step, the
`life` lines, run-twice, "Cost"); `docs/ui-judges.md`, `docs/ui-judges-render.md`, `docs/ui-judges-identity.md` (how a
judge plugs in: context, findings, exceptions, `checks-examined`, `check-vacuous`, `check-blocked`, canaries, the
honesty table); `docs/ui-contract.md` (`[[timer]]`, dwell, `ui_contract_dwell.py`); `gate/rigor_lib/ui_judge*.py`,
`gate/rigor_lib/ui_explore*.py`; `selftest/ui_canary_product/`; `docs/ui-lockers-first-run.md`;
`/var/tmp/cache/boot/lockers-classes.paths.json` (29 replay paths reaching every screen class of the kiosk, produced
and tested by the product's adapter task).

## Why
The historic defect F1 was a message that vanished before anyone could read it; F6a a countdown shown wrong. Nothing
in the gate judges time: how long a timed element stays, whether its countdown counts, whether an auto-transition is
visible, whether behaviour depends on the absolute clock. The explorer already records, per step, the virtual time,
the patches, the trace and the semantic tree; no judge reads them as a timeline.

## Do
1. A fourth judge name, `ui-time`, in `--judges`. It reads a PATH as a timeline: for each step (t, word, patches,
   trace, semantic, identity when present, `life` lines when frames are taken). It needs `--contract` (timers) and
   judges per path, deterministically; findings keyed by (state key of first appearance, element), replayable.
2. Element lifetime: an element with a contract timer (`[[timer]]`: which kinds exist, their `lifetime_ms`, the
   dwell table of `ui_contract_dwell`) is identified through identity when the probe has it (state class of the
   topmost message, element ids) and otherwise through the scene role of the layer (dialog, snackbar, banner) —
   say exactly which timers can be bound without identity and report the rest as `check-blocked`. To observe a
   lifetime the judge needs the element's appearance and disappearance instants: where the explorer's own words do
   not give them (it jumps to deadlines), add what is needed to the explorer as a time-probing mode used only when
   `ui-time` is selected (for example: after a step in which a timed element appears, a deterministic probing
   sequence `before-due` / `fire-due` / bounded `advance` words that brackets its disappearance to within one tick);
   say its cost and bound it.
3. Checks (P004 ids; implement exactly, or BLOCKED in the honesty table with the missing fact; an approximation gets
   its own id):
   - `notice-lifetime-short`: visible for less than D - tick with no allowed dismiss addressed to it and no declared
     successor (D = the dwell of 3.10: max of the contract lifetime and the reading-time floor; tick from the
     contract or the catalogue, not a literal);
   - `notice-lifetime-long`: still shown after L + tick without input;
   - `flash`: a non-countdown element appears and disappears within the contract's flash threshold with no input
     between and no declared successor, measured on patches (and `life` lines when present), including an element
     created and destroyed within one step;
   - `countdown-wrong`: while a timed element is shown its countdown node (role `countdown`) is present, starts at
     ceil(L/1000) (+-1), changes at least once per virtual second, never shows 0, never increases except by a
     declared ambient restart (U05d) — the oracle-string half is BLOCKED (no oracle);
   - `invisible-auto-transition`: a time step (no input) changes the state class or the abstraction key's
     user-relevant part while semantic and frame are unchanged — define "user-relevant" exactly from what the gate has
     (identity state class; key facts), and BLOCK the O1 half (no view-state stage in the protocol);
   - `dwell-below-reading-time`: static, from the contract and the message catalogue lengths — say what is available
     (the contract's dwell table already computes reading time from displayed text: use the text seen in the run when
     no catalogue is given, and say so);
   - `clock-origin-divergence` (metamorphic): replay the same path with origins {1, 1000, 10^9, 2^32 + 7, 2^40} ms and
     require the same sequence of semantic trees and identities with absolute times masked (countdowns compared as
     values); bounded: applied to a deterministic selection of paths (say which and why) and counted against the
     budget;
   - `unresponsive-intent`: BLOCKED unless the contract marks intents effective per state class; say what the
     contract would need.
4. Canary: timed variants seeded with each implemented defect (a notice that leaves early, one that never leaves, a
   flash inside one step, a countdown that skips / shows 0 / starts wrong, a silent auto-transition, a model whose
   timers use the absolute clock modulo 2^32) and a clean timed state; `selftest/ui_judges.sh` (or a new
   `selftest/ui_time.sh` called by one line) asserts ids, targets, counts. Each check seen failing once against a
   broken judge.
5. The kiosk's class paths: check in `products/business-apps/ui/lockers.classes.paths.json` (a DRAFT, unsigned,
   copied byte for byte from `/var/tmp/cache/boot/lockers-classes.paths.json`, with a sibling `.md` or header note
   of its provenance: business-apps `docs/lockers/ui-model.md` "Reaching every screen class by a path") and a loader
   test that it parses as `ui-explore-paths/1` and that every word is a word of the draft catalogue.
6. Evidence on the real kiosk (not acceptance): build the probe read-only in `/home/user/business-apps`
   (`gate/tools/buck2 build //apps/lockers/lkapp/uimodel:lockers_ui_probe --show-output`; that checkout pins a gate
   without U05e/U09 but with the same probe protocol; never edit there), replay the class paths with
   `--judges ui-scene,ui-fit,ui-render,ui-time` and record in `docs/ui-lockers-first-run.md` a third section: the
   ui-time findings with your triage labelled as your reading (true defect / contract gap / gate false positive /
   blocked), the measured lifetimes per timed element against the contract (a table), and the cost.
7. Docs: `docs/ui-judges-time.md` (rules, what each reads, the probing mode and its bound, the honesty table, the
   break table), links from `docs/ui-judges.md` and `docs/ui-explore.md`.

## Paths
`gate/rigor_lib/ui_judge*.py` (new `ui_judge_time*.py`), `gate/rigor_lib/ui_explore*.py` (the probing mode, the
origin replays, the judge interface; keep changes localized), `gate/rigor_lib/ui_contract*.py` only if a timer table
needs a loader addition (no values in `products/**/lockers.toml`), `gate/rigor_lib/cli.py` (the judge name),
`gate/tests/test_ui_*.py`, `gate/tests/data/ui_explore/**`, `selftest/ui_canary_product/**`, `selftest/ui*.sh`,
`docs/ui-*.md`, `products/business-apps/ui/lockers.classes.paths.json` (+ its note), `tools/affected.toml` for new
files.

## Acceptance (the orchestrator re-runs all of it)
- `bash selftest/ui.sh` twice in a row, exit 0, tree clean, no process left.
- `tools/buck2 test //ui/...` in release and with `--target-platforms toolchains//:linux_san`.
- `python3 -I -B gate/tests/run_parallel.py` at the host baseline (the `ssh-keygen` errors and
  `test_job…test_the_deadline_kills_the_whole_process_group` only); your new tests must pass 10 times in a row while
  the suite runs (no timing-fragile tests: nothing may depend on wall time).
- `python3 -I tools/affected.py --check`. Files <= 500 lines, functions <= 50 lines; C17 rules for the canary.
- One documented real-kiosk replay re-run by the orchestrator gives the documented exit code and finding ids.

## Report
What changed; real output; the honesty table; the kiosk's lifetime table and triage; each check seen failing;
changed expectations with why; deviations; what you could not do. Never kill a process by name; explorer runs under
`--budget-s` and `timeout -s KILL`. Scratch under `/var/tmp/cache/U09/`. At most 2 heavy processes at once.
