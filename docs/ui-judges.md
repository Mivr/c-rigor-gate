# The `ui-scene` and `ui-fit` judges (U06, P004 3.1, 3.2)

Two judges of `rigor ui-explore` (docs/ui-explore.md) that turn the escaped defect classes "a button under an overlay",
"a target too small", "text that does not fit or is cut" into findings, from the scene (O2) and the rendered tree (O3),
without the oracle. Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_stage.py` | the O3 parser (lvprobe's `node`, `label`, `fit`, `frame` records), the scene vocabulary (O2), the association |
| `ui_judge_context.py` | what one step gives the checks; the stage findings `scene-vocabulary` and `stage-unmatched` |
| `ui_judge_findings.py` | finding ids, `contract-pending`, exceptions, `exception-unused`, the judge set the explorer calls |
| `ui_judge_scene.py` | the O2 checks of `ui-scene` |
| `ui_judge_geom.py` | the O2 + O3 (geometric) checks of `ui-scene` |
| `ui_judge_fit.py` | the `ui-fit` checks |

```
rigor ui-explore ... --judges ui-scene,ui-fit --contract FILE.toml
```

`--judges` takes distinct names of `ui-scene` and `ui-fit` and needs `--contract` (the UI contract, docs/ui-contract.md)
and a probe that announces `frame-facts`; otherwise exit 2 before (or, for the capability, right after) the greeting.
The judges are one step judge of the explorer (called for every completed step of every first run) and one call at the
end of the run (`exception-unused`). Every threshold is read from the contract when a check runs; none is a constant
of a judge. Selftest: `selftest/ui_judges.sh` (called by `selftest/ui.sh`) on the canary product
`selftest/ui_canary_product/`. Unit tests: `gate/tests/test_ui_judge_*.py` over hand-built observations
(`test_ui_judge_helpers.py` writes O2 and O3 lines as the probe writes them).

## What a judge reads, per check

| Check | Gate | Stage | Contract values |
|---|---|---|---|
| `touch-target-small` | ui-scene | O2 | `thresholds.touch_min_dp`, `[[role_min]].touch_dp_min`; `thresholds.touch_min_mm` with `panel.diagonal_in` (ppi) |
| `font-below-min` | ui-scene | O2 | `[[style]]`, `[type_scale]`, `[[role_min]].font_px_min` |
| `hierarchy-violated` | ui-scene | O2 | `[[importance]]`, `thresholds.hierarchy_ratio_k`, the style sizes |
| `raw-text` | ui-scene | O2 | `[[role]]` (which nodes are text nodes) |
| `wrap-policy-undeclared` | ui-scene | O2 | `[[role]]`, `[[wrap]]` |
| `occluded-target` | ui-scene | O2 + O3 | `thresholds.probe_grid_pct`; the disc: `thresholds.probe_disc_radius_mm` with the ppi; `[[input_layer]]` (modal blockers) |
| `overlay-policy` | ui-scene | O2 + O3 | `[[input_layer]]` |
| `target-spacing` | ui-scene | O2 + O3 | `thresholds.hit_overlap_allowed`; `spacing_hard_mm`, `spacing_recommended_mm` with the ppi |
| `node-out-of-bounds` | ui-scene | O2 + O3 | `window.width_px`, `window.height_px` |
| `text-overlap` | ui-scene | O2 + O3 | `[[input_layer]]` (which layer a text is in) |
| `text-overflow` | ui-fit | O2 + O3 | `[[wrap]]` (`wrap`, `max_lines`, `ellipsis`, `clip`) |
| `text-clipped`, `full-string-shown` | ui-fit | O3 (+ O2 for the owner's scope) | `[[wrap]]` (`clip`, `ellipsis`) |
| `fit-unmeasurable`, `glyph-missing` | ui-fit | O3 | none |
| `stage-unmatched`, `scene-vocabulary` | first selected | O2 + O3 | `[[role]]`, `[[style]]`, `[[input_layer]]`, `[[wrap]]` |

O2 is the step's `semantic` reply, O3 its `frame` reply (lvprobe's records; `ink` is never requested: the explorer does
not offer judges the `ink` command, so no check uses ink). The O2-only checks need no association; the others use the
rendered node associated with each scene node for its box (equal to the scene rect by construction), its paint order
(lvprobe's walk order), its ancestors and its clip chain, because the semantic records have no parent, no z order and no
layer (P004 2.1 lists them for O2; model.h's 14 fields do not carry them).

## The scene vocabulary (how the judges read O2)

model.h fixes the 14 fields and their grammar but leaves every field except the numbers and `enabled` to the product.
The judges read them as follows; a value outside this vocabulary is the finding `scene-vocabulary` (error, identity
`["scene", key, fields]`) and that node takes part in no other check (it is reported, never guessed):

| Field | The judges read |
|---|---|
| `key` | the scene node's identity; unique in a state (a duplicate is `scene-vocabulary` with field `key`, for both) |
| `role` | a text node iff the role is a `[[role]]` id of the contract; a node with a non-empty `label` must have one |
| `label` | the formatted string, as bytes |
| `x y w h` | the node's rect in **display pixels** (absolute), scene units = px (the lockers contract: px = dp at 1280x800) |
| `intent` | `-` or `<uint32>:<int32>`; interactive = an intent, `enabled` 1, not `inert` |
| `flags` | `-` or distinct comma-separated tokens of `hidden`, `inert`, `selected` |
| `style` | of a text node: a `[[style]]` id (its font size is `type_scale` of the style's `scale`); of any other node: free |
| `importance` | `-` or a level `1`..`9` |
| `input_policy` | `-`, or a `[[input_layer]]` layer id: the node is then a declared layer with that row's policy |
| `wrap_policy` | `-` (undeclared), or a `[[wrap]]` scope id |

The policy of a declared layer: `blocks_input_below` = capture-modal-inert (a modal blocker), `tap_outside_dismisses`
= capture-and-dismiss, neither = pass-through.

## Scene to rendered (the association)

There is no key in the frame records. A scene node S is the rendered node N exactly when:
1. S's rect `(x, y, x + w - 1, y + h - 1)` is N's box (lvprobe's inclusive coords), N not a screen or layer root; and
2. S's label is N's text: for a label, its own text (lvprobe's `full_text` when it is dotted, otherwise `text`); for any
   other node, either S's label is empty (a container), or exactly one of N's direct label children has S's label as
   its own text (that child is then S's text label: a button and its label); and
3. it is unique both ways: no other rendered node satisfies 1 and 2 for S, and no other scene node for N.

Otherwise S is `stage-unmatched` (info for now), `reason` `absent` (no candidate) or `ambiguous` (several candidates,
or another scene node claims the same rendered node), and takes part in no O2 + O3 check. A shown rendered label with a
non-empty text that no scene node owns is `stage-unmatched` too (`side` `frame`, identity by its walk index); the
`ui-fit` checks still judge it (by index), except `text-overflow`, which needs a declared rect and scope. Comparison is
of bytes, exact; there is no best match, no tolerance and no substring. A product whose adapter reports rects in another
frame (parent-relative, say) gets only `stage-unmatched` for its O2 + O3 checks, which is visible, never silent.

## Findings

Schema of docs/ui-explore.md ("Findings"): `id`, `gate` (`ui-scene` or `ui-fit`), `check`, `layer` (L4 for the checks
of P004 3.1 and 3.2, L3 for `stage-unmatched`, `meta` for the vocabulary, the contract and the exceptions), `severity`,
`state`, `path`, `observed`, `blame` (`[]`), `evidence`, `explanation` (null). The id is
`<gate>.<check>/<first 12 hex of sha256(canonical JSON of [gate, check, [identity, state key]])>`; for findings about the
contract or the run (`contract-pending`, `contract-incomplete`, `exception-unused`) `[gate, check, identity]`. The state
key is the explorer's abstraction key of the state the step reached. Identities name scene nodes by key, rendered nodes
without a scene node by their walk index, never exploration order. `observed` holds gate text, numbers and keys, never a
label text; the records involved go to the evidence file `records.json` (with `--evidence`). The stage findings belong to
the first selected gate in the order ui-scene, ui-fit. The explorer keeps one finding per id (the shortest path).

The explorer's summary counts findings by its own check list only (`ui_explore_judges.CHECKS`): the judges' findings are
in `--out` and in the exit code, not in the summary's `findings` counts (an engine change this task may not make).

## Pending values and exceptions

**Pending.** A check that needs a value the owner has not decided reports `contract-pending` (severity
`ui_contract.PENDING_SEVERITY`, error; `state` null; identity `[check, entry]`, so one per check and entry per run) and
skips exactly what needs it: the mm parts of `touch-target-small` and `target-spacing` and the probe disc of
`occluded-target` while `panel.diagonal_in` is pending (their scene-unit parts still run, as P004 3.10 says);
`hierarchy-violated` while `[[importance]]` or `hierarchy_ratio_k` is pending (both are reported). No default is used.

**Exceptions.** A contract `[[exception]]` row whose `rule` is a check of a selected judge and that has not expired on
the run's date (UTC; `ui_contract.active_exceptions`) suppresses exactly the finding with that check and that target: it
is reported with severity `info` and `observed.exception = {"id", "expires"}`, id unchanged. The target of a finding is
the key of its node; of a pair (`text-overlap`, `target-spacing`) `<first>/<second>` in key order; of `overlay-policy`
`<layer>/<node>`. A finding on a node without a key (an unowned label, an undeclared layer), `scene-vocabulary` and the
contract findings have no target and cannot be excepted. At the end of the run, an exception that turned no finding,
a second exception for the same rule and target, and an expired exception are each `exception-unused` (error, `observed`
says `expired`). The loader's closed rule list (`ui_contract.EXCEPTION_RULES`) takes three of the judges' own ids:
`fit-unmeasurable`, `glyph-missing`, `stage-unmatched`. The date is the only wall-clock input of the judges: an
exception that expires between two runs changes the second run's output.

## The checks

### ui-scene (P004 3.1)

- **`touch-target-small`** (O2). A shown interactive node with `w` or `h` below `max(touch_min_dp, touch_dp_min of its
  role)` (identity `[key, "dp"]`); once the panel is sealed, below `mm_to_px(touch_min_mm)` (`[key, "mm"]`).
- **`font-below-min`** (O2). A shown text node whose style's size is below its role's `font_px_min`. A role with no
  `[[role_min]]` row is `contract-incomplete` (`["role-min", role]`).
- **`hierarchy-violated`** (O2, per state, shown text nodes). Parts: `undeclared` (importance `-`), `level` (not the level
  the contract gives the role; a role in no level is `contract-incomplete`), `levels` (more than 3 distinct levels),
  `rank` (a node of another level larger than the smallest level-1 node), `ratio` (smallest level-1 size below k times
  the largest level-2 size, exact with fractions), `single-size` (text nodes of two or more roles in one size).
- **`raw-text`** (O2). A shown text node whose label is empty.
- **`wrap-policy-undeclared`** (O2). A shown text node with `wrap_policy` `-`.
- **`occluded-target`** (O2 + O3). An interactive node, not behind a declared modal blocker (a later-painted declared
  layer with `blocks_input_below` whose box meets the node's), any of whose probe points lies under a covering node: a
  later-painted rendered node that is not its ancestor or descendant, is shown, and is clickable or paints a background
  (`bg_opa_drawn` above 0 or a background image), over its visible box (cut by the display and its clip chain), or a
  label's drawn glyph box. Probe points: x1 + floor(w x p / 100) (at most x2) for p in `probe_grid_pct` and 50, the same
  for y; the disc: a covering region within `mm_to_px(probe_disc_radius_mm)` of the centre, inside the node's box
  (exact geometry, no sampling). One finding per node, the covering nodes in `observed.covered_by`.
- **`overlay-policy`** (O2 + O3). (a) A declared layer whose row captures input (`blocks_input_below` or
  `tap_outside_dismisses`) painted over an enabled node with an intent (earlier in the walk, not related, boxes meet),
  unless the layer blocks input below and the node is `inert`: `[layer, node, "captures"]`. (b) A shown clickable rendered
  node in no declared layer and not part of an interactive node, painted over an interactive node: a layer that declares
  no policy, `["undeclared", index, node]`.
- **`target-spacing`** (O2 + O3). Two interactive nodes with distinct intents, neither behind a modal blocker: boxes that
  share a pixel (unless `hit_overlap_allowed`); once the panel is sealed, an edge-to-edge distance (pixels between them,
  Euclidean between the boxes) below `spacing_hard_mm` (error) or `spacing_recommended_mm` (info).
- **`node-out-of-bounds`** (O2 + O3). A shown node with an area whose box is not inside the window
  (`window.width_px` x `height_px`), or not inside its parent's box when the parent is not a root.
- **`text-overlap`** (O2 + O3). Two shown text nodes with a text, in the same layer (the nearest declared layer that is
  the node or an ancestor; the base otherwise), neither an ancestor of the other, whose boxes share a pixel. Text in
  different layers is an occlusion, which `ui-render.covered-node` judges, not an overlap.

### ui-fit (P004 3.2)

Every label of the frame, in walk order:
- **`fit-unmeasurable`** (error): lvprobe marks it `unsupported`, or it has no `fit` record; nothing else is judged on
  it. Also, for an owned label whose owner declares no wrap scope, `text-overflow` cannot be judged:
  `fit-unmeasurable` with reason `no-wrap-scope`.
- **`glyph-missing`** (error): lvprobe counts placeholder glyphs (`missing` above 0).
- **`text-clipped`**: lvprobe's `clipped` (glyphs outside the visible box of LVGL's own clip chain, or a text that takes
  room and no part of whose content box survives it), unless the owner's scope declares `clip`.
- **`full-string-shown`**: LVGL's dots replaced the end of the text (`dotted`), unless the owner's scope declares an
  ellipsis.
- **`text-overflow`** (owned, shown, non-empty labels): with a `wrap = none` scope, the natural width above the owner's
  `w`; with a wrapping scope, the laid-out height above the owner's `h`, or more lines than `max_lines` (0: no cap); a
  scope with `ellipsis` or `clip` makes the excess intended. Measured at the font the label is rendered with (below).

## Honesty table

| Check | Status | Why / what is missing |
|---|---|---|
| `occluded-target` | implemented (grid; disc pending while `panel.diagonal_in` is) | Coverage is lvprobe's per-node facts (clickable, drawn background, label glyphs), not ink: `ink` is not offered to judges by the explorer. A background drawn under an `opa_layered` ancestor (`bg_opa_exact` 0) is taken as covering when its drawn opacity is above 0; LVGL's extended click area is not modelled |
| `overlay-policy` | implemented | "visibly dimmed" (P004) is not checked: it needs pixels or ink (U-task of `ui-render`); the O3 half (hit-test injection) is `ui-input`'s |
| `touch-target-small` | implemented (dp; mm floor pending while the ppi is) | The keypad (20 mm) and button (16.5/19 mm) floors are not applied: the contract has no role-to-target-class table (and Q10 is pending in lockers) |
| `target-spacing` | implemented (overlap; mm gaps pending while the ppi is) | Uses the rendered boxes, not LVGL's extended click areas |
| `node-out-of-bounds` | implemented | A child of a scrolling container outside its parent is reported: the scene declares no scroll policy |
| `text-overlap` | implemented | |
| `font-below-min` | implemented | Reads the declared style; the rendered font is `font-shrunk`'s |
| `hierarchy-violated` | implemented; pending in lockers (Q7 importance table, Q5 k) | Prominence is the style's font size only (P004 gap G2) |
| `value-split` | **blocked** | The contract has no list of value elements (locker number, entered code) and O2 no element id that groups nodes into one value; needs a contract table and a scene field (U10 follow-up and model.h) |
| `required-element-missing` | **blocked** | O2 carries no state class (which `[[state_class]]` a state is), and the contract's extra elements (`countdown`, `numpad`, `language_switch`, ...) have no mapping to scene nodes; needs a state-class record in the probe protocol and an element field (model.h, U03 follow-up) |
| `toggle-group-indistinct` | **blocked** | Needs the selection of the group from O1 (the view state), which no stage records: when the defect holds, O2 cannot show which member is selected; needs an O1 projection (P004 2.1; a probe command) |
| `raw-text` | implemented for the empty string; **blocked** for the raw msgid | O2 has no msgid and args field (P004 2.1 lists them for O2) |
| `wrap-policy-undeclared` | implemented, stricter | Every shown text node must declare a scope, not only sentence roles that render on one line: the contract has no sentence-role list, and `text-overflow` needs the scope of every node |
| `text-overflow` | implemented at the **rendered** font | P004 says "at the declared font"; lvprobe maps no font (`lvprobe_map_font`, every font id is `-`) and the gate has no metrics of the declared font: a label rendered smaller than declared hides an overflow at the declared size (false negative); a label rendered larger is judged at that size |
| `text-clipped` | implemented | lvprobe's `clipped` does not model occlusion, corner masks or transforms (docs/ui-lvprobe.md, "Limits") |
| `full-string-shown` | implemented for LVGL's dots | The comparison with `i18n_format(msgid, args, lang)` is blocked (no msgid in O2): a text the product truncates itself, or the wrong text, is `stage-unmatched` (info) or `ui-render.render-text-mismatch`; a clipped tail is `text-clipped` |
| `font-shrunk` | **blocked** | The resolved font of a label is not observable: lvprobe's font ids are not mapped (`lvprobe_map_font`, docs/ui-model.md "Known gaps") and the contract has no style-to-line-height table; needs the font mapping (a later lvprobe/model task) |
| `phrase-too-long` | out of scope | A product build check (P003) |
| `fit-unmeasurable`, `glyph-missing`, `stage-unmatched`, `scene-vocabulary`, `contract-pending`, `contract-incomplete`, `exception-unused` | implemented | the judges' own findings |

## The historic defects (P004 1.1)

| # | Defect | Checks of these judges that catch it | Canary reproduces the mechanism? |
|---|---|---|---|
| F2 | Pad shows no digits (DOT panels paint nothing) | none: the content half is `required-element-missing` and `ui-parity` (blocked here); the render half is `ui-render.invisible-node` | no |
| F3 | Banner covers keypad "1"; its full-window clickable scrim swallows the first tap | `occluded-target` (the card or scrim later-painted over the key's probe points); `overlay-policy` (a capture-and-dismiss layer over an enabled, non-inert key; an undeclared clickable scrim) | partly: `v-occluded` (an opaque panel over a button's probe points) and `v-overlay` (a declared modal layer over an enabled, non-inert button); the capture-and-dismiss and undeclared-scrim forms are in the unit tests (`OverlayTest`), not in the canary |
| F5 | "82" as two small glyph labels in one font | none implemented: `value-split` and `font-shrunk` are blocked; `hierarchy-violated` sees only the scene, which declared the right style | no |
| F6 | Countdown clipped (20 dp row, 36 px line) and in m:ss | `text-clipped` (b), `text-overflow` (b, wrapping scope: laid-out height above the row); (a) the format needs the msgid (blocked) | partly: `v-clipped` cuts a label by its parent's box (the same clip-chain mechanism), `v-overflow` exceeds a rect; the too-short row is in the unit tests (`OverflowTest`) |
| F8 | Bulgarian subtitle cut mid-sentence (745 px text, 608 px box, 40 px row) | `text-overflow` (single-line scope: natural width; wrapping scope: laid-out height), `text-clipped`, `wrap-policy-undeclared` | yes: `v-overflow` (natural width above the rect at a single-line scope) and `v-wrap` |
| F9 | BG/EN toggles show no selected state | none: `toggle-group-indistinct` is blocked | no |
| F10 | Splash has no version line | none: `required-element-missing` is blocked | no |
| F11 | Report without columns and lines; clipped caption rows | the clipped rows: `text-clipped`, `text-overflow`; the missing content: blocked (`required-element-missing`) | the clipped rows partly, as F6 |
| X2 | "Open source licenses..." row (h 20) clipped | `text-clipped`, `text-overflow` | partly, as F6 |

## Canaries (`selftest/ui_canary_product/`)

A 320x240 LVGL app (`canary.c`) with a model adapter (`model.c`) built through `c_ui_probe`, its event catalogue
(`canary.events.toml`: one u1 intent per variant), its contract (`canary.toml`: a 10 inch panel, 40 ppi, every value
the judges read decided) and the paths `canary.paths.json` (`open`, then `open` + each variant). The clean state is a
title, a body text and two buttons; each variant changes exactly one thing and has its own title, so that every state
has its own abstraction key (the key reads O2 only; two variants differ only in how they are drawn):

| Event | Defect | Finding (identity) |
|---|---|---|
| `v-occluded` | an opaque, non-clickable panel over the right third of `ok` | `ui-scene.occluded-target` (`["ok"]`) |
| `v-overlay` | a transparent clickable layer declared `modal` over `ok`, which is not inert | `ui-scene.overlay-policy` (`["veil", "ok", "captures"]`) |
| `v-small` | `ok` 30 px high (floor 48) | `ui-scene.touch-target-small` (`["ok", "dp"]`) |
| `v-spacing` | `back` right next to `ok` (gap 0 px, 1 mm = 1.57 px) | `ui-scene.target-spacing` (`["back", "ok", "hard"]`) |
| `v-bounds` | a panel past the right edge of the window | `ui-scene.node-out-of-bounds` (`["edge", "window"]`) |
| `v-overlap` | the body text moved into the title's rows | `ui-scene.text-overlap` (`["body", "title"]`) |
| `v-font` | the body text in the 10 px caption style (role minimum 14) | `ui-scene.font-below-min` (`["body"]`) |
| `v-hierarchy` | the body text (level 2) in the 24 px headline style, larger than the 20 px title | `ui-scene.hierarchy-violated` (`["rank"]`) |
| `v-raw` | the body text empty | `ui-scene.raw-text` (`["body", "empty"]`) |
| `v-wrap` | the body text without a wrap scope | `ui-scene.wrap-policy-undeclared` (`["body"]`) and, stated, `ui-fit.fit-unmeasurable` (`["body", "scope"]`) |
| `v-overflow` | a 156 px text in a 100 px single-line rect (LVGL wraps it into 2 lines that fit) | `ui-fit.text-overflow` (`["body"]`) |
| `v-clipped` | `ok`'s label pushed 22 px down, past the button's bottom edge | `ui-fit.text-clipped` (`["ok"]`) |
| `v-dots` | a long text in a 60 px DOTS label | `ui-fit.full-string-shown` (`["body"]`) |
| `v-unmeasurable` | a drop shadow on the body label (LVGL draws it through a sub-layer) | `ui-fit.fit-unmeasurable` (`["body", "facts"]`) |
| `v-glyph` | the body text "Й" in Montserrat 14, which has no Cyrillic | `ui-fit.glyph-missing` (`["body"]`) |
| `v-unmatched` | a scene node with no rendered node | `ui-scene.stage-unmatched` (`["scene", "ghost", "absent"]`, info) |

`selftest/ui_judges.sh` builds the probe in release and san, replays the paths with both judges and checks: per
variant exactly the findings in the table, their ids recomputed from the identity and the state key; nothing in the
clean state; byte-identical findings and evidence twice in release, and release equal to san; every finding replays
from its `paths.json` to its id; a live exception turns exactly its finding into info with its expiry, an unused and an
expired one are `exception-unused`; `--judges` without `--contract`, or with an unknown name, exits 2; no canary probe
is left. The contract-pending cases are unit tests (the canary contract decides everything).

## Each check seen failing against a broken judge

Each line was applied to the judge, the unit tests (`gate/tests/test_ui_judge_*.py`) were run and failed, and the
change was reverted (the U06 report lists the failing tests and the canary selftest run against one of them):

| Check | Deliberate break |
|---|---|
| occluded-target | `if grid_hits or disc_hit:` -> `if False:` |
| overlay-policy | the capture loop always `continue`s |
| touch-target-small | `w < need or h < need` -> `and` |
| target-spacing | `gap2 < hard * hard` -> `gap2 < 0` |
| node-out-of-bounds | the window test -> `if False:` |
| text-overlap | `intersect(...) is not None` -> `is None` |
| font-below-min | `size < minimum` -> `size < minimum - 1` |
| hierarchy-violated | the ratio test without `k` |
| raw-text | `label == b""` -> `label == b"-"` |
| wrap-policy-undeclared | `wrap_policy == "-"` -> `== "none"` |
| text-overflow | `natural_w > owner.w` -> `> owner.w + 1` |
| text-clipped | `fit.clipped` -> `False` |
| full-string-shown | `label.dotted` -> `False` |
| fit-unmeasurable | `fit is None or fit.unsupported` -> `fit is None` |
| glyph-missing | `missing > 0` -> `missing > 1` |
| stage-unmatched | the association takes the first of several candidates (`len(hits) == 1` -> `hits`) |
| scene-vocabulary | the vocabulary result ignored |
| contract-pending | `Reporter.pending` reports nothing |
| exceptions | `Exceptions.apply` never applies |
| exception-unused | `finish` returns nothing |

## Deviations and interface gaps

- **O2 lacks the tree.** The semantic records have no parent, z order, layer, msgid, args, state class or element id.
  The geometric checks therefore read the associated O3 nodes; the checks that need the rest are blocked (table above).
- **The scene vocabulary is the judges'.** model.h leaves the field values to the product; this document fixes how the
  judges read them, with rects in display pixels. The toy of `selftest/ui_product` does not follow it (its roles are
  `label` and `button`): judged with a contract, it is `scene-vocabulary` throughout (`test_ui_judge_exceptions`).
- **Finding names added**: `stage-unmatched`, `fit-unmeasurable`, `glyph-missing`, `exception-unused`,
  `contract-pending` (named by the task), and `scene-vocabulary`, `contract-incomplete` (the loader's name, here for a
  role the contract has no `[[role_min]]` row or level for).
- **State identity is the abstraction key**, as in the explorer: a rendered difference under one key (the key reads
  O2 only) is the same state to the ids, and `key-too-coarse` does not compare frames.
- **The explorer's summary** counts only its own checks (above).
- **The explorer offers no `ink`, `hit-test` or `crop` to judges**: a judge sees the replies of the step only. Evidence
  images (crops with the node box) are therefore not attached; the records are.
