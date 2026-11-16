# The first exploration of the real lockers kiosk (U23)

`rigor ui-explore` with the `ui-scene` and `ui-fit` judges on the release probe of the real kiosk, with the DRAFT event
catalogue and key `products/business-apps/ui/lockers.events.toml` (unsigned, for the owner's review, row by row). This
page records what the machine found, what it cost, and where the gate, the catalogue or the adapter is still wrong.
Nothing in the gate, the contract or the product was changed. Evidence stayed in `/var/tmp/cache/U23/` (not
committed); what matters is quoted here.

**Inputs.** Probe: business-apps `1acc1cb` (U04a checkout, its `gate/` submodule's probe protocol is the same),
`biz//apps/lockers/lkapp/uimodel:lockers_ui_probe`, built with `gate/tools/buck2 build
//apps/lockers/lkapp/uimodel:lockers_ui_probe --show-output` from that checkout (cached, no download), sha256
`0e068b0bd0d2ab30...`; it greets `ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop pointer`, the summary
records `taps = entry`. Catalogue sha256 `32c7ed60f2559a97...` (every run below but `bfs-envkeyed-m6`, which used the
earlier key with `env-inputs`). Contract `products/business-apps/ui/lockers.toml` unchanged, `--today 2026-11-16`.

## Summary

- The explorer accepts the real probe: no `probe-internal-error`, no `ui-explore-timeout`, no `model-nondeterministic`
  and no `run-twice-mismatch` in any run (about 3 700 paths, each run twice).
- `sweep` cannot run: exit 2, "sweep needs a model with a view domain (uim_domain_count() is 0)", on every boot seed
  (the adapter has no view-domain enumerator, its doc "Limits"). The boot seeds were run as replays instead.
- `bfs` is bounded by the gate's cost model, not by the host: with `max_wait_ms` covering the 5 min report, the
  pre-run check allows at most **6 admitted states** under `--budget-s 1200` (7 is refused, exit 2). A bfs with 18
  states took 1274 s of wall time (it needed `--budget-s 3200` to pass the check). The bfs reaches 5 of the 13 screen
  classes (Welcome with its banner, the pad, the rejection dialog, Choose size, the report) and the splash; replays
  reach all 13.
- Every known product defect was found again through the explorer, and two NEW instances: the `?40` storage label also
  in the fault DIALOG of a visit (disk-full boot), and a single persistent banner drawn over the Choose-size BG/EN switch.
  A NEW timing behaviour: `timer-starvation` during every locker opening and with the relay powered off (a 5 ms poll).
- The countdown-restart rule works end to end on the real report: one `ambient-restart` (298 -> 300), complement and
  root taps refused, and without the declaration exactly those taps are `noop-tap-effect`.
- The largest false-positive classes are the explorer's own `intent-missed`/`tap-misrouted` under the modal dialog and
  the fixed-point taps that are not scoped to a state.

## The catalogue

Counts: u1 31 (every scene key with an intent: digits 32..42, Del 41, OK 43, sizes 48/49/50, Cancel 17, Done 16, the
notice Dismiss 323 and scrim 320, six banner Dismiss buttons and six banner scrims), u2 18, u3 4, u4 17 (11 wedge,
6 pad), u5 2, e1 29 (every row of the adapter: 2-15, 20-25, 30-34, 40, 41, 50, 51), t1 10 (fire-due, before-due,
until-change, one frame, one tick, and the product timers 4 s, 8 s, 30 s, 60 s, 300.256 s). `requires` all seven
capabilities; `drain_ms = 60000`; `max_wait_ms = 300256`; `[ambient]` `trace = ["touch"]` and
`countdown_restart_role = "countdown"`, no `due_restart_ms`. Every row's provenance is in the comment beside it
(product spec line, adapter doc line, or the probe record it was read from).

Decisions and deviations in the catalogue:
- **u1 intents are scene node keys with arg 0.** The adapter takes `apply 3 <node key> 0` (business-apps
  docs/lockers/ui-model.md L76); the catalogue's `intent` field carries the node key.
- **u4 through the pad: zeros only.** The catalogue's pad macro sends `apply 3 <digit_intent> <digit>`; the adapter
  refuses any non-zero arg (each digit is its own scene key). Only codes of zeros (`digit_intent = 42`, the key "0")
  can be typed, so the pad covers `empty`, `one-digit`, `max-minus-1`, `max`, `max-plus-1` and `unknown` (000000) but
  not the valid visitor or staff codes. That is an interface gap between `ui-events/1` and this adapter (below).
- **Boundaries.** The pad holds at most 64 digits (a 65th is refused, measured); 64 is "max" (rules L52: "longer than
  64" is invalid). `expired` is the fixture's INACTIVE staff code 666661 (the fixtures have no expired code).
- **Persistent-banner scrims are `expect = "refuse"`**: by the spec they have no tap-outside area (rules L17, L71); the
  product publishes the intent anyway (the known defect), and the press is missed.
- **Boot seeds are not a catalogue field** (`ui-events/1` has none): the header lists them (112 healthy, 113-119
  profiles 1-7, 120 codes offline) and they are each run's `--seed`.
- Only fake codes appear (121212, 666662, 666661, 343434, 999999 and filler digits); no network address of any kind, no token.

## The abstraction key

Fields: every semantic field but `label` (`role x y w h enabled intent flags style importance input_policy
wrap_policy`); facts: `deadline`; derived: the length bucket and the first-number bucket of every `text` node, and the
labels of every `button` and every `key`. `ignore = []`.

- **Separates:** the screen class and every notice of the stack (the projection lists every record by its node key),
  the language (the BG/EN style tokens 20/21 and the button and key labels), the entered-digit count (the echo's dot
  panels are scene nodes, so the count is exact, 0..64), the selection (style, enabled, D), the text content by length
  and first number (report counters, locker 82, a sync status 401).
- **Leaves out:** countdown values (role `countdown` is never selected; `label` is not a field) and absolute times
  (the report's "Приключи в 00:00 UTC", the sync-late banner's time: their length is constant and their first number
  is the hour). Because `label` is not ignored, `key-too-coarse` still compares every label.
- **`env-inputs` is NOT in the key** (a deviation from the toy's key, measured): with it the bfs spent its whole bound
  on armed-row combinations at the splash, `bfs-envkeyed-m6`: states per depth `[1, 20, 83]`, 104 states, every
  admitted state an armed-row splash, Welcome reached only at depth 2. Without it the same bound gives `[1, 2, 8, 9]`
  over Welcome, the pad, dialogs and Choose size. The price: an armed row that shows nothing is merged with the healthy
  state, so the bfs never explores "arm a row, then visit"; walks and replays do.

**Neither too coarse nor exploding** (the evidence):
- `key-too-coarse` (info) in the bfs with 18 states: 25 findings, every one classified from its `records.json`:
  18 differ only in the fact `env-inputs` (the deliberate merge above) and 7 only in one countdown label (node 6
  "300 сек" -> "299 сек", "30 сек" -> "29 сек"; node 326 "8 сек" -> "7 сек", in BG and EN). No other field differed in
  any run (bfs-m18 25, walk-3x30 10, walk-5x100 32, screens 10, boot-seeds 10: the same two causes only).
- `depth-unsaturated` in every bfs, reason `state-bound` only (never `last-depth-adds-states` below the bound): the
  bound, not the key, stops the bfs.
- `model-nondeterministic`: none.
- States per depth, healthy seed 112, origin 1000: `[1, 2, 8, 18, 11]` (18 states admitted, 40 states seen, 22
  dropped); the smaller bfs (depth 2, same bound) `[1, 2, 8]`, equal on the shared depths; the 6-state bfs
  `[1, 2, 8, 9]` (its depth 3 is from a 3-state frontier, so 9 is not comparable).

## Coverage: the 13 screen classes

| Screen class (adapter table) | bfs-m18 | walks | replays |
|---|---|---|---|
| Welcome with the self-test banner | yes, bg+en | yes | screens |
| Keypad, digits entered | 1-3 digits, bg+en | 1-6 | screens (4, bg+en) |
| Rejection dialog | yes, bg+en | yes | screens |
| Choose size | yes, bg+en | yes | screens |
| Opened 82 | no (dropped by the bound) | no | screens |
| "A door may have opened" dialog | no | no | screens (row 2) |
| "Reservation saved." snackbar | no | no | screens (row 11) |
| Codes offline at boot | no (seed 120) | no | screens, boot-seeds |
| Three banners (audit, sync, codes stale) | no | 2-3 banners | screens (seed 119, rows 20, 30) |
| End-of-shift report | bg only | yes | screens (bg+en), restart |
| Relay fault screen | no (seed 113) | no | screens, boot-seeds |
| Storage fault screen | no (seed 114) | no | screens, boot-seeds |
| Lockout | no | yes | screens |

Not reached by any run: the not-saved banner WITH the opened screen as a judged state of the bfs (a replay passes it),
row 50's "Clock looks wrong" and row 33's sync-late banner (they need a self-test after a shift, or more than 1 h).
Screens the fault and lockout states cannot show in English (the adapter doc: they have no switch).

## Runs

All from the U23 worktree with `gate/rigor ui-explore --probe <probe> --catalogue
products/business-apps/ui/lockers.events.toml --judges ui-scene,ui-fit --contract products/business-apps/ui/lockers.toml
--today 2026-11-16 --out F --summary S --evidence E` and the arguments below, under `timeout`. Findings: total
(errors); the main checks.

| Run | Arguments | Exit | Wall | States | Runs x2 | Findings |
|---|---|---|---|---|---|---|
| sweep-112 .. sweep-120 | `--strategy sweep --origin-ms 1000 --seed S --budget-s 600` | 2 | 0.5-0.7 s | - | - | none: "sweep needs a model with a view domain (uim_domain_count() is 0)" |
| bfs-cost-m7 | `--strategy bfs ... --depth 12 --max-states 7 --budget-s 1200` | 2 | 0.4 s | - | - | refused: "could take 19837356 ms of virtual time, about 1239 s ... over --budget-s 1200" |
| bfs-envkeyed-m6 | the same with 6 states (key with env-inputs) | 1 | 302 s | 104 | 667 | 10946 (10944): 10878 C8 gaps, 46 event-never-accepted, 5 timer-starvation, 6 occluded-target |
| bfs-m6 | `--strategy bfs --origin-ms 1000 --seed 112 --depth 12 --max-states 6 --budget-s 1200` | 1 | 369 s | 20 | 667 | 1649 (1636): 1554 C8 gaps, 41 intent-missed, 8 tap-misrouted, 13 event-never-accepted, 11 key-too-coarse, 1 timer-starvation, 7 occluded-target, text-clipped + text-overflow on 8 |
| bfs-m18 | `... --depth 12 --max-states 18 --budget-s 3200` | 1 | 1274 s | 40 | 1999 | 2698 (2671): 2442 C8 gaps, 160 intent-missed, 31 tap-misrouted, 10 event-never-accepted, 25 key-too-coarse, 2 timer-starvation, 12 occluded-target, 2+2 on 8 |
| bfs-m18-d2 | `... --depth 2 --max-states 18 --budget-s 3200` | 1 | 147 s | 11 | 334 | 930 (921), `[1, 2, 8]` |
| walk-3x30 | `--strategy walk --origin-ms 1000 --seed 112 --walk-seeds 1,2,3 --walk-length 30 --extra-origins 0 --budget-s 3600` | 1 | 17 s | 15 | 3 | 40 (28): 8 intent-missed, 1 tap-misrouted, 8 occluded-target, 10 key-too-coarse |
| walk-5x100 | `... --walk-seeds 1,2,3,4,5 --walk-length 100 --extra-origins 1 --budget-s 40000` | 1 | 213 s | 49 | 10 | 195 (161): 92 intent-missed, 16 tap-misrouted, 35 occluded-target, 6 overlay-policy |
| screens | `--strategy replay --paths screens.json --budget-s 7200` (23 paths: the 13 classes, bg and en) | 1 | 9 s | 37 | 23 | 85 (61): 28 occluded-target, 10 overlay-policy, 4 stage-unowned-target, 14 stage-unmatched (4 errors), 1 stage-text-mismatch, 2 noop-tap-effect, 2 ambient-restart |
| boot-seeds | `--strategy replay --paths boot-seeds.json --budget-s 3600` (seeds 112-120) | 1 | 4 s | 20 | 9 | 39 (27): 13 occluded-target, 4 overlay-policy, 2 stage-text-mismatch |
| restart-decl-1, -2 | `--strategy replay --paths restart.json --budget-s 600` | 1 | 1.8 s | 3 | 4 | 16 (12), identical bytes twice |
| restart-nodecl-1, -2 | the same with the scratch catalogue without `countdown_restart_role` | 1 | 1.8 s | 3 | 4 | 18 (15), identical bytes twice |
| replay-* | the `paths.json` of `ambient-restart/3a908e5f38f5`, `noop-tap-effect/14b0e62792cb`, `text-clipped/971c4b3a0575`, `timer-starvation/db80754e7c98`, `timer-starvation/05d45d3c5764` | 1 | 0.6-2.2 s | | | each replays to its id |

Every run also has the contract findings that do not depend on the path: `ui-scene.contract-pending` x5 (Q9 the panel:
occluded-target, touch-target-small, overlay-policy, target-spacing; Q7 the importance table: hierarchy-violated) and
`ui-scene.contract-incomplete` `role-wrap` for muted_caption, key_label, staff_strong, screen_headline and, where the
lockout is reached, large_countdown. No `check-vacuous` in any run that leaves the splash; the one replay that stays on it (the timer-starvation path
`05d45d3c5764`, relay powered off at the splash) has seven and two `key-fact-unmatched` (key-labels, button-labels):
a derived selector that matches nothing on a splash-only run.

## The countdown-restart rule end to end (contract item 3a)

`restart.json` (origin 1000, seed 112; the report is shown at 4200 with "300 сек", at 6200 it shows "298 сек"):

```json
{"schema": "ui-explore-paths/1", "criteria": [], "paths": [
 ["open 1000 112", "at 3200", "wedge-staff", "at 5200", "blank-bottom-left", "blank-bottom-left"],
 ["open 1000 112", "at 3200", "wedge-staff", "at 5200", "tap-done-opened"],
 ["open 1000 112", "at 3200", "wedge-staff", "at 5200", "disabled-medium", "tap-key-1"],
 ["open 1000 112", "at 3200", "wedge-staff", "at 5200", "tap-done-report"]
]}
```

With the declaration (`restart-decl-1`):
- the complement taps (`blank-bottom-left`, `disabled-medium`, u3) and the root taps (`tap-done-opened` at 640,595 and
  `tap-key-1` at 754,124 are u2 points that land on the report's screen, `pressed lv_obj 0,0,1279,799 root`) are all
  `tap refused`; no `noop-tap-effect`;
- exactly one `ui-explore.ambient-restart/3a908e5f38f5` (info): `observed` `{"node": "6", "old": 298, "new": 300,
  "word": "blank-bottom-left"}`, path `open 1000 112, at 3200, wedge-staff, at 5200, blank-bottom-left`; its id is
  sha256 of `["ambient-restart", ["restart", "25f76679...fe44e", "6"]]` (recomputed), the key being the report's
  (the same key as the report's `key-too-coarse` state). The root tap of path 2 restarts the same node of the same
  state and is merged into that id (the explorer keeps the shortest path);
- the second tap at the same instant (path 1's second word, path 3's `tap-key-1`) is `tap refused` with no patch and no
  further finding;
- `tap-done-report` (the Done button, intent 7:0) is `tap ok`, `pressed lv_button 24,705,1255,752 aimed`.
- **Not shown: "a u2 tap on a non-intent node there is `intent-missed`".** The real report has NO clickable non-root
  node without an intent: its frame holds the screen, the two layers, 16 labels (not clickable) and the Done button
  (frames.out of the probe, below). Every point but Done presses the screen root, so the case cannot occur there; the
  gate's own fixture covers it (stub mode `pcount`).

Without the declaration (`restart-nodecl-1`, the scratch copy differs in that one key only): the same three restarting
taps are `noop-tap-effect` with `changed = ["patches", "semantic", "frame"]` (`0e10b18d47ae` disabled-medium,
`14b0e62792cb` blank-bottom-left, `c72344e7a0c1` tap-done-opened); the second taps stay refused (no patch at the same
instant); no `ambient-restart`. The rule is load-bearing.

Both runs are byte-identical when run twice; `ambient-restart/3a908e5f38f5` and `noop-tap-effect/14b0e62792cb` replay
to their ids from their evidence `paths.json`.

**The two report frames** (the probe directly, the same instants: `open 1000 112`, `advance 4200`, `apply 2 0 0
363636363632`, `advance 6200`, `frame`, `semantic`, `tap 5 795`, `frame`, `semantic`, `patches`, `trace`, then a second
`tap 5 795`): the tap is `ok tap 1 1` (the screen), trace `46 touch 6200`, patch `update 6 text 298 сек 300 сек`,
`next-due` 6250 before and after. Without the first frame's `taps` line both frames have 76 lines in the same order;
the lines that differ are exactly:

```
frame   1280 800 d5bab163 -> c9a42085
region  0 / 1 / 19 / 20   d5bab163 -> c9a42085   (bottom layer, screen, top and sys layers: they cover the label)
label   3 ... =298 сек -> =300 сек                (font -, line_h 18, align 2/2, long 0, not dotted, 1 line, 55x18 both)
region  3                 2a31efad -> fb0b8d3b
```

The countdown's walk index 3 is the only label showing "298 сек"; its `node` record (`lv_label 24 82 423 101`) and its
`fit` record are unchanged (laid 55 x 18 before and after, so the box rule has nothing to allow); no ancestor or sibling
`node` record changed. The `label` text field `=298 \xd1\x81\xd0\xb5\xd0\xba` equals the semantic label of node 6
`298 \xd1\x81\xd0\xb5\xd0\xba` byte for byte after the `=` prefix. The second tap changes no frame line and makes no
patch (trace `47 touch 6200` only).

## Triage (every distinct finding, by id prefix and target)

| Finding | Where (first path) | Class |
|---|---|---|
| `ui-scene.occluded-target` `layer-unreachable` on scrims 296 (self-test), 264 (audit), 272 (sync), 280 (codes offline), 288 (codes stale) | every banner state, e.g. `at 3200` | **product defect, known**: dead tap-outside of the persistent banners (scrim rect = card rect) |
| `ui-explore.intent-missed` on `banner-*-scrim` (u1 296 etc.) | `timer-snackbar > banner-selftest-scrim` | **product defect, known**: the same dead tap-outside, seen at the input (the scene publishes an intent the spec forbids, rules L71) |
| `ui-scene.overlay-policy` `captures` 320/11, 320/12, 320/16; `stage-unowned-target` card 128,626-1151,791 and its Dismiss; `stage-unmatched` 321, 323 (errors), 322, 326 + three unowned labels (info) | snackbar, `env-book-second-save-fails > wedge-visitor > size-small > at 4300` (bg, en) | **product defect, known**: the snackbar drawn away from its scene rect and its full-window capturing scrim |
| `ui-scene.overlay-policy` `captures` 288/11, 288/12 | seed 119, `env-codes-unreachable > env-sync-401 > at 300500` (bg, en) | **product defect, known**: stacked banners over BG/EN |
| `ui-scene.overlay-policy` `captures` 264/11, 264/12 on Choose size | seed 118 and 119 boot-seeds `... wedge-visitor`; walk-5x100 | **product defect, NEW instance**: ONE persistent banner (audit) over the Choose-size BG/EN switch. Reader's check, `records.json`: scrim 264 `24 24 1232 108` 258:0; drawn card node 18 `lv_obj 24 24 1255 131`, opaque (bg ffb4ab, opa 255), painted after the BG button node 4 `lv_button 540 100 635 147`: the card covers BG/EN at y 100..131 |
| `ui-fit.text-clipped`, `text-overflow` (`height`) on 8 | `timer-snackbar > wedge-staff` (bg only) | **product defect, known**: the Bulgarian licences line clipped on the report |
| `ui-scene.stage-text-mismatch` on 5 | seed 114 `at 3200` | **product defect, known**: the storage-fault detail drawn as `?40` |
| `ui-scene.stage-text-mismatch` on 325 | seed 118 (disk full) `at 3200 > ... > wedge-visitor > size-small` | **product defect, NEW instance of the `?40` cause**: the fault DIALOG's staff cause ("Грешка в паметта: книгата с резервации не може да се запише или зареди.", scene 304,418 672x48) is drawn as `label 55 ... =?40` (laid 27 x 18) |
| `ui-explore.timer-starvation` (33 firings in 1005..1165 ms) | `env-relay-powered-off > settle x33` | **pending owner decision** (docs/ui-explore.md "Starvation": whether timers under ~31 ms are allowed is open), behaviour NEW to the record: while the relay dial is pending the product's next deadline is 5 ms away (probe: next-due 1005, 1010, ... 1045, then 1105, 1205, measured) |
| `ui-explore.timer-starvation` | `timer-snackbar > wedge-visitor > size-small > settle x33` | **pending owner decision**, the same 5 ms cadence during EVERY healthy locker opening (next-due 4205, 4210, 4215, 4220 after `size-small` at 4200). Bounded (the opening ends), not a 0-delay loop; a product defect only if the owner rules such a poll out |
| `ui-explore.intent-missed`, `ui-explore.tap-misrouted` for pad digits, Del, OK, BG/EN, banner Dismiss, the u2 taps of other screens, pad macros, under the rejection dialog | `timer-snackbar > enter > digit-1` etc. | **gate false positive** (explorer): input behind a dialog does nothing by the spec (rules L11, L17) and the sealed `[[input_layer]] dialog` blocks input below; the explorer's own `intent-missed` and `tap-misrouted` do not consult the layer policy. Minimal reproduction: paths `["open 1000 112", "timer-snackbar", "enter", "digit-1"]` and `[..., "enter", "tap-key-1"]` |
| `ui-explore.intent-missed` for u2 points that are not a control in that state (`tap-choose-bg` on Welcome lands on the self-test banner card, `tap-dialog-dismiss-tall` on the rejection dialog's card, `tap-done-opened` on the scrim) | `timer-snackbar > tap-choose-bg` | **gate limitation** (catalogue model): u2 points are fixed for every state, while P004 4.3 derives them per state from the rendered tree; a fixed point on a clickable card without an intent is "missed". No catalogue fix exists short of dropping the points |
| `ui-explore.noop-tap-effect` `blank-bottom-left` on the snackbar | screens, `... at 4300 > blank-bottom-left` | **gate false positive** against the spec (rules L13: a tap outside the snackbar dismisses it; P004 4.3 U3 "expected outcome: no intent, or the declared dismiss"): the explorer has no "declared dismiss" outcome. The capture itself over BG/EN/Done is the known snackbar defect |
| `ui-explore.event-never-accepted` (10 in bfs-m18: the five banner Dismiss buttons not on Welcome, `notice-scrim`, the undo rows 15, 25, 34, 51) | bfs | **exploration limit**: the bounded bfs never reaches those states (and the key merges an armed row with the healthy state); the screens replay accepts `notice-scrim` on the snackbar |
| `ui-explore.ui-coverage-gap` C8 (2442 in bfs-m18) | bfs | **exploration limit**: pairs of dropped states (`state-bound`) |
| `ui-explore.depth-unsaturated` `state-bound` | bfs | **exploration limit / gate cost model** (below) |
| `ui-explore.key-too-coarse` (info) | every run | **intended merges**: env-inputs and countdown values only (above) |
| `ui-explore.ambient-restart` (info) | the report | **the declared restart** (above) |
| `ui-scene.contract-pending` x5 | every run | **pending owner decisions** Q9 (panel) and Q7 (importance) |
| `ui-scene.contract-incomplete` `role-wrap` muted_caption, key_label, staff_strong, screen_headline, large_countdown | every run | **contract gap**: the five roles without a `[[role_wrap]]` row (docs/ui-judges.md) |
| `ui-explore.key-fact-unmatched` (key-labels, button-labels), `check-vacuous` x7 | runs that never leave the splash (replay of `timer-starvation/05d45d3c5764`; the first smoke replay) | **expected for a splash-only run** (no key or button exists there). A catalogue lesson, fixed in the documented paths: `until-change` from the splash stops after 5 ms at the deadline fact's change, so the paths leave the splash with `at 3200` or `timer-snackbar` |

Unclassified: none. No `scene-vocabulary`, no `probe-internal-error`, no `ambient-missing`/`ambient-extra`, no
`event-accepted` (Medium, Large and the banner scrims were never accepted).

## Cost

- Per path, both runs: 0.45-0.6 s on this 4-CPU host with the judges (bfs-m18: 1999 paths in 1274 s, 516 530 probe
  commands, 38.4 M ms of virtual time; ~30 000 virtual ms per wall second overall, against the cost model's 16 000).
- The pre-run cost check is the binding limit: bfs worst = 2 x max_states x sum over the 110 sendable events of (span
  + 1024 ms). `fire-due`, `before-due` and `until-change` each count `max_wait_ms` (300 256) although the kiosk's next
  deadline is a 250 ms tick, and `timer-report` counts 300 256, so the sum is about 1.42 M ms and `--budget-s 1200`
  admits 6 states. Replay `at <offset>` words also count `max_wait_ms` each, not min(offset, max_wait) (the replays
  needed `--budget-s 600` for four paths of two `at` words).
- Walks: `--walk-length 30` for 3 seeds needs `--budget-s 3600` by the same arithmetic; 5 x 100 x 2 origins needed
  40 000 and took 213 s.

## Limits

- Render-only differences are not keyed: two states that differ only in what LVGL draws (the snackbar's position, a
  label clipped in one language) are one state; the judges see the first visit's frame per path (docs/ui-judges.md).
- No view-domain enumerator: `sweep` refuses; C1 cannot be evaluated; the boot seeds are replays.
- The bfs cannot explore "arm an environment row, then act" under this key, and with `env-inputs` keyed it explodes.
- u2 and u3 points are fixed for every state; the explorer's tap judges do not read the contract's layer policy.
- The pad macro cannot type a non-zero digit on this adapter.
- `--require` today: `C8` is evaluated by every bfs (and fails with the bound's gaps); `C1` can never be evaluated
  (no view domain). A `--require C8` gate on the real kiosk would fail on every bounded bfs until the bound or the key
  changes.

## The changes that would most raise what the machine finds

1. **A cost model that reads the next deadline** (or a per-word measured span): the 250 ms tick makes `fire-due` and
   `until-change` cost 250 ms, not 300 s; the same 20 min would admit hundreds of states instead of 6.
2. **The modal layer in the explorer's tap and intent judges**: skip or downgrade `intent-missed`/`tap-misrouted` under a
   sealed capture-modal-inert layer (and a "declared dismiss" outcome for complement taps under a tap-outside layer);
   that removes most of the 160 errors of bfs-m18.
3. **State-scoped u2 points** (P004 4.3: the centre and P(n) of every interactive node of the rendered tree) instead
   of fixed points.
4. **A view-domain enumerator in the adapter** (`uim_domain_count` > 0): sweep, C1 and the 13 classes x 2 languages
   without long paths.
5. **A pad macro that matches the adapter** (one intent per digit key, e.g. a digit-to-intent map in `u4`), so the
   valid codes go through the pad too.
6. **A start-from-state option** (bfs from a replayed prefix such as Welcome or the report), so the bound is spent on
   UI states, not on the splash.

## Re-running

Build the probe in the business-apps checkout (cached): `cd /var/tmp/wt/business-apps/U04a && gate/tools/buck2 build
//apps/lockers/lkapp/uimodel:lockers_ui_probe --show-output`. From the c-rigor-gate worktree, with `P` that output:

```sh
gate/rigor ui-explore --probe "$P" --catalogue products/business-apps/ui/lockers.events.toml --strategy sweep \
  --origin-ms 1000 --seed 112 --budget-s 600 --out OUT --summary SUM \
  --judges ui-scene,ui-fit --contract products/business-apps/ui/lockers.toml --today 2026-11-16
# exit 2: rigor: internal error: InternalError: sweep needs a model with a view domain (uim_domain_count() is 0)

gate/rigor ui-explore --probe "$P" --catalogue products/business-apps/ui/lockers.events.toml --strategy replay \
  --paths restart.json --budget-s 600 --out OUT --summary SUM \
  --judges ui-scene,ui-fit --contract products/business-apps/ui/lockers.toml --today 2026-11-16
# exit 1; 16 findings: ui-explore.ambient-restart/3a908e5f38f5, ui-explore.key-too-coarse/e4f3eb9d3db4,
# ui-fit.checks-examined/4e0d1448cc93, ui-fit.text-clipped/971c4b3a0575, ui-fit.text-overflow/6117603b8ff9,
# ui-scene.checks-examined/c4c4df33ffbd, ui-scene.contract-incomplete/{951558b98cb8,980d4e4eb125,cf468399e460,
# d4bdc5505308}, ui-scene.contract-pending/{148b81015f4f,3eef6d994176,5ae64644b993,91f89d0854c9,aa9761e42588},
# ui-scene.occluded-target/439bd29e91fe; no noop-tap-effect
```

The loader test: `gate/tests/test_ui_lockers_catalogue.py` (schema, requires, the ambient declaration, every e1 row of
the adapter once, no `due_restart_ms`, the key without countdown values, fake codes only).
