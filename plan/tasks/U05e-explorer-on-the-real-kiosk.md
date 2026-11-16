# U05e: make the explorer useful on the real kiosk (cost model, state-scoped taps, layer policy, dismiss, pad, prefix)

Repo `Mivr/c-rigor-gate`, branch `task/U05e`. Read first: `plan/tasks/U00-ui-gate-rules.md`;
`docs/ui-lockers-first-run.md` in full (the measured first run on the real kiosk: "Cost", "Limits", "Triage", "The
changes that would most raise what the machine finds"); `docs/ui-explore.md` in full; `plan/P004-visual-gate.md` 3.4
(`tap-misrouted`, `noop-tap-effect`, the probe point set P(n)), 3.10 and 4.3; `docs/ui-judges.md` (layers, the sealed
`[[input_layer]]` policy, R7 inert, how a judge gets the layer context); `docs/ui-contract.md`;
`gate/rigor_lib/ui_explore*.py`, `gate/rigor_lib/ui_judge_context.py`; `products/business-apps/ui/lockers.events.toml`
(the draft catalogue) and `lockers.toml` (read only).

## Why
The first real exploration ran, but the gate limited itself: the pre-run cost check admits 6 states in 20 minutes
(a bfs of 18 states took 21 minutes of wall time and needed `--budget-s 3200` to be allowed); most of its 160+ tap
errors are false (taps judged without the contract's layer policy; fixed tap points that mean different things on
different screens; no notion of a declared tap-outside dismiss); valid codes cannot be typed through the pad; the
bound is spent on the splash. Each item below is one of those, measured in the doc.

## Do
1. Cost model. Today every `fire-due`, `before-due`, `until-change` and replay `at` word is costed at `max_wait_ms`.
   Replace the estimate with one that cannot under-estimate by construction yet is not absurd: keep the pre-run check
   as a refusal of impossible requests only (say exactly what it bounds), and enforce `--budget-s` at run time on
   measured wall time, ending the exploration cleanly with the existing bound finding (`depth-unsaturated`, reason
   budget) and exit code as for any other bound; a run cut by the budget is never reported as complete. Replay `at`
   words cost min(offset, max_wait). Show old and new admission for the lockers numbers in the doc.
2. State-scoped taps (P004 3.4 / 4.3 U2). A catalogue may declare `[taps] scope = "scene"`: in each state the u2 taps
   are, for every enabled interactive scene node, the centre and the inset 3x3 grid of its rendered box (grid inset
   from the contract's `probe_grid_pct` when a contract is given, else a catalogue value); u3 complement taps are
   derived per state too (a deterministic set of points on non-interactive area, under each scrim, and on each
   disabled control). Deterministic order; word names stable and replayable (e.g. `tap@<key>#<i>`, `blank#<i>`);
   counts bounded per state with an explicit cap and an info finding when capped. Fixed-point u2/u3 rows stay valid.
3. Layer policy in the tap judges. When `--contract` is given, `intent-missed`, `tap-misrouted` and `noop-tap-effect`
   use the same sealed layer context as the ui-scene judge (do not copy the predicate; share it): a tap on a node
   that is inert under a capture-modal-inert layer per R7 expects NO effect (an effect is the finding
   `blocked-target-live`, P004 3.4), and is not `intent-missed`; a tap under a layer whose sealed policy is
   tap-outside-dismisses expects exactly that layer's dismiss intent and nothing else (new outcome `dismissed`;
   anything else is `tap-misrouted` naming both); a tap under a layer the contract says does not block must have the
   same effect as without the layer (`tap-swallowed-first` when it only removes the overlay). Without `--contract`
   behaviour is unchanged.
4. Pad macro: `u4` `via = "pad"` gains an optional `digit_map` (digit -> {intent, arg}) for products whose digit keys
   are one intent per key or carry the digit elsewhere; without it the behaviour is unchanged.
5. `[boot]` in the catalogue: `seeds = [...]` with provenance; `--seed` stays; a new `--boot-seeds catalogue` runs
   the strategy once per declared seed and merges findings (ids unchanged per seed). Optional `prefix` for bfs: a
   declared word list replayed before the search starts (`--prefix NAME` picks a `[[prefix]]` row), so the bound is
   spent on UI states; the prefix is part of every finding's path.
6. Stub modes and unit tests for every item; `selftest/ui.sh` steps (or a new `selftest/ui_taps.sh` called by one
   line, if `ui.sh` would pass 500 lines). Each new check seen failing once with the rule disabled.
7. The real kiosk (the probe is built read-only in `/var/tmp/wt/business-apps/U04a` by
   `gate/tools/buck2 build //apps/lockers/lkapp/uimodel:lockers_ui_probe --show-output`; never edit there): update
   the DRAFT `products/business-apps/ui/lockers.events.toml` to use scene-scoped taps, the digit map, the boot seeds
   and a Welcome prefix (keep it marked unsigned, every row with provenance), re-run a 20-minute bfs and the walk
   with `--judges ui-scene,ui-fit,ui-render` and record in `docs/ui-lockers-first-run.md` a second run table next to
   the first: states, screen classes reached, findings by id, and for each finding class of the first run whether it
   is gone, still there (true), or still false. This is also the first inked run of the real kiosk: triage the
   ui-render findings (true defect / contract gap / gate false positive / unmeasurable) without fixing anything.

## Paths
`gate/rigor_lib/ui_explore*.py`, `gate/rigor_lib/ui_judge_context.py` (only to share the layer context, no behaviour
change for the judges), `gate/rigor_lib/cli.py` (options), `gate/tests/test_ui_explore*.py`,
`gate/tests/test_ui_lockers_catalogue.py`, `gate/tests/data/ui_explore/**`, `selftest/ui.sh`, `selftest/ui_taps.sh`
(new, optional), `docs/ui-explore.md`, `docs/ui-lockers-first-run.md`,
`products/business-apps/ui/lockers.events.toml` (the draft only), `tools/affected.toml` for new files. Another lane
(U24, scene identity) is editing `ui_explore_probe.py`, `ui_explore_grammar.py`, `ui_explore_run.py`,
`ui_explore_strategies.py` for a new `identity` command: keep your changes in those files minimal and localized.

## Acceptance (the orchestrator re-runs)
- `bash selftest/ui.sh` twice in a row, exit 0, tree clean, no process left.
- `python3 -I -B gate/tests/run_parallel.py` at the host baseline (the `ssh-keygen` errors and
  `test_job…test_the_deadline_kills_the_whole_process_group` only).
- `python3 -I tools/affected.py --check`. Files <= 500 lines, functions <= 50 lines.
- One documented real-kiosk command (a short replay or a small bfs) re-run by the orchestrator gives the documented
  exit code and finding ids.

## Report
What changed; real output of each acceptance command; the two run tables; each new check seen failing; every
changed selftest expectation and why; deviations; what you could not do. Never kill a process by name. Scratch,
evidence and `TMPDIR` under `/var/tmp/cache/U05e/`. At most 2 heavy processes at once.
