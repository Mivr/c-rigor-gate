# The `ui-render` judge (U07, P004 3.3)

**What it finds today.** On the canary every implemented check fires exactly where it is seeded. On the 23 recorded
frames of the real lockers kiosk the stage checks (`flag-mismatch`, `align-mismatch`, `line-height-mismatch`) find
nothing (760, 350 and 350 verdicts). The ink checks reach no verdict there: **the recorded transcript has no `ink`
records** (the session that recorded it never sent `ink`). The first real run with ink belongs to the catalogue task.

The third judge of `rigor ui-explore` (docs/ui-explore.md), after `ui-scene` and `ui-fit` (docs/ui-judges.md, whose
sections on the association, findings, pending values, exceptions, `checks-examined` and `check-vacuous` apply here
unchanged). It judges what is painted: a node that paints no pixel, text with too little contrast, rendered flags,
long mode, alignment and line height that disagree with the scene or the sealed tables. Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_render.py` | the judge; the ink checks `invisible-node`, `contrast-low`, `ink-unmeasurable` |
| `ui_judge_render_ink.py` | the `ink`/`noink` records (their format is the gate's), the WCAG arithmetic |
| `ui_judge_render_stage.py` | the L3 checks on O2 + O3 without ink: `flag-mismatch`, `align-mismatch`, `line-height-mismatch` |

```
rigor ui-explore ... --judges ui-scene,ui-fit,ui-render --contract FILE.toml --today YYYY-MM-DD
```

`ui-render` has the rules of the other two (`--contract`, `--today`, a probe that announces `frame-facts`) and needs a
probe that announces `ink`; without it exit 2 (`--judges ui-render needs a probe that announces ink`). No implemented
check reads pixels (`glyph-run-gap`, the one that would, is blocked below), so `crop` is not required. Alone,
`ui-render` owns the stage findings (`stage-unmatched`, ...): they belong to the first selected judge in the order
ui-scene, ui-fit, ui-render.

## Ink per new state (the explorer)

When `ui-render` is selected the explorer takes `ink` (every node of the frame) once per abstraction key: at the first
step of the exploration whose key no inked step had (`ui_explore_run.InkPlan`, shared by every path), right after the
step's observation. The second run of the same path inks exactly the steps the first inked, and run-twice compares the
`ink` part too (an ink that differs between the runs is `run-twice-mismatch`). After the ink the explorer takes `frame`
again: an ink whose retry settle flushed drops the probe's frame (docs/ui-model.md, "Statuses") and the next word may
need one. If that frame (without `life` and `taps` lines) differs from the step's, the step's `ink_moved` is set and
the judge reads none of its ink: every node a check needs is `ink-unmeasurable` with reason `frame-moved`. A later visit
of an inked key carries no ink, so no ink check runs on it (its verdicts are those of the first visit:
`checks-examined` keeps per state the largest count of a key's visits). An `ink` error ends the run in a pseudo step
`ink`, as an evidence error does.

**Cost measured on the canary** (33 states, replay of `canary.paths.json`, this 4-CPU host, three runs each):
`--judges ui-scene,ui-fit` 0.93 to 1.02 s, 1042 probe commands; `--judges ui-scene,ui-fit,ui-render` 1.07 to 1.26 s,
1174 commands (+132: one `ink` and one `frame` per state and run, 33 states x 2 runs). The 33 states have 341 non-root
nodes (10.3 per state); lvprobe refreshes twice per node it inks, so about 682 refreshes per run of all paths, 1364 with
run-twice, at 320x240. The real kiosk (1280x800, about 34 nodes per frame) was not measured: no ink was taken there.

## The checks

Every check keys its target by the scene key (never by walk index); identities are `[key]` or `[key, part]`.

| Check | Layer | Reads | Contract |
|---|---|---|---|
| `invisible-node` | L4 | O2 + O3 + ink | none |
| `contrast-low` | L4 | O2 + O3 + ink | `thresholds.contrast_large`, `thresholds.contrast_text` |
| `ink-unmeasurable` (info) | L4 | ink | none |
| `flag-mismatch` | L3 | O2 + O3 | the wrap scope (`[[element]]`, `[[role_wrap]]`, `[[wrap]]`) |
| `align-mismatch` | L3 | O2 + O3 (`label` `align_drawn`, `fit`) | `[[role]]` `align`, `align_banner` |
| `line-height-mismatch` | L3 | O2 + O3 (`label` `line_h`) | `[[style_line]]` (a product baseline) |

- **`invisible-node`**. A shown scene node that must paint: a `text` or `countdown` with a non-empty label, a `button`
  or `key`, a card (`dialog`, `banner`, `snackbar`), whose associated rendered node is shown, has a visible box, and has
  ink count 0 (hiding it changes no pixel). Excluded: scene-hidden nodes (`H`) and rendered-hidden ones (those are
  `flag-mismatch`'s when the two disagree); a node whose whole visible box lies inside a later-painted, unrelated, shown
  node with an exact background opacity of 255 (it is covered, so no pixel of it can change; covered text is
  `covered-node`'s, which is blocked); a panel (no contract table gives a panel a tone, below).
- **`contrast-low`** (part `below-large`). For a shown text-bearing node with a typographic role and a non-empty drawn
  text, the ink of the label that carries its text (the label itself, or a button's or key's label child). How the
  bounds are combined: lvprobe gives two ink extremes (`ink_lo`, `ink_hi`: the darkest and lightest pixel drawn WITH the
  node) and two background extremes (`bg_lo`, `bg_hi`: the same pixels WITHOUT it), as colours. Each is turned into
  WCAG relative luminance (sRGB channels linearised with the 0.03928 knee; 0.2126 R + 0.7152 G + 0.0722 B); the ratio is
  `(L1 + 0.05) / (L2 + 0.05)`. The contrast of the node is the MAX over the two ink extremes of the MIN over the
  background interval `[min(L(bg_lo), L(bg_hi)), max(...)]` (an ink extreme inside the interval gives 1:1, outside it
  the nearest end counts). Why this is the conservative side: the background side is the worst case, since any
  background luminance between the two measured extremes may lie behind some glyph, the nearest one is assumed. The
  ink side cannot be the worst case: an antialiased glyph always has edge pixels that are blends of the text colour
  with what is behind it, so the min over all four extremes is about 1:1 for every text (measured on the clean canary:
  1.03 to 1.21 for every label, against 8.6 to 16.1 by this rule); the text colour is the ink extreme farther from the
  background. A finding thus says that even the strongest pixel the text drew is too close to some background pixel.
  Thresholds: below `contrast_large` (3:1 in the canary) the text fails at any size: a finding. At or above
  `contrast_text` (4.5:1) it passes. In between the verdict needs the definition of large text (WCAG: 24 px, or
  18.66 px bold), which the contract does not have (no entry or table of docs/ui-contract.md defines it, and adding one
  is the owner's): the node is no verdict and its typographic role is `contract-incomplete` (`["large-text", role]`,
  once per run). While either threshold is pending (lockers: q15), `contract-pending` and no verdict. A node whose ink
  count is 0 is no contrast verdict (`invisible-node`'s, or covered).
- **`ink-unmeasurable`** (info). A node one of the two ink checks needs (the node itself for `invisible-node`, its text
  carrier for `contrast-low`) whose record is `noink unstable` or `noink transformed`, or every needed node of a step
  whose frame moved under the ink: one finding per scene node, `observed.unmeasured` lists `[what, reason]` (`what`
  `node` or `text`). That node is no verdict of the check that needed it, so a state where nothing could be measured
  makes `invisible-node` and `contrast-low` `check-vacuous` (as U06's `fit-unmeasurable`); each needed record is a
  verdict of `ink-unmeasurable` itself.
- **`flag-mismatch`** (L3). Per associated scene node: scene `H` but rendered shown (part `shown`), no `H` but rendered
  not shown (`hidden`, the node or an ancestor hidden in LVGL). For a node shown on both sides whose rendered node is
  clickable: disabled in the scene (`enabled` 0 or `D`) is `disabled-clickable` (the real kiosk clears clickable on its
  disabled buttons, which agrees); `I` is `inert-clickable`; no intent is `clickable`, except a layer role (scrim,
  dialog, banner, snackbar): whether a layer's clickable scrim or card takes taps it should not is ui-scene's
  `overlay-policy` (sealed and rendered halves), and a card is clickable by design so that a tap on it does not reach
  its scrim. Per text carrier with a wrap scope: the label's long mode against the mode the scope needs (`long-mode`):
  an ellipsis scope needs DOTS, a clip scope CLIP, every other scope WRAP (a `none` scope included: LVGL has no
  non-wrapping long mode that does not cut the text; a single line that does not fit is ui-fit's `text-overflow`).
  The other direction of P004's "intent <-> clickable", an intent whose rendered node is not clickable, is already
  ui-scene's `stage-unmatched`: the association pairs a node with an intent only with a clickable object, so that node
  is unmatched (`absent` or `ambiguous`); no second id.
- **`align-mismatch`** (L3). Per text carrier that lvprobe drew (a `fit` record, drawn, not unsupported: without a draw
  task there is no drawn alignment): `align_drawn` (LVGL's resolved alignment: 1 left, 2 centre) against the `[[role]]`
  `align` of the node's typographic role, or `align_banner` when the carrier lies inside the rendered node of a scene
  `banner` and the role has one. Exact.
- **`line-height-mismatch`** (L3, part `above`). Per owned text carrier: the label's line height ABOVE the
  `[[style_line]]` line height of the owner's style (a regression baseline read from the product,
  `product-baseline:<commit>`; the finding carries `basis`). Below it is ui-fit's `font-shrunk` (one cause, one
  finding). A style without a row is `contract-incomplete` (`style-line`).

## Findings

Schema, ids, `observed` and evidence as docs/ui-judges.md ("Findings"); `gate` is `ui-render`. Layer L3 for
`flag-mismatch`, `align-mismatch` and `line-height-mismatch`, L4 for the ink checks. All are errors but
`ink-unmeasurable` (info: data, never a silent pass). `checks-examined` lists the six checks; `check-vacuous` applies to
each of them when `[[role]]` has a row (the default rule of docs/ui-judges.md). An exception may name `invisible-node`,
`contrast-low`, `flag-mismatch` or `align-mismatch` (they are in the loader's closed list `EXCEPTION_RULES`);
`line-height-mismatch` and `ink-unmeasurable` are not in that list and `gate/rigor_lib/ui_contract.py` is outside this
task's paths, so no exception can name them yet (deviation below).

## Honesty table (P004 3.3)

| Check | Status | Why / what is missing |
|---|---|---|
| `invisible-node` | implemented (text, button, key, card) | panels are not judged: P004 says "a panel with a non-NONE tone", and no contract table maps a panel's style token to a tone (`[[style]]` rows are typographic; panel tones and card kinds are not read, docs/ui-judges.md). Needs a sealed `[[panel_tone]]` table (token -> tone). A fully covered node is skipped, not called invisible (that is `covered-node`, blocked). Corner radii are not in the facts: a cover with a radius is taken as covering its whole box (false negatives at its corners) |
| `contrast-low` | implemented in part: the large-text floor exactly (`contrast_large`); the text threshold is blocked | the definition of large text (P004 3.10: "3:1 for large text"; WCAG 24 px or 18.66 px bold) is not in the contract schema: needs a sealed entry, e.g. `[thresholds] large_text_px` and `large_text_bold_px` with the weight that is bold, in `ui_contract.py` and the owner's contract. Between 3:1 and 4.5:1 the node is `contract-incomplete` `large-text`. lvprobe chooses the extremes by luma over the encoded channels, not by relative luminance: for pixels of different hues the two orders can disagree, so another pixel could be darker or lighter in luminance than the reported ones (exact for one-colour text on a one-colour background, as on the canary and the kiosk). The state-indicator half ("a state indicator (selection, pressed) < 3:1 against adjacent colours") is blocked: neither the scene nor lvprobe says which pixels are a state indicator and which are adjacent; needs the indicator part per node (model.h) or a contract table of indicator styles |
| `flag-mismatch` | implemented: hidden, clickable (disabled, inert, no intent), long mode | the opacity half ("opacity disagrees with the scene's flags"): the scene has no opacity or visibility-level field (model.h's 14 fields); the intent -> not clickable half is ui-scene's `stage-unmatched` (above); clickable layers are `overlay-policy`'s |
| `align-mismatch` | implemented, exact | judged on drawn labels only (a label lvprobe did not dry-draw has no draw-task alignment) |
| `font-size-mismatch` | **blocked**; approximated as `line-height-mismatch` (own id) | P004: "the label's resolved font id/size != the sealed style->font table entry". (1) lvprobe can map fonts (`lvprobe_map_font`) but the probe maps none, so every `label` record says `-` for the font id: needs a model.h entry through which the product names its fonts, e.g. `bool uim_fonts(const lv_font_t **fonts, uint16_t *ids, uint16_t cap, uint16_t *count)`, called by the probe before the first walk; (2) a sealed contract column naming each style's font id (`[[style]] font`, owner's). The line height is not the font size (two fonts of one line height pass), hence its own id |
| `line-height-mismatch` | implemented (approximation of `font-size-mismatch`) | against a product baseline, not a spec value; `font-shrunk` owns the smaller side |
| `covered-node` | **blocked** | "share of a node's ink overwritten by a later object" is not computable from the `ink` record: lvprobe's ink is the set of pixels that change when the node is hidden in the FINAL frame, so a pixel a later object overwrote never changes and is simply absent; the record has no denominator. Needs a lvprobe fact: the node's solo ink count (the pixels that change when it is hidden with every later-painted, unrelated node hidden too), e.g. a 9th `ink` field `solo`; the share covered is then `1 - count / solo`, and the threshold ([P] 50%) a sealed contract entry |
| `glyph-run-gap` | **blocked** | (1) the threshold ([P] 0.5 em) is not in the contract (`[thresholds]` has no glyph-gap entry; P004 marks it [P]); (2) an em needs the font size, which the frame facts do not give (only the line height; font ids are unmapped, see `font-size-mismatch`); (3) a "numeric value run" needs the value's extent in the scene (the msgid and arguments, two semantic fields, model.h; docs/ui-judges.md `value-split`). With those, `crop` of the carrier's ink box and a column projection give the gaps |
| `legibility-floor` | **blocked** | needs (1) the rendered x-height per label (a lvprobe `label` field, e.g. the box height of the glyph `x` from `lv_font_get_glyph_dsc`; LVGL fonts carry no x-height), and (2) the ppi and the sealed farthest viewing distance (`panel.diagonal_in`, `panel.viewing_distance_mm`: pending q9 in lockers; the canary has them). The "primary content larger by the contract ratio" half needs the importance table (pending q7 in lockers) |
| `diff-render-divergence` | **blocked** | "two fresh renders differ" is the explorer's run-twice (every path in two fresh probes; `frame` with its CRC is compared). The diff-path-versus-fresh half needs a model call that forces a full re-render of the current scene, proposed (NOT added): `bool uim_rebuild(uim_t *m)` in model.h, "drop every LVGL object of the scene and build the current scene from scratch, as `uim_open` would, keeping the model state", and a probe command `rebuild`; the gate then compares the frame CRC (and region hashes) after `rebuild` with the one before |
| `render-geometry-mismatch` | = ui-scene's `stage-unmatched` | the association is by exact rect (tolerance 0): a node whose rendered box is not its scene rect is `stage-unmatched` (`absent`, or `ambiguous`), with the drawn candidates (and `stage-unowned-target` for a drawn control the scene does not have); the owner-sealed exception list is `[[exception]]` with rule `stage-unmatched`. Not separable: a node drawn elsewhere and a node not drawn are both `absent` |
| `render-text-mismatch` | partly = ui-scene's `stage-text-mismatch` | U06 compares the drawn text with the scene's formatted label; `i18n_format(msgid, args, lang)` needs the msgid and the arguments of each text node, which the scene does not have (two semantic fields, model.h), so a product that formats wrongly AND reports the wrong string in its scene is not caught |
| `a11y-stage-mismatch` | partly covered | label: `stage-text-mismatch`; rect: the association (`stage-unmatched`); role: the association's compatibility (a button or key needs an `lv_button`, text a label, a card a drawn background) makes a wrong one `ambiguous`; `selected`: blocked (the scene's `X` is not emitted by the real adapter, and lvprobe's `node` record has no checked state: needs `LV_STATE_CHECKED` as a `node` field) |

## The real kiosk (`gate/tests/test_ui_judge_lockers.py`, `LockersRenderTest`)

`ui-render` alone over the 23 recorded frames with `products/business-apps/ui/lockers.toml`: per frame exactly the stage
findings of docs/ui-judges.md (now under `ui-render`, the only selected judge) and nothing else; verdicts
`flag-mismatch` 760, `align-mismatch` 350 (the notice texts inside banners are drawn left, as `align_banner` says, and
centred in dialogs), `line-height-mismatch` 350; `invisible-node`, `contrast-low` and `ink-unmeasurable` 0, so all three
are `check-vacuous` (error), because the transcript has no `ink` or `noink` line (the test checks that too). Nothing was
invented and nothing under business-apps was touched. Seen by a reader: the kiosk's disabled buttons (`enabled` 0, `D`)
are not clickable, its banner, dialog and snackbar cards are clickable without an intent (layers: not a mismatch), and
its scrims are clickable (overlay-policy's).

## Canaries (`selftest/ui_canary_product/`)

U07 adds nine variants (intents 24 to 32), each with its own title; the canary now draws every label with centred text
(every role of `canary.toml` is `centre`, and the loader allows only notice roles to be left-aligned) and the OK, Back
and Close buttons in `0x0D47A1` (white text on it 8.6:1; LVGL's default `0x2196F3` gives 3.1:1, which would be a
`contract-incomplete` `large-text` in the clean state). `session.out` was regenerated for that (colours, alignment,
glyph boxes and checksums only).

| Event | Defect | Finding (identity) |
|---|---|---|
| `v-invisible` | the body text drawn with text opacity 0 | `invisible-node` (`["body"]`) |
| `v-contrast` | the body text `#bbbbbb` on white (1.92:1) | `contrast-low` (`["body", "below-large"]`) |
| `v-disabled` | Back disabled in the scene (`enabled` 0, `D`), clickable in LVGL | `flag-mismatch` (`["back", "disabled-clickable"]`) |
| `v-click` | the body label clickable, no intent | `flag-mismatch` (`["body", "clickable"]`) |
| `v-hidden` | the body label hidden in LVGL, shown in the scene | `flag-mismatch` (`["body", "hidden"]`) |
| `v-long` | the body label in CLIP mode, its scope `default` wraps | `flag-mismatch` (`["body", "long-mode"]`) |
| `v-align` | the body text left-aligned, its role centred | `align-mismatch` (`["body"]`) |
| `v-line` | the body text in a font with a 20 px line (baseline 16) | `line-height-mismatch` (`["body"]`) |
| `v-noink` | the OK button scaled by 257/256 (a transform) | `ink-unmeasurable` (`["ok"]`, info) |
| `v-dots` (U06) | the body label in DOTS mode | besides ui-fit's `full-string-shown`: `flag-mismatch` (`["body", "long-mode"]`) |

`selftest/ui_judges.sh` now runs the three judges together on all 33 states and asserts per variant exactly the
findings of both tables (docs/ui-judges.md and this one), the recomputed ids, the parts, nothing in the clean state nor
under `v-modal`, three `checks-examined` with every check above 0, no `check-vacuous`, every finding an error but
`ink-unmeasurable`, the summary counts (`ui-render.flag-mismatch` 5), byte-identical findings and evidence twice in
release and release equal to san, every one of the 35 findings replayed to its id, a live exception of a ui-render
check (`x-invisible`), and exit 2 for a contract whose `[[input_layer]]` row is misnamed (`bnner`). Its log names are
deterministic (per step and output variable, per platform), no longer `$RANDOM`.

## Each check seen failing against a broken judge

Each break was applied to the code, `gate/tests/test_ui_judge_render.py`, `test_ui_judge_lockers.py` and
`test_ui_judge_stage.py` were run (failures as listed), and the change was reverted:

| Check | Deliberate break | Failing |
|---|---|---|
| invisible-node | `item.count == 0` -> `< 0` | render 2 |
| invisible-node, the cover | an opaque cover -> any opacity | render 1 |
| contrast-low | `worst < large` -> `worst < 1` | render 1 |
| contrast, the text extreme | min instead of max over the ink extremes | render 6 |
| contrast, the nearest background | the farther end of the background interval | render 1 |
| contrast, large text | the between-floors incompleteness never reported | render 1 |
| contrast, pending | `contract-pending` not reported | render 1 |
| ink-unmeasurable | a noink record taken as measured | render 1 |
| ink-unmeasurable, frame moved | `ink_moved` ignored | render 1 |
| flag-mismatch hidden/shown | never reported | render 1 |
| flag-mismatch disabled-clickable | `D` ignored | render 1 |
| flag-mismatch inert-clickable | `I` ignored | render 1 |
| flag-mismatch clickable | never reported | render 1 |
| flag-mismatch, layers exempt | layers judged too | render 1, lockers 1 |
| flag-mismatch long-mode | never reported | render 1 |
| flag-mismatch, the scope's mode | the ellipsis scope's DOTS ignored | render 1 |
| align-mismatch | never reported | render 1 |
| align-mismatch, align_banner | `align_banner` ignored | lockers 1 |
| align-mismatch, drawn only | judged without a draw task | render 1 |
| align, the field | `align_drawn` read from the `align` field | render 6 |
| line-height-mismatch | `line_h > baseline` -> `> baseline + 99` | render 1 |
| line-height-mismatch, one cause | `>` -> `!=` (repeats font-shrunk) | render 1 |
| ink plan, once per key | every step inked | render 1 |
| ink plan, the second run | the second run inks nothing | render 1 |
| ui-render needs ink | the capability check removed | render 1 |
| ink format | an ink reply missing a node accepted | render 1 (error) |
| no ink on a later visit | a step without ink judged as inked | render 7, lockers 1 (errors) |
| LAYER_ROLES once | a second definition in ui_judge_vocab | render 1 |

The harness that applied them is not part of the repository (it lived in the task's scratch directory).

## U06 review housekeeping

- `LAYER_ROLES` is defined once, in `ui_judge_contract` (with the input-layer naming rule), and imported by
  `ui_judge_vocab` (and through it by the context and the geometric checks); a test asserts it is one object.
- The input-layer naming rule: the stricter rule (only names a judge reads) would refuse the lockers contract (its rows
  `screen`, `splash`, `lockout` are read by no judge), so `docs/ui-contract.md` ("Accepted, not judged") now names the
  accepted names no judge reads.
- The unknown-record test of `test_ui_judge_stage.py` matches its message (`assertRaisesRegex`).
- `selftest/ui_judges.sh`: an end-to-end exit-2 case for a bad `[[input_layer]]` name; deterministic log names.

## Deviations

- **`font-size-mismatch` is approximated as `line-height-mismatch`** (its own id, honest row above), as the contract
  asks for an approximation; the font-id half cannot be judged (no font is mapped).
- **`contrast-low` judges only the large-text floor**; between the floors `contract-incomplete` `large-text`. The
  contract says a missing definition makes the check `contract-pending`; `contract-pending` needs a pending entry with a
  question number in the loader's closed list, and there is no entry to be pending, so the U06 form for a missing
  definition (`contract-incomplete`) is used.
- **`flag-mismatch` exempts layers from `clickable`** and leaves the intent -> not clickable half to `stage-unmatched`
  (above); P004's rule reads both directions literally.
- **`v-dots` gives two findings** (ui-fit's `full-string-shown` and ui-render's `long-mode`): the DOTS mode is the
  label's long mode against a wrapping scope (L3) and the dots are a cut text (L4); the canary assertion lists both.
- **No exception can name `line-height-mismatch` or `ink-unmeasurable`**: the loader's `EXCEPTION_RULES` is in
  `gate/rigor_lib/ui_contract.py`, outside this task's paths.
- **`crop` is not required**: no implemented check reads pixels.
- **The canary's drawing changed** (centred labels, a darker button fill) and `session.out` was regenerated; no U06
  finding changed (the U06 assertions of `ui_judges.sh` are unchanged but for the counts the nine new states add).
- **`ui_explore_run.PARTS`** gains `ink` and `ink_moved`, so run-twice compares them.
