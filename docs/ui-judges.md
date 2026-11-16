# The `ui-scene` and `ui-fit` judges (U06, P004 3.1, 3.2)

Two judges of `rigor ui-explore` (docs/ui-explore.md) that turn the escaped defect classes "a button under an overlay",
"a target too small", "text that does not fit or is cut", "a toggle that shows no selection" into findings, from the
scene (O2) and the rendered tree (O3), without the oracle. Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_stage.py` | the O3 parser (lvprobe's `node`, `label`, `fit`, `frame` records) |
| `ui_judge_vocab.py` | the scene vocabulary (O2), the typographic role of a style token, the association |
| `ui_judge_context.py` | what one step gives the checks; the stage findings; inertness (R5); layers |
| `ui_judge_findings.py` | ids, `contract-pending`, exceptions, `exception-unused`, `checks-examined`, `check-vacuous`, the judge set |
| `ui_judge_scene.py` | the O2 checks of `ui-scene` and `toggle-group-indistinct` |
| `ui_judge_geom.py` | the O2 + O3 (geometric) checks of `ui-scene` |
| `ui_judge_fit.py` | the `ui-fit` checks |

```
rigor ui-explore ... --judges ui-scene,ui-fit --contract FILE.toml --today YYYY-MM-DD
```

`--judges` takes distinct names of `ui-scene` and `ui-fit` and needs `--contract` (docs/ui-contract.md), `--today`
(the date the contract's exceptions expire against: the judges never read the wall clock) and a probe that announces
`frame-facts`; otherwise exit 2. `--today` without `--judges` is exit 2 too. Selftest: `selftest/ui_judges.sh` (called
by `selftest/ui.sh`) on the canary product `selftest/ui_canary_product/`. Unit tests: `gate/tests/test_ui_judge_*.py`
over hand-built observations (`test_ui_judge_helpers.py` writes O2 and O3 lines as the probe writes them), and
`test_ui_judge_lockers.py` over the 23 frames of the real kiosk.

## The scene vocabulary (orchestrator rulings R1 to R6)

model.h fixes the 14 fields of a semantic record; their values are read as follows (exactly what the real lockers
adapter, business-apps `apps/lockers/lkapp/uimodel`, writes). A value outside this vocabulary is `scene-vocabulary`
(error, identity `["scene", key, fields]`) and that node takes part in no other check.

| Field | The judges read |
|---|---|
| `key` | the scene node's identity; unique in a state (a duplicate is `scene-vocabulary` with field `key`, for both) |
| `role` | a STRUCTURAL role of the closed list `root panel text button key countdown scrim dialog banner snackbar` (`ui_contract.STRUCTURAL_ROLES`; exactly what the real adapter emits, nothing added) |
| `label` | the formatted string, as bytes. A panel's label is its accessible label only (ui-look.md 4.3, owner decision X6): it is never compared with what is drawn |
| `x y w h` | the rect in display pixels (absolute); scene units = px (the lockers contract: px = dp at 1280x800) |
| `enabled` | 0 or 1 |
| `intent` | `-` or `<uint32>:<int32>` |
| `flags` | `-` or distinct letters of `I` inert, `D` disabled, `W` warn, `N` notice, `S` scroll, `H` hidden, `X` selected (H and X are not emitted by the real adapter yet) |
| `style` | the product's numeric style token (0 or a positive decimal). For the text-bearing roles `text button key countdown` the TYPOGRAPHIC role is derived: token -> the contract's `[[style]]` row -> the `[[role]]` that names the style, else its `[[style_role]]` row. A token the contract does not know is `contract-incomplete` (`["style-token", token]`, once per run); a style no role names is `contract-incomplete` (`["style-role", style]`). Other roles' tokens (panel tones, card kinds) are not read |
| `importance`, `input_policy`, `wrap_policy` | `-` by design: the judges take importance from the contract's importance table by typographic role, the wrap scope from `[[role_wrap]]` by typographic role, the layer policy from `[[layer]]` by structural role. A present value must be a level `1`..`9`, a policy (`pass-through`, `capture-modal-inert`, `capture-and-dismiss`) or a `[[wrap]]` scope, else `scene-vocabulary`; one that contradicts the contract is a finding of the check that reads it |

Interactive: an intent, `enabled` 1, neither `I` nor `D`. Shown (O2): no `H`.

**Layers (R6).** A node of role `scrim`, `dialog`, `banner` or `snackbar` is the layer; its policy is the contract's
`[[layer]]` row of its role. A scrim's row is chosen by the card it belongs to, the next scene node when its role is a
card role (`dialog banner snackbar`); a card that follows a scrim is judged through that scrim (one layer). No policy in
the scene is needed.

**Inertness (R5, P004's "declared modal blocker").** An interactive node is inert when it carries `I`, or when a
later-painted, shown scene node carrying `I` covers all of its probe points (the grid points, and with the ppi the
corners of the probe disc's bounding box inside the node; a bounding box is larger than the disc, so this errs towards
"not inert"). The real kiosk declares its background inert this way: a full-window panel with `I` under the dialog.

## Scene to rendered (the association)

There is no key in the frame records. Every scene node but the root (role `root` is the screen and is associated with
nothing) is paired with a rendered node, never a screen or layer root, by its rect: the scene rect
`(x, y, x + w - 1, y + h - 1)` must be the rendered box exactly. Scene nodes with the same rect are paired by rank: the
k-th of them in scene order with the k-th rendered node of that box in walk order, when both counts agree (a scrim and
its card, a full-window inert panel and a scrim: 8 of the 23 real frames). Otherwise every scene node with that rect is
`stage-unmatched` (`ambiguous`; `absent` when no rendered node has it): an ERROR when the node is interactive or a
layer, info otherwise. A paired node whose label is not the drawn text (a label's own text, `full_text` when dotted;
for any other node either an empty label or the own text of exactly one direct label child) is `stage-text-mismatch`
(error): the scene label is the formatted string, so the drawn text differs from it. Panels are exempt (their label is
accessible only). A shown rendered label with a text that no scene node owns is `stage-unmatched` (info, `side`
`frame`), named by class, box and the first 8 hex of the sha256 of its text (target
`node/<class>/<x1>/<y1>/<x2>/<y2>/<8 hex>`), never by walk index; a label of a mismatched node is not reported again.

## What a judge reads, per check

| Check | Gate | Stage | Contract |
|---|---|---|---|
| `touch-target-small` | ui-scene | O2 | `touch_min_dp`, `[[role_min]].touch_dp_min` of the typographic role; `touch_min_mm` with the ppi |
| `font-below-min` | ui-scene | O2 | the style's `type_scale` size, `[[role_min]].font_px_min` |
| `hierarchy-violated` | ui-scene | O2 | the style sizes; `[[importance]]`; `hierarchy_ratio_k` |
| `raw-text` | ui-scene | O2 | none (roles `text` and `countdown`) |
| `wrap-policy-undeclared` | ui-scene | O2 | `[[role_wrap]]` |
| `toggle-group-indistinct` | ui-scene | O2 + O3 | `[[toggle_group]]` (members, `marks`), `[[element]]` |
| `occluded-target` | ui-scene | O2 + O3 | `probe_grid_pct`; the disc: `probe_disc_radius_mm` with the ppi |
| `overlay-policy` | ui-scene | O2 + O3 | `[[layer]]` |
| `target-spacing` | ui-scene | O2 + O3 | `hit_overlap_allowed`; `spacing_hard_mm`, `spacing_recommended_mm` with the ppi |
| `node-out-of-bounds` | ui-scene | O2 + O3 | `window.width_px`, `height_px` |
| `text-overlap` | ui-scene | O2 + O3 | none |
| `text-overflow` | ui-fit | O2 + O3 | `[[role_wrap]]`, `[[wrap]]` |
| `font-shrunk` | ui-fit | O2 + O3 | `[[style_line]]` |
| `text-clipped`, `full-string-shown` | ui-fit | O3 (+ the owner's scope) | `[[wrap]]` (`clip`, `ellipsis`) |
| `fit-unmeasurable`, `glyph-missing` | ui-fit | O3 | none |
| stage findings | first selected gate | O2 + O3 | `[[style]]`, `[[role]]`, `[[style_role]]`, `[[wrap]]` |

The geometric checks read the box (equal to the scene rect by the association), the paint order (lvprobe's walk
order), ancestors and the clip chain of the associated rendered nodes, because the semantic records carry no parent,
z order or layer.

## Findings

Schema of docs/ui-explore.md ("Findings"); `gate` is `ui-scene` or `ui-fit`; `layer` L4 for the checks of P004 3.1 and
3.2, L3 for `stage-unmatched`, `stage-text-mismatch` and `font-shrunk`, `meta` for the vocabulary, the contract and the
run. The id is `<gate>.<check>/<12 hex of sha256(canonical JSON of [gate, check, [identity, state key]])>`, or of
`[gate, check, identity]` for findings about the contract or the run (`contract-pending`, `contract-incomplete`,
`wrap-policy-undeclared` for a role, `exception-unused`, `checks-examined`, `check-vacuous`; `state` null). The state
key is the explorer's abstraction key. Identities name scene nodes by key and rendered nodes without a scene node by
class, box and text hash. `observed` holds gate text, numbers and keys, never a label text; the records involved go to
`records.json` (with `--evidence`). The stage findings belong to the first selected gate in the order ui-scene, ui-fit.
The explorer's summary counts them as `<gate>.<check>`.

**Run-level findings.** At the end of the run each selected judge reports `checks-examined` (info): per check the
number of nodes it examined, in total and per state (by abstraction key; the largest count of a key's visits), so a
later wiring task can require it to be above 0. A check that examined no node in any visited state while the contract
declares what it applies to is `check-vacuous` (error): `touch-target-small`, `occluded-target`, `target-spacing`
apply when a `[[role_min]]` row has a touch minimum; `overlay-policy` when `[[layer]]` has a row; `toggle-group-
indistinct` when `[[toggle_group]]` has one; every other check when `[[role]]` has one. A node whose check skipped part
of its work for a pending value still counts as examined (the pending finding reports the skip).

## Pending values and exceptions

**Pending.** `contract-pending` (severity `ui_contract.PENDING_SEVERITY`, error; `state` null; identity `[check, entry]`,
so one per check and entry per run) skips exactly what needs the value:
- the ppi (`panel.diagonal_in`): the mm part of `touch-target-small`, the mm gaps of `target-spacing`, the probe disc of
  `occluded-target` (and its R5 corners); every scene-unit part runs;
- the importance table: the `level`, `levels`, `rank` and `ratio` parts of `hierarchy-violated`; `single-size` needs
  neither and runs; `hierarchy_ratio_k`: the `ratio` part only;
- a pending `[[role_wrap]]` row: `wrap-policy-undeclared` and `text-overflow` for that role's nodes (both reported);
- a pending `[[layer]]` row: `overlay-policy` for that layer.

**Exceptions.** A contract `[[exception]]` row whose `rule` is a check of a selected judge and that has not expired on
`--today` (`ui_contract.active_exceptions`) suppresses exactly the finding with that check and target: severity `info`,
`observed.exception = {"id", "expires"}`, id unchanged. The target of a finding is the key of its node; of a pair
(`text-overlap`, `target-spacing`) `<first>/<second>` in key order; of `overlay-policy` `<layer>/<node>`; of a rendered
node without a scene node its name (above). At the end of the run every exception of a selected check that turned no
finding, a second one for the same rule and target, and an expired one is `exception-unused`: an ERROR when it has
expired or its target was visited, info otherwise. **Visited** is decided per step: a target is visited when some step
of the run (every step of every first run) showed a scene node with that key, or a rendered label without a scene node
of that name, or, for a pair `a/b`, both in the same step. An exception whose target never appeared names a state the
exploration did not reach, so it cannot be called unused.

## The checks

### ui-scene (P004 3.1)

- **`touch-target-small`** (O2). A shown interactive node with `w` or `h` below `max(touch_min_dp, touch_dp_min of its
  typographic role)` (`[key, "dp"]`); once the panel is sealed, below `mm_to_px(touch_min_mm)` (`[key, "mm"]`).
- **`font-below-min`** (O2). A shown text-bearing node whose style's size is below its typographic role's
  `font_px_min` (possible through a `[[style_role]]` variant style). A role without a `[[role_min]]` row is
  `contract-incomplete`.
- **`hierarchy-violated`** (O2, per state, shown text-bearing nodes with a typographic role). `single-size` (two or more
  roles, one size); with the importance table: `level` (a level in the scene that is not the contract's; `-` is
  normal), `levels` (more than 3), `rank` (a node of another level larger than the smallest level-1 node); with k too,
  `ratio` (smallest level-1 size below k times the largest level-2 size, exact with fractions).
- **`raw-text`** (O2). A shown node of role `text` or `countdown` whose label is empty.
- **`wrap-policy-undeclared`** (O2 + contract). A shown text-bearing node whose typographic role has no `[[role_wrap]]`
  row (identity `["role", role]`, once per run); a scope in the scene that is not the contract's (`[key, "contradicts"]`).
- **`toggle-group-indistinct`** (O2 + O3, one state). For each `[[toggle_group]]`: its members' scene keys come from
  `[[element]]`. When any member is shown, all must be present, shown and associated (else part `members`); then for
  each declared mark (`bg`: the rendered node's background colour; `bg_opa`: its drawn background opacity; `style`: the
  scene's token) exactly one member differs from the others, which are all equal (2 members: they differ). On the real
  kiosk BG and EN differ in fill (2b4678 / 282a2f) and token (20 / 21).
- **`occluded-target`** (O2 + O3). An interactive, not inert node, any of whose probe points lies under a covering node:
  a rendered node painted later that is not its ancestor and not its own part (a descendant counts only when another
  scene node is associated with it) and that is shown and clickable, draws a background opacity above 0, has a
  background image, or is a label whose drawn glyphs are there; its region is its visible box (display and clip chain).
  Probe points: x1 + floor(w x p / 100) (at most x2) for p in `probe_grid_pct` and 50, the same for y; the disc: a
  covering region within `mm_to_px(probe_disc_radius_mm)` of the centre inside the box (exact geometry). For a layer (a
  scrim with an intent, whose tap area is what its card leaves free) the finding is part `layer-unreachable` and needs
  ALL grid points covered.
- **`overlay-policy`** (O2 + O3). (a) A layer whose contract policy captures input (`capture-modal-inert`,
  `capture-and-dismiss`) painted over an enabled, not disabled node with an intent (earlier in the walk, not related,
  boxes meet), unless the policy is capture-modal-inert and the node is inert (R5): `[layer, node, "captures"]`. (b) A
  policy in the scene that is not the contract's: `[layer, "contradicts"]`. (c) A shown clickable rendered node in no
  layer and not part of any associated scene node, painted over an interactive node: a layer that declares nothing,
  `["undeclared", name, node]`.
- **`target-spacing`** (O2 + O3). Two interactive, not inert nodes with distinct intents that are not layers (a scrim
  overlaps by design; that is overlay-policy's and occluded-target's) whose boxes share a pixel (unless
  `hit_overlap_allowed`); with the ppi, an edge-to-edge gap below `spacing_hard_mm` (error) or
  `spacing_recommended_mm` (info).
- **`node-out-of-bounds`** (O2 + O3). A shown node with an area whose box is not inside the window, or not inside its
  parent when the parent is not a root; a node in a scrolling viewport is not judged: an ancestor that is lvprobe's
  scroll context and not a screen or layer root, or whose scene node carries `S` (a scrolling screen does not excuse,
  so content beyond the window is still found).
- **`text-overlap`** (O2 + O3). Two shown text-bearing nodes with a typographic role and a text, in the same layer (the
  nearest layer-role node that is the node or its ancestor; the base otherwise), neither an ancestor of the other,
  whose boxes share a pixel.

### ui-fit (P004 3.2)

Every shown label with a text, in walk order:
- **`fit-unmeasurable`** (error): `unsupported`, or no `fit` record; nothing else is judged on it.
- **`glyph-missing`** (error): placeholder glyphs (`missing` above 0).
- **`text-clipped`**: lvprobe's `clipped`, unless the owner's scope declares `clip`.
- **`full-string-shown`**: LVGL's dots (`dotted`), unless the owner's scope declares an ellipsis. (A text that is not the
  scene's formatted string is `stage-text-mismatch`.)
- **`text-overflow`** (owned): a `wrap = none` scope: the natural width above the owner's `w`; a wrapping scope: the
  laid-out height above the owner's `h`, or more lines than `max_lines` (0: no cap); `ellipsis` or `clip` make the excess
  intended. Measured at the font the label is rendered with. A role without a scope is `contract-incomplete`
  (`role-wrap`) here, a pending scope `contract-pending`.
- **`font-shrunk`** (owned): the label's line height below the `[[style_line]]` line height of the owner's style; a
  style without a row is `contract-incomplete` (`style-line`).

## The real kiosk (`gate/tests/test_ui_judge_lockers.py`)

The judges over the 23 frames of business-apps `apps/lockers/lkapp/uimodel/tests/screens.out` (commit `f1274bf`;
`gate/tests/data/ui_judge/lockers-screens.{in,out}`, digests in `SHA256SUMS`; to refresh, copy both files, rewrite
`SHA256SUMS` and re-classify), with `products/business-apps/ui/lockers.toml`. No `scene-vocabulary`, no `check-vacuous`.
Every finding, classified:

| Frames | Finding | Class |
|---|---|---|
| 1-4, 15-18 | `occluded-target` part `layer-unreachable` on the banner scrims 296 (self-test), 280 (codes offline), 264, 272, 288 | **true product defect**: a banner of the persistent set has a scrim with the dismiss intent (262:0 ...) whose card has the same rectangle, so no tap reaches the scrim (the known defect of business-apps docs/lockers/ui-model.md, "The set banner's tap-outside point"); ui-rules.md wants no tap-outside area for these banners, so the scrim's intent is dead |
| 17, 18 | `occluded-target` on 11, 12 (BG, EN) | **true product defect**: the fourth stacked banner (288, 352..499) is painted over the language switch |
| 13, 14 | `occluded-target` and `overlay-policy` (`320/11`, `320/12`, `320/16`) on BG, EN and Done | **true by P004's rule** (F3b class): the snackbar's full-window dismissing scrim takes the first tap on the visible controls. ui-rules.md decides that a tap outside a snackbar dismisses it; P004 requires the covered controls to be declared inert. An owner decision, not a judge false positive |
| 13, 14 | `stage-unmatched` 321 (the snackbar card, error), 323 (its Dismiss, error), 322, 326 (info), and its three labels from the rendered side (info) | **true product defect**: the snackbar is drawn at 128,626-1151,791, not at the scene's 360,476 560x300: the notice parts ignore the scene rect (P004 F3b root cause) |
| 19 | `text-clipped` and `text-overflow` on 8 | **true product defect** (X2, the known one): the Bulgarian licences line needs two 18 px lines in a 20 px row |
| 22 | `stage-text-mismatch` on 5 | **true product defect**: the storage-fault screen's staff detail is drawn as `?40` instead of the scene's sentence |
| every frame | `contract-pending` | **consequence of pending contract values**: the panel (q9: the disc, the mm parts), the importance table (q7), the wrap scopes of `screen_headline`, `key_label`, `small_button_label`, `staff_strong` (q7), the banner's layer policy (q7) |

No false positive is left. The two the review found are fixed in the judge: the rejection dialog (frames 5, 6, 11, 12)
gave occluded-target and overlay-policy on every key, the language switch and the banner under it; the kiosk declares
them inert by the full-window panel with `I` under the dialog (R5), and they now give nothing. The digits echo panel
(key 13) carries "Digits entered: N" but draws no text: by owner decision X6 a panel's label is its accessible label,
the dots (panels 128..131, filled e2e2e9) are the visible echo; it is not a mismatch.

Nodes examined on the 23 frames (`checks-examined`): occluded-target 172, overlay-policy 26 (layers),
touch-target-small 238, target-spacing 154, node-out-of-bounds 466, text-overlap 351, font-below-min 357,
hierarchy-violated 357, raw-text 137, wrap-policy-undeclared 357, toggle-group-indistinct 36; text-overflow 109 (the
other text nodes' roles have pending scopes), text-clipped, full-string-shown, fit-unmeasurable, glyph-missing 357 each,
font-shrunk 350.

## Honesty table

| Check | Status | Why / what is missing |
|---|---|---|
| `occluded-target` | implemented (grid; disc pending while `panel.diagonal_in` is) | Coverage is lvprobe's per-node facts, not ink (the explorer offers judges no `ink`). Not counted as covering (false negatives): borders, outlines and shadows only; an `lv_image`'s own image, an arc, bar, line or any other widget's own drawing; a gradient without a background opacity. A background drawn under an `opa_layered` ancestor (`bg_opa_exact` 0) counts when its drawn opacity is above 0. LVGL's extended click area is not modelled |
| `overlay-policy` | implemented | "visibly dimmed" is not checked (needs pixels or ink); the O3 half (hit-test injection) is `ui-input`'s |
| `touch-target-small` | implemented (dp; the mm floor while the ppi is pending is contract-pending) | The keypad (20 mm) and button (16.5/19 mm) floors are not applied: the contract has no role-to-target-class table (and Q10 is pending) |
| `target-spacing` | implemented (overlap; mm gaps pending while the ppi is) | rendered boxes, not LVGL's extended click areas |
| `node-out-of-bounds` | implemented | a declared clip container is not excused: the vocabulary has no clip flag (S is scroll) |
| `text-overlap`, `font-below-min`, `raw-text` (empty) | implemented | |
| `hierarchy-violated` | implemented; in lockers only `single-size` runs (Q7 importance, Q5 k) | prominence is the style's font size only (P004 gap G2) |
| `wrap-policy-undeclared` | implemented from the contract (R4) | the lockers spec decides wrapping per node; four roles are pending (Q7) |
| `toggle-group-indistinct` | implemented within one state | `exactly_one` (which member is selected) is not checked: X is not emitted |
| `text-overflow` | implemented at the **rendered** font | the declared font is not measured: lvprobe maps no font; `font-shrunk` reports a rendered font smaller than the style's |
| `text-clipped`, `glyph-missing`, `fit-unmeasurable` | implemented | lvprobe's `clipped` does not model occlusion, corner masks or transforms |
| `full-string-shown` | implemented: dots; the comparison with the formatted string is `stage-text-mismatch` | |
| `font-shrunk` | implemented against `[[style_line]]` | **the line heights are read from the C kiosk itself** (`oracle:` provenance, owner review pending): it catches a font that becomes smaller than today, not one that is already wrong; it compares line heights, not font ids (`lvprobe_map_font` maps none), so a smaller font with the same line height is not seen |
| `value-split` | **blocked** | needs (1) a contract table of value elements (`[[value]]`: element id, the phrase whose arguments make the value, e.g. the locker number and the entered code) and (2) an element id per scene node (a 15th semantic field, model.h) so that the nodes of one value can be counted |
| `required-element-missing` | **blocked** | needs (1) the state class of each step (`[[state_class]]` id: a probe reply or a 15th field of the root record, model.h) and (2) an element id per scene node for the contract's extra elements (`countdown`, `dismiss`, `numpad`, `language_switch`, `size_buttons`, ...); `[[element]]` maps element ids to fixed keys only, which a numpad or a size-button list does not have |
| `raw-text` (raw msgid) | **blocked** | needs the msgid and the arguments of each text node in the scene (two semantic fields, model.h) to tell a raw msgid from a formatted string |
| `phrase-too-long` | out of scope | a product build check (P003) |
| `stage-unmatched`, `stage-text-mismatch`, `scene-vocabulary`, `contract-incomplete`, `contract-pending`, `exception-unused`, `checks-examined`, `check-vacuous` | implemented | the judges' own findings |

## The historic defects (P004 1.1)

| # | Defect | Checks that catch it | Canary reproduces the mechanism? |
|---|---|---|---|
| F2 | Pad shows no digits | none here: the content half is `required-element-missing` (blocked) and `ui-parity`; the render half is `ui-render.invisible-node` (the real kiosk now paints its dots) | no |
| F3 | Banner covers key "1"; its scrim swallows the first tap | `occluded-target` (a card or scrim painted over the key's probe points; `layer-unreachable` for a scrim whose card covers it), `overlay-policy` (a capturing layer over an enabled, non-inert key; an undeclared clickable scrim) | partly: `v-occluded` (an opaque panel over a button), `v-overlay` (a modal layer over an enabled, non-inert button); the dismissing scrim and the undeclared scrim are in the unit tests (`OverlayTest`, `OccludedTest`) and on the real frames 13, 14 |
| F5 | "82" as two glyph labels in one font | `font-shrunk` for the font (the real kiosk now draws them at the display style); the split: `value-split` (blocked) | `v-shrunk` for the font, not the split |
| F6 | Countdown clipped (20 dp row, 36 px line) and in m:ss | `text-clipped`, `text-overflow` (height); the format: blocked (no msgid) | partly: `v-clipped` (a label cut by its parent), `v-overflow` (width); the short row is in the unit tests |
| F8 | Bulgarian subtitle cut mid-sentence | `text-overflow`, `text-clipped`, `wrap-policy-undeclared` | yes: `v-overflow`, `v-wrap` |
| F9 | BG/EN toggles show no selected state | `toggle-group-indistinct` (fill and token) | yes: `v-toggle` |
| F10 | Splash has no version line | none: `required-element-missing` is blocked | no |
| F11 | Report without columns; clipped caption rows | the clipped rows: `text-clipped`, `text-overflow`; the missing content: blocked | partly, as F6 |
| X2 | "Open source licenses..." row clipped | `text-clipped`, `text-overflow` (found on the real frame 19) | partly, as F6 |

## The abstraction key (an engine limit, reported, not changed)

The explorer explores once per abstraction key, and the key reads the scene (O2) and model facts only. Two states that
differ only in what is drawn (a snackbar laid out elsewhere, a label clipped in one language) are one state to the
explorer: only the first visit's frame is judged per path, and the judges' ids (which include the key) merge them.
A lockers key must therefore include every semantic field that separates what is drawn: `label` (the language and every
formatted value), `x y w h` (the layout), `flags` (I, D, W, N), `style` (the selection of BG/EN, button variants),
`enabled` and `intent`, besides the `deadline` fact. No key can separate states that differ only in O3: that needs a
key over frame facts (a later engine task), or a product whose scene states everything it draws.

## Canaries (`selftest/ui_canary_product/`)

A 320x240 LVGL app (`canary.c`) with a model adapter (`model.c`) built through `c_ui_probe`, in the vocabulary of the
real kiosk: structural roles, style tokens (`canary.toml`'s `[[style]]` with `[[style_role]]` variants), flag letters,
`-` for the three policies. Its catalogue `canary.events.toml` (one u1 intent per variant), its contract `canary.toml`
(a 10 inch panel, 40 ppi, everything the judges read decided) and the paths `canary.paths.json`. The clean state is a
title, a body text, two buttons and the BG/EN switch; each variant changes one thing and has its own title, so every
state has its own abstraction key:

| Event | Defect | Findings (identity) |
|---|---|---|
| `v-occluded` | an opaque, non-clickable panel over the right third of `ok` | `ui-scene.occluded-target` (`["ok"]`) |
| `v-overlay` | a transparent `dialog` (capture-modal-inert) over `ok`, which is not inert | `ui-scene.overlay-policy` (`["veil", "ok", "captures"]`) |
| `v-small` | `ok` 30 px high (floor 48) | `ui-scene.touch-target-small` (`["ok", "dp"]`) |
| `v-spacing` | `back` right next to `ok` (gap 0 px; 1 mm = 1.57 px) | `ui-scene.target-spacing` (`["back", "ok", "hard"]`) |
| `v-bounds` | a panel past the window's right edge | `ui-scene.node-out-of-bounds` (`["edge", "window"]`) |
| `v-overlap` | the body text moved into the title's rows | `ui-scene.text-overlap` (`["body", "title"]`) |
| `v-font` | the body text in token 8, a 10 px variant style of the role body (minimum 14) | `ui-scene.font-below-min` (`["body"]`) |
| `v-hierarchy` | the body text in token 9, a 24 px variant of body (level 2), larger than the 20 px title | `ui-scene.hierarchy-violated` (`["rank"]`) |
| `v-raw` | the body text empty | `ui-scene.raw-text` (`["body", "empty"]`) |
| `v-wrap` | the body text in the caption style, a role without a wrap scope | `ui-scene.wrap-policy-undeclared` (`["role", "caption"]`) and `ui-fit.contract-incomplete` (`["role-wrap", "caption"]`), both per run |
| `v-overflow` | a 272 px title in a 200 px single-line rect (LVGL wraps it into two lines that fit) | `ui-fit.text-overflow` (`["title"]`) |
| `v-clipped` | `ok`'s label pushed 22 px down, past the button's bottom edge | `ui-fit.text-clipped` (`["ok"]`) |
| `v-dots` | a long text in a 60 px DOTS label | `ui-fit.full-string-shown` (`["body"]`) |
| `v-unmeasurable` | a drop shadow on the body label | `ui-fit.fit-unmeasurable` (`["body", "facts"]`) |
| `v-glyph` | the body text "Й" in Montserrat 14 | `ui-fit.glyph-missing` (`["body"]`) |
| `v-unmatched` | a button in the scene that is not drawn | `ui-scene.stage-unmatched` (`["scene", "ghost", "absent"]`, error) |
| `v-toggle` | BG and EN drawn with the same fill (tokens still differ) | `ui-scene.toggle-group-indistinct` (`["language", "bg"]`) |
| `v-text` | the body text drawn as "All clean" for the scene's "All clear" | `ui-scene.stage-text-mismatch` (`["scene", "body"]`) |
| `v-shrunk` | the body text drawn in a font with a 10 px line (the style's is 16) | `ui-fit.font-shrunk` (`["body"]`) |
| `v-modal` | a CORRECT modal dialog: a full-window panel with `I`, an opaque dialog card, its Close button | none (R5) |

`selftest/ui_judges.sh` builds the probe in release and san, replays the paths with both judges and `--today
2026-11-16`, and checks: per variant exactly the findings above, their ids recomputed from identity and state key;
nothing in the clean state nor under `v-modal`; one `checks-examined` per judge with every check above 0 and no
`check-vacuous`; the summary's `<gate>.<check>` counts; byte-identical findings and evidence twice in release, and
release equal to san; every finding replays to its id from its `paths.json`; the exceptions against `--today` (a live
one turns its finding into info, an unused one with a visited target and an expired one are errors, one whose target
never appears is info); exit 2 without a contract, without `--today`, with an unknown judge, a malformed date, or
`--today` without `--judges`; no canary probe is left.

## Each check seen failing against a broken judge

Each line was applied to the judge, the unit tests (`gate/tests/test_ui_judge_*.py`, the real-transcript test
included) were run and failed, and the change was reverted (the U06 report lists the failing tests):

| Check | Deliberate break |
|---|---|
| occluded-target | `if (layer and covered == ...) or (not layer and covering):` -> `if False:` |
| occluded-target, layer part | a layer needs any point (`covered == set(probe.points)` -> `covered`) |
| R5 inertness | `Context.inert` returns `"I" in node.flags` only |
| overlay-policy | the capture loop always `continue`s |
| touch-target-small | `w < need or h < need` -> `and` |
| target-spacing | `gap2 < hard * hard` -> `gap2 < 0` |
| node-out-of-bounds | the window test -> `if False:` |
| node-out-of-bounds viewport | `_in_viewport` returns False |
| text-overlap | `intersect(...) is not None` -> `is None` |
| font-below-min | `size < minimum` -> `size < minimum - 1` |
| hierarchy-violated | the ratio test without `k` |
| hierarchy pending | importance pending returns before `single-size` |
| raw-text | `label == b""` -> `label == b"-"` |
| wrap-policy-undeclared | `if not rows:` -> `if False:` |
| toggle-group-indistinct | `len(set(values)) != 2` -> `len(set(values)) > 2` |
| text-overflow | `natural_w > owner.w` -> `> owner.w + 1` |
| font-shrunk | `line_h < lines[style]` -> `line_h < lines[style] - 1` |
| text-clipped | `fit.clipped` -> `False` |
| full-string-shown | `label.dotted` -> `False` |
| fit-unmeasurable | `fit is None or fit.unsupported` -> `fit is None` |
| glyph-missing | `missing > 0` -> `missing > 1` |
| association rank | equal boxes always ambiguous (`len(found) != len(nodes)` -> `len(found) != 1`) |
| stage-text-mismatch | `ok` taken as True |
| stage-unmatched severity | always info |
| scene-vocabulary | the vocabulary result ignored |
| contract-pending | `Reporter.pending` reports nothing |
| exceptions | `Exceptions.apply` never applies |
| exception-unused visited | always error |
| check-vacuous | never reported |

## Deviations and interface gaps

- **O2 lacks the tree**: no parent, z order, layer, msgid, args, state class or element id in the semantic records. The
  geometric checks read the associated O3 nodes; the checks that need the rest are blocked (above).
- **The scene vocabulary is the gate's** (the orchestrator's rulings R1 to R6); model.h will cite this section.
- **Finding names added**: `stage-unmatched`, `stage-text-mismatch`, `fit-unmeasurable`, `glyph-missing`,
  `scene-vocabulary`, `contract-incomplete`, `contract-pending`, `exception-unused`, `checks-examined`,
  `check-vacuous`. Exceptions may name `stage-unmatched`, `stage-text-mismatch`, `fit-unmeasurable`, `glyph-missing`.
- **`[[style_line]]` uses `oracle:` provenance for values read from the C kiosk**, as instructed; docs/ui-contract.md
  defines `oracle:` as "read from the Rust oracle", so the owner should seal another form for these.
- **State identity is the abstraction key** (above), as in the explorer.
- **The explorer offers judges no `ink`, `hit-test` or `crop`**: evidence images are not attached; the records are.
