# The `ui-scene` and `ui-fit` judges (U06, U24, P004 3.1, 3.2)

The third judge, `ui-render` (U07, P004 3.3: what is painted, from lvprobe's ink), has its own page:
[docs/ui-judges-render.md](ui-judges-render.md). Everything below about findings, pending values, exceptions,
`checks-examined` and `check-vacuous` applies to it too.

**What they find today.** On the 23 frames of the real lockers kiosk the judges find six true product defects: banner
scrims no tap can reach (frames 1-4, 15-18), the snackbar's clickable full-window scrim over BG, EN and Done and the
snackbar drawn away from its scene rect (frames 13, 14), the fourth stacked banner's scrim over BG/EN (17, 18), the
clipped Bulgarian licences line (19) and the storage-fault detail drawn as `?40` (22). The contract rows in the block
"ADDED BY THE U06 AGENT" of `products/business-apps/ui/lockers.toml` are unsigned and need the owner's review, row by
row (the list is under "Rows this task added to the lockers contract").

Two judges of `rigor ui-explore` (docs/ui-explore.md) that turn the escaped defect classes "a button under an overlay",
"a target too small", "text that does not fit or is cut", "a toggle that shows no selection" into findings, from the
scene (O2) and the rendered tree (O3), without the oracle. Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_stage.py` | the O3 parser (lvprobe's `node`, `label`, `fit`, `frame` records) |
| `ui_judge_vocab.py` | the scene vocabulary (O2), the typographic role of a style token, the association |
| `ui_judge_contract.py` | the contract tables this task added (`[[style_role]]`, `[[role_wrap]]`, `[[element]]`, `[[style_line]]`), their checks and lookups; the loader takes them from here |
| `ui_judge_context.py` | what one step gives the checks; the stage findings; layers and their sealed policy (R8); inertness (R7) |
| `ui_judge_findings.py` | ids, `contract-pending`, exceptions, `exception-unused`, `checks-examined`, `check-vacuous`, the judge set |
| `ui_judge_scene.py` | the O2 checks of `ui-scene` and `toggle-group-indistinct` |
| `ui_judge_identity.py` | U24: the checks on the scene identity (`required-element-missing`, `value-split`, `raw-text`'s identity parts); the tables they read are `ui_contract_identity.py`'s |
| `ui_judge_geom.py` | the O2 + O3 (geometric) checks of `ui-scene` |
| `ui_judge_fit.py` | the `ui-fit` checks |

```
rigor ui-explore ... --judges ui-scene,ui-fit --contract FILE.toml --today YYYY-MM-DD
```

`--judges` takes distinct names of `ui-scene`, `ui-fit` and `ui-render` (U07; that one also needs `ink`) and needs
`--contract` (docs/ui-contract.md), `--today` (the date the contract's exceptions expire against: the judges never read
the wall clock) and a probe that announces `frame-facts`; otherwise exit 2. `--today` without `--judges` is exit 2 too.
Of the frame records, the judges read `lvprobe`, `frame`, `node`, `label` and `fit`, and ignore `region`, `life` and
`taps` (the tap path of a session's first frame, U05c); any other record type is the gate's error. Selftest:
`selftest/ui_judges.sh` (called by `selftest/ui.sh`) on the canary product `selftest/ui_canary_product/`. Unit tests:
`gate/tests/test_ui_judge_*.py` over hand-built observations (`test_ui_judge_helpers.py` writes O2 and O3 lines as the
probe writes them), and `test_ui_judge_lockers.py` over the 23 frames of the real kiosk.

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
| `importance`, `input_policy`, `wrap_policy` | `-` by design: the judges take importance from the importance table by typographic role, the wrap scope from `[[element]]` (by scene key) or else `[[role_wrap]]` (by typographic role), and the layer policy from the sealed `[[input_layer]]` table (R8). A present value must be a level `1`..`9`, a policy (`pass-through`, `capture-modal-inert`, `capture-and-dismiss`) or a `[[wrap]]` scope, else `scene-vocabulary`; one that contradicts the contract is a finding of the check that reads it |

Interactive: an intent, `enabled` 1, neither `I` nor `D`. Shown (O2): no `H`.

**Layers (R6, R8).** A node of role `scrim`, `dialog`, `banner` or `snackbar` is the layer; a card that follows a
scrim is judged through that scrim (one layer: the scrim and its card), and a scrim's card is the next scene node when
its role is a card role. The policy is the SEALED `[[input_layer]]` table's: the rows of the layer's role (a scrim:
of its card's role) are the row named the role and the rows named `<role>_...` (lockers: `dialog`; `snackbar`;
`banner_notice` and `banner_persistent`). `blocks_input_below = true` is capture-modal-inert, `false` pass-through.
Rows of one role that disagree, or none, are `contract-incomplete` (`input-layer`, the role); a scrim the scene follows
with no card is `overlay-policy` part `no-card`. No policy is decided by the gate or in the scene.

**Inertness (R7, P004's "declared modal blocker").** An interactive node is inert when it carries `I`, or when it lies
under a capture-modal-inert layer whose rendered scrim (the scrim, or a card without one) is painted later, clickable,
drawn with a background opacity above 0 (`bg_opa_drawn`: the "visibly dimmed" proxy from the rendered facts) and
covers every probe point of the node (the grid points, and with the ppi the corners of the probe disc's bounding box
inside the node; a box larger than the disc errs towards "not inert"). A bare `I` panel grants nothing: the reviewer's
transparent inert panel over frame 17 now silences nothing (`v-fake-inert`). The real kiosk's dialog scrim (full
window, clickable, opacity 82) makes the keys, the language switch and the banners under it inert.

## Scene to rendered (the association)

There is no key in the frame records. Every scene node but the root (role `root` is the screen and is associated with
nothing) is paired with a rendered node, never a screen or layer root, by its rect: the scene rect
`(x, y, x + w - 1, y + h - 1)` must be the rendered box exactly. Scene nodes with the same rect are paired by rank (the
k-th of them in scene order with the k-th rendered node of that box in walk order) when both counts agree AND every
pair is compatible: a `button` or `key` needs an `lv_button`, a `text` or `countdown` a label, a card (`dialog`,
`banner`, `snackbar`) a drawn background, a node with an intent a clickable object. Otherwise every scene node with that
rect is `stage-unmatched` (`ambiguous`; `absent` when no rendered node has it); swapping a scrim and its card in the
scene makes both ambiguous, never a silent wrong match. `stage-unmatched` is an ERROR for an interactive node or a
layer, info otherwise, and names the rendered candidates (class and box) that carry its text (a label, or the control
whose child it is) or, for a node without text, the free rendered nodes compatible with it; its `scene_box` is the
scene's rect. A paired node whose label is not the drawn text (a label's own text, `full_text` when dotted; for any
other node either an empty label or the own text of exactly one direct label child) is `stage-text-mismatch` (error),
unless its `[[element]]` row says `label = "accessible"` (the kiosk's echo panel, key 13, ui-look.md L259/L262).
A shown rendered label with a text that no scene node owns is `stage-unmatched` (info, `side` `frame`); a shown,
CLICKABLE rendered node no scene node has, and not part of a scene button or key, is `stage-unowned-target` (error): a
control the scene does not know (the drawn snackbar card and its Dismiss on the real frames 13, 14). Rendered nodes
without a scene node are named by class, box and the first 8 hex of the sha256 of their text (target
`node/<class>/<x1>/<y1>/<x2>/<y2>[/<8 hex>]`), never by walk index.

## What a judge reads, per check

| Check | Gate | Stage | Contract |
|---|---|---|---|
| `touch-target-small` | ui-scene | O2 | `touch_min_dp`, `[[role_min]].touch_dp_min` of the typographic role; `touch_min_mm` with the ppi |
| `font-below-min` | ui-scene | O2 | the style's `type_scale` size, `[[role_min]].font_px_min` |
| `hierarchy-violated` | ui-scene | O2 | the style sizes; `[[importance]]`; `hierarchy_ratio_k` |
| `raw-text` | ui-scene | O2 (+ identity, U24) | none for the empty part (roles `text` and `countdown`); `[[catalogue]]` (`msgids`, `text_roles`), `[[identity_literal]]` for the identity parts |
| `required-element-missing` (U24) | ui-scene | O2 + O3 + identity | `[[state_class]]` (`required`) |
| `value-split` (U24) | ui-scene | O2 + O3 + identity | `[[value]]` (`element`, `max_nodes`) |
| `identity-role-mismatch` (U24 fix-up 1) | ui-scene | O2 + identity | `[[role]]`, `[[style]]`, `[[style_role]]` (the gate's typographic role) |
| `wrap-policy-undeclared` | ui-scene | O2 | `[[element]]` `wrap`, `[[role_wrap]]` |
| `toggle-group-indistinct` | ui-scene | O2 + O3 | `[[toggle_group]]` (members, `marks`), `[[element]]` |
| `occluded-target` | ui-scene | O2 + O3 | `probe_grid_pct`; the disc: `probe_disc_radius_mm` with the ppi; `touch_min_dp` (a layer's free square) |
| `overlay-policy` | ui-scene | O2 + O3 | the sealed `[[input_layer]]` |
| `target-spacing` | ui-scene | O2 + O3 | `hit_overlap_allowed`; `spacing_hard_mm`, `spacing_recommended_mm` with the ppi |
| `node-out-of-bounds` | ui-scene | O2 + O3 | `window.width_px`, `height_px` |
| `text-overlap` | ui-scene | O2 + O3 | none |
| `text-overflow` | ui-fit | O2 + O3 | the scope (`[[element]]`, `[[role_wrap]]`), `[[wrap]]` |
| `font-shrunk` | ui-fit | O2 + O3 | `[[style_line]]` (a product baseline) |
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
number of VERDICTS it reached, in total and per state (by abstraction key; the largest count of a key's visits), so a
later wiring task can require it to be above 0. A node the check skipped for a pending or missing contract value, or
whose scope makes the excess intended (`text-overflow` with an ellipsis or clip scope), is no verdict. A check that
reached no verdict in any visited state while the contract declares what it applies to is `check-vacuous` (error):
`touch-target-small`, `occluded-target`, `target-spacing` apply when a `[[role_min]]` row has a touch minimum;
`overlay-policy` when `[[input_layer]]` has a row; `toggle-group-indistinct` when `[[toggle_group]]` has one;
`required-element-missing` when `[[state_class]]` has one and `value-split` when `[[value]]` has one (U24: both only in
a run whose probe announces `identity`, the only runs that count their verdicts); every other check when `[[role]]` has
one.

**`check-blocked`** (U24, error, `state` null, identity `["blocked", check]`, observed `{check, needs: "identity"}`):
in a run whose probe does NOT announce `identity`, once per identity check that applies to the contract
(`required-element-missing` with a `[[state_class]]` row, `value-split` with a `[[value]]` row, `raw-text` with a
`[[catalogue]]` row: its identity parts). Never a silent pass: such a run cannot pass the judge. The blocked checks are
neither counted in `checks-examined` nor `check-vacuous`. A caller of `JudgeSet` that does not say whether the probe
has identity (the unit tests' direct use) gets neither.

## Pending values and exceptions

**Pending.** `contract-pending` (severity `ui_contract.PENDING_SEVERITY`, error; `state` null; identity `[check, entry]`,
so one per check and entry per run) skips exactly what needs the value:
- the ppi (`panel.diagonal_in`): the mm part of `touch-target-small`, the mm gaps of `target-spacing`, the probe disc of
  `occluded-target` (and its R7 corners); every scene-unit part runs;
- the importance table: the `level`, `levels`, `rank` and `ratio` parts of `hierarchy-violated`; `single-size` needs
  neither and runs; `hierarchy_ratio_k`: the `ratio` part only;
- (no row of the tables this task added may be pending: where the spec does not decide, the row is absent and the
  node is `contract-incomplete`, an error naming the role, ruling R9).

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
- **`hierarchy-violated`** (O2, per state). `single-size` (two or more roles, one size); with the importance table:
  `level` (a level in the scene that is not the contract's; `-` is normal), `levels` (more than 3), `rank` (a node of
  another level larger than the smallest level-1 node); with k too, `ratio` (exact with fractions).
- **`raw-text`** (O2). A shown node of role `text` or `countdown` whose label is empty (part `empty`). With the scene
  identity (U24) also, for such a node: part `msgid`, its label equals its msgid byte for byte and the msgid is no
  `[[identity_literal]]` row, where every `[[catalogue]]` declares `msgids = "key"` (with `source-text` msgids, as
  gettext's, a label equal to its msgid is right in the source language and raw in another only when the msgid has a
  translation there: that needs the catalogue, U17b, so the node is counted not applicable); part `no-msgid`, it has a
  label and no msgid while its typographic role is in the `[[catalogue]]`'s `text_roles`. One verdict per node, as before;
  (fix-up 1) `no-msgid` also judges every other shown text-bearing node (a button's or key's label) whose typographic
  role is listed, one verdict each: the canary lists no button role, so it gives no new finding there.
- **`required-element-missing`**, **`value-split`**, **`identity-role-mismatch`**, **`state-class-unstable`** (U24, on
  the probe's scene identity): [docs/ui-judges-identity.md](ui-judges-identity.md).
- **`wrap-policy-undeclared`** (O2 + contract). The declaration lives in the contract (R4, R9): a shown text node takes
  its scope from its `[[element]]` row's `wrap` (by scene key), else its role's `[[role_wrap]]`; a node with neither is
  `contract-incomplete` (`role-wrap`, the role; error, once per run). The check judges every node with a scope and
  reports a scope the scene states that is not the contract's (part `contradicts`).
- **`toggle-group-indistinct`** (O2 + O3, one state). The members' scene keys come from `[[element]]`; when any member
  is shown, all must be present, shown and associated (part `members`); for each declared mark (`bg`, `bg_opa`, `style`)
  exactly one member differs from the others, which are all equal (2 members: they differ).
- **`overlay-policy`** (O2 + O3, per layer with a sealed policy; it runs before `occluded-target`). (a) capture-modal-
  inert over an enabled control with an intent painted below it, unless the control is inert (R7): part `captures`,
  basis `sealed`; (b) pass-through, but the layer's rendered scrim or card is clickable over an interactive, not inert
  control: part `captures`, basis `rendered` (the real snackbar: the sealed row says it does not block input below,
  the drawn full-window scrim does); (c) a policy the scene states that is not the sealed one: `contradicts`; (d) a
  clickable rendered node in no layer and not part of any scene node over an interactive node: `undeclared`; (e) a
  scrim without a card: `no-card`. **One cause, one finding:** a capture this check reports is its own;
  `occluded-target` does not count that layer's nodes over that control.
- **`occluded-target`** (O2 + O3). An interactive, not inert node, any of whose probe points lies under a covering node:
  a rendered node painted later that is not its ancestor and not its own part (a descendant counts only when another
  scene node is associated with it), not part of a layer whose capture of it overlay-policy reported, and that is
  shown and clickable, draws a background opacity above 0, has a background image, or is a label whose drawn glyphs are
  there (its visible box, cut by the display and its clip chain). Probe points: x1 + floor(w x p / 100) (at most x2)
  for p in `probe_grid_pct` and 50, the same for y; the disc: a covering region within `mm_to_px(probe_disc_radius_mm)`
  of the centre inside the box (exact geometry). For a scrim with an intent (its tap area is what its card leaves free):
  part `layer-unreachable` when no free square of `touch_min_dp` fits in its visible box once the covering regions are
  taken out (exact: a free square slides left and up to a box or obstacle edge, so those corners are the candidates).
- **`target-spacing`** (O2 + O3). Two interactive, not inert nodes with distinct intents that are not layers whose boxes
  share a pixel (unless `hit_overlap_allowed`); with the ppi, an edge-to-edge gap below `spacing_hard_mm` (error) or
  `spacing_recommended_mm` (info).
- **`node-out-of-bounds`** (O2 + O3). A shown node with an area whose box is not inside the window, or not inside its
  parent when the parent is not a root; a node in a scrolling viewport is not judged (an ancestor that is lvprobe's
  scroll context other than a root, or whose scene node carries `S`).
- **`text-overlap`** (O2 + O3). Two shown text-bearing nodes with a typographic role and a text, in the same layer,
  neither an ancestor of the other, whose boxes share a pixel.

### ui-fit (P004 3.2)

Every shown label with a text, in walk order:
- **`fit-unmeasurable`** (error): `unsupported`, or no `fit` record; nothing else is judged on it.
- **`glyph-missing`** (error): placeholder glyphs (`missing` above 0).
- **`text-clipped`**: lvprobe's `clipped`, unless the owner's scope declares `clip`.
- **`full-string-shown`**: LVGL's dots (`dotted`), unless the owner's scope declares an ellipsis. (A text that is not the
  scene's formatted string is `stage-text-mismatch`.)
- **`text-overflow`** (owned, with a scope): a `wrap = none` scope: the natural width above the owner's `w`; a wrapping
  scope: the laid-out height above the owner's `h`, or more lines than `max_lines` (0: no cap); an `ellipsis` or `clip`
  scope makes the excess intended (no verdict). Measured at the font the label is rendered with.
- **`font-shrunk`** (owned): the label's line height below the `[[style_line]]` line height of the owner's style. That
  table is a REGRESSION BASELINE read from the product under test (`product-baseline:<commit>`), not a spec value: the
  finding carries `basis` (the provenance) and `baseline_line_h`, and the table needs the owner's signature. A style
  without a row is `contract-incomplete` (`style-line`).

## The real kiosk (`gate/tests/test_ui_judge_lockers.py`)

The judges over the 23 frames of business-apps `apps/lockers/lkapp/uimodel/tests/screens.out` (commit `f1274bf`;
`gate/tests/data/ui_judge/lockers-screens.{in,out}`, digests in `SHA256SUMS`; to refresh, copy both files, rewrite
`SHA256SUMS` and re-classify), with `products/business-apps/ui/lockers.toml`. No `scene-vocabulary`, no
`check-vacuous`. The test asserts every finding's check, subject, part and severity. Classified, with the check that
owns each cause:

| Frames | Finding (part) | Owner | Class |
|---|---|---|---|
| 1-4, 15-18 | `occluded-target` (`layer-unreachable`) on the banner scrims 296, 280, 264, 272, 288 | occluded-target | **true product defect**: the scrim carries the dismiss intent but its card has the same rectangle, so no tap reaches it (the known defect of the persistent banners' tap-outside, business-apps docs/lockers/ui-model.md) |
| 13, 14 | `overlay-policy` (`captures`, basis `rendered`) `320/11`, `320/12`, `320/16` | overlay-policy (occluded-target does not repeat it) | **true product defect**: the sealed `snackbar` row says a snackbar does not block input below; the drawn full-window scrim is clickable over BG, EN and Done |
| 17, 18 | `overlay-policy` (`captures`, basis `rendered`) `288/11`, `288/12` | overlay-policy | **true product defect**: the fourth stacked banner's clickable scrim lies over the BG/EN switch |
| 13, 14 | `stage-unmatched` 321 (card, error), 323 (Dismiss, error; candidate the drawn lv_button), 322, 326 (info), three unowned labels (info); `stage-unowned-target` for the drawn card 128,626-1151,791 and its Dismiss (error) | the stage findings | **true product defect**: the snackbar is drawn at 128,626-1151,791, not at the scene's 360,476 560x300 (notice parts ignore the scene rect) |
| 19 | `text-clipped`, `text-overflow` (`height`) on 8 | ui-fit | **true product defect** (X2): the Bulgarian licences line needs two 18 px lines in a 20 px row |
| 22 | `stage-text-mismatch` on 5 | the stage | **true product defect**: the storage-fault detail is drawn as `?40` |
| most | `contract-incomplete` `role-wrap`: key_label (the notice Dismiss keys), muted_caption (the countdowns), screen_headline, staff_strong (Inspected, Blocked), large_countdown | the stage | **contract gap**: ui-look.md 5 decides these nodes' wrapping by node, and no spec line names their keys, so no row can be written; the owner decides |
| every frame | `contract-pending` (q9 the panel: the disc, the mm parts; q7 the importance table) | | **consequence of pending contract values** |

No false positive remains. The rejection dialog (frames 5, 6, 11, 12) gives no `occluded-target` and no
`overlay-policy`: its scrim is a capture-modal-inert layer's dimmed, clickable scrim over every key (R7). The digits
echo panel (key 13) is not a mismatch because its `[[element]]` row declares its label accessible only.

Verdicts on the 23 frames (`checks-examined`): occluded-target 172, overlay-policy 26 (layers with a sealed policy),
touch-target-small 238, target-spacing 154, node-out-of-bounds 466, text-overlap 351, font-below-min 357,
hierarchy-violated 357, raw-text 137, wrap-policy-undeclared 299 (text nodes with a scope), toggle-group-indistinct 36;
text-overflow 294, text-clipped, full-string-shown, fit-unmeasurable and glyph-missing 357 each, font-shrunk 350.

## Seen by a reader, not by a check

What a reviewer saw in the real records that no check of these judges covers (reported, not fixed):
- **Frames 15-18**: the opaque banner cards cover the welcome headline and subtitle. Text under another layer is the
  later `ui-render.covered-node` check's; `text-overlap` compares texts within one layer only.
- **Frames 9, 10, 13, 14**: the hero number "82" is two text nodes ("8" and "2"). `value-split` is blocked (below).
- **Frames 5, 6, 11, 12**: the dialog scrim is drawn with background opacity 82 where ui-look.md L73 says black at alpha
  `0x99` (153). A sound check would need a contract row for the scrim's opacity (the sealed contract has no colour or
  opacity table, and adding one is the owner's); not implemented.
- **Frames 13, 14, in the SCENE**: the snackbar card (360,476-919,775) overlaps BG/EN (y 511..558) and Done (567..622)
  on the Opened screen; once the render follows the scene, those controls will be covered. The judges see the
  rendered geometry, where the card is elsewhere.

## Honesty table

| Check | Status | Why / what is missing |
|---|---|---|
| `occluded-target` | implemented (grid; disc pending while `panel.diagonal_in` is; a layer's free square) | Coverage is lvprobe's per-node facts, not ink (this judge reads no ink; ui-render does, docs/ui-judges-render.md). Not counted as covering (false negatives): borders, outlines and shadows only; an `lv_image`'s own image, an arc, bar, line or any other widget's own drawing; a gradient without a background opacity. A background drawn under an `opa_layered` ancestor (`bg_opa_exact` 0) counts when its drawn opacity is above 0. LVGL's extended click area is not modelled |
| `overlay-policy` | implemented: sealed and rendered halves | "visibly dimmed" is judged by the proxy the rendered facts give (a background opacity above 0 on the clickable scrim, R7), not by luminance; the hit-test injection half is `ui-input`'s |
| `touch-target-small` | implemented (dp; the mm floor while the ppi is pending is contract-pending) | The keypad (20 mm) and button (16.5/19 mm) floors are not applied: the contract has no role-to-target-class table (and Q10 is pending) |
| `target-spacing` | implemented (overlap; mm gaps pending while the ppi is) | rendered boxes, not LVGL's extended click areas |
| `node-out-of-bounds` | implemented | a declared clip container is not excused: the vocabulary has no clip flag (S is scroll) |
| `text-overlap`, `font-below-min`, `raw-text` (empty) | implemented | |
| `hierarchy-violated` | implemented; in lockers only `single-size` runs (Q7 importance, Q5 k) | prominence is the style's font size only (P004 gap G2) |
| `wrap-policy-undeclared` | implemented from the contract (R4, R9): the contradiction | a node without a scope is `contract-incomplete`; in lockers the roles key_label, muted_caption, screen_headline, staff_strong and large_countdown have nodes no spec line gives a scope |
| `toggle-group-indistinct` | implemented within one state | `exactly_one` (which member is selected) is not checked: X is not emitted |
| `text-overflow` | implemented at the **rendered** font | the declared font is not measured: lvprobe maps no font; `font-shrunk` reports a rendered font smaller than the style's |
| `text-clipped`, `glyph-missing`, `fit-unmeasurable` | implemented | lvprobe's `clipped` does not model occlusion, corner masks or transforms |
| `full-string-shown` | implemented: dots; the comparison with the formatted string is `stage-text-mismatch` | |
| `font-shrunk` | implemented as a REGRESSION check | `[[style_line]]` is read from the product under test (`product-baseline:f1274bf`) and needs the owner's signature: it catches a font that becomes smaller than at that commit, not one that is already wrong (no spec value exists to compare with: the spec gives sizes, not line heights; font ids are not mapped). It compares line heights, so a smaller font with the same line height is not seen |
| `value-split` | implemented (U24) with the probe's identity; `check-blocked` without it | counts the DRAWN nodes that are one element (by the gate's role for a role id, else the product's tag); whether nodes of another element id are the digits of the same value is the product's claim. The lockers kiosk has no `[[value]]` row yet (the owner's) and its adapter no identity yet (a product task) |
| `required-element-missing` | implemented (U24) with the probe's identity; `check-blocked` without it | presence is gate-observed (fix-up 1: associated, shown, a non-empty visible box, a drawn non-empty label); which node IS the element is the gate's role for a role id and the product's tag for any other id (`numpad`, `dismiss`, `done`, ...: a product could tag a wrong but drawn node, which no check sees). "Every report section under the all-sections fixture" (P004 3.1) needs that fixture (a later task) |
| state class (`state` of identity) | **the product's claim** | the gate cannot derive the class of a screen; what binds it today: the class must be a `[[state_class]]` row (else `contract-incomplete`), one abstraction key has one class in a run (`state-class-unstable`), and the class's `required` elements must be drawn, the role ids among them by the gate's own role. A product that names a class with fewer requirements than its screen has is not caught (a later oracle task: `ui-parity`'s screen inventory) |
| `identity-role-mismatch` | implemented (U24 fix-up 1) | only for tags that name a role id; other element ids cannot be checked against the scene |
| `raw-text` (raw msgid) | implemented (U24) where decidable from identity: `msgid` (label == msgid, key msgids, no identity-literal) and `no-msgid` (catalogue text without a msgid) | **blocked on the catalogue (U17b)** for `source-text` msgids (lockers' gettext catalogues): a label equal to its msgid is raw only in a language where the msgid has a translation; also a label that is another msgid, or the right msgid formatted with the wrong arguments (`render-text-mismatch`, `i18n_format`) |
| `phrase-too-long` | out of scope | a product build check (P003) |
| `stage-unmatched`, `stage-text-mismatch`, `stage-unowned-target`, `scene-vocabulary`, `contract-incomplete`, `contract-pending`, `exception-unused`, `checks-examined`, `check-vacuous` | implemented | the judges' own findings |

## The historic defects (P004 1.1)

| # | Defect | Checks that catch it | Canary reproduces the mechanism? |
|---|---|---|---|
| F2 | Pad shows no digits | the content half: `required-element-missing` (U24) once the lockers contract requires the echo of a welcome state with digits (the `code_echo` element; P004 3.1 "the entered-code echo on Welcome when pad_len > 0" needs a state class of its own, the owner's) and `ui-parity`; the render half is `ui-render.invisible-node` (the real kiosk now paints its dots) | the mechanism yes: `v-missing` (a state class without a required element) |
| F3 | Banner covers key "1"; its scrim swallows the first tap | `overlay-policy` (a layer that takes the taps: sealed, or rendered clickable over a control; an undeclared clickable scrim), `occluded-target` (a card drawn over the key's probe points; `layer-unreachable` for a scrim whose card leaves no free square) | yes: `v-overlay` (a modal layer over an enabled, non-inert button), `v-unreachable`; and on the real frames 13, 14, 17, 18 (rendered clickable scrims over controls) |
| F5 | "82" as two glyph labels in one font | `font-shrunk` for the font (the real kiosk now draws them at the display style); the split: `value-split` (U24), once the adapter gives both nodes the element `hero_number` and the contract has its `[[value]]` row | `v-shrunk` for the font; `v-split` for the split (the title, one value, as two text nodes) |
| F6 | Countdown clipped (20 dp row, 36 px line) and in m:ss | `text-clipped`, `text-overflow` (height); the format: blocked (no msgid) | partly: `v-clipped` (a label cut by its parent), `v-overflow` (width); the short row is in the unit tests |
| F8 | Bulgarian subtitle cut mid-sentence | `text-overflow`, `text-clipped`, `wrap-policy-undeclared` | yes: `v-overflow`, `v-wrap` |
| F9 | BG/EN toggles show no selected state | `toggle-group-indistinct` (fill and token) | yes: `v-toggle` |
| F10 | Splash has no version line | `required-element-missing` (U24), once the lockers `splash` row requires a version element (today it requires `screen_headline` only: the owner's) and the adapter reports identity | yes: `v-missing` (the `detail` class without its required body) |
| F11 | Report without columns; clipped caption rows | the clipped rows: `text-clipped`, `text-overflow`; the missing content: `required-element-missing` (U24) once the `report` row lists the columns and the adapter reports identity | partly, as F6; the missing content as `v-missing` |
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

A 320x240 LVGL app (`canary.c`) with a model adapter (`model.c`) built through `c_ui_probe`; it has no pointer entry
(`uim_pointer_supported()` is false) and no pointer indev of its own; it reports its scene identity (U24:
`uim_identity_supported()` is true; state class `main`, or `detail` for `v-missing`; element ids `title` and `body`,
msgids `canary.*`, the title's number as its argument; its catalogue `requires` `identity`), so its taps go through the indev the probe
creates (`taps probe`) and the explorer reports no `taps-injected` (that finding is for a product that HAS its own indev
but no entry); the app is in the vocabulary of the
real kiosk: structural roles, style tokens (`canary.toml`'s `[[style]]` with `[[style_role]]` variants), flag letters,
`-` for the three policies. Its catalogue `canary.events.toml` (one u1 intent per variant), its contract `canary.toml`
(a 10 inch panel, 40 ppi, everything the judges read decided) and the paths `canary.paths.json`. The clean state is a
title, a body text, two buttons and the BG/EN switch; each variant changes one thing and has its own title, so every
state has its own abstraction key:

| Event | Defect | Findings (identity) |
|---|---|---|
| `v-occluded` | an opaque, non-clickable panel over the right third of `ok` | `ui-scene.occluded-target` (`["ok"]`) |
| `v-overlay` | a translucent, non-clickable `dialog` (sealed capture-modal-inert) over `ok`: it shields nothing, so `ok` is not inert | `ui-scene.overlay-policy` (`["veil", "ok", "captures"]`, basis sealed; occluded-target does not repeat it) |
| `v-small` | `ok` 30 px high (floor 48) | `ui-scene.touch-target-small` (`["ok", "dp"]`) |
| `v-spacing` | `back` right next to `ok` (gap 0 px; 1 mm = 1.57 px) | `ui-scene.target-spacing` (`["back", "ok", "hard"]`) |
| `v-bounds` | a panel past the window's right edge | `ui-scene.node-out-of-bounds` (`["edge", "window"]`) |
| `v-overlap` | the body text moved into the title's rows | `ui-scene.text-overlap` (`["body", "title"]`) |
| `v-font` | the body text in token 8, a 10 px variant style of the role body (minimum 14) | `ui-scene.font-below-min` (`["body"]`) |
| `v-hierarchy` | the body text in token 9, a 24 px variant of body (level 2), larger than the 20 px title | `ui-scene.hierarchy-violated` (`["rank"]`) |
| `v-raw` | the body text empty | `ui-scene.raw-text` (`["body", "empty"]`) |
| `v-wrap` | the body text in the caption style, a role the contract gives no wrap scope | `ui-scene.contract-incomplete` (`["role-wrap", "caption"]`, per run) |
| `v-wrap-contra` | the body text states the scope `single_line`; the contract's is `default` | `ui-scene.wrap-policy-undeclared` (`["body", "contradicts"]`) |
| `v-overflow` | a 272 px title in a 200 px single-line rect (LVGL wraps it into two lines that fit) | `ui-fit.text-overflow` (`["title"]`) |
| `v-clipped` | `ok`'s label pushed 22 px down, past the button's bottom edge | `ui-fit.text-clipped` (`["ok"]`) |
| `v-dots` | a long text in a 60 px DOTS label | `ui-fit.full-string-shown` (`["body"]`) |
| `v-unmeasurable` | a drop shadow on the body label | `ui-fit.fit-unmeasurable` (`["body", "facts"]`) |
| `v-glyph` | the body text "Й" in Montserrat 14 | `ui-fit.glyph-missing` (`["body"]`) |
| `v-unmatched` | a button in the scene that is not drawn | `ui-scene.stage-unmatched` (`["scene", "ghost", "absent"]`, error) |
| `v-toggle` | BG and EN drawn with the same fill (tokens still differ) | `ui-scene.toggle-group-indistinct` (`["language", "bg"]`) |
| `v-text` | the body text drawn as "All clean" for the scene's "All clear" | `ui-scene.stage-text-mismatch` (`["scene", "body"]`) |
| `v-shrunk` | the body text drawn in a font with a 10 px line (the style's is 16) | `ui-fit.font-shrunk` (`["body"]`) |
| `v-modal` | a CORRECT modal dialog: a full-window scrim with an intent, clickable, background opacity 82, then an opaque dialog card with its Close button | none: the background is inert (R7) and the scrim's free bands around the card are reachable |
| `v-missing` (U24) | the state class `detail` (requires title and body) shown without its body text | `ui-scene.required-element-missing` (`["detail", "body"]`) |
| `v-split` (U24) | the title, ONE `[[value]]`, drawn as two text nodes "Canary" and "37", both element `title` | `ui-scene.value-split` (`["title"]`) |
| `v-raw-msgid` (U24) | the body's label is its msgid `canary.body` (the canary's msgids are keys) | `ui-scene.raw-text` (`["body", "msgid"]`) |
| `v-undrawn` (U24 fix-up 1) | the `detail` class with its body in the scene and tagged, but hidden in LVGL | `ui-scene.required-element-missing` (`["detail", "body"]`, undrawn `body`) and `ui-render.flag-mismatch` (`["body", "hidden"]`) |
| `v-tag` (U24 fix-up 1) | the title tagged as the body, a role it lacks | `ui-scene.identity-role-mismatch` (`["title"]`) |
| `v-fake-inert` | the `v-occluded` cover, and over everything a transparent, non-clickable panel with `I` | `ui-scene.occluded-target` (`["ok"]`): a bare I panel grants nothing |
| `v-unreachable` | a scrim with an intent and a banner card with its rectangle | `ui-scene.occluded-target` (`["bscrim"]`, part `layer-unreachable`) |

`selftest/ui_judges.sh` builds the probe in release and san, runs the canary sessions `session.in` and (U24)
`identity.in` (the identity of the clean state and of three identity variants) as the
`c_ui_probe_session` tests `:session_test` and `:identity_test` in both modes, replays the paths with the judges and `--today
2026-11-16`, and checks: per variant exactly the findings above, their ids recomputed from identity and state key;
the part of each finding where a part tells causes apart; nothing in the clean state nor under `v-modal`; one `checks-examined` per judge with every check above 0 and no
`check-vacuous`; the summary's `<gate>.<check>` counts; byte-identical findings and evidence twice in release, and
release equal to san; every finding replays to its id from its `paths.json`; the exceptions against `--today` (a live
one turns its finding into info, an unused one with a visited target and an expired one are errors, one whose target
never appears is info); exit 2 without a contract, without `--today`, with an unknown judge, a malformed date, or
`--today` without `--judges`; U24: without ui-scene no `identity` command is sent, and every one is read after a
step's `env-inputs`; a probe that does not announce `identity` (the canary's greeting with the word removed) is refused
by the canary catalogue (`requires`), and under a copy of the catalogue that does not require it the three identity
checks are `check-blocked` errors and none of them reaches a verdict; no canary probe is left.

## What the lockers adapter must emit (U24)

In [docs/ui-judges-identity.md](ui-judges-identity.md), "What the lockers adapter must emit".

## Rows this task added to the lockers contract (for the owner to sign or reject, row by row)

In `products/business-apps/ui/lockers.toml`, all after the comment "ADDED BY THE U06 AGENT". Provenance cites ui-look.md
by line (`#L<n>`, `/` joins two lines); nothing is decided where the spec is silent:
- `[[style_role]]`: `btn_action` -> `key_label` (L149/L187), `btn_cancel` -> `key_label` (L156/L189),
  `btn_cancel_small` -> `small_button_label` (L156/L190), `btn_lang_on` -> `small_button_label` (L150/L191),
  `btn_lang_off` -> `small_button_label` (L158/L192).
- `[[role_wrap]]`: `hero_number` single_line (L275); `subtitle` (L282), `body` (L285/L287), `report_title` (L289),
  `staff_detail` (L288), `caption` (L289), `error_caption` (L289), `notice_title` (L292/L295), `notice_body`
  (L292/L294), `notice_caption` (L292/L293): `default` (word, no cap).
- `[[element]]`: `lang_bg` 11 and `lang_en` 12, single_line (L207/L296); `code_echo` 13, wrap code_echo, label
  accessible (L259/L262); `numpad_32` .. `numpad_43` (keys 32..43), single_line (L208/L296); `done` 16, single_line
  (L218/L296); `cancel` 17, single_line (L213/L276); `size_48` .. `size_53`, size_button_label (L212/L284); `released`
  20, default (L224/L289); `licenses` 8, default (L220/L290).
- `[[toggle_group]] language`: the key `marks = ["bg", "style"]` (another fill L309, another token L207); the row's
  own provenance (`spec:ui-look.md#6.1`) is the earlier task's.
- `[[style_line]]`: the line height of 19 styles read from the transcript, `product-baseline:f1274bf` (a regression
  baseline, not a spec value): display 229, headline 55, title 45, body 36, body_muted 36, count_large 45, staff 27,
  staff_strong 27, caption 18, caption_muted 18, notice_title 45, notice_body 36, notice_caption 18, btn_key 36,
  btn_action 36, btn_action_small 27, btn_cancel 36, btn_lang_on 27, btn_lang_off 27.
- Removed by ruling R8/R9: every `[[layer]]` row and every pending `[[role_wrap]]` row of fix-up 1.

## Each check seen failing against a broken judge

Each break was applied to the judge, the unit tests (`gate/tests/test_ui_judge_*.py`, the real-transcript test and
`test_ui_contract.py` included) were run and failed (1 to 35 failing tests each), and the change was reverted:

| Check | Deliberate break |
|---|---|
| occluded-target | `if covering:` -> `if False:` |
| occluded-target, layer-unreachable | the free-square test -> `if False and ...` |
| free square | `free_square` ignores the obstacles; the square one pixel short |
| R7: a bare I panel | any other node with I makes the target inert |
| R7: the scrim must be dimmed / clickable | the `bg_opa_drawn > 0` or the `clickable` condition removed |
| R8: policy from [[input_layer]] | every layer capture-modal-inert; a scrim's policy not by its card; disagreeing rows accepted |
| overlay-policy, sealed half | only pass-through layers judged |
| overlay-policy, rendered half | a pass-through layer never captures |
| overlay-policy, captures | the capture loop `continue`s before reporting |
| overlay-policy, no-card | never reported |
| one cause, one finding | overlay-policy does not record its capture (occluded-target repeats it) |
| rank pairing | every equal-box pairing ambiguous; compatibility not checked; a card's background not required |
| stage-unmatched candidates | `candidates` always empty |
| stage-unowned-target | never reported |
| stage-text-mismatch | `ok` taken as True; the accessible exemption for every panel, not by element |
| stage-unmatched severity | always info |
| scene-vocabulary | the vocabulary result ignored |
| wrap scope | the element's `wrap` ignored; `role-wrap` incompleteness not reported |
| wrap-policy-undeclared | the contradiction never reported |
| touch-target-small | `w < need or h < need` -> `and` |
| target-spacing | `gap2 < hard * hard` -> `gap2 < 0` |
| node-out-of-bounds | the window test -> `if False:`; `_in_viewport` returns False |
| text-overlap | `intersect(...) is not None` -> `is None` |
| font-below-min | `size < minimum` -> `size < minimum - 1` |
| hierarchy-violated | the ratio without `k`; importance pending returns before `single-size` |
| raw-text | `label == b""` -> `label == b"-"` |
| U24 (the rows below: `test_ui_judge_identity.py` and `test_ui_explore_identity.py` run, 1 to 3 failing tests each; the C rows `//ui/model:probe_test`) | |
| U24: required-element-missing | a missing element taken as present (`if True: continue`); hidden nodes counted as present; an unknown class not reported |
| U24: value-split | `len(nodes) > limit` -> `> limit + 1`; `max_nodes` ignored |
| U24: raw-text, identity parts | the msgid comparison `False and ...`; `[[identity_literal]]` ignored; source-text msgids judged; `no-msgid` never reported |
| U24: check-blocked | never emitted; the identity verdicts counted without identity |
| U24: grammar and explorer | a repeated key, and a node line without identity, accepted (Python); the key cross-check removed; identity not read; the C grammar accepting a node line without identity, and a second `state` line (`//ui/model:probe_test` fails) |
| U24: loader | a `[[value]]` element that names nothing accepted |
| U24 fix-up 1 (`test_ui_judge_identity_presence.py` too) | presence by the product's claim (no association, shown or box test): 6 failing; any label counted: 2; a role id taken from the tag: 3; identity-role-mismatch never reported: 2; value-split counting undrawn nodes: 2; `no-msgid` skipping buttons: 1; exception targets not seen: 1; state-class-unstable never reported: 1; a second `[[catalogue]]` accepted: 1; a key twice accepted (Python): 2; a model changed by `identity` accepted: 2; the C grammar accepting a key twice (`//ui/model:probe_test` fails) |
| toggle-group-indistinct | `len(set(values)) != 2` -> `> 2` |
| text-overflow | `natural_w > owner.w` -> `> owner.w + 1` |
| text-overflow verdicts | an ellipsis or clip scope counted as a verdict |
| font-shrunk | `line_h < height` -> `< height - 1`; the finding's `basis` dropped |
| text-clipped, full-string-shown, fit-unmeasurable, glyph-missing | each condition broken (`False`, `fit is None`, `missing > 1`) |
| overlay-policy verdicts | a layer without a policy counted as a verdict |
| contract-pending | `Reporter.pending` reports nothing |
| exceptions, exception-unused, check-vacuous | never applied; always an error; never reported |
| loader: product-baseline, element keys | baseline accepted outside style_line; duplicate element keys accepted |

## Deviations and interface gaps

- **O2 lacks the tree**: no parent, z order or layer in the semantic records. The geometric checks read the associated
  O3 nodes. Msgid, arguments, state class and element id come from the scene identity (U24, a call and a probe command
  of their own, docs/ui-model.md "Scene identity"), not from new semantic fields: no recorded transcript changed.
- **U24, `[[catalogue]].msgids`**: the contract's rule "label == msgid and the msgid is not an identity-literal" is
  wrong for a gettext catalogue (msgid = the English text: every correct English label equals its msgid). The decidable
  part is therefore conditioned on a contract row that says the msgids are keys (docs/ui-contract.md); lockers' raw
  msgids stay blocked on U17b.
- **U24, targets**: a `required-element-missing` finding's exception target is the element id, a `value-split`'s the
  value id. Fix-up 1: a state with identity visits the element ids its class requires and every `[[value]]` id, so an
  unused exception of these rules whose target a visited state requires is `exception-unused` error, as for every
  other rule (selftest: `x-element`).
- **The scene vocabulary is the gate's** (the orchestrator's rulings R1 to R6); model.h will cite this section.
- **Finding names added**: `stage-unmatched`, `stage-text-mismatch`, `fit-unmeasurable`, `glyph-missing`,
  `scene-vocabulary`, `contract-incomplete`, `contract-pending`, `exception-unused`, `checks-examined`,
  `check-vacuous`. Exceptions may name `stage-unmatched`, `stage-text-mismatch`, `fit-unmeasurable`, `glyph-missing`.
- **`[[style_line]]` has its own provenance form `product-baseline:<commit>`** (ruling R9), allowed in that table only
  and required there.
- **ui_contract.py is split** (fix-up 3): the tables this task added are in ui_judge_contract.py, the dwell table in
  ui_contract_dwell.py and the consistency checks in ui_contract_checks.py; ui_contract re-exports every public name.
- **State identity is the abstraction key** (above), as in the explorer.
- **The explorer offers judges no `hit-test` or `crop`**: evidence images are not attached; the records are. Since U07
  it takes `ink` once per new abstract state for `ui-render` (docs/ui-judges-render.md).
