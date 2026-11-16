# U07: the `ui-render` judge (P004 3.3) on the facts the probe already gives

Repo `Mivr/c-rigor-gate`, branch `task/U07`. Read first: `plan/tasks/U00-ui-gate-rules.md`; `plan/P004-visual-gate.md`
3.0, 3.3, 3.10, 6.3, 6.4; `docs/ui-judges.md` in full (the association, findings, pending values, exceptions, the
honesty table, canaries); `docs/ui-lvprobe.md` ("What the facts mean", "Definitions", "Text format", "Limits");
`docs/ui-model.md` (the `ink` and `crop` commands, statuses); `docs/ui-contract.md`; `gate/rigor_lib/ui_judge_*.py`;
`gate/rigor_lib/ui_explore_probe.py` (`ink`, `crop`), `ui_explore_run.py`, `ui_explore_strategies.py`;
`selftest/ui_judges.sh`, `selftest/ui_canary_product/`; `gate/tests/test_ui_judge_lockers.py` and the real frames it
reads.

## Why
`ui-scene` and `ui-fit` judge the scene and the rendered tree. Nothing yet judges what is painted: a node that paints
no pixel, text with too little contrast, a rendered flag that disagrees with the scene, a font that is not the sealed
one. The probe already measures ink (`ink`: pixel count, ink box, ink and background luminance bounds per node) and
gives pixels (`crop`) and the frame checksum; no judge reads them.

## Do
1. A third judge name, `ui-render`, in `rigor ui-explore --judges` (same rules: needs `--contract`, `--today`,
   `frame-facts`; additionally the `ink` capability, and `crop` for the checks that read pixels; without them exit 2).
   When `ui-render` is selected the explorer takes `ink` for each NEW abstract state's frame (once per state key, not
   per step) and the judge reads it. State the cost measured on the canary (refreshes, time) in the doc. `noink
   unstable` / `noink transformed` is data: a finding `ink-unmeasurable` (info), never a silent pass, and it counts
   against `check-vacuous` as U06 does for unmeasurable fits.
2. Checks. Use P004's ids. For each: implement it exactly, or mark it BLOCKED in the honesty table with the precise
   missing fact (which record or field, which model.h or lvprobe addition, which contract table). Do not approximate a
   check under its P004 name; an approximation gets its own id and an honest row.
   - `invisible-node`: a scene node that must paint (non-empty text; a button or key; a card; a panel whose contract
     style has a tone) whose associated rendered node has ink count 0. Hidden nodes and nodes the scene flags hidden are
     out of scope.
   - `contrast-low`: from the ink record's luminance bounds of ink and background under a text node: worst-case
     contrast ratio (WCAG relative luminance formula; say exactly how the bounds are combined and why it is the
     conservative side) below the contract threshold (4.5:1; 3:1 for large text; the thresholds and the large-text
     definition come from the sealed contract; if the contract lacks them the check is `contract-pending`, you do not
     write values into `products/**`).
   - `flag-mismatch`: rendered `clickable` / `hidden` / long mode against the scene: intent <-> clickable, inert or
     disabled <-> not clickable (note: the real kiosk clears clickable on disabled controls; that agrees), scene wrap
     policy <-> the label's long mode via `[[wrap]]`. Say what U06's stage findings already cover and do not duplicate
     an id.
   - `font-size-mismatch`, `align-mismatch`: the label's font id / line height and `align` / `align_drawn` against the
     sealed tables (`[[style]]`, `[[style_line]]`, `[[role]]`); exact. If a needed column is not in the contract,
     `contract-incomplete` naming it.
   - `covered-node`: decide from lvprobe's definition of ink (docs/ui-lvprobe.md) whether "share of a node's ink
     overwritten by a later object" is computable from the `ink` record alone. If not, BLOCKED with the lvprobe fact
     needed (e.g. solo ink count).
   - `glyph-run-gap`: via `crop` of a numeric text node's ink box (column projection; gap in em from the label's line
     height); or BLOCKED with the reason.
   - `legibility-floor`: needs x-height and the sealed viewing distance; implement if both are available, else BLOCKED.
   - `diff-render-divergence`: two fresh renders differing is the explorer's run-twice; the diff-path-versus-fresh
     half needs a model call that forces a full re-render. Expected: BLOCKED with the proposed model.h entry. Do not
     add the entry.
   - `render-geometry-mismatch`, `render-text-mismatch`, `a11y-stage-mismatch`: map each to the U06 stage finding that
     already is this check, or say what is missing (msgid and arguments are not in the scene).
3. Findings follow `ui_judge_findings` (ids, evidence, exceptions with expiry, `exception-unused`, `checks-examined`,
   `check-vacuous`). Targets are keyed through the scene, never by walk index.
4. Canary: extend `selftest/ui_canary_product/` with seeded defects so every implemented check id fires exactly where
   seeded and nowhere else, and a clean state where none fires; `selftest/ui_judges.sh` asserts ids, targets and
   counts. Every check must be seen failing once against a deliberately broken judge (table in the doc, as U06).
5. The real kiosk: add the 23 real frames' render findings to `gate/tests/test_ui_judge_lockers.py` ONLY for what the
   recorded transcripts contain. If the recorded frames have no ink records, say so; do not invent them and do not
   edit anything under `/home/user/business-apps` (read only). The first real run with ink belongs to the catalogue
   task.
6. Housekeeping from the U06 review (same files): define `LAYER_ROLES` once (in `ui_judge_contract`, imported by
   `ui_judge_vocab`); the input-layer naming rule accepts only names a judge reads, or `docs/ui-contract.md` says
   which accepted names are not judged (pick the stricter one that keeps `products/business-apps/ui/lockers.toml`
   loading; if it would not load, report, do not edit the file); the unknown-record test matches its message
   (`assertRaisesRegex`); an end-to-end exit-2 case for a bad `[[input_layer]]` name in `selftest/ui_judges.sh`; the
   session log name in `ui_judges.sh` deterministic (per platform, not `$RANDOM`).
7. `docs/ui-judges.md` (or a new `docs/ui-judges-render.md` linked from it if the file would pass 500 lines): the
   checks, what each reads, the honesty table rows, measured cost, canaries, deviations.

## Paths
`gate/rigor_lib/ui_judge*.py` (new `ui_judge_render*.py`), `gate/rigor_lib/ui_explore.py`, `ui_explore_run.py`,
`ui_explore_strategies.py`, `ui_explore_probe.py` (only what collecting ink per new state needs; another lane is
editing `ui_explore_words.py`, `ui_explore_catalogue.py`, `ui_explore_judges.py`: avoid them, and if you must touch
one keep the change minimal and say so), `gate/rigor_lib/cli.py` (the judge name only), `gate/tests/test_ui_judge*.py`,
`selftest/ui_canary_product/**`, `selftest/ui_judges.sh`, `docs/ui-judges*.md`, `docs/ui-contract.md`,
`tools/affected.toml` only for a new file no rule matches. Nothing under `products/`, `ui/`, `rules/`.

## Acceptance (the orchestrator re-runs all of it)
- `bash selftest/ui.sh` twice in a row, exit 0, tree clean after, no process left.
- `tools/buck2 test //ui/lvprobe/...` in release and with `--target-platforms toolchains//:linux_san`.
- `python3 -I -B gate/tests/run_parallel.py`: only the host baseline (the `ssh-keygen` errors and
  `test_job…test_the_deadline_kills_the_whole_process_group`).
- `python3 -I tools/affected.py --check`.
- Files <= 500 lines, functions <= 50 lines in touched Python; C17 rules for the canary.

## Report
What changed; real output of each acceptance command; the honesty table (implemented / approximated under its own id /
blocked, with the missing fact); how each check was seen failing; every deviation; what you could not do. Never kill
a process by name. Scratch under `/var/tmp/cache/U07/`.
