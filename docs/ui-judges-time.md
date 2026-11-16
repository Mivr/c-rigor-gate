# The `ui-time` judge (U09, P004 3.5)

The fourth judge of `rigor ui-explore` (docs/ui-explore.md): it reads every PATH as a timeline and judges how long timed
elements stay, their countdowns, elements that flash, state changes nobody can see, timers too short to read, and
behaviour that depends on the absolute clock. The historic defects it targets are F1 (a message that vanished before
anyone could read it) and F6a (a countdown shown wrong). Everything of docs/ui-judges.md about the finding schema,
`contract-pending`, exceptions, `exception-unused`, `checks-examined`, `check-vacuous` and `check-blocked` applies.
Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_time_model.py` | the timeline: per step a `Facts` (word mode, virtual time, state class, the timed elements shown, their countdowns and text, comparable records, patches); binding contract timers |
| `ui_judge_time_checks.py` | the rules, pure, on bounds; the probing plan (`plan`, `refine`, `bracket`) |
| `ui_judge_time.py` | the judge: per path, the probes and replays, findings, contract values, `finish` |
| `ui_explore_time.py` | the explorer's side: the hook and the `Runner` of the probing runs and the origin replays |

```
rigor ui-explore ... --judges ui-time[,ui-scene,ui-fit,ui-render] --contract FILE.toml --today YYYY-MM-DD
```

`ui-time` needs `--contract` and `--today` like every judge, and a probe that announces `frame-facts`. With a probe that
announces `identity` the explorer reads the identity of every step for it (also when `ui-scene` is not selected).
Without `ui-time`, nothing of this runs: the hook returns the explorer unchanged (proof in "Deviations and limits").
Selftest: `selftest/ui_time.sh` (called by `selftest/ui.sh`) on the timed canary. Unit tests:
`gate/tests/test_ui_judge_time.py` (the rules on hand-built `Facts`; the judge over a timed product simulated in Python,
`test_ui_judge_time_helpers.py`, millisecond by millisecond, no wall time) and `test_ui_lockers_classes.py`.

## What it reads

Per step of the first run of a path (the explorer's own observation, docs/ui-explore.md "Paths and time"):

- the word's **mode**: `open`, `input` (u1 to u5: a user input), `env` (an e1 reply: no user input), `time` (`settle`,
  `wait-change`, `at`, a t1 event) or `domain`;
- `now` and the step before's `now`. Something new at a step appeared at an instant in **(before, now]** for a time
  step, at exactly `now` otherwise (`appear_lo`);
- the **state class** of the identity (`state` line), when the probe has identity;
- the **semantic records** (key, role, label), the **patches** (`create <key> node - <role>`, `remove <key> node <role>
  -`, `update <key> text <old> <new>`: the lockers adapter's forms) and the **frame** without its `life` and `taps`
  lines (they are in one frame only);
- the keys of a declared countdown restart (U05d, the step's `restart`).

`life` lines are not read (the flash row of the honesty table says why). Nothing reads the wall clock.

**Binding a contract timer** (`[[timer]]`, docs/ui-contract.md: kind, class, `lifetime_ms` L, `countdown_shown`):
- with identity: a kind is shown iff the step's state class IS the kind (the class of the topmost message, else of the
  screen; docs/ui-judges-identity.md). Every timer can be bound;
- without identity: only a timer of class `message` whose kind is a scene layer role (`dialog`, `banner`,
  `snackbar`) can be bound, shown iff a semantic record has that role. Every other timer (all screen timers: lockers'
  `choose_size`, `opened`, `report`, `lockout`) is one `check-blocked` per check that would read it (identity
  `["blocked", check, kind]`, `needs: identity`), and `invisible-auto-transition` is `check-blocked` too.

**Scope of an element** (where its countdown and text are): semantic records are in tree order and a message is drawn
above its screen, so a message's scope is from the LAST record of a message layer role to the end; a screen's, the
records before the first layer record (`scrim` included); without identity, from the last record of the kind's role.
The countdown is the records of role `countdown` in the scope; the text, the non-empty labels of role `text` there.

**Contract values**: `clock.tick_ms` (the tick), `reading.rate_wpm`, `thresholds.dwell_base_ms`, `dwell_floor_ms`,
`dwell_chars_per_word` (the dwell), `thresholds.flicker_floor_ms` (the flash threshold). A pending one is
`contract-pending` (identity `[check, entry]`, once per run) for each check that needs it, and that check gives no
verdict (and is never vacuous). Lockers: `rate_wpm` (Q11) and `flicker_floor_ms` (Q5) are pending.

## The time-probing mode

The explorer's words jump: `fire-due` to the next deadline, `at` to an offset, `until-change` to the change. To judge a
lifetime the judge needs the instant an element appears and the instant it goes, so for every **appearance** (a step
where a bound kind is shown and was not at the step before), once per (state key, kind) in the whole exploration, it
runs PROBING PATHS: the path up to the appearance step, then `at` words. No input: whatever ends the element is time.

1. **The plan** (`plan`): the two deciding instants, `appear_lo + D - tick - 1` (gone by then: short) and
   `now + L + tick` (still shown then: long), and a grid of at most 16 instants up to the later one, in multiples of
   the tick, never more than `max_wait_ms` apart. Without a known D, the floor approximation's instant; with L = 0
   (no limit) and no D, no probe.
2. **The bracket**: the disappearance lies in (last instant shown, first instant gone].
3. **Refinement**: while the bracket is wider than one tick, another run with at most 16 `at` words inside it.

**Bound**: at most 4 runs per appearance (the grid, then refinements by 16: 16^3 ticks cover 1024 s, the longest
lockers timer is 300 s), each with at most 18 `at` words, each run twice (as every path, with the explorer's run judges:
a probe error or a nondeterminism in a probing run is the explorer's own finding); at most 64 appearances per
exploration (`probes_capped` counts the rest; none in any run here). Virtual time per run: the prefix plus at most
L + tick. Probing runs are not strategy paths: no step judge of another gate sees them and coverage does not record
them; they spend the wall budget (`--budget-s`; a spent budget is the explorer's budget timeout) and are added to the
summary's `cost`; `checks-examined` reports the judge's own share (`cost`: `probe_runs`, `origin_runs`,
`probe_commands`, `virtual_ms`). The pre-run cost check (`check_cost`) does not count them: they are known only once a
path has run.

**Measured cost**: the timed canary, 12 paths: 15 probing runs and 32 origin replays, 3 312 probe commands and 121 744
virtual ms of the run's 3 864 and 124 144, 1.6 s of wall time in all (without ui-time: 402 commands, 2 400 ms). The real
kiosk's 29 class paths with all four judges: 31 probing runs, 32 origin replays, 20 318 probe commands and 3.97 M
virtual ms; 43 s of wall time against 14 s without ui-time (docs/ui-lockers-first-run.md, "ui-time on the class paths").

A key that does not tell two behaviours apart is probed once: the abstraction key is the owner's
(docs/ui-explore.md); `key-too-coarse` is the explorer's finding for such a key. The canary gives each variant its
own title for that reason.

## The rules

Instants are virtual ms; every rule is decided on bounds and gives a finding only when the bounds decide it.
Identity of a finding: `ui-time.<check>/<12 hex of sha256([gate, check, [identity, state key]])>`, the state key of
the step named below; `path` the words up to that step (so the finding replays: the replay probes again).

| Check | Rule | Identity, target, state |
|---|---|---|
| `notice-lifetime-short` | shown for less than D - tick: the first instant gone minus `appear_lo` < D - tick, where D = max(L, max(`dwell_floor_ms`, `dwell_base_ms` + reading)) (P004 3.10), reading from the element's text as the run shows it | `[kind]`, target the kind; the appearance |
| `notice-lifetime-short-floor` | (an approximation, its own id) while the reading rate is pending: the same with max(L, `dwell_floor_ms`), a lower bound of D for any rate | as above |
| `notice-lifetime-long` | L > 0 and still shown at `now + L + tick` | `[kind]`; the appearance |
| `flash` | a scene node not of role `countdown`, created and removed (patches) with no user input after its creation (env replies and time steps are no user input), the removal step's `now` minus the creation's `appear_lo` < `flicker_floor_ms`; a node created and removed within ONE step is measured by that step's span (0 for an input) | `[key, role]`, target the key; the creation step, path to the removal |
| `countdown-wrong` | while the element is shown (from the appearance, one run): `absent` (no countdown in its scope); `start` (the first value outside ceil(L/1000) +-1, or, for an element that appeared inside a time step, below ceil((L - span)/1000) - 1); `zero` (0 shown, in a label or a patch); `increase` (a value that grows in a time step, but a declared restart); `stalled` (no change for 1000 ms or more after the last instant a change can have happened, or one step of W ms with c changes and W >= 1000 (c + 1)) | `[kind, part]`; the appearance |
| `invisible-auto-transition` | a time or env step changes the state class while the semantic records and the frame (but `life` and `taps`) are byte-identical | `[from, to]`, target `from/to`; the step before |
| `dwell-below-reading-time` | static: a `message` timer with L > 0 below max(`dwell_floor_ms`, `dwell_base_ms` + reading) of the text the run shows (no message catalogue is given; the reading rule is the contract's dwell table, `ui_contract_dwell`) | `[kind, msgid or text:<16 hex>]`, no state (one per message) |
| `clock-origin-divergence` | the path replayed from each origin of {1, 1000, 10^9, 2^32 + 7, 2^40} ms but its own: the first step whose semantic records (a countdown's label as its value) or identity differ, or where the replay ended | `[["origin", word, part], key]`, the step before; path the whole path |

**"User-relevant"** (`invisible-auto-transition`): the gate's facts about what the state IS are the identity's state
class and the catalogue key's derived facts. Derived facts are computed from the semantic records, so with the records
unchanged they cannot change: the rule is the state class. Model facts (`deadline`, `env-inputs`) are not
user-relevant.

**Clock-origin selection**: the first 8 distinct paths (run order) whose first run shows a bound timed element: timers
are where absolute-vs-relative time bugs live, and replaying every path at 4 more origins would multiply the run's cost
by 5. Each replay runs once (the comparison is against the path's own first run, which run-twice already checked).

**Not judged**: an `[[exception]]` names the target above; the ui-time rules are in the loader's closed list. A
"declared successor" cannot be declared (the contract has no such table): none excuses. A dismiss "addressed to" the
element cannot happen in a probing run (no input).

## Honesty table

| P004 3.5 check | Status |
|---|---|
| `notice-lifetime-short` | implemented; D needs `reading.rate_wpm`, pending for lockers (Q11): there `contract-pending`, and the floor approximation below |
| (approximation) `notice-lifetime-short-floor` | its own id: D bounded below by max(L, `dwell_floor_ms`) while the rate is pending |
| `notice-lifetime-long` | implemented |
| `flash` | implemented on patches. The `life`-line half is BLOCKED: a `life` line carries no object identity, and `node -1` is written both for an object that was never in a reported walk and for an event after an unreported retried walk (docs/ui-model.md), so a created and a deleted line cannot be tied to one object nor told from a retried snapshot; the missing fact is an object id in `life` lines. The threshold is `flicker_floor_ms`, pending for lockers (Q5) |
| `countdown-wrong` | implemented for presence, start, zero, increase and the once-per-second recurrence. The formatted string against the oracle's at the same virtual time is BLOCKED: no oracle in the gate |
| `invisible-auto-transition` | implemented for the state class (a time or env step, semantic and frame unchanged); BLOCKED without identity (`check-blocked`). The O1 half (a view-state field) is BLOCKED: the protocol has no view-state stage |
| `dwell-below-reading-time` | implemented from the texts the run shows (no message catalogue; the longest locale is the longest the run shows); needs `rate_wpm` (pending for lockers) |
| `clock-origin-divergence` | implemented, bounded (8 paths, 4 origins each) |
| `unresponsive-intent` | BLOCKED: the contract does not mark which intents are effective in which state class. It would need, per `[[state_class]]`, the effective intents and a feedback bound (P004 3.10's 5 frames) |

The blocked halves are also listed in `checks-examined` (`blocked_parts`), with `bound` (the kinds bound) and
`blocked_kinds`, the per-check totals, the probing cost and `lifetimes`: per appearance the kind, state key, path, L,
D, the floor, `shown_more_than_ms`, `shown_at_most_ms` and the number of probing runs (the kiosk's table is in
docs/ui-lockers-first-run.md).

## Canaries (`selftest/ui_canary_product/timed*`)

A 320x240 LVGL app (`timed.c`) with its model adapter (`timed_model.c`, `:time_probe`): the scene is a pure function of
(variant, the instant it was asked for, now), published as semantic records and patches; the deadline is the next
instant it may change; identity is the state line only. Catalogue `timed.events.toml` (one u1 intent per variant, a t1
`fire-due`), contract `time.toml` (canary.toml with a 4 s `dialog` timer with a countdown and a `banner` without a
limit), paths `timed.paths.json` (origin 10^9). Each variant has its own title, so its own state.

| Event | Variant | Findings (identity) |
|---|---|---|
| (open) | the title | none |
| `v-clean` | a 4 s dialog "Saved." whose countdown counts 4 3 2 1; lifetime bracketed to (3999, 4000] in 2 runs | none |
| `v-early` | the dialog leaves after 1 s | `notice-lifetime-short` (`["dialog"]`) |
| `v-never` | the dialog never leaves, its countdown stops at 1 | `notice-lifetime-long` (`["dialog"]`), `countdown-wrong` (`["dialog", "stalled"]`) |
| `v-flash` | an LVGL object created and deleted within the input (patches `create`/`remove flash`) | `flash` (`["flash", "panel"]`) |
| `v-blink`, `fire-due` | a panel shown for 200 ms | `flash` (`["blink", "panel"]`) |
| `v-skip` | the countdown counts 4 2 (every 2 s) | `countdown-wrong` (`["dialog", "stalled"]`) |
| `v-zero` | the countdown counts 3 2 1 0 | `countdown-wrong` (`["dialog", "zero"]`) |
| `v-start` | the countdown starts at 9 | `countdown-wrong` (`["dialog", "start"]`) |
| `v-silent`, `fire-due` | the state class turns `detail` 1 s later, nothing visible changes | `invisible-auto-transition` (`["main", "detail"]`) |
| `v-clock` | the expiry kept modulo 2^32 against the 64-bit clock: from 2^32 + 7 and 2^40 the dialog never shows | `clock-origin-divergence` (`[["origin", "v-clock", "semantic"], key of the open state]`) |
| `v-wordy` | a 4 s dialog whose 96 characters need 6878 ms of dwell | `dwell-below-reading-time` (`["dialog", "text:..."]`), `notice-lifetime-short` (`["dialog"]`, D 6878) |

`selftest/ui_time.sh` asserts exactly these (ids recomputed from identity and state key, target and part), nothing on
the clean dialog, every check with verdicts and none vacuous or blocked, the clean bracket, byte-identical findings over
two release runs and release/san, every finding replayed from its `paths.json`, no ui-time finding and the same runs
without `--judges`, exit 2 without a contract, and no probe left.

## Each check seen failing against a broken judge

A copy of `gate/` with one rule broken, the canary replayed, the selftest's own assertion block run on the findings
(`/var/tmp/cache/U09/mut/run.sh`, not committed). Every row failed the assertion:

| Broken | How | The selftest says |
|---|---|---|
| `notice-lifetime-short` | `at_most < dwell - tick` minus 100 000 | the v-early and v-wordy findings missing |
| `notice-lifetime-long` | `above >= lifetime + tick` plus 100 000 | the v-never finding missing |
| `flash` | `< threshold` to `< 0` | both flash findings missing |
| `countdown-wrong` start / zero / stalled | `> 1` to `> 100`; `0 in` to `-1 in`; the stall test to False | the v-start, v-zero, v-skip and v-never parts missing |
| `invisible-auto-transition` | the class comparison to False | the v-silent finding missing |
| `dwell-below-reading-time` | `if lifetime >= least` to `if True` | the v-wordy dwell finding missing |
| `clock-origin-divergence` | the semantic comparison to False | the id differs (the identity part then diverges first) |
| the probing mode | `if not instants` to `if True` | no lifetime row (the clean bracket check fails) |
| the refinement | the loop to `while False` | no finding of the expected set (the bracket is not one tick) |
| `notice-lifetime-short-floor` | `at_most < floor - tick` minus 100 000 | `test_ui_judge_time` RulesTest fails (it fires only with a pending rate, which the canary contract does not have) |

## Deviations and limits

- **Without ui-time nothing changes.** The canary judges replay (`ui-scene,ui-fit,ui-render`), a toy bfs and the timed
  canary without judges give findings, summary and stdout byte-identical to the gate before U09 (`aa69748`); on the
  real kiosk the other gates' 101 findings are the same with and without ui-time.
- **One class per state**: a screen timer appears to end while a message is over its screen (identity names the
  message). Probing runs have no input, so this matters only when a message appears by time.
- **Appearance inside a time step**: an element that appears during a long `at` or advance is known only to have
  appeared in (before, now]; its lifetime bounds are that much wider and often decide nothing (the kiosk's opened screen
  and the relay-hang dialog: 2 s). Refining the appearance (splitting the step) is not done.
- **Same-kind replacement**: a message replaced by another of the same kind without a gap is one element.
- **Resolution of flash**: decided only when the bound is under the threshold; a 200 ms blink first observed 600 ms
  later is not found.
- **The cost pre-check** does not include the probing runs and replays (they depend on what the paths show).
- **`--judges ui-time` alone** builds no step context (no frame association): the stage findings of ui-scene are
  ui-scene's.
