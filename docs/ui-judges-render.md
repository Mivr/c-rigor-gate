# The `ui-render` judge (U07, P004 3.3)

**What it finds today.** On the canary every implemented check fires exactly where it is seeded. On the 23 recorded
frames of the real lockers kiosk the stage checks (`flag-mismatch`, `align-mismatch`, `line-height-mismatch`) find
nothing (760, 350 and 350 verdicts). The ink checks reach no verdict there: **the recorded transcript has no `ink`
records** (the session that recorded it never sent `ink`). The first real run with ink belongs to the catalogue task.

The third judge of `rigor ui-explore` (docs/ui-explore.md), after `ui-scene` and `ui-fit` (docs/ui-judges.md, whose
sections on the association, findings, pending values, exceptions, `checks-examined` and `check-vacuous` apply here
unchanged). It judges what is painted: a node that paints no pixel, text with too little contrast, rendered flags,
long mode, alignment and line height that disagree with the scene or the contract tables. It fails closed: what a check
needs and lvprobe did not measure is an error (`ink-unmeasurable`). Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_render.py` | the judge; `invisible-node`, `ink-unmeasurable` |
| `ui_judge_render_contrast.py` | `contrast-low` |
| `ui_judge_render_common.py` | what the ink checks share: the ink a check needs, the opaque cover of a node, R7 for paint |
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

## Ink per new state (the explorer, `ui_explore_run.InkPlan`)

When `ui-render` is selected the explorer takes `ink` (every node of the frame) right after a step's observation, per
**(abstraction key, frame checksum)**: the frame's `crc` separates states the key merges but the render does not
(docs/ui-judges.md, "The abstraction key"). The plan is shared by every path of the exploration:
- a (key, crc) is inked until it has one **usable** ink (the frame did not move under it and at least one node was
  measured), at most twice (the first try and one retry at a later visit; deterministic: discovery order);
- at most **4 checksums per key** (`INK_CRC_CAP`), in discovery order; a key whose frames show more is reported once per
  run as `ink-plan-capped` (info, identity `["capped", key]`, a ui-render run-level finding), so the limit is visible;
- the second run of a path tries exactly the steps the first one tried (`Run.inked`, recorded before the ink, so an ink
  error gives the same pseudo step in both runs), and run-twice compares `ink` and `ink_moved` (`PARTS`).

After the ink the explorer takes `frame` again: an ink whose retry settle flushed drops the probe's frame
(docs/ui-model.md, "Statuses") and the next word may need one. If that frame (without `life` and `taps` lines) differs
from the step's, `ink_moved` is set and the judge reads none of that ink: every node a check needs is `ink-unmeasurable`
(`frame-moved`). A visit without ink runs no ink check (`checks-examined` keeps per state the largest count of a key's
visits). An `ink` error ends the run in a pseudo step `ink`, as an evidence error does.

The tap-node evidence image of a step (`_evidence`) is read BEFORE its ink (fix-up 2), so it is the step's own frame.
An input word after a step whose frame moved under its ink compares against a FRESH snapshot taken just before it
(`ui_explore_run.before_inputs`; `inputs` snapshots when given None), not against that step's stale observation: its
noop, missed and countdown-restart verdicts never blame the input for what moved during the ink (a rare case: one extra
observation's commands). The same holds for the key a `wait-change` word or a t1 until-change event waits to leave
(`ui_explore_run.base_key`, fix-up 3): after a moved ink it is the key of a fresh observation (semantic, deadline, env
inputs), not the stale step's.

**Cost measured on the canary** (36 states, one checksum each, replay of `canary.paths.json`, this 4-CPU host, three
runs each): `--judges ui-scene,ui-fit` 1.23 to 1.34 s, 1138 probe commands; `--judges ui-scene,ui-fit,ui-render` 1.48
to 1.62 s, 1282 commands (+144: one `ink` and one `frame` per state and run, 36 x 2; no retry, no cap). The 36 states
have 372 non-root nodes (10.3 per state); lvprobe refreshes twice per node it inks: about 744 refreshes per run of all
paths, 1488 with run-twice, at 320x240. The real kiosk (1280x800, about 34 nodes per frame) was not measured.

**Known limits** (for later tasks): `strategies.check_cost` does not count the `ink` and the re-taken `frame` of each
new (key, crc), so its budget arithmetic is low by those commands; and the `life` lines of the re-taken frame (lifecycle
events since the step's frame: normally none, ink creates and deletes nothing) are consumed there and lost to a later
lifecycle judge (N6, the ui-time task).

## The checks

Every check keys its target by the scene key (never by walk index); identities are `[key]` or `[key, part]`. **R7 for
what is painted** (`ui_judge_render_common.exempt`, fix-up 2: the context's own `Context.inert` at the four corners
of the node's visible box, exact for a box): a node the scene marks inert (`I`), or whose visible box lies under
a capture-modal-inert layer's rendered scrim (or card without one) painted later, clickable and drawn with a background
opacity above 0 (docs/ui-judges.md, "Inertness"), is NOT APPLICABLE to `invisible-node` and `contrast-low`: counted in
`checks-examined` under `not_applicable`, never a finding (the background of a correct modal is dimmed and covered by
design).

| Check | Layer | Reads | Contract |
|---|---|---|---|
| `invisible-node` | L4 | O2 + O3 + ink | none |
| `contrast-low` | L4 | O2 + O3 + ink | `thresholds.contrast_large`, `thresholds.contrast_text` |
| `ink-unmeasurable` | L4 | ink, O3 | none |
| `flag-mismatch` | L3 | O2 + O3 | the wrap scope (`[[element]]`, `[[role_wrap]]`, `[[wrap]]`) |
| `align-mismatch` | L3 | O2 + O3 (`label` `align_drawn`, `align`; `fit`) | `[[role]]` `align`, `align_banner` |
| `line-height-mismatch` | L3 | O2 + O3 (`label` `line_h`) | `[[style_line]]` (a product baseline) |

- **`invisible-node`** (P004: "changes no pixel"). A shown scene node that must paint (a `text` or `countdown` with a
  non-empty label, a `button` or `key`, a card: `dialog`, `banner`, `snackbar`) whose associated rendered node is shown
  and has a visible box (a label: also one without, a fully clipped text), unless R7 exempts it. The INK decides,
  first for the node, then (a button or key) for the label that carries its text: a count above 0 is no finding,
  whatever covers it (a rounded or transformed cover may not hide it); a count of 0 is
  - `covered` when a later-painted, shown, unrelated node with an exact background opacity of 255 contains the whole
    visible box: the cover is named as the cause (`observed.by`: a scene key, or class, box and text hash;
    `observed.covered` is `node` or `text`);
  - `node` (the node itself) or `text` (the button's or key's text carrier, shown, with a non-empty drawn text, while
    the button's subtree ink is its fill) otherwise.
  A label lvprobe reports `clipped` carries `observed.clipped`. One cause, one finding: when ui-fit is SELECTED and
  reports that label's `text-clipped` (its scope does not declare `clip`), the clipped label is ui-fit's and a counted
  not-applicable here; with ui-render alone, or under a `clip` scope, it is reported here (the canary's `v-clipped`
  label, pushed out of its button, is ui-fit's in the three-judge run). The rule mirrors every early return of
  ui-fit's label rule (a shown label with a non-empty own text, measured). An owner exception on `text-clipped` for a
  target turns ui-fit's finding into info while ui-render still counts that label not-applicable: the exception
  covers the one cause, and nothing else reports it. A label with NO visible box (fix-up 3) is judged only when it is
  not in a scrolling viewport (`ui_judge_geom._in_viewport`: a list row scrolled out of view paints nothing by
  design) and ui-scene, when selected, would not report it `node-out-of-bounds`; otherwise it is a counted
  not-applicable.
  Excluded: scene-hidden (`H`) and rendered-hidden nodes (`flag-mismatch` when the two disagree); panels (below).
- **`contrast-low`** (part `below-large`). For a shown text-bearing node with a typographic role and a non-empty drawn
  text, the ink of the label that carries its text (the label itself, or a button's or key's label child), unless R7
  exempts it (dimmed text under a correct scrim is no finding). Relative luminance is WCAG's (sRGB channels linearised
  with the 0.03928 knee; 0.2126 R + 0.7152 G + 0.0722 B); the ratio `(L1 + 0.05) / (L2 + 0.05)`.
  - **A carrier without a background of its own** (`bg_opa_drawn` 0, no gradient, no image): lvprobe gives two ink
    extremes (`ink_lo`, `ink_hi`: the darkest and lightest pixel drawn WITH the node) and two background extremes
    (`bg_lo`, `bg_hi`: the same pixels WITHOUT it). The contrast is the MAX over the two ink extremes of the MIN over
    the background interval `[min(L(bg_lo), L(bg_hi)), max(...)]` (an ink extreme inside the interval gives 1:1).
    Why this is the conservative side: on the background side the worst case is taken (any background luminance between
    the measured extremes may lie behind some glyph). The ink side cannot be the worst case: an antialiased glyph always
    has edge pixels that blend the text colour with what is behind, so the min over all four extremes is about 1:1 for
    every text (measured on the clean canary: 1.03 to 1.21 for every label, against 8.6 to 16.1 by this rule); the text
    colour is the ink extreme farther from the background.
  - **A carrier with its own exactly opaque, single-colour background** (`bg_opa_exact`, `bg_opa_drawn` 255, no
    gradient, no image): ink is subtree ink, so the fill itself is ink and the background extremes are what is behind
    the LABEL, not behind the text (a `#000`-filled label with `#222` text on white measures 21:1 by the rule above:
    the test shows it). Then what is compared is each ink extreme with the label's own `bg` colour: the extremes are
    the fill, the text colour or a blend of the two, and the result is the max of their two ratios to the fill. That
    is an UPPER bound of the text's contrast (a border, outline or shadow of the label, which the facts do not show,
    could be the farther extreme), so only a value below a threshold is sound: below `contrast_large` it is a finding
    (`observed.against` `own-fill`; `#222` on `#000`: 1.32:1); otherwise no verdict and `ink-unmeasurable` reason
    `own-background`. A carrier with any other background of its own (translucent, inexact, gradient, image) is
    `ink-unmeasurable` (`own-background`) at once.
  - **Thresholds, each read on its own** (`decide`; both comparisons strict below, a ratio equal to a threshold meets
    it): below `contrast_large` (3:1 in the canary) the text fails at any size: a finding. At or above `contrast_text`
    (4.5:1) it passes (`767676` on white, 4.54:1, passes; `777777`, 4.48:1, does not). In between the verdict needs the
    definition of large text (WCAG: 24 px, or 18.66 px bold), which the contract does not have: no verdict, and the
    role is `contract-incomplete` (`["large-text", role]`, once per run). A pending threshold (lockers: q15) is
    `contract-pending`, and the other one still decides what it can (with only `contrast_text` decided a text passes at
    4.5:1 and anything below is no verdict; with only `contrast_large`, anything below 3:1 fails).
  - A carrier whose ink count is 0 is no contrast verdict (`invisible-node`'s).
- **`ink-unmeasurable`** (ERROR; the judge fails closed, as docs/ui-lvprobe.md says). Every node it reports is one a
  check needs: a must-paint node or a text carrier. Reasons: `unstable`, `transformed` (lvprobe's `noink`),
  `frame-moved` (the frame moved under the ink), `own-background` (above). One finding per scene node,
  `observed.unmeasured` lists `[what, reason]` (`what` `node` or `text`). That node is no verdict of the check that
  needed it, so a state where nothing could be measured makes `invisible-node` and `contrast-low` `check-vacuous` (as
  U06's `fit-unmeasurable`); each needed record is a verdict of `ink-unmeasurable` itself. An owner may except it by id
  and target.
- **`flag-mismatch`** (L3). Per associated scene node: scene `H` but rendered shown (part `shown`), no `H` but rendered
  not shown (`hidden`). For a node shown on both sides whose rendered node is clickable: disabled in the scene
  (`enabled` 0 or `D`) is `disabled-clickable` (the real kiosk clears clickable on its disabled buttons, which agrees);
  `I` is `inert-clickable`; no intent is `clickable`, except a layer role (scrim, dialog, banner, snackbar): whether a
  layer's clickable scrim or card takes taps it should not is ui-scene's `overlay-policy`, and a card is clickable by
  design so that a tap on it does not reach its scrim. Per text carrier with a wrap scope: the label's long mode against
  the mode the scope needs (`long-mode`): an ellipsis scope needs DOTS, a clip scope CLIP, every other scope WRAP (a
  `none` scope included: LVGL has no non-wrapping long mode that does not cut the text; a single line that does not fit
  is ui-fit's `text-overflow`). The other direction of P004's "intent <-> clickable", an intent whose rendered node is
  not clickable, is ui-scene's `stage-unmatched` (the association pairs a node with an intent only with a clickable
  object); no second id.
- **`align-mismatch`** (L3). Per text carrier: the alignment LVGL drew (`align_drawn`: 1 left, 2 centre) when lvprobe
  drew the label (a `fit` record, drawn, not unsupported); otherwise the label's `align` style when it is not auto
  (`observed.source` `style`); an undrawn label with an auto style is a counted no-verdict (`not_applicable`: nothing
  says how LVGL would resolve it). Compared with the `[[role]]` `align` of the node's typographic role, or
  `align_banner` when the carrier lies inside the rendered node of a scene `banner` and the role has one. Exact.
- **`line-height-mismatch`** (L3, part `above`). Per owned text carrier: the label's line height ABOVE the
  `[[style_line]]` line height of the owner's style (a regression baseline read from the product,
  `product-baseline:<commit>`; the finding carries `basis`). Below it is ui-fit's `font-shrunk` (one cause, one
  finding). A style without a row is `contract-incomplete` (`style-line`).

## Findings

Schema, ids, `observed` and evidence as docs/ui-judges.md ("Findings"); `gate` is `ui-render`. Layer L3 for
`flag-mismatch`, `align-mismatch` and `line-height-mismatch`, L4 for the ink checks, `meta` for `ink-plan-capped`. Every
finding is an error but `ink-plan-capped` (info: a fact about the run). `checks-examined` lists the six checks and, when
any, `not_applicable` per check; `check-vacuous` applies to each of them when `[[role]]` has a row (the default rule of
docs/ui-judges.md). An exception may name every ui-render finding id but `ink-plan-capped`: `invisible-node`,
`contrast-low`, `flag-mismatch`, `align-mismatch` were in the loader's closed list `EXCEPTION_RULES`; U07 fix-up 1 adds
`ink-unmeasurable` and `line-height-mismatch` (`ink-plan-capped` is info and never passes through an exception, so it is
not in the list; `gate/rigor_lib/ui_contract.py`; a test in `test_ui_judge_render.py` loads an exception for each:
`test_ui_contract.py` would pass the 500-line limit).

## Honesty table (P004 3.3)

| Check | Status | Why / what is missing |
|---|---|---|
| `invisible-node` | implemented (text, button, key, card; parts `node`, `covered`, `text`) | panels are not judged: P004 says "a panel with a non-NONE tone", and no contract table maps a panel's style token to a tone (`[[style]]` rows are typographic). Needs a contract `[[panel_tone]]` table (token -> tone). `covered` takes a cover with a corner radius as covering its whole box (radii are not in the facts) |
| `contrast-low` | implemented in part: the large-text floor exactly; the text threshold only as a pass | the definition of large text (P004 3.10: "3:1 for large text"; WCAG 24 px or 18.66 px bold) is not in the contract schema: needs a contract entry, e.g. `[thresholds] large_text_px` and `large_text_bold_px` with the weight that is bold, in `ui_contract.py` and the owner's contract. Between 3:1 and 4.5:1 `contract-incomplete` `large-text`. A carrier with its own background: a finding only when the upper bound fails, else `ink-unmeasurable` `own-background`. lvprobe chooses the extremes by luma over the encoded channels, not by relative luminance: for pixels of different hues the two orders can disagree (exact for one-colour text on a one-colour background, as on the canary and the kiosk). The state-indicator half ("a state indicator (selection, pressed) < 3:1 against adjacent colours") is blocked: neither the scene nor lvprobe says which pixels are a state indicator and which are adjacent; needs the indicator part per node (model.h) or a contract table of indicator styles |
| `flag-mismatch` | implemented: hidden, clickable (disabled, inert, no intent), long mode | the opacity half ("opacity disagrees with the scene's flags"): the scene has no opacity or visibility-level field (model.h's 14 fields); the intent -> not clickable half is ui-scene's `stage-unmatched`; clickable layers are `overlay-policy`'s |
| `align-mismatch` | implemented, exact | an undrawn label with an auto `align` style is no verdict (counted) |
| `font-size-mismatch` | **blocked**; approximated as `line-height-mismatch` (own id) | P004: "the label's resolved font id/size != the sealed style->font table entry". (1) lvprobe can map fonts (`lvprobe_map_font`) but the probe maps none, so every `label` record says `-` for the font id: needs a model.h entry through which the product names its fonts, e.g. `bool uim_fonts(const lv_font_t **fonts, uint16_t *ids, uint16_t cap, uint16_t *count)`, called by the probe before the first walk; (2) a sealed contract column naming each style's font id (`[[style]] font`, owner's). The line height is not the font size (two fonts of one line height pass), hence its own id |
| `line-height-mismatch` | implemented (approximation of `font-size-mismatch`) | against a product baseline, not a spec value; `font-shrunk` owns the smaller side |
| `covered-node` | **blocked** (ink share); a box approximation is feasible, not done | "share of a node's ink overwritten by a later object" is not computable from the `ink` record: lvprobe's ink is the set of pixels that change when the node is hidden in the FINAL frame, so an overwritten pixel never changes and is absent; the record has no denominator. Needs a lvprobe fact: the node's solo ink count (the pixels that change when it is hidden with every later-painted, unrelated node hidden too), e.g. a 9th `ink` field `solo`; the share is `1 - count / solo`. A box-based approximation IS computable from the node facts alone: the share of a must-paint node's box under the union of later, opaque (`bg_opa_exact`, 255), unrelated, shown nodes' visible boxes (exact area of a union of rectangles), with the R7 exemption; a whole-box cover is already `invisible-node` part `covered`. Not implemented: its threshold ([P] 50%) is not in the contract (`[thresholds]` has no such entry), so it would be a gate-chosen value; it would get its own id, `box-covered-node` |
| `glyph-run-gap` | **blocked** | (1) the threshold ([P] 0.5 em) is not in the contract; (2) an em needs the font size, which the frame facts do not give (only the line height; font ids are unmapped); (3) a "numeric value run" needs the value's extent in the scene (the msgid and arguments, two semantic fields, model.h; docs/ui-judges.md `value-split`). With those, `crop` of the carrier's ink box and a column projection give the gaps |
| `legibility-floor` | **blocked** | needs (1) the rendered x-height per label (a lvprobe `label` field, e.g. the box height of the glyph `x` from `lv_font_get_glyph_dsc`; LVGL fonts carry no x-height), and (2) the ppi and the decided farthest viewing distance (`panel.diagonal_in`, `panel.viewing_distance_mm`: pending q9 in lockers; the canary has them). The "primary content larger by the contract ratio" half needs the importance table (pending q7 in lockers) |
| `diff-render-divergence` | **blocked** | "two fresh renders differ" is the explorer's run-twice (every path in two fresh probes; `frame` with its CRC, and now `ink`, are compared). The diff-path-versus-fresh half needs a model call that forces a full re-render of the current scene, proposed (NOT added): `bool uim_rebuild(uim_t *m)` in model.h, "drop every LVGL object of the scene and build the current scene from scratch, as `uim_open` would, keeping the model state", and a probe command `rebuild`; the gate then compares the frame CRC (and region hashes) after `rebuild` with the one before |
| `render-geometry-mismatch` | = ui-scene's `stage-unmatched` | the association is by exact rect (tolerance 0): a node whose rendered box is not its scene rect is `stage-unmatched` (`absent`, or `ambiguous`), with the drawn candidates (and `stage-unowned-target` for a drawn control the scene does not have); the contract's exception list is `[[exception]]` with rule `stage-unmatched`. Not separable: a node drawn elsewhere and a node not drawn are both `absent` |
| `render-text-mismatch` | partly = ui-scene's `stage-text-mismatch` | U06 compares the drawn text with the scene's formatted label; `i18n_format(msgid, args, lang)` needs the msgid and the arguments of each text node, which the scene does not have (two semantic fields, model.h) |
| `a11y-stage-mismatch` | partly covered | label: `stage-text-mismatch`; rect: the association (`stage-unmatched`); role: the association's compatibility makes a wrong one `ambiguous`; `selected`: blocked (the scene's `X` is not emitted by the real adapter, and lvprobe's `node` record has no checked state: needs `LV_STATE_CHECKED` as a `node` field) |

## The real kiosk (`gate/tests/test_ui_judge_lockers.py`, `LockersRenderTest`)

`ui-render` alone over the 23 recorded frames with `products/business-apps/ui/lockers.toml`: per frame exactly the stage
findings of docs/ui-judges.md (now under `ui-render`, the only selected judge) and nothing else; verdicts
`flag-mismatch` 760, `align-mismatch` 350 (the notice texts inside banners are drawn left, as `align_banner` says, and
centred in dialogs), `line-height-mismatch` 350; `invisible-node`, `contrast-low` and `ink-unmeasurable` 0, so all three
are `check-vacuous` (error), because the transcript has no `ink` or `noink` line (the test checks that too). Nothing was
invented and nothing under business-apps was touched. Seen by a reader: the kiosk's disabled buttons (`enabled` 0, `D`)
are not clickable, its banner, dialog and snackbar cards are clickable without an intent (layers: not a mismatch), and
its scrims are clickable (overlay-policy's). What `invisible-node` part `covered` could say once these frames are
inked (the cover is an O3 fact, computed from the recorded frames with the judge's own `cover_of` and `exempt`; not
asserted by a test, the judge runs only on inked steps; and each of these is a finding only if the node's ink count
is then 0, since a count above 0 is no finding whatever covers it): under the rejection dialog (frames 5, 6, 11, 12) the
dialog card 321 wholly covers BG (12) and keys 35, 38, all EXEMPT by R7 (the dimmed, clickable scrim); in frames 15,
17 and 18 the opaque banner cards wholly cover text 3 (card 297, 273) and 4 (card 289) and, in 17, BG and EN (11, 12,
card 289), not exempt (banners are pass-through): up to six findings of the class docs/ui-judges.md noted by
reading.

## Canaries (`selftest/ui_canary_product/`)

U07 adds twelve variants (intents 24 to 35), each with its own title. The canary draws every label with centred text
(every role of `canary.toml` is `centre`; the loader allows only notice roles to be left-aligned) and the OK, Back and
Close buttons in `0x0D47A1` (white text on it 8.6:1; LVGL's default `0x2196F3` gives 3.1:1, which would be a
`contract-incomplete` `large-text` in the clean state). `session.out` was regenerated for that (colours, alignment,
glyph boxes and checksums only).

| Event | Defect | Finding (identity) |
|---|---|---|
| `v-invisible` | the body text drawn with text opacity 0 | `invisible-node` (`["body", "node"]`) |
| `v-contrast` | the body text `#bbbbbb` on white (1.92:1) | `contrast-low` (`["body", "below-large"]`, against `behind`) |
| `v-disabled` | Back disabled in the scene (`enabled` 0, `D`), clickable in LVGL | `flag-mismatch` (`["back", "disabled-clickable"]`) |
| `v-click` | the body label clickable, no intent | `flag-mismatch` (`["body", "clickable"]`) |
| `v-hidden` | the body label hidden in LVGL, shown in the scene | `flag-mismatch` (`["body", "hidden"]`) |
| `v-long` | the body label in CLIP mode, its scope `default` wraps | `flag-mismatch` (`["body", "long-mode"]`) |
| `v-align` | the body text left-aligned, its role centred | `align-mismatch` (`["body"]`) |
| `v-line` | the body text in a font with a 20 px line (baseline 16) | `line-height-mismatch` (`["body"]`) |
| `v-noink` | the OK button scaled by 257/256 (a transform) | `ink-unmeasurable` (`["ok"]`, error) |
| `v-covered` | an opaque object the scene does not have over the whole title | `invisible-node` (`["title", "covered"]`) |
| `v-btn-text` | OK's label with text opacity 0 (the button's fill still paints) | `invisible-node` (`["ok", "text"]`) |
| `v-fill` | the body label with an opaque `#000` fill and `#222` text | `contrast-low` (`["body", "below-large"]`, against `own-fill`) |
| `v-dots` (U06) | the body label in DOTS mode | besides ui-fit's `full-string-shown`: `flag-mismatch` (`["body", "long-mode"]`) |
| `v-modal` (U06) | a correct modal dialog | nothing: the background is not applicable (6 nodes for `invisible-node` and for `contrast-low`) |

`selftest/ui_judges.sh` runs the three judges together on all 36 states and asserts per variant exactly the findings of
both tables (docs/ui-judges.md and this one), the recomputed ids, the parts, nothing in the clean state nor under
`v-modal`, three `checks-examined` with every check above 0, no `check-vacuous`, every finding an error, the summary
counts (`ui-render.flag-mismatch` 5, `ui-render.invisible-node` 3, `ui-render.ink-unmeasurable` 1), byte-identical
findings and evidence twice in release and release equal to san, every one of the 38 findings replayed to its id, a
live exception of a ui-render check (`x-invisible`), exit 2 for a contract whose `[[input_layer]]` row is misnamed
(`bnner`), and (fix-up 1, S8) one run with `--judges ui-scene,ui-fit` through a probe wrapper that logs every command:
no `ink` command is sent, and its findings equal the ui-scene and ui-fit findings of the three-judge run (evidence lists
aside). Its log names are deterministic (per step and output variable, per platform).

**Selftest expectations changed by fix-up 1** (each a strengthening or a consequence of a new check): `v-noink`'s
`ink-unmeasurable` is an error (was info; the "all errors but ink-unmeasurable" assertion is now "all errors");
`v-invisible`'s identity gains its part (`["body", "node"]`); three new variants; states 33 -> 36, replayed findings
35 -> 38; the `x-invisible` exception's finding is selected by its target `body` (there are now three
`invisible-node` findings); the new S8 step.

## Each check seen failing against a broken judge

Each break was applied to the code, `gate/tests/test_ui_judge_render.py` (and, from fix-up 2,
`test_ui_judge_render_explore.py`), `test_ui_judge_lockers.py`, `test_ui_judge_stage.py` and `test_ui_contract.py` were
run (failures as listed), and the change was reverted. All 48
breaks of fix-up 1 failed at least one test (one, the gradient case, survived at first because its test's fill colour
gave the same answer either way; the test now uses a `#000` fill and the break fails it):

| Check | Deliberate break | Failing |
|---|---|---|
| invisible-node `node` | ink count 0 not reported | render 3 |
| invisible-node `covered` | a cover never reported | render 1 |
| `covered`, the opaque cover | any opacity covers | render 1 |
| invisible-node `text` | the carrier not judged | render 1 |
| `text`, clipped is text-clipped's | a clipped carrier judged | render 1 |
| R7, inert | `I` not exempt | render 1 |
| R7, under a modal scrim | the policy test inverted | render 2 |
| R7, counted | `not_applicable` not counted | render 1 (error) |
| contrast-low | `worst < large` -> `worst < 1` | render 5 |
| contrast, strict below the floor | `<` -> `<=` | render 1 |
| contrast, the text threshold met | `>=` -> `> text + 0.1` | render 1 |
| contrast, the text extreme | min instead of max over the ink extremes | render 11 |
| contrast, the nearest background | the farther end of the background interval | render 1 |
| contrast, large text | the between-floors incompleteness never reported | render 1 |
| contrast, each threshold alone | one pending threshold drops both | render 1 |
| contrast, the modal exemption | not exempt | render 2 |
| contrast, own fill compared | against what is behind (the old rule) | render 1 |
| contrast, own fill no pass | the upper bound taken as a pass | render 1 |
| contrast, own fill gradient | a gradient taken as one colour | render 1 |
| ink-unmeasurable | a noink record taken as measured | render 1 |
| ink-unmeasurable is an error | severity info | render 2 |
| ink-unmeasurable, frame moved | `ink_moved` ignored | render 1 |
| flag-mismatch hidden/shown | never reported | render 1 |
| flag-mismatch disabled-clickable | `D` ignored | render 1 |
| flag-mismatch inert-clickable | `I` ignored | render 1 |
| flag-mismatch clickable | never reported | render 1 |
| flag-mismatch, layers exempt | layers judged too | render 1, lockers 1 |
| flag-mismatch long-mode | never reported | render 2 |
| flag-mismatch, the scope's mode | the ellipsis scope's DOTS ignored | render 1 |
| align-mismatch | never reported | render 1 |
| align-mismatch, align_banner | `align_banner` ignored | lockers 1 |
| align-mismatch, the style when not drawn | the style fallback ignored | render 1 |
| align-mismatch, counted no-verdict | not counted | render 1 (error) |
| align, the field | `align_drawn` read from the `align` field | render 4 |
| line-height-mismatch | `line_h > baseline` -> `> baseline + 99` | render 1 |
| line-height-mismatch, one cause | `>` -> `!=` (repeats font-shrunk) | render 1 |
| ink plan, once per key and crc | a done (key, crc) inked again | render 2 |
| ink plan, one retry | no retry | render 1 |
| ink plan, done only when usable | an unusable ink marks done | render 2 |
| ink plan, the crc cap | no cap | render 1 |
| ink plan, the second run | the tried steps not recorded | render 2 |
| ink step, `ink_moved` | always false | render 1 |
| ink-plan-capped | never reported | render 1 |
| ui-render needs ink | the capability check removed | render 1 |
| ink format | an ink reply missing a node accepted | render 1 (error) |
| no ink on a later visit | a step without ink judged as inked | render 8, lockers 1 (errors) |
| exception rules | the fix-up ids removed from `EXCEPTION_RULES` | render 1 |
| LAYER_ROLES once | a second definition in ui_judge_vocab | render 1 |
| fix-up 2: part `node` | count 0 not reported | render 4 |
| fix-up 2: part `text` | the carrier not judged | render 2 |
| fix-up 2: the ink decides | a count above 0 judged as 0 | render 11 |
| fix-up 2: clip ownership needs ui-fit selected | left to ui-fit with ui-render alone | render 1 |
| fix-up 2: a clip scope keeps it ui-render's | left to ui-fit under a `clip` scope | render 1 |
| fix-up 2: R7 through `Context.inert` | only `I` exempts | render 2 |
| fix-up 2: R7 counted | the not-applicable not counted | render 1 (error) |
| fix-up 2: exception rules | the two ids removed | render 1 |
| fix-up 2: a fresh snapshot after a moved ink | the stale observation compared | render_explore 1 |
| fix-up 3: a scrolled-out label not judged | the viewport test removed | render 1 |
| fix-up 3: ui-scene's out-of-bounds owns an off-display label | the ui-scene rule removed | render 1 |
| fix-up 3: ui-fit owns only a label it judges | the `own_text` condition removed | render 1 |
| fix-up 3: wait-change after a moved ink | the stale key | render_explore 1 |

The harness that applied them is not part of the repository (it lived in the task's scratch directory). On the canary
the selftest sees every implemented check fire in its own variant.

## U06 review housekeeping

- `LAYER_ROLES` is defined once, in `ui_judge_contract` (with the input-layer naming rule), and imported by
  `ui_judge_vocab` (and through it by the context and the geometric checks); a test asserts it is one object.
- The input-layer naming rule: the stricter rule (only names a judge reads) would refuse the lockers contract (its rows
  `screen`, `splash`, `lockout` are read by no judge), so `docs/ui-contract.md` ("Accepted, not judged") names the
  accepted names no judge reads.
- The unknown-record test of `test_ui_judge_stage.py` matches its message (`assertRaisesRegex`).
- `selftest/ui_judges.sh`: an end-to-end exit-2 case for a bad `[[input_layer]]` name; deterministic log names.

## Deviations

- **`font-size-mismatch` is approximated as `line-height-mismatch`** (its own id, honest row above); the font-id half
  cannot be judged (no font is mapped).
- **`contrast-low` judges only the large-text floor, and the text threshold as a pass**; between the floors
  `contract-incomplete` `large-text`. A missing definition has no pending entry with a question number in the loader's
  closed list, so the U06 form for a missing definition (`contract-incomplete`) is used, not `contract-pending`.
- **`flag-mismatch` exempts layers from `clickable`** and leaves the intent -> not clickable half to `stage-unmatched`.
- **`v-dots` gives two findings** (ui-fit's `full-string-shown` and ui-render's `long-mode`): the DOTS mode is the
  label's long mode against a wrapping scope (L3) and the dots are a cut text (L4).
- **A clipped label that paints nothing is left to ui-fit only when ui-fit is selected and reports its
  `text-clipped`** (fix-up 2; fix-up 1 left it to ui-fit unconditionally, which failed open).
- **`gate/rigor_lib/ui_contract.py` was changed** (a sanctioned deviation of fix-up 1, the orchestrator's extension of
  the paths): `EXCEPTION_RULES` gains `ink-unmeasurable` and `line-height-mismatch`, nothing else.
- **`crop` is not required**: no implemented check reads pixels.
- **`box-covered-node` is not implemented** (feasible; its threshold is not decided): honest row above.
- **The canary's drawing changed** (centred labels, a darker button fill) and `session.out` was regenerated; no U06
  finding changed (`ui_judges.sh`'s S8 step now proves it on every run).
- **`ui_explore_run.PARTS`** gains `ink` and `ink_moved`, so run-twice compares them; `Run` gains `inked`.
