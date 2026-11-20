# P004 (draft): the visual/UI gate — a deterministic machine that finds what a human finds by looking

Design only: no gate code, no product change, no farm build. Read against business-apps `a318b33`, c-rigor-gate
`c589774` (P003 as of T124's no-go, T127 profiles merged), club-apps `0bd2f6e`, and the visual review harness
`business-apps tools/ui-review/` (runs `out/{en,bg,lock,short,probe,probe2,probe3}`). One extra harness run was made for this
draft (`out/p004lang`, scenario `scenarios/p004-lang2.txt`) and one 110-line scene-check prototype was run over the
captured trees (`business-apps `tools/ui-review/p004/`scene_checks.py`). Nothing else was built or edited.

> **Relation to P003.** P003 is owned by another session (tasks T124–T127 and its W-packages). This draft does not
> change P003; it **fills** three P003 cells that are named but not designed: the `ui` profile's
> `catalogue_and_layout`, `whole_app_simulation` and `oracle_trace_replay` techniques (P003 §4.1, `docs/profiles.md`),
> the `ui-fit` gate (P003 §7.6, §11), and the §12 row "Style not rendered, banner scrim — Partly". Where this draft
> proposes a change to a P003 sentence it says so in §12 ("Proposed amendments to P003"), for that session to accept
> or refuse.

**Evidence tags** (P003 convention). **[M]** measured or read in our repos (path or run given). **[E]** published
evidence — **none is cited in this draft**; every place that needs it is marked `[E: LIT-n]` and listed in §15 for
the literature agent. **[P]** a proposal or a starting number, to be re-derived from data. Nothing tagged [P] is a
finding.

## Summary

| # | Decision | Why | Tag |
|---|---|---|---|
| 1 | **Observe downstream of the renderer.** Every check reads the LVGL object tree and the framebuffer of a headless render, not only the scene | The C e2e tree is built from the scene (`lib/ui/a11y`), so it says `30 s` while the screen shows `0:30`; 7 of the 11 failures (F2–F7, F9) have a cause in `lvrender`/`uikit`/`uiloop` | [M] |
| 2 | **Six check families** (scene, fit, render, input, time, parity) with ~30 deterministic checks and stable finding ids | Each failure is caught by checks of ≥ 2 families (F4 by one, but it is the same defect as F3b); no check needs a human or a learned model | [M] [P] |
| 3 | **A machine, `rigor ui-explore`**: domain sweep over view equivalence classes + bounded BFS over reachable states + seeded walks + clock-origin metamorphic runs + headless replay of the oracle scenarios | The 23 Rust scenarios cover only some states; the view domain is small (~2k classes) and the reactor is pure and replayable | [M] [P] |
| 4 | **The Rust oracle becomes a bound bundle of trees + PNGs**, compared by labels, relations and size classes (never pixels across renderers) | Slint's tree is the real element tree with absolute geometry (`club-apps apps/lockers-e2e/src/lib.rs:46-72`); FemtoVG and LVGL pixels cannot be equal | [M] |
| 5 | **Pinned deviations become debt.** The `DISAGREEMENTS` sections of headers are machine-readable and every entry that diverges from the oracle is a `pinned-deviation` finding under a debt cap | 6 of the 11 failures are written down in header disagreement lists (screens L1, L2, L3, L5, L10; notices N3, N5) and nothing tracks them | [M] |
| 6 | **Gate-owned contract, product-owned model adapter.** The checks, tolerances, explorer and LVGL probe are the gate's; the product supplies a pure model adapter and its view-domain enumerator | Agents must not be able to weaken a check (AGENTS rule 2) | [P] |
| 7 | **Tiers**: scene+fit at lane, full sweep + input + time + headless parity at merge, BFS + Xvfb at nightly, golden frames only after zero open `ui-*` findings at release | Fits P003 §9 budgets | [P] |

## 1. The evidence this design answers

### 1.1 The 11 failures, root-caused [M]

All paths are business-apps `a318b33` unless prefixed `club-apps:` or `harness:` (business-apps `tools/ui-review`).
Class: **RX** reactor/view logic, **GEO** scene geometry, **REN** renderer/style, **TXT** i18n/text layout,
**HIT** interaction/hit-testing, **PAR** content parity.

| # | Failure | Root cause (file:line) | Class |
|---|---|---|---|
| F1 | "Code not accepted" dialog removed ~60 ms after it appears (wedge and pad) | **Cross-module time contract broken.** `lkrx/fold_status/fold_status.h:32-34` says every reactor stamps `h.mono_ms` on what it emits; `lkrx/pad/pad.h:42-43` and `lkrx/codes/codes.h:84` say "mono_ms 0 (the runtime stamps them)"; neither `lib/rt/rx` nor `lkapp/runtime` stamps reactor emissions (`runtime.h:19` stamps only *results*; `rx.h:25,35` assigns only `seq`). So `pad.c:8-11,13-19` and `codes.c:12-17,41-47` emit `code_rejected` with `mono_ms = 0`, `fs_notice.c:32-41` sets `deadline_ms = 0 + LK_DIALOG_MS = 8000`, and on the next 250 ms tick `notice.c:14-18,54-55` sees `now >= 8000` and emits `notice_cleared{by=TIMEOUT}`. The view also computes countdown 0 (`view.h` R4), so the dialog shows no countdown in its 60 ms. `visit`, `shift`, `sync` stamp (`visit.c:52`, `shift.c:52`, `sync.c:21`), so only rejections are hit. Harness: `out/probe*/sample.log` (visible at 1.77 s, gone at 1.84 s; 1.74→1.80; 2.00→2.06); `out/en/driver.log` "wait That code is not recognised. TIMEOUT 0.0s" (seen once, then gone) | RX |
| F2 | Pad entry shows no digits (Rust: `000120`) | Two causes. (a) Content: `vstate.h:30-31` D1 drops the typed digits from the view (privacy of traces); `screens.h:103-105,147-148` L1 pins "one DOT marker per digit, never the digit"; `screens/src/pad.c:16,20` builds 16x16 PANELs of tone DOT. (b) Render: a PANEL is an empty `kit_label` (`lvrender.h:28`) and STYLE has no visual effect (`lvrender.h:86`), so a DOT paints nothing. Rust: `club-apps` idle screen `entered` text | PAR + REN |
| F3 | Self-test banner centred across the width, covers keypad "1"; its scrim swallows the first keypad tap | (a) Geometry: `notices.h:87-90` banner column x 340, w 600, pinned by N5 (`notices.h:159-161`) because the Rust placement was "outside the staged sources"; it is in `club-apps:ui/lockers/ui/lockers.slint:219-227` (x = pad, width = `idle-left` on the idle screen). Banner card 340..940 overlaps key "1" at 664..845. (b) Render: the scene's banner scrim equals the card rect (`notices.h:91-93`, ui-rules.md:71), but notice parts ignore RECT (`lvrender.h:82-83`), uikit makes every scrim 100%x100% of its parent (`uikit/src/uikit_notice.c:127`), and lvrender turns tap-outside on whenever the scrim node has an intent (`lvrender/src/lvr_fields.c:159-162`). So the rendered banner scrim is a **full-window, clickable, transparent** layer whose tap dismisses the banner | GEO + REN + HIT |
| F4 | Tapping EN on the Bulgarian Welcome does nothing | **Same root cause as F3(b)**, not a language bug. Harness run `out/p004lang`: first EN tap at (380,422) → banner gone, language still BG (`p1-after-first.tree.txt`); second EN tap → `Welcome` (`p1-after-second.tree.txt`). The fold (`fold_core/src/session.c:242-246`) and the intent map (`lkui/input/src/input.c:42`) are correct | HIT |
| F5 | Opened: "82" rendered as two small separate glyph labels | `screens.h:123-126` + L10 (`screens.h:169-170`): the catalog has no bare "{0}" phrase, so one TEXT node per digit (120x250 each, style 200); then one font for everything: `uiloop.h:31,172` (`UIL_FONT_PX = LKUI_FONT_BODY = 32`), `uiloop.c:148`, STYLE ignored (`lvrender.h:86`), labels left-aligned (`uikit/src/uikit_widgets.c:28-38`, LVGL default) | PAR + REN |
| F6 | Countdown clipped and in `m:ss` (Rust "30 s") | (a) Format: a COUNTDOWN ignores its msgid (`lvrender.h:94-96`, `lvr_text.c:33-42`) and uikit formats `M:SS` (`uikit.h:42-44`; pinned by `uikit/tests/label_test.c:83-84`), so the scene's `LK_CATALOG_N0_S` "{0} s" / "{0} сек" never reaches the screen. (b) Clip: the countdown row is 20 dp tall for a 16 dp caption (`screens.h:73-76`, `LKUI_LINE`), rendered with the 32 px font (line ≈ 36 px). Same for the report's 20/30 dp rows | REN + TXT |
| F7 | All text one size, left-aligned | `uiloop.h:31` "uikit and lvrender ignore the STYLE field"; `lvrender.h:86`; known gap P290 §7 (`plan/P290-shell-linux-plan.md:304-305`). Tests pin it: `lvrender/tests/ops_test.c:123`, `surv_notice_test.c:81,138` treat `SD_F_STYLE` as a no-op mask | REN |
| F8 | No wrapping: Bulgarian subtitle cut mid-sentence | `screens.h:151-152` L3 and `notices.h` N3: "no wrapping is modelled: a text is one rect" of `LKUI_LINE(f)`. The BG subtitle needs **745 px** at 32 px in a 608 px box, i.e. two lines (72 px) in a 40 px row — at the scene's **own** font, independent of F7 [M: prototype §1.3] | TXT |
| F9 | BG/EN toggles show no selected state | `screens.h:77-80`: selection = PANEL key 10, tone SELECTED, behind the button; a PANEL paints nothing (`lvrender.h:28,86`); both buttons get the same uikit button style | REN |
| F10 | Splash has no version line | `screens.h:149-150` L2: "lk_view_t has no version stamp. Pinned: omitted", though `lkapp/version` exists and D17 fixed `Lockers 1.0.0`; ui-rules.md:25 requires the version on the splash | PAR |
| F11 | End-of-shift: no Inspected/Blocked columns, no "Ended HH:MM UTC", no rejected/lockouts/relay-down/app-starts lines, no version | `vstate.h:37-38` D4 (report = four numbers), `screens.h:134-138` + L5 (`screens.h:156-160`) + L2; plus the clipped caption rows of F6(b) | PAR + TXT |

**Extra findings visible in the same evidence** (the machine would report them too) [M]:
- X1. The ABOUT row is still a 160x120 PANEL of tone ATTRIBUTION on splash/shift/report (`screens.h:82,87,132`) though
  owner decision D14 dropped the Slint attribution; it paints nothing (an invisible node, and an extra node vs the oracle).
- X2. The report's "Open source licenses are packaged with this app." row (h 20) is clipped at render (prototype).
- X3. `lockers-02-returning` loses its first keypad tap to the banner scrim (F3b), so even a visible echo would show 5
  digits (`out/en/driver.log`).
- X4. The notice countdown path (`kit_notice_set_countdown`, `lvr_fields.c` LP_COUNT) has the same `M:SS` format as F6.

### 1.2 Why every existing gate missed them [M]

| Gate / practice | Why it could not see these |
|---|---|
| **Unit tests** (both modes) | Each module is tested against **its own header**, and the headers pin the deviation: `pad.h:43` says mono 0 and the pad tests check it; the notice tests hand-stamp `mono_ms = 2200` (`lkrx/notice/tests/nt_tick_test.c:33-45`); uikit's tests pin `M:SS`; lvrender's tests treat STYLE as a no-op. F1 is a contradiction **between** two headers; no test composes pad → fold_status → notice with a realistic clock (the wire test world's fake clock starts at 1000, `wire/tests/world.h:79`; near origin 0 a deadline of 0 + 8000 still looks plausible, and no wire test checks a dialog's lifetime) |
| **Mutation** | Rates code that exists (P003 §1.3 "omission"). STYLE handling, wrapping, a version line, an echo text do not exist, so there is no mutant. The pad's missing stamp is not a mutant of anything. lvrender/uikit are adapters (L2, informational survivors) |
| **Witness** | A witness is written against the same header, including its DISAGREEMENTS; it agrees with the implementation by construction. Same-model independence is weak (P003 P5) |
| **Parity docs** | The deviations are **recorded** (screens L1, L2, L3, L5, L10; notices N3, N5; vstate D1, D4; lvrender "STYLE not interpreted") but nothing counts, caps or re-checks them, and the staged Rust sources were incomplete (N5: banner placement "outside the staged sources") |
| **e2e / a11y tree** | `lib/ui/a11y` encodes the **scene** + catalog (`lkapp/e2e/src/tree.c:59-68`), upstream of lvrender/uikit. It reports `30 s` where the screen shows `0:30`, the banner scrim as 600x108 where the live object is 1280x800, text where nothing is legible. The Rust tree, by contrast, is the real Slint element tree. The club scenarios still caught F1, F2 and F11 by label waits (`out/en/driver.log`) — but they are not in the gate |
| **Owner decision D7** "one visual sign-off" | P003 §16 removed the human; nothing replaced the look |
| **P003 as designed** | `ui-fit` (box fit) would catch F6b, F8, F11-clip **if** it measures with the font that is actually rendered; golden frames pin whatever the first frame is; `oracle` trace replay compares ViewStates, so it can catch F1 (a timed reject trace) but not F2–F11, which are below or outside the view. P003 §12 already rates this row "Partly" |

### 1.3 A 110-line prototype already catches 5 of the 11 from the trees we have [M]

`business-apps `tools/ui-review/p004/`scene_checks.py` (PIL, not gate-eligible; the gate version computes metrics in C, §4.2)
reads the 13 captured C trees, infers each text node's font from its row height (`LKUI_LINE`), and runs three checks.
Output totals: `S1 occluded-target` 4 (key "1" under the banner on every Welcome capture: F3a), `S3 text-overflow-scene`
2 (BG subtitle 745 > 608 px at 32 px: F8), `R3 glyph-clipped-render` 11 (countdowns "30 s", "8 s", "288 s" in 20 px
rows; report lines "Released", "Doors opened", "0 uncertain…", "Open source…": F6b, F11, X2). Wall time: well under a
second. This is the cheapest evidence that most of the class is mechanically decidable.

## 2. Principles

1. **Observe what the visitor observes.** A check that reads the model can only find model bugs. Read the render
   tree and pixels; use the scene as the *intent* to compare against (scene-vs-render consistency is itself a check).
2. **Invariants over examples.** A check is a property of *every* state the app can show, not an assertion about one
   screenshot. Then exploration, not scenario writing, decides coverage.
3. **Diverse methods** (P003 P5): every failure class is caught by two families that share no code path (e.g. F3:
   scene geometry *and* hit-test injection *and* oracle relations).
4. **Determinism by construction.** Virtual clock, fixed seeds, headless software rendering, settle-by-equality; a
   check that can flake is a check that will be waived.
5. **The oracle tells *what*, the contract tells *how much*.** Labels and relations come from the Rust bundle; tolerances
   and timers are gate-owned numbers, never inferred from the C side.
6. **A pinned deviation is debt, not a decision.** Writing "Pinned: omitted" in a header does not make a defect go away.

## 3. Detector catalogue

Finding ids are `<gate>.<check>`; a finding instance id is `sha256(check, element identity, state class)[:12]`
(element identity = role + owner key range + msgid name; state class = screen, notice kind/phrase, banner set,
language), independent of exploration order. Severity: **E** error, **I** info.

### 3.1 Scene level (pure; per explored state; no rasterisation) — gate `ui-scene`

| Check | Rule (deterministic) | Catches |
|---|---|---|
| `occluded-target` E | An interactive node (intent ≠ 0, not inert, not behind a dialog blocker) whose centre, or ≥ [P] 25% of its area, lies under a later-painted, non-inert node that is not its ancestor or descendant | F3a |
| `touch-target-small` E | Interactive w or h < contract `touch_min` (48 dp) [E: LIT-5] | (class) |
| `node-out-of-bounds` E | Rect outside the window or outside its parent (children of panels) | (class) |
| `text-overlap` E | Two text-bearing nodes, neither an ancestor of the other, whose rects intersect | (class) |
| `font-below-min` E | Style font of a text node < the role minimum of the contract | (class) |
| `hierarchy-violated` E | Contract hierarchy per screen (e.g. OPENED: the `primary` element is the largest text; titles > body > caption) fails on the style tokens | F5 (scene side) |
| `value-split` E | A contract `value` element (locker number, entered code) is represented by more than one text node | F5 (L10) |
| `required-element-missing` E | A contract element required for this state class (version line on splash/report; countdown on a timed screen or notice; the entered code on Welcome when pad_len > 0; report columns) has no node | F2, F10, F11 |
| `toggle-group-indistinct` E | For a contract toggle group, the scenes of two states that differ only in the selection differ in no style/flag of the members | F9 (scene side) |

### 3.2 Text fit — gate `ui-fit` (P003's name, made concrete)

Metrics come from the **real font through the real engine** (`lv_text_get_size` with the TinyTTF font at the node's
size, in the probe binary, §4.2), for every language, every node, every explored state; and exhaustively for every
catalogue message × language × host role (P003's "the domain is finite": 135 msgids × 2 languages [M]).

| Check | Rule | Catches |
|---|---|---|
| `phrase-too-long` E | P003's existing buffer check (`LVR_TEXT_MAX`) | (P003 escape) |
| `text-overflow` E | At the node's **declared** font: if the node is single-line by contract, one-line width > rect w; if wrapping, wrapped lines × line height > rect h | F8 |
| `text-clipped` E | At the font **actually used** by the rendered label: laid-out text box (width, lines × line height) exceeds the label's content box, or LVGL dot-truncation replaced text | F6b, F8, F11, X2 |

### 3.3 Render level (headless LVGL framebuffer + object tree) — gate `ui-render`

| Check | Rule | Catches |
|---|---|---|
| `render-geometry-mismatch` E | For every node whose role honours RECT, and for notice scrims/cards, the LVGL object's coords ≠ the scene rect (tolerance 0 px; a documented contract exception list, gate-owned) | F3b |
| `render-text-mismatch` E | The label text on screen ≠ `i18n_format(msgid, args, lang)` of the node (the a11y label) | F6a, X4 |
| `font-size-mismatch` E | The label's font line height differs from the contract's style→px table by more than [P] 1 px | F5, F7 |
| `align-mismatch` E | The label's resolved text alignment differs from the contract alignment of its role (Rust: centred titles/body on most screens) | F7 |
| `invisible-node` E | A node that must paint (non-empty text, a panel with a non-NONE tone, a button) changes no pixel: render the frame, hide the object, re-render its area, compare (ink = pixels that change) | F2b, F9, X1 |
| `covered-node` E | ≥ [P] 50% of a node's ink is overwritten by a later object (ink attribution by the same hide/re-render differential) | F3a (render side) |
| `diff-render-divergence` E | Frame CRC after the diff path (`scenediff` + `lvr_apply` from the previous state) ≠ CRC after a fresh render of the same scene; or two fresh renders differ | (determinism; lvrender's INVARIANT on every explored state) |

### 3.4 Interaction (inject at the rendered tree) — gate `ui-input`

| Check | Rule | Catches |
|---|---|---|
| `tap-misrouted` E | For every interactive node, a press+release at its centre (through `lvh_pointer`, the shell's own path) must queue **exactly** that node's `{intent, arg}`; anything else (another node's intent, a dismiss, nothing) is a finding with both nodes named | F3b, F4 |
| `blocked-target-live` E | With a dialog shown, a tap at any interactive node outside the card queues an intent (the scrim must swallow it) — the positive control of the rule above | (class) |
| `toggle-state-invisible` E | Tap a toggle member that is not selected: the frame pixels inside the group's rects must change (selected look), and the scene's selection must move | F9 |
| `dead-intent` E | A queued intent produces no scene change within [P] 8 reactor instants, unless the contract lists it as a no-op in this state class (e.g. digits on lockout) | F4 at reactor level (not the cause here, but the class) |

### 3.5 Temporal (event → view → scene trace on a virtual clock) — gate `ui-time`

The trace is the sequence `(t, input, emitted events, scene hash, semantic tree)` the explorer records for every path
(§4). Timers come from the contract, which copies ui-rules.md:33-46 (choose 30 s, opened 8 s, dialogs 8 s, report
5 min, lockout 60 s, snackbar 4 s).

| Check | Rule | Catches |
|---|---|---|
| `notice-lifetime-short` E | An element with contract limit L appears at t0 and disappears at t1 with no user intent addressed to it in between: require `t1 - t0 ≥ L - tick` (tick = 250 ms, `runtime.h` C2) | F1 |
| `notice-lifetime-long` E | Shown for more than `L + tick` without input (a countdown that never fires) | (class) |
| `flash` E | Any non-countdown element appears and disappears within [P] 500 ms with no user input in between | F1 (generic form) |
| `countdown-wrong` E | While a timed element is shown, its countdown must be present, start at ⌈L/1000⌉ (±1), decrease by 1 per virtual second, and never show 0 | F1 (no countdown in its 60 ms) |
| `clock-origin-divergence` E | **Metamorphic** [E: LIT-4]: the same input path run with monotonic origins {1, 1 000, 10⁹, 2³² + 7, 2⁴⁰} ms must give the same sequence of semantic trees (countdowns compared as values, absolute times masked). Absolute-vs-relative time bugs, unstamped events and 32-bit truncation all show here | F1 (and its class) |
| `unresponsive-intent` E | A user intent the contract marks effective in this state changes nothing within K instants | (class) |

### 3.6 Differential parity against the Rust oracle — gate `ui-parity`

Inputs: the **UI oracle bundle** (§5) and C captures produced by replaying the **same scenario files** headlessly
against the probe (§4.4). Normalisation table (gate-owned): version stamps → `<version>`, countdown values → `<n>`
with the unit word kept, locker numbers kept, HH:MM kept (both sides use the frozen virtual epoch).

| Check | Rule | Catches |
|---|---|---|
| `oracle-label-missing` E | A normalised label present at an oracle step is absent from the C **render** tree at the same step | F2 (`000120`), F5 (`82`), F6a (`30 s`), F10, F11 (8 labels) |
| `oracle-label-extra` I | A C label the oracle step lacks | X1 |
| `oracle-layout-relation` E | For each pair of matched elements: the relations left-of / above / overlaps / contains, and the horizontal alignment class within the parent column (start, centre, end), must equal the oracle's | F3a (banner left of keypad, no overlap), F7 (alignment) |
| `oracle-size-class` E | Matched text height ratio C/Rust outside [P] [0.8, 1.25] | F5, F7 |
| `oracle-scenario-diverged` E | A scenario step passes on the oracle and fails on C (wait/absent/label-has/expect-value) | F1 (04, 07), F2 (02), F11 (05) |
| `pinned-deviation` E (debt) | A header `DISAGREEMENTS` entry tagged machine-readably (§8.3) whose subject diverges from the oracle; counted against a debt cap | F2, F3a, F5, F8, F10, F11 |

Pixel comparison across renderers is **not** a check: FemtoVG and LVGL differ in antialiasing and font rasterisation.
A coarse "ink map" comparison (32x20 grid of ink presence) is kept as **report only** until §14 measures its noise.
Exact pixel identity is used only C-vs-C (golden frames, P003; `screens-compare` style).

### 3.7 Meta — gate `ui-explore`

`ui-coverage-gap` E (a coverage criterion of §4.3 below 100% where it is required), `model-nondeterministic` E (the
same path twice gives a different trace hash), `probe-internal-error` E, `ui-explore-timeout` E (P003: a timeout is a
FAIL, never a skip).

## 4. The machine: `rigor ui-explore`

### 4.1 Shape

```
            gate-owned                                          product-owned
 ┌─────────────────────────────────────────┐        ┌──────────────────────────────────────┐
 │ rigor ui-explore (Python, stdlib)        │        │ c_ui_model (C, implements            │
 │  strategies: sweep · BFS · walks ·       │ lines  │  gate//ui:model.h)                   │
 │  clock-origin · scenario replay          │<──────>│  - the single-thread sim composition │
 │  judges: §3 checks over probe facts      │ stdin/ │    (P003 W8 c_sim) + uiloop on a     │
 │  findings.json + evidence/               │ stdout │    memory surface                    │
 └─────────────────────────────────────────┘        │  - view-domain enumerator            │
            │ builds                                  │  - env/fault input catalogue         │
            ▼                                         └──────────────────────────────────────┘
 ┌─────────────────────────────────────────┐                      │ linked into
 │ c_ui_probe (gate macro) = product model  │<─────────────────────┘
 │  + gate//ui:lvprobe (C over gate LVGL):  │
 │   object-tree walk, text metrics, ink    │
 │   attribution, hit injection, frame CRC, │
 │   raw RGBA crops for evidence            │
 └─────────────────────────────────────────┘
```

- **Why a probe binary and not the Xvfb app.** The UI loop is already seam-based (`uil_wire_t` with
  `scene/post/side/stopping`, `uiloop.h`), lvhost has a capturing flush, and LVGL is gate-owned third party, so the
  gate can walk the object tree and read the framebuffer in-process, deterministically, with no display server and
  no input timing. The Xvfb path (shell_linux, X11 glue) is covered separately at nightly (§6).
- **Python stays stdlib** (AGENTS rule 5): all pixel and font work is in C inside the probe; Python only reads JSON
  facts and writes PNG evidence with `zlib`/`struct` (as `club-apps:tools/e2e/screens-compare` decodes PNG).

### 4.2 The probe protocol (gate header `gate//ui:model.h`, sketch [P])

```c
/* Product implements; static storage; pure apart from the virtual clock it is given. */
bool     uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed);          /* boot to first stable scene   */
uint16_t uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap);            /* enabled env/fault inputs now  */
bool     uim_apply(uim_t *m, const uim_input_t *in);                           /* env input, wedge line, intent */
uint64_t uim_next_due(const uim_t *m);                                         /* next timer, or UINT64_MAX    */
bool     uim_advance(uim_t *m, uint64_t to_ms);                                /* run steps up to `to`         */
bool     uim_frame(uim_t *m, lv_display_t **disp);                             /* scene adopted + LVGL drawn   */
bool     uim_semantic(uim_t *m, core_buf_t *out);                              /* scene as a11y+ lines         */
uint16_t uim_domain_count(void);  bool uim_domain_at(uim_t *m, uint16_t i);    /* view-domain sweep (optional) */
bool     uim_trace(uim_t *m, core_buf_t *out);                                 /* emitted events since last    */
```

`a11y+` = the CLUB_A11Y seven fields plus `key, role, intent:arg, flags, style` (appended fields; existing drivers
read seven). `gate//ui:lvprobe` emits, per state: the LVGL tree (class, coords, hidden, clickable, label text, font
line height, text align, long mode, bg colour/opa), per-node ink box and ink count, the hit-test table (node → intent
queued by a centre tap), and the frame CRC. All C, all bounded, static memory.

Exploration needs no product snapshot API: paths are replayed from `uim_open` (depth ≤ 12, reactor steps are µs).
A memcpy snapshot of the static model is an optional speed-up (a C strength, P003 §3).

### 4.3 Strategies, bounds and coverage

1. **Domain sweep** (needs only the pure builders): enumerate equivalence classes of `lk_view_t`, build the scene
   (`lkui_build` + `lkui_notices`), render, run §3.1–3.4. Classes [P]:

| Factor | Classes | Count |
|---|---|---|
| Screen variants | SPLASH 1; WELCOME pad_len {0,1,6,25,26,64} 6; CHOOSE n_sizes 1..6 × {all free, all full, alternating} × countdown {max, 1 s} 36; OPENED digits {1,2,3} × first_time × countdown 12; SHIFT {0/0, 1/2, 2/2, max} 4; REPORT {0, 65535} × write_failed × countdown 8; LOCKOUT 2; FAULT 2 screens × 10 faults 20 | 89 |
| Language | bg, en | ×2 |
| Notice (over WELCOME/OPENED where the view allows) | none; dialogs: 3 rejects, no-locker, fault 10 × 3 doors × {0, 1-digit, 3-digit locker} = 94; snackbar 1; banner-kind notice × 13 phrases | 109 |
| Banners | single variants: not_saved, audit, sync {rejected 3 status classes, late}, codes offline, codes stale, self-test {OK, 9 issue bits, 3 count bits} ≈ 21; subsets of the 6 kinds 64 | |

   Coverage set [P]: (a) every screen variant × language with no message (178); (b) every notice variant × host
   screen × language (≈ 109 × 2 × 2 = 436); (c) every single banner variant × screens where shown × language (≈ 378);
   (d) all 64 banner subsets × {WELCOME, OPENED, CHOOSE} × language (384); (e) a strength-2 covering array over
   (screen variant, notice, banner subset, language) [E: LIT-1] ≈ a few hundred. **Total ≈ 1.6k–2k states.**
2. **Reachability BFS** over the model: actions = (i) a centre tap on every interactive node **of the rendered tree**
   (never a product-declared list), (ii) wedge lines from a gate-owned code-class catalogue (valid visitor, valid
   staff, unknown, 1/5 digits, 64, 65, non-digit, empty), (iii) the product's env/fault inputs (relay down/up/stuck,
   open fault per kind, book save fail, audit fail, disk full, codes offline/stale/failed, sync rejected/late,
   self-test results), (iv) time jumps to `next_due − 1`, `next_due`, `+tick`, `+5 min idle`. Dedup key: hash of the
   normalised semantic tree + the enabled-action set + timer classes (gate-computed; the product cannot collapse
   states). Bounds [P]: depth 12, 20k states, coverage-guided ordering (prefer actions that reach an unseen
   (screen, notice kind, banner count, language) class) [E: LIT-1].
3. **Seeded random walks** (long paths, 200 seeds at merge — the same seeds P003 §7.4 uses for `sim`), each also run
   at 4 extra clock origins for `clock-origin-divergence`.
4. **Oracle scenario replay** (§4.4).

**Coverage criteria** (findings `ui-coverage-gap`): C1 every screen class × language rendered — **required**; C2 every
catalogue message × language rendered in each host role it can take (screen text, notice title/body/detail, banner) —
**required** (ties to P003 `ui-fit` exhaustiveness); C3 every interactive node class tapped in every screen class —
**required**; C4 every notice kind over every host screen, banner counts {0,1,2,6} — required; C5 every contract timer
observed to expiry at ≥ 2 clock origins — **required**; C6 every env fault injected in every screen class where it is
enabled (pairwise) — reported; C7 every oracle scenario step replayed — **required**.

**Runtime estimate** [P, to be measured by T1xx.01]: reactor + scene build per state: µs. Full-frame LVGL software
render at 1280x800 XRGB8888: assumed 5–15 ms. Ink attribution (hide one object, re-render only its area) ≈ 0.5–2 ms per
painted node × ~25 nodes. Hit injection: ~0.1 ms per interactive node. ⇒ ≈ 30–60 ms per state. Sweep (2k states):
1–2 CPU-min; BFS (20k): 10–20 CPU-min; walks (200 × ~200 steps, mostly no render — render only on scene change):
a few CPU-min. Sharded over the farm (concurrency 64) the merge-tier set fits in ~1–2 min wall.

### 4.4 Headless scenario replay

The 23 scenario files (`club-apps:tools/e2e/scenarios/*.txt`, mirrored in the harness) use a closed command set
(`wait/click/type/key/absent/pause/within/label-has/expect-value/freeze-clock/thaw-clock/screenshot`, README). The
explorer interprets them against the probe: `click L` = centre tap on the **render-tree** node labelled L (button
first, as the Rust driver does), `type`/`key enter` = wedge, `pause`/`within` = virtual time, `freeze-clock` = stop
advancing, `screenshot N` = capture render tree + frame after the scene settles (two identical semantic trees, as the
Rust driver does). Output per step: `C/<scenario>/<step>.{rtree,png}` with the same names as the oracle bundle.

### 4.5 Findings and evidence

One JSON line per finding (schema [P]):

```json
{"id":"ui-time.notice-lifetime-short/3f9a0c21e7b4","gate":"ui-time","check":"notice-lifetime-short","severity":"error",
 "state":{"screen":"welcome","notice":"dialog/reject_invalid","banners":["self_test"],"lang":"en","origin_ms":1000000000},
 "path":["open","advance +2500","wedge 12345","enter"],
 "observed":{"shown_ms":1000002512,"gone_ms":1000002750,"lifetime_ms":238,"limit_ms":8000,
             "removed_by":"notice_cleared{kind=dialog,by=timeout}","deadline_from":"code_rejected h.mono_ms=0"},
 "blame":[{"module":"//apps/lockers/lkrx/pad:pad","symbol":"lk_react_pad","file":"apps/lockers/lkrx/pad/src/pad.c","line":8},
          {"module":"//apps/lockers/lkrx/fold_status:fold_status","file":"apps/lockers/lkrx/fold_status/src/fs_notice.c","line":38}],
 "evidence":["ui-evidence/3f9a0c21e7b4/t0.png","ui-evidence/3f9a0c21e7b4/t1.png","ui-evidence/3f9a0c21e7b4/trace.txt"]}
```

**Blame** is mechanical where possible: temporal findings walk the trace to the event that removed the element and
the event whose header set its deadline, then name the emitting reactor (catalogue wiring table) and its function's
file:line (`llvm-symbolizer` on the reactor table entry). Scene findings name the builder by the contract's key-range
owner table (keys 1..255 → `lkui/screens`, 0x100..0x147 → `lkui/notices`, `notices.h:26-37`). Render findings name
`lvrender`/`uikit` by LVGL object class and the scene role. Evidence images are crops with the node box drawn, plus
before/after frames for temporal and input findings.

## 5. The oracle side, reproducible

- **Bundle content**: per scenario step that has a `screenshot`: the Rust tree (`.tree.txt`, real Slint element
  geometry), the PNG, and a manifest (club-apps commit, driver commit, Xvfb geometry, `SLINT_SCALE_FACTOR=1`,
  font hashes). Bound into the verdict by sha256, like the witness and P003's trace bundle.
- **Determinism already present** in club-apps (`tools/e2e/README.md`): fixed version stamp `Lockers
  0.0.0+e2e2e2e2e2e2`, virtual clock `1796126415000 + BOOT_IDX × 600000`, `freeze-clock` before countdown screens,
  screenshot after two identical trees. Missing: the driver writes no tree file at `screenshot` — one small club-apps
  task (T1xx.11). Acceptance for the bundle producer: two runs on the same commit give `screens-compare … 0 differ`
  **and** byte-identical tree files.
- **Freshness**: D12 freezes Rust lockers behaviour between M5 and M6; the bundle is rebuilt only by a club-apps task
  and a gate change (graded under the previous gate, P003 §10.3).
- **Visibility** [P]: the PNGs and labels are the specification of the look, so implementers may see them (unlike
  P003's trace bundle). The tolerances, normalisation table and the domain/BFS states are gate-side; the domain sweep
  covers states no scenario reaches, so hard-coding the bundle's labels does not pass (and is AGENTS rule 3 anyway).
- **Limits**: the oracle reproduces Rust's own bugs (P003 §16); the Rust tree carries only elements with an
  accessible role, so relations are judged on those.

## 6. Fit into the gate

### 6.1 Gates, tiers, budgets [P]

| Gate | Lane | Merge | Nightly | Release |
|---|---|---|---|---|
| `ui-fit` | ● exhaustive catalogue × language × host role at the declared font (no raster; seconds) | ● + `text-clipped` on the sweep | ● + reachable states | ● |
| `ui-scene` | ● on the domain sweep, scene only | ● | ● + reachable | ● |
| `ui-render` | ○ | ● on the sweep | ● + reachable | ● |
| `ui-input` | | ● every interactive node of every swept state | ● + reachable | ● |
| `ui-time` | | ● 200 seeds (P003 `sim` seeds) × 5 clock origins; every timer to expiry | ● BFS depth 12 + long walks + soak hours | ● |
| `ui-parity` | | ● headless replay of all scenarios vs the bundle (labels, relations, size classes, scenario divergence); `pinned-deviation` debt count | ● + Xvfb real-window replay of the same scenarios with the pinned driver; ink map ○ | ● |
| `ui-explore` (meta) | | ● coverage C1, C3, C5, C7 | ● all criteria | ● |
| golden frames (P003) | | | | ● only when every `ui-*` gate is PASS for that frame's state (§8.4) |

**Scope at merge** (P003 §9): run when any module reachable from the `c_ui_probe` target changed (Buck2 graph), or the
contract, the bundle or the gate's UI code changed. A pure non-UI change does not pay for the sweep.

**Profile matrix rows** (additions to `profiles.MATRIX`, for the P003 owner): `ui_scene_render_input` ● for `ui`;
`ui_time` ● for `ui` and `wiring`; `ui_parity` ● for `ui`. They run at app level (the probe), triggered by any
changed module with profile `ui` or `wiring` on the probe's dependency closure.

### 6.2 What is gate-owned, what is product-owned

| Item | Owner | Why |
|---|---|---|
| Check code, judges, tolerances, normalisation table, explorer strategies, code-class catalogue, clock origins, seeds | gate | Agents must not weaken checks (rule 2) |
| `gate//ui:lvprobe`, `gate//ui:model.h`, `c_ui_probe` macro | gate | Observation point must be trusted; LVGL is already gate third party |
| **UI contract** `products/business-apps/ui/lockers.toml`: window, touch_min, style→px table, role minimums, alignment per role, timers, toggle groups, hierarchy, required elements per state class, key-range owners, exception list | gate (like `policy.toml`) | A product-owned contract would be the first thing an agent edits. Every entry carries a provenance (ui-rules.md line, oracle bundle step, owner decision) |
| Model adapter (`c_ui_model`), view-domain enumerator, env/fault input catalogue | product | Product types; it is what is tested. Guarded: the env catalogue must name every input event of the product's event catalogue classified as env (a facts check over `LK_EV_TYPES`), and the domain enumerator must produce every `LKS_*` × language (C1) |
| Oracle bundle | produced by a club-apps task, held by the gate | As P003 §7.5 |
| `DISAGREEMENTS` tags in headers | product writes them; the gate counts them | §8.3 |

The contract is derived mechanically where it can be: timers from the ui-rules.md table, required elements from "present
in every oracle capture of that state class", the style→px table cross-checked against the oracle's measured text heights
(and against Rust `KioskMetrics`: display 200, headline 48, title 40, body 32, staff 24, caption 16, `screens.h:40-41`).
What remains a judgement (hierarchy, toggle groups) is a gate change, graded under the previous gate and ledgered.

### 6.3 Gaming resistance

- The checks read the LVGL tree and framebuffer through gate code; the product cannot report geometry or text.
- Taps are injected at render-tree centres through the shell's own pointer path, not at declared positions.
- Exploration inputs come from the render tree and gate catalogues; the product's env catalogue is checked for
  completeness; clock origins and seeds are derived from the verdict's input hash, so a special case for a known seed
  or origin fails on the next grade.
- `gate//ui:model.h` symbols may be linked only by `c_ui_probe` targets (symbols policy); product code that detects the
  probe, `CLUB_E2E` or the explorer is AGENTS rule 3 and a symbol violation.
- Scene-vs-render consistency checks (`render-geometry-mismatch`, `render-text-mismatch`) make "fix the a11y tree, not
  the screen" impossible.
- **Canaries** (P003: every new gate ships with one): a selftest app with one seeded defect per check, and the
  **historic canary**: business-apps `a318b33` must keep producing findings for all eleven classes F1–F11 (mapping in §7).
  A gate change that loses one fails under the previous-gate rule.

### 6.4 False positives

- **Report first.** A new check runs ○ for [P] 5 nightlies on `main`; its findings are triaged by the refuter role
  (P003 §10.2) and only then promoted to ● by a gate task (the P003 §13 ordering rule, applied per check).
- **Baseline ratchet.** On promotion, the open findings on `main` become a baseline list (ids). The list may only
  shrink (P003 ratchet); a new id fails the merge.
- **No free waiver.** A finding that is not a defect is a P003 §10.2 **claim** ("this is intended") signed by the
  arbiter, bound to the finding id, under a debt cap, ledgered, and refutable by executable evidence (an oracle step
  showing the difference, a tap that misroutes, a rendered crop). An owner decision that departs from the oracle (D14:
  no attribution) is a **normalisation entry** in the contract, not a waiver.
- **Tolerances are numbers with provenance** (e.g. `notice-lifetime-short` slack = one tick, from `runtime.h` C2;
  size band [0.8, 1.25] [P] from the measured C/Rust spread at the first PASS, ratcheting inward only).

## 7. Failure → root cause → why missed → detectors → tier → effort

Effort: S ≤ 1 agent-day, M 2–4, L 5+ [P]. "First tier" = the cheapest tier at which a ● check fires.

| # | Root cause (§1.1) | Why missed (§1.2) | Detectors | First tier | Effort of the detectors |
|---|---|---|---|---|---|
| F1 | `pad.c:8-11`, `codes.c:12-17` emit unstamped; `fs_notice.c:38-39` deadline 0+8000; `notice.c:55` times out | Header-vs-header contradiction; notice tests hand-stamp; world clock at 1000 | `ui-time.notice-lifetime-short`, `flash`, `countdown-wrong`, `clock-origin-divergence`; `ui-parity.oracle-scenario-diverged` (04, 07); [P003 `oracle` can also catch it] | merge | M (needs c_sim) |
| F2 | `vstate.h:30-31` D1, `screens.h:147-148` L1, DOT panel paints nothing (`lvrender.h:28,86`) | Pinned in headers; no render observation | `ui-render.invisible-node`; `ui-scene.required-element-missing`; `ui-parity.oracle-label-missing` (`000120`), `oracle-scenario-diverged` (02); `pinned-deviation` | lane (scene) / merge | S on top of the probe |
| F3 | (a) `notices.h:87-90`, N5 `:159-161`; (b) `lvrender.h:82-83`, `uikit_notice.c:127`, `lvr_fields.c:159-162` | Staged sources incomplete; a11y tree shows the scene rect, not the live scrim | `ui-scene.occluded-target`; `ui-render.render-geometry-mismatch`, `covered-node`; `ui-input.tap-misrouted`; `ui-parity.oracle-layout-relation` | lane (a) / merge (b) | S / M |
| F4 | = F3(b) (`out/p004lang`) | as F3 | `ui-input.tap-misrouted` (EN → banner dismiss) | merge | (shared with F3) |
| F5 | L10 `screens.h:169-170`; one font `uiloop.h:31,172`; STYLE `lvrender.h:86` | Pinned; renderer gap "known" (P290 §7) but not gated | `ui-scene.value-split`, `hierarchy-violated`; `ui-render.font-size-mismatch`; `ui-parity.oracle-label-missing` (`82`), `oracle-size-class` | lane / merge | S |
| F6 | `lvrender.h:94-96` + `uikit.h:42-44` (`M:SS`); row h 20 (`screens.h:73-76`) vs 32 px font | Tests pin `M:SS` (`label_test.c:83-84`); a11y shows `30 s` | `ui-render.render-text-mismatch`; `ui-fit.text-clipped`; `ui-parity.oracle-label-missing` | merge | S |
| F7 | `uiloop.h:31`, `uiloop.c:148`, `lvrender.h:86`; LVGL default left align | Tests pin STYLE as a no-op | `ui-render.font-size-mismatch`, `align-mismatch`; `ui-scene.hierarchy-violated` (render); `ui-parity.oracle-size-class`, `oracle-layout-relation` | merge | S |
| F8 | L3 `screens.h:151-152`, N3; BG 745 px > 608 px | "No wrapping modelled" pinned; no metrics anywhere | `ui-fit.text-overflow` (scene font), `text-clipped`; `ui-parity.pinned-deviation` (L3) | lane | S (metrics in probe) |
| F9 | `screens.h:77-80` selection = PANEL; PANEL paints nothing | Render not observed | `ui-render.invisible-node`; `ui-input.toggle-state-invisible`; `ui-scene.toggle-group-indistinct` (scene passes: the style differs, so render is what fails) | merge | S |
| F10 | L2 `screens.h:149-150`; view has no version | Pinned; ui-rules.md:25 not checked | `ui-scene.required-element-missing`; `ui-parity.oracle-label-missing`; `pinned-deviation` | lane / merge | S (contract entry) |
| F11 | `vstate.h:37-38` D4, L5 `screens.h:156-160`, L2; clipped rows | Pinned; scenario 05 not in the gate | `ui-parity.oracle-label-missing` (Inspected, Blocked, Ended, Rejected codes, Lockouts, Relay down, App starts, version), `oracle-scenario-diverged` (05); `ui-fit.text-clipped`; `pinned-deviation` | merge | S |

Coverage of the 11 by family: scene 5 (F2, F3, F5, F7, F10), fit 3 (F6, F8, F11), render 6 (F2, F3, F5, F6, F7, F9),
input 3 (F3, F4, F9), time 1 (F1), parity 9 (F1, F2, F3, F5, F6, F7, F8 via `pinned-deviation` L3, F10, F11). Every
failure has detectors in ≥ 2 families except F4, which has one (input) but is the same defect as F3(b), which has three.

## 8. Decisions

| # | Decision | Default |
|---|---|---|
| D1 | Observation point | Checks read the LVGL object tree + framebuffer of a headless render (§4.1); scene-only checks are the cheap lane subset |
| D2 | Genericity boundary | The gate owns explorer, checks, lvprobe, contract; the product owns a model adapter behind `gate//ui:model.h` (§4.2, §6.2). Any LVGL product (stock, fiscal) gets the gate by writing one adapter |
| D3 | Exploration | Domain sweep + BFS (depth 12, 20k states) + 200 seeded walks × 5 clock origins + headless scenario replay; replay-from-start, no snapshot API needed [P] |
| D4 | Oracle comparison | Trees (labels, relations, size classes) and scenario outcomes; never cross-renderer pixels; ink map report-only |
| D5 | Contract | Gate-owned `products/<p>/ui/<app>.toml`, every entry with provenance; derived mechanically where possible |
| D6 | Tiers | §6.1 table |
| D7 | False positives | Report-first promotion, baseline ratchet, P003 claims; no free waiver (§6.4) |
| D8 | Pinned deviations | Debt with a cap (§8.3) |
| D9 | Golden frames | Approvable only for a state with zero open `ui-*` findings (§8.4) |
| D10 | Real window | Xvfb replay nightly and at release only, with a pinned driver (§11 Q6) |
| D11 | The C e2e tree | Add an `rtree` command (render-derived) to the e2e server for the Xvfb path; keep `tree` (scene) for the club driver until the owner decides (§11 Q2) |
| D12 | P003 `sim` invariant | Propose "every event an instant emits carries that instant's `h.mono_ms`" to the P003 list (it catches F1 at event level without any UI) — P003 owner's call |

### 8.3 Pinned deviations as debt

Every header disagreement line gets a machine-readable tag, e.g. `@deviation(LKUI-L2, oracle="version-line",
state="splash,report", until="T1xx")`. The gate (a facts scan over headers) lists the tags; `ui-parity` marks each tag
whose subject diverges from the bundle as `pinned-deviation`. The count is a ratchet (P003 §10.1) and has a cap [P]
(e.g. 5 per app); a new tag above the cap fails. A tag whose subject no longer diverges is `deviation-stale` (info →
delete the tag). Untagged divergence is still caught by the other parity checks; tagging only makes it explicit.

### 8.4 Golden frames (precondition for P003 §7.6)

P003 §16 notes that nothing says the first golden is right. P004 narrows that: a golden frame can be approved (P003
claim) only for a state whose `ui-scene`, `ui-fit`, `ui-render`, `ui-input` and `ui-parity` findings are all clear, so
the first golden is at least *legible, reachable, tappable and oracle-consistent*. It does not make it beautiful.

## 9. Task breakdown

`T1xx.n` are placeholders (not T124–T127; the next free gate number at `c589774` is after T132). L = business-apps
task, C = club-apps task, otherwise gate. Acceptance commands follow AGENTS (`tools/job` for > 2 min).

| Task | What | Acceptance |
|---|---|---|
| **T1xx.01** Measure first (P003 W1 style) | Throwaway probe on business-apps `a318b33` in a scratch worktree: domain enumerator over `lk_view_t`, uiloop on lvhost with a capturing flush, an LVGL tree dump, `lv_text_get_size`; no gate wiring | `plan/metrics/ui-probe-<date>.md`: states per class, ms per state (render, ink, hit), and F3b, F5, F6, F7, F8, F9 reproduced from render facts alone; go/no-go on the §4.3 runtime estimate |
| **T1xx.02** `gate//ui:lvprobe` | C library over gate LVGL: object walk, metrics, ink attribution, hit injection, frame CRC, RGBA crop | Tests on the LVGL test display: a hidden label has ink 0; a label in a box too small is `clipped`; a full-parent transparent clickable object steals a centre tap (F3b canary red); two renders CRC-equal |
| **T1xx.03** `gate//ui:model.h` + `c_ui_probe` macro + symbols rule | Header, macro, facts rule "model symbols only in probe targets" | A product library calling a `uim_*` symbol is `symbol-not-allowed`; the selftest app's probe builds in release and san |
| **T1xx.04 (L)** lockers model adapter | Implements `model.h` over the single-thread sim composition (coordinate with P003 W8 `c_sim`), view-domain enumerator (§4.3), env/fault catalogue | `rigor ui-explore --strategy sweep` on the adapter covers C1 = 100%; the env catalogue names every env input of `LK_EV_TYPES` (facts check green) |
| **T1xx.05** `rigor ui-explore` driver | Strategies, dedup, replay, findings schema, PNG evidence (stdlib) | Same inputs twice → byte-identical `findings.json`; a seeded nondeterministic adapter → `model-nondeterministic` |
| **T1xx.06** `ui-scene` + `ui-fit` judges | §3.1, §3.2 | Selftest canaries red one per check; on `a318b33`: `occluded-target` (key 1), `text-overflow` (BG subtitle), `value-split` (82), `required-element-missing` (version) |
| **T1xx.07** `ui-render` judges | §3.3 | On `a318b33`: `render-geometry-mismatch` (banner scrim 1280x800 vs 600x108), `render-text-mismatch` (`0:30`), `font-size-mismatch`, `invisible-node` (DOT, SELECTED, ATTRIBUTION) |
| **T1xx.08** `ui-input` judges | §3.4 | On `a318b33`: `tap-misrouted` for key "1" and for EN over the self-test banner; `toggle-state-invisible` for BG/EN |
| **T1xx.09** `ui-time` judges | §3.5 incl. clock-origin metamorphic | On `a318b33`: `notice-lifetime-short` for all three reject phrases via pad and wedge; `clock-origin-divergence`; a canary snackbar with a correct 4 s life is green |
| **T1xx.10** UI contract schema + lockers contract | Schema, provenance field, derivation script from ui-rules.md and the bundle | Every entry has a provenance; removing a timer row reproduces as `contract-incomplete`; style→px matches `KioskMetrics` |
| **T1xx.11 (C)** Oracle tree dump + bundle | Rust driver writes `<name>.tree.txt` at `screenshot`; bundle manifest; producer script | Two runs on one commit: `screens-compare` 0 differ and identical trees; bundle sha recorded |
| **T1xx.12** `ui-parity` judges + headless scenario interpreter + normalisation table | §3.6, §4.4 | On `a318b33`: `oracle-label-missing` for `000120`, `82`, `30 s`, version, the 8 report labels; `oracle-scenario-diverged` for 02, 04, 05, 07; `oracle-layout-relation` for the banner |
| **T1xx.13 (L)** `@deviation` tags | Tag the existing DISAGREEMENTS (screens L1–L12, notices N1–N9, vstate D1–D7, lvrender STYLE, uikit countdown) | The facts scan lists them; `pinned-deviation` count = number of tags that diverge; count recorded as the ratchet start |
| **T1xx.14** Gate wiring | Register `ui-scene`, `ui-fit` (extended), `ui-render`, `ui-input`, `ui-time`, `ui-parity`, `ui-explore` in `GATES`/`order.txt`; tiers; report-first flags; ratchet baselines; ledger claims; historic canary `a318b33` | `selftest/grade.sh` green twice; the canary pack red; a gate change that drops any F1–F11 class on `a318b33` fails under the previous gate |
| **T1xx.15** Nightly real window | Xvfb replay of all scenarios with a pinned driver; `rtree` vs bundle; ink map ○ | Two nightly runs identical; the Xvfb captures equal the headless captures for every step (or the differences are listed — this also answers §11 Q1) |
| **T1xx.16 (L)** `rtree` command in `lkapp/e2e` | Render-derived tree from the lvr map (needs D11) | Driver `wait 0:30` succeeds where `tree` says `30 s` on `a318b33` |

Dependencies: 01 first. 02, 03, 10, 11, 13 can start at once. 04 needs 03 (and shares the sim composition with P003
W8). 06–09 need 02 + 04; 12 needs 11 + 04; 14 last; 15 and 16 after 12.

## 10. What this does not do (known limits)

- **No aesthetics.** Colour harmony, spacing rhythm and "looks right" are not decided; parity relations and size
  classes are a proxy, as good as the oracle.
- **The oracle's bugs are reproduced** (P003 §16), and only elements with an accessible role are compared.
- **Domain classes are chosen by someone.** A missing class is a missing check; C1–C7 and the BFS limit the damage.
- **BFS dedup by observable state** can merge states that differ in hidden state; seeded long walks and the
  clock-origin runs are the mitigation, not a proof.
- **Headless ≠ the window.** X11 glue (shell_linux, L1, untested by design) is only seen by the nightly Xvfb replay.
- **Fonts and LVGL are pinned**; a toolchain bump that changes metrics moves fit results, by design (it is a gate change).

## 11. Open questions

1. **Golden frames headless or Xvfb?** P003 §7.6 says "under Xvfb"; the headless capturing flush is the same buffer the
   shell blits. Proposal: headless goldens, with T1xx.15 proving equality once. (P003 owner.)
2. **Should the C a11y tree become render-derived** (product `lkapp/e2e`), so the club driver also sees the screen?
   It changes what the existing harness asserts. (Owner.)
3. **Pad digits (F2): parity or privacy?** vstate D1 keeps the digits out of traces; Rust shows them. Options: a
   UI-thread-only echo that never enters the trace (uiloop already holds the wedge buffer), or keep dots, make them
   visible, and record a normalisation entry. (Owner.)
4. **Oracle bundle visibility** to implementers (§5): visible PNG/labels proposed, unlike P003's trace bundle.
5. **Tolerances** (size band, flash window, occlusion share, ink threshold) are [P]; who signs the first values — the
   §6.4 rule (measured at first PASS, ratchet inward) or an owner number?
6. **Real-window driver**: reuse the pinned club-apps Rust e2e driver binary (one driver for both apps: the strongest
   parity statement, a cross-repo input) or a gate-owned C XTest driver (needs the X11 sysroot members of P290 D1=A)?
7. **Hierarchy and toggle-group rules** are the only judgement entries of the contract. Derive them from the oracle
   (largest text per screen in the Rust tree) instead?
8. **P003 `sim` invariant D12** (event stamping) belongs to the P003 session.

## 12. Proposed amendments to P003 (for its owner; nothing here is changed)

| P003 place | Proposal |
|---|---|
| §4.1 / `profiles.MATRIX` | Rows `ui_scene_render_input` (● ui), `ui_time` (● ui, wiring), `ui_parity` (● ui) beside `catalogue_and_layout` |
| §7.6 `ui-fit` | "fits its box" is measured with the font the renderer **actually uses**, through `lv_text_get_size`, in every language |
| §7.6 golden frames | Precondition §8.4; headless capture (Q1) |
| §7.4 sim invariants | Add "every emitted event carries the instant's `h.mono_ms`" (D12) |
| §11 gate list | Add `ui-scene`, `ui-render`, `ui-input`, `ui-time`, `ui-parity`, `ui-explore` (merge/nightly per §6.1) |
| §12 row "Style not rendered, banner scrim" | "Yes — `ui-render`, `ui-input`, `ui-parity`" once T1xx.14 lands |
| §13 ordering rule | `ui` loses nothing until the `ui-*` gates are ● (they add evidence; `ui` never had a mutation gate to lose) |

## 13. Measured inputs used [M]

- Harness runs `review harness runs `{en,bg,lock,short,probe,probe2,probe3}` (owner's) and `out/p004lang` (this
  draft; scenario `scenarios/p004-lang2.txt`: banner present → first EN tap removes it, language unchanged → second
  tap switches).
- Prototype `business-apps `tools/ui-review/p004/`scene_checks.py` over 13 trees (§1.3).
- Side-by-side images `business-apps plan/reviews/2026-11-10-visual/cmp/{1-welcome,2-numpad,5-end-of-shift,7-short-rejected,bg-1-choose-size}.png`.
- Catalogue size: `lkui/catalog/i18n/lockers.pot` 101 msgids, `kit.pot` 34.
- Rust tree source: `club-apps:apps/lockers-e2e/src/lib.rs:46-72` (Slint `ElementHandle`, absolute position, size).
- Rust banner placement: `club-apps:ui/lockers/ui/lockers.slint:219-227`.

## 14. Measurement plan

1. **Cost**: T1xx.01 ms/state; then per tier wall time on ten real merges (P003 §14 item 1).
2. **Yield**: distinct real UI defects per check per CPU-hour over the first month; a check that finds nothing and
   costs > [P] 5% of the nightly budget is demoted (P003 §14 item 3).
3. **Noise**: FP rate per check during its report-first period; promotion only below [P] 1 FP per nightly.
4. **Escapes**: every UI defect found by a person after this lands is classified by which check should have caught it
   (P003 §14 item 4); a defect no check could catch opens a gate task.

## 15. Places that need external evidence (for the literature agent)

Nothing below is cited; each slot states the question the evidence must answer.

- **[E: LIT-1] Automated GUI exploration and state abstraction.** How effective are model-based / systematic GUI
  explorers versus scripted scenarios at finding display and interaction defects; what state-abstraction (widget-tree
  hash vs full state) loses; whether coverage-guided ordering and combinatorial (pairwise) state selection are
  supported as cost-effective.
- **[E: LIT-2] Detection of layout/presentation failures.** Published automated detectors for overlap, clipping,
  truncation, out-of-viewport and internationalisation presentation failures (text expansion), and their precision /
  false-positive rates — to set the tolerances of §3.1–§3.3.
- **[E: LIT-3] Cross-platform/differential visual consistency.** Tree-based vs image-based comparison between two
  implementations of one UI; reported noise of image metrics across renderers; supports or refutes D4.
- **[E: LIT-4] Metamorphic testing for time handling.** Evidence that clock-shift/metamorphic relations find timer and
  time-base bugs (F1's class) and at what cost.
- **[E: LIT-5] Minimum touch-target size.** The platform guideline (Material 48 dp) and accessibility guidance on
  target size, as provenance for `touch_min` (currently taken from Rust `KioskMetrics`).
- **[E: LIT-6] Transient UI elements / timing properties.** Evidence on bugs where messages vanish or persist wrongly,
  and on property-based checks over UI event traces.
- **[E: LIT-7] Golden-image/visual regression practice.** False-positive rates and approval workflows, to calibrate
  §6.4 and §8.4.
- **[E: LIT-8] Text expansion between English and Bulgarian (or Slavic languages generally)**, to set a design margin
  for `text-overflow` beyond "fits today".
