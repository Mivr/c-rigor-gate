# The `ui-time` judge (U09, P004 3.5)

The fourth judge of `rigor ui-explore` (docs/ui-explore.md): it reads every PATH as a timeline and judges how long timed
elements stay, their countdowns, elements that flash, state changes nobody can see, timers too short to read, and
behaviour that depends on the absolute clock. The historic defects it targets are F1 (a message that vanished before
anyone could read it) and F6a (a countdown shown wrong). Everything of docs/ui-judges.md about the finding schema,
`contract-pending`, exceptions, `exception-unused`, `checks-examined`, `check-vacuous` and `check-blocked` applies.
Python, stdlib only:

| Module | Concern |
|---|---|
| `ui_judge_time_model.py` | the timeline: per step a `Facts` (word mode, virtual time, state class, the timed elements shown, their countdowns and text, comparable records, patches and whether they agree with the records); binding contract timers; countdown formats |
| `ui_judge_time_checks.py` | the rules, pure, decided on bounds (`decisions`: yes, no or undecided); the probing plan (`plan`, `refine`, `rising`, `falling`) |
| `ui_judge_time_probe.py` | the probing runs: appearance and disappearance bisection, sampling inside a step, `probe-diverged`, the `at`-word cap |
| `ui_judge_time_inside.py` | what is shown only inside a time step: its created-and-removed keys, the element instances seen there, their rules |
| `ui_judge_time_origin.py` | `clock-origin-divergence`: the selection of paths and the comparison |
| `ui_judge_time.py`, `ui_judge_time_finish.py` | the judge: per path, findings, contract values; the end of the run |
| `ui_explore_time.py` | the explorer's side: the hook and the `Runner` of the probing runs and the origin replays |

```
rigor ui-explore ... --judges ui-time[,ui-scene,ui-fit,ui-render] --contract FILE.toml --today YYYY-MM-DD
```

`ui-time` needs `--contract` and `--today` like every judge, and a probe that announces `frame-facts`. With a probe that
announces `identity` the explorer reads the identity of every step for it (also when `ui-scene` is not selected).
Without `ui-time`, nothing of this runs: the hook returns the explorer unchanged (proof in "Deviations and limits").
Selftest: `selftest/ui_time.sh` (called by `selftest/ui.sh`) on the timed canary. Unit tests:
`gate/tests/test_ui_judge_time.py` (the rules on hand-built `Facts`; the judge over a timed product simulated in Python,
`test_ui_judge_time_helpers.py`, millisecond by millisecond, no wall time), `test_ui_judge_time_probe.py` (the probing,
undecided, diverged and capped probes, lying patches, a screen under a message, the origin comparison) and
`test_ui_lockers_classes.py`.

## What it reads

Per step of the first run of a path (the explorer's own observation, docs/ui-explore.md "Paths and time"):

- the word's **mode**: `open`, `input` (u1 to u5: a user input), `env` (an e1 reply: no user input), `time` (`settle`,
  `wait-change`, `at`, a t1 event) or `domain`;
- `now`, the step before's `now`, and `next-due`, both relative to the origin;
- the **state class** of the identity (`state` line), when the probe has identity;
- the **semantic records** (key, role, label), the **patches** (`create <key> node - <role>`, `remove <key> node <role>
  -`, `update <key> text <old> <new>`: the lockers adapter's forms) and the **frame** without its `life` and `taps`
  lines (they are in one frame only);
- the keys of a declared countdown restart (U05d, the step's `restart`).

**Patches are the product's claim** and are checked: from the second step on, the step's patches must lead from the
step before's semantic records to its own (a `create` of a key not shown, a `remove` of a key shown, a text `update`
whose old text is the label shown, and at the end the same keys and, where the chain knows a label, the same label: the
countdown-restart rule's check). A step where they do not is `patches-inconsistent` (on the path, not on probing runs,
which repeat its prefix) and gives `flash`, `stalled` and `increase` no verdict. `life` lines are not read (honesty
table). Nothing reads the wall clock.

**An element is an instance** (fix-up 2), not a kind, followed by its own nodes: the nodes of its kind's scope when it
first is the topmost element of that kind. It stays shown while every one of those nodes is in the scene with the same
role and label and no patch of the step removed it, also under another element of the same kind stacked over it (the
kiosk stacks its self-test banner over a boot banner). Countdown nodes are not part of it: a countdown that ticks, is
made again or is removed leaves the element shown (`countdown-wrong` judges the countdown: a removed one is `absent`).
A new topmost scope (another text, other keys, a node made again) is a new instance and a new appearance. Banner A
replaced by banner B is two elements, each with its own lifetime. Every probing sample shows the element only while it
is that instance; the countdown rules read its countdown only while it is the topmost of its kind.

**Binding a contract timer** (`[[timer]]`, docs/ui-contract.md: kind, class, `lifetime_ms` L, `countdown_shown`):
- with identity: a kind is shown iff the step's state class IS the kind (the class of the topmost message, else of the
  screen; docs/ui-judges-identity.md). An element shown at the step before also stays shown while ANOTHER message kind
  is the class and every node of its scope keeps its key, its role and (a countdown aside) its label, and no patch of
  the step removed it: a message is drawn over what it covers, which stays visible behind it (ui-rules), so a screen
  under a dialog and a banner under a snackbar continue, and a dismissed message gives no new appearance. Keys alone
  do not tell: the kiosk reuses key 3 for the headline of several screens;
- without identity: only a timer of class `message` whose kind is a scene layer role (`dialog`, `banner`, `snackbar`)
  can be bound, shown iff a semantic record has that role. Every other timer (all screen timers: lockers'
  `choose_size`, `opened`, `report`, `lockout`) is one `check-blocked` per check that would read it (identity
  `["blocked", check, kind]`, `needs: identity`), and `invisible-auto-transition` is `check-blocked` too.

**Scope of an element** (where its countdown and text are): semantic records are in tree order and a message is drawn
above its screen, so a message's scope is from the LAST record of a message layer role to the end; a screen's, the
records before the first layer record (`scrim` included); without identity, from the last record of the kind's role.
The countdown is the records of role `countdown` in the scope; the text, the non-empty labels of role `text` there.

**A countdown's value.** Neither the contract nor the catalogue declares a countdown format, so the gate's: a label
whose only digits are one run of 1 to 18 digits shows that many seconds (`298 сек`); a label whose only digits are
`M:SS` shows minutes and seconds (`0:29` is 29 s, not 0); anything else has no value and is one `contract-incomplete`
(`["countdown-format", kind]`) per kind per run. A declared format (a contract or catalogue key) would replace this.

**Contract values**: `clock.tick_ms` (the tick), `reading.rate_wpm`, `thresholds.dwell_base_ms`, `dwell_floor_ms`,
`dwell_chars_per_word` (the dwell; the static dwell rule does not need the tick), `thresholds.flicker_floor_ms` (the
flash threshold). A pending one is `contract-pending` (identity `[check, entry]`, once per run) for each check that
needs it, and that check gives no verdict (and is never vacuous). Lockers: `rate_wpm` (Q11) and `flicker_floor_ms`
(Q5) are pending.

## The time-probing mode

The explorer's words jump: `fire-due` to the next deadline, `at` to an offset, `until-change` to the change. To judge a
lifetime the judge needs the instant an element appears and the instant it goes. For every **appearance** (a step
where a bound kind is shown and was not at the step before), once per (state key, kind) in the whole exploration, and
for every **time step whose patches create and then remove one key** (something was shown only inside the step), it
runs PROBING PATHS made of the path's own words and `at` words. No input: whatever ends the element is time.

1. **The appearance** of an element first shown at the end of a TIME step lies in (the step before, now]. The path up
   to the step before, then at most 15 `at` words inside that span, bisects it, to one tick, then further while a rule
   is undecided. An input step's appearance is exact (the clock does not move).
2. **The plan** (`plan`) after the appearance step: the deciding instants `a_hi + D - tick - 1` (still shown then:
   not short) and `a_hi + L + tick` (still shown then: long), and a grid of 16 instants up to the later one, in ticks,
   never more than `max_wait_ms` apart. Without a known D, the floor approximation's instant; with L = 0 and no D
   nothing to decide.
3. **The disappearance**: (last instant shown, first instant gone], refined by runs of at most 15 `at` words inside it:
   to one ms for a timer with a countdown (the last label before it goes is read: a `0` shown for under a tick is seen),
   else to one tick, then further while a rule is undecided.
4. **Inside a step** (a time step whose patches create and then remove one key, whatever the flash threshold): the
   path to the step before, then 15 `at` words inside the step; then, while a created-and-removed key has not been
   seen in any sample, the midpoints of the 15 widest gaps between consecutive samples; then the instants that narrow
   the edges still undecided; at most 6 runs, every later run re-sampling one instant already seen (runs must agree).
   Each element instance seen only inside (neither at the step before nor at its end) gets the lifetime rules and
   `flash`, each created-and-removed key no such instance holds gets `flash`, both edges from the samples; a key no
   sample ever showed is `lifetime-undecided` (`why` `hidden-unsampled`, identity `["inside", word, key, "hidden"]`)
   and its flash is not counted. Keyed by the state before the step; such a step counts against the probe cap.

**Decided or reported.** Each lifetime rule is decided on the bounds (`decisions`): yes (a finding), no, or undecided.
An undecided rule is NOT counted as examined and is one `lifetime-undecided` (error: the gate could not judge a
contract timer; identity `[kind, check]` and the state key of the appearance; `observed` the brackets, the bound and
`why`: `bracket` when the runs could not narrow it, `at-word-cap` when the plan was not run, `hidden-unsampled` for a
key shown only inside a step that no sample caught). `flash` too: a node created at one step and removed at a later
one is shown for more than (the step before the removal) - (its creation) and at most (the removal) - (its earliest
creation); undecided between, it is `lifetime-undecided` (check `flash`) and not counted. It is exceptable like
the other ui-time findings (`lifetime-undecided` is in the loader's closed rule list).

**Bound.** Per edge at most 6 runs (`MAX_PHASES`; 16^5 > 600 000: a bracket of the longest advance down to one ms); a
refining run has at most 15 `at` words; the plan's run has at most 16 + 2 + ceil(horizon / `max_wait_ms`) and is not
run above 64 (`MAX_AT`: then `lifetime-undecided`, `why` `at-word-cap`; with `max_wait_ms` >= horizon / 46 it never
happens: the lockers catalogue's 300 256 ms covers every horizon). At most 64 probed appearances per exploration
(`MAX_PROBES`); the rest are not judged and one info `time-probes-capped` names the first capped (state key, kind) and
the count. Every probing run is run twice with the explorer's run judges (a probe error or nondeterminism there is the
explorer's own finding). A probing run that does not show the element at the appearance step as the path did (another
state key there; for a bisected appearance, the instance at the step's end), or whose samples disagree with another
run's (samples must change at most once in time: `monotone`; inside a step, one life per key; an instant re-sampled
must agree) is `probe-diverged` (error, with the path and the probing path), and that element is not counted as
examined: a missing element never moves a bound. Probing runs are not strategy paths: no step judge of another gate sees them, coverage does not record
them, and (U05e) they run with a non-judging scene, as the layer policy's sibling replays do (scene tap words resolve;
no layer verdict, no sibling replay). They spend the wall budget: a budget spent inside a probing run raises out of the
path's run, so the strategy ends as a cut run (`budget_spent`, never reported complete; a bfs drops the state that path
reached, though the path's own steps are already recorded). The origin replays that wait for the end of the run run
right after the strategy, inside the same budget handling (`ui_explore_time.end`): a budget spent there ends the run
as a cut run too (`budget_spent` true, no criterion evaluated, the explorer's budget timeout). They are added to the
summary's `cost`; `checks-examined` reports the judge's own
share (`cost`: `probe_runs`, `origin_runs`, `probe_commands`, `virtual_ms`). The pre-run cost check (`check_cost`)
does not count them: they are known only once a path has run.

**Measured cost**: the timed canary, 15 paths: 30 probing runs and 32 origin replays, 8 930 probe commands and 231 494
virtual ms of the run's 9 656 and 235 894; 3.0 s of wall time in all (without ui-time: 528 commands, 4 400 ms). The real
kiosk: docs/ui-lockers-first-run.md, "ui-time on the class paths".

A key that does not tell two behaviours apart is probed once: the abstraction key is the owner's
(docs/ui-explore.md); `key-too-coarse` is the explorer's finding for such a key. The canary gives each variant its
own title for that reason.

## The rules

Instants are virtual ms; every rule is decided on bounds and gives a finding only when the bounds decide it.
Identity of a finding: `ui-time.<check>/<12 hex of sha256([gate, check, [identity, state key]])>`, the state key of
the step named below; `path` the words up to that step (so the finding replays: the replay probes again). An
appearance is (a_lo, a_hi), the disappearance (t1_lo, t1_hi]: shown for more than t1_lo - a_hi and at most t1_hi - a_lo.

| Check | Rule | Identity, target, state |
|---|---|---|
| `notice-lifetime-short` | shown at most t1_hi - a_lo < D - tick (not short when more than D - tick - 1), D = max(L, max(`dwell_floor_ms`, `dwell_base_ms` + reading)) (P004 3.10), reading from the element's text as the run shows it | `[kind]`, target the kind; the appearance (`["inside", word, kind]`, the step before, for an element shown only inside a step) |
| `notice-lifetime-short-floor` | (an approximation, its own id) while the reading rate is pending: the same with max(L, `dwell_floor_ms`), a lower bound of D for any rate | as above |
| `notice-lifetime-long` | L > 0 and shown for more than L + tick (not long when at most L + tick) | as above |
| `flash` | a scene node not of role `countdown`, created and removed (patches) with no user input after its creation (env replies and time steps are no user input), the removal step's `now` minus the creation's `appear_lo` < `flicker_floor_ms`; a node created and removed within ONE step is measured by that step's span (0 for an input) | `[key, role]`, target the key; the creation step, path to the removal |
| `countdown-wrong` | while the element is shown (from the appearance, one run, and every probing sample of the same instance): `absent` (no countdown in its scope while it is the topmost of its kind, also on the path's own steps; then no `stalled`); `start` (the first value outside ceil(L/1000) +-1; for an appearance bracket of s ms, any value down to ceil((L - s)/1000) - 1); `zero` (0 as a step-end label, or a patch to 0 on a node still shown at that step's end); `increase` (a value that grows, in a step's patches or from one step-end label to the next (a node made again), while the same instance stays shown, on time AND input steps of the path and of the probing runs after their prefix, unless a declared countdown restart on a tap, U05d); `stalled` (no change for 1000 ms or more after the last instant a change can have happened, or one step of W ms with c changes and W >= 1000 (c + 1)) | `[kind, part]`; the appearance (an increase on the path: the step of the increase) |
| `invisible-auto-transition` | a time or env step changes the state class while the semantic records and the frame (but `life` and `taps`) are byte-identical | `[from, to]`, target `from/to`; the step before |
| `dwell-below-reading-time` | static: a `message` timer with L > 0 below max(`dwell_floor_ms`, `dwell_base_ms` + reading) of the text the run shows (no message catalogue is given; the reading rule is the contract's dwell table, `ui_contract_dwell`) | `[kind, msgid or text:<16 hex>]`, no state (one per message) |
| `clock-origin-divergence` | the path replayed from each origin of {1, 1000, 10^9, 2^32 + 7, 2^40} ms but its own: the first step whose semantic records (a countdown's label with every digit run masked and its value kept), identity, time since the origin or `next-due` relative to the origin differ, or where the replay ended | `[["origin", word, part], key]`, the step before; path the whole path |
| `patches-inconsistent` | the step's patches do not lead from the records before it to its own (above); judged on the path and on the probing runs after their prefix | `[word, why]`; the step before, path to the step |

Run-level and meta findings besides those of docs/ui-judges.md: `lifetime-undecided`, `probe-diverged`,
`time-probes-capped` (info) and `contract-incomplete` (`countdown-format`).

**"User-relevant"** (`invisible-auto-transition`): the gate's facts about what the state IS are the identity's state
class and the catalogue key's derived facts. Derived facts are computed from the semantic records, so with the records
unchanged they cannot change: the rule is the state class. Model facts (`deadline`, `env-inputs`) are not
user-relevant.

**Clock-origin selection**: first every path that shows a (state key at the appearance, timer kind) pair no selected
path has shown, in run order; paths whose pairs are all covered wait and fill the quota at the end of the run, in run
order. The quota is 8 paths per seed of the `open` word (with the explorer's boot seeds, per boot seed). Timers are
where absolute-vs-relative time bugs live, and replaying every path at 4 more origins would multiply the run's cost by
5. Each replay runs once (the comparison is against the path's own first run, which run-twice already checked).

**Not judged**: an `[[exception]]` names the target above; the ui-time rules are in the loader's closed list
(`patches-inconsistent`, a breach of the protocol, is not exceptable). A "declared successor" cannot be declared (the
contract has no such table): none excuses. A dismiss "addressed to" the element cannot happen in a probing run (no
input).

## Honesty table

| P004 3.5 check | Status |
|---|---|
| `notice-lifetime-short` | implemented; D needs `reading.rate_wpm`, pending for lockers (Q11): there `contract-pending`, and the floor approximation below. Undecided bounds are `lifetime-undecided`, never silent |
| (approximation) `notice-lifetime-short-floor` | its own id: D bounded below by max(L, `dwell_floor_ms`) while the rate is pending |
| `notice-lifetime-long` | implemented |
| `flash` | implemented on patches the gate checks against the records (`patches-inconsistent`), decided on bounds (undecided: `lifetime-undecided`, not counted); a create/remove pair inside a time step longer than the threshold is sampled inside the step. The `life`-line half is BLOCKED: a `life` line carries no object identity, and `node -1` is written both for an object that was never in a reported walk and for an event after an unreported retried walk (docs/ui-model.md), so a created and a deleted line cannot be tied to one object nor told from a retried snapshot; the missing fact is an object id in `life` lines. The threshold is `flicker_floor_ms`, pending for lockers (Q5) |
| `countdown-wrong` | implemented for presence, start, zero, increase and the once-per-second recurrence. The formatted string against the oracle's at the same virtual time is BLOCKED: no oracle in the gate. A countdown format is the gate's (no declaration exists) |
| `invisible-auto-transition` | implemented for the state class (a time or env step, semantic and frame unchanged); BLOCKED without identity (`check-blocked`). The O1 half (a view-state field) is BLOCKED: the protocol has no view-state stage |
| `dwell-below-reading-time` | implemented from the texts the run shows (no message catalogue; the longest locale is the longest the run shows); needs `rate_wpm` (pending for lockers) |
| `clock-origin-divergence` | implemented, bounded (8 paths per seed, 4 origins each) |
| `unresponsive-intent` | BLOCKED: the contract does not mark which intents are effective in which state class. It would need, per `[[state_class]]`, the effective intents and a feedback bound (P004 3.10's 5 frames) |

The blocked halves are also listed in `checks-examined` (`blocked_parts`), with `bound` (the kinds bound) and
`blocked_kinds`, the per-check totals, the probing cost and `lifetimes`: per probed element the kind, state key, path,
L, D, the floor, `appeared` (a_lo, a_hi), `shown_more_than_ms`, `shown_at_most_ms`, the runs and `decided` (per rule
true, false or null) (the kiosk's table is in docs/ui-lockers-first-run.md).

## Canaries (`selftest/ui_canary_product/timed*`)

A 320x240 LVGL app (`timed.c`) with its model adapter (`timed_model.c`, `:time_probe`): the scene is a pure function of
(variant, the instant it was asked for, now), published as semantic records and patches; the deadline is the next
instant it may change; identity is the state line only. Catalogue `timed.events.toml` (one u1 intent per variant, a t1
`fire-due`), contract `time.toml` (canary.toml with a 4 s `dialog` timer with a countdown and a `banner` without a
limit), paths `timed.paths.json` (origin 10^9). Each variant has its own title, so its own state.

| Path (after `open`) | Variant | Findings (identity), each exactly once |
|---|---|---|
| (none) | the title | none |
| `v-clean` | a 4 s dialog "Saved." whose countdown counts 4 3 2 1; lifetime bracketed to (3999, 4000] | none |
| `v-early` | the dialog leaves after 1 s | `notice-lifetime-short` (`["dialog"]`) |
| `v-never` | the dialog never leaves, its countdown stops at 1 | `notice-lifetime-long` (`["dialog"]`), `countdown-wrong` (`["dialog", "stalled"]`) |
| `v-flash` | an LVGL object created and deleted within the input (patches `create`/`remove flash`) | `flash` (`["flash", "panel"]`) |
| `v-blink`, `fire-due` | a panel shown for 200 ms | `flash` (`["blink", "panel"]`) |
| `v-skip` | the countdown counts 4 2 (every 2 s) | `countdown-wrong` (`["dialog", "stalled"]`) |
| `v-zero` | the countdown counts 3 2 1 0 | `countdown-wrong` (`["dialog", "zero"]`) |
| `v-start` | the countdown starts at 9 | `countdown-wrong` (`["dialog", "start"]`) |
| `v-silent`, `fire-due` | the state class turns `detail` 1 s later, nothing visible changes | `invisible-auto-transition` (`["main", "detail"]`) |
| `v-clock` | the expiry kept modulo 2^32 against the 64-bit clock: from 2^32 + 7 and 2^40 (exactly those two) the dialog never shows | `clock-origin-divergence` (`[["origin", "v-clock", "semantic"], key of the open state]`) |
| `v-wordy` | a 4 s dialog whose 96 characters need 6878 ms of dwell | `dwell-below-reading-time` (`["dialog", "text:..."]`), `notice-lifetime-short` (`["dialog"]`, D 6878) |
| `v-up` | the countdown counts 4 3 4 3 | `countdown-wrong` (`["dialog", "increase"]`) |
| `v-bare` | a 4 s dialog without a countdown | `countdown-wrong` (`["dialog", "absent"]`) |
| `v-clean`, `fire-due`, `v-bump` | an input restarts the dialog's countdown (3 to 4), no declared restart | `countdown-wrong` (`["dialog", "increase"]`, the state of the bump) |

`selftest/ui_time.sh` asserts exactly these, by count (ids recomputed from identity and state key, target and part),
the short finding keyed by the v-early appearance's state, the two diverging origins of v-clock, nothing on the clean
dialog, every check with verdicts and none vacuous, blocked, undecided, diverged or cut, the clean bracket, the origin
replays equal to 4 x the selected paths, byte-identical findings over two release runs and release/san, every finding
replayed from its `paths.json`, no ui-time finding and the same runs without `--judges`, exit 2 without a contract,
and no probe left.

## Each check seen failing against a broken judge

A copy of `gate/` with one rule broken (`/var/tmp/cache/U09/mut/run3.sh` and `run4.sh`, not committed): the canary
checks against the selftest's own assertion block (with `--evidence`, as the selftest runs it; the unmutated copy
passes it), the others against `test_ui_judge_time`, `test_ui_judge_time_probe` and `test_ui_judge_time_fixup2`.
`zero` and `increase` are each found two ways (labels and patches; patches and step-end values), so both ways were
broken together for the canary row. Every row failed:

| Broken | How | Failed |
|---|---|---|
| `notice-lifetime-short` | the short bound minus 100 000 | the selftest (v-early, v-wordy) |
| `notice-lifetime-long` | the long bound plus 100 000 | the selftest (v-never) |
| `flash` | `< threshold` to `< 0` | the selftest (v-flash, v-blink) |
| `countdown-wrong` start / zero / stalled / increase | each part's test to False | the selftest (v-start; v-zero; v-skip, v-never; v-up, v-bump) |
| `countdown-wrong` absent on the path | not judged | `test_a_removed_countdown_leaves_the_screen_shown_and_is_absent` |
| `invisible-auto-transition` | the class comparison to False | the selftest (v-silent) |
| `dwell-below-reading-time` | `if lifetime >= least` to `if True` | the selftest (v-wordy) |
| `clock-origin-divergence` | the semantic comparison to constants | the selftest (the id: the identity part then diverges first) |
| `notice-lifetime-short-floor` | the floor bound dropped | `test_pending_rate_gives_contract_pending_and_the_floor_check`, `test_floor_approximation_only_without_dwell` |
| `lifetime-undecided` | an undecided rule silently skipped | `test_undecided_is_a_finding_and_not_examined` |
| `probe-diverged` | a diverging run accepted | `test_a_diverging_probe_run_is_a_finding` |
| `time-probes-capped` | not reported | `test_the_probe_cap_is_reported` |
| `patches-inconsistent` | the chain check removed | `test_patches_that_contradict_the_records_are_a_finding_and_judge_nothing` |
| appearance bisection | off | `test_an_appearance_inside_a_time_step_is_bisected_to_decide` |
| elements shown only inside a step | off | `test_a_one_second_notice_inside_a_five_second_step_is_short` |
| a screen under a message | not carried | `test_a_screen_continues_under_a_message` |
| origin `time` / `due` | not compared | `test_time_and_deadline_relative_to_the_origin` |
| countdown `M:SS` | read as its first run | `test_countdown_formats` |
| (fix-up 2) sampling inside a step until every key is seen | only the undecided edges refined | `test_the_samples_are_refined_until_every_key_is_seen` |
| (fix-up 2) `hidden-unsampled` | not reported | `test_a_key_never_sampled_is_undecided` |
| (fix-up 2) instances followed by their nodes | every node always held | `test_a_replacement_across_steps_is_a_new_appearance` |
| (fix-up 2) a new instance is a new appearance | only a new kind | `test_ids_are_keyed_by_the_state_of_the_first_appearance`, `test_an_appearance_inside_a_time_step_is_bisected_to_decide` |
| (fix-up 2) carry checks roles and labels | keys only | `test_not_carried_when_the_screen_underneath_changed`, `test_no_carry_to_a_successor_screen_with_a_superset_of_keys` |
| (fix-up 2) samples change at most once | always monotone | `test_monotone` |
| (fix-up 2) the instance at the step's end in the appearance run | not checked | `test_another_instance_at_the_end_of_the_step_is_a_divergence` |
| (fix-up 2) a re-sampled instant must agree | not checked | `test_a_diverging_inside_run` |
| (fix-up 2) increase from step-end values | off | `test_increase_by_a_node_made_again` |
| (fix-up 2) patch chain and increases on probing runs | path only | `test_patches_that_contradict_the_records_are_a_finding_and_judge_nothing` |
| (fix-up 2) the origin fill inside the budget handling | not run there | `test_a_cut_during_the_origin_fill_is_a_cut_run` |
| (fix-up 2) flash undecided | dropped | `test_flash_needs_no_input_between_and_ignores_countdowns` |

## Deviations and limits

- **Without ui-time nothing changes.** The canary judges replay (`ui-scene,ui-fit,ui-render`), a toy bfs and the timed
  canary without judges give findings, summary and stdout byte-identical to the gate before U09 (`aa69748`); on the
  real kiosk the other gates' findings are the same with and without ui-time.
- **One class per state**: identity names one class; an element is carried under another message only while its own
  nodes stay as they were (above).
- **Instance signature**: a replacement that keeps the msgid and the text of its first text node and reuses the same
  keys without a remove patch is not seen as a replacement.
- **Inside a step**: an element shown so briefly that six sampling runs miss it is `lifetime-undecided`
  (`hidden-unsampled`); the refinement of undecided edges takes the 15 earliest instants per run.
- **The cost pre-check** does not include the probing runs and replays (they depend on what the paths show).
- **The origin quota is per seed of the open word** even without the explorer's boot seeds (a paths file with several
  seeds gets 8 per seed).
- **`--judges ui-time` alone** builds no step context (no frame association): the stage findings of ui-scene are
  ui-scene's.
