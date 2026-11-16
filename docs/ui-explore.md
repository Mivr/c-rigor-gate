# `rigor ui-explore`: the explorer driver (U05, P004 3.7, 4.1 to 4.5)

The machine every UI judge runs on. It starts a probe binary (`c_ui_probe`, docs/ui-model.md), drives it along input
paths through `ui-probe/1`, runs **every path twice in fresh probe processes**, keys the states it reaches by an
owner-declared abstraction key, applies the judges and writes one JSON line per finding. Python, stdlib only, in
`gate/rigor_lib/`:

| Module | Concern |
|---|---|
| `ui_explore.py` | the CLI: paths files, output safety, evidence, summary, signals, the capability launch |
| `ui_explore_probe.py` | the probe client: one process, deadlines, the run budget, typed errors, process groups |
| `ui_explore_grammar.py` | the reply and record grammar and the protocol's limits |
| `ui_explore_catalogue.py` | the catalogue and key loader (`ui-events/1`) |
| `ui_explore_key.py` | projection, key hash, derived facts, normalised record, readable state |
| `ui_explore_words.py` | what one path word does: inputs, the refusal check, time, drains, starvation counting |
| `ui_explore_run.py` | steps, runs, run-twice comparison |
| `ui_explore_judges.py` | findings, step judges and run judges, key-too-coarse |
| `ui_explore_coverage.py` | the exploration (visited graph) and the exploration judges (C1, C8, key facts) |
| `ui_explore_strategies.py` | sweep, bfs, walk, replay, and the cost check |
| `ui_explore_scene.py` | U05e: the state-scoped taps of a state ("Scene taps") |
| `ui_explore_layers.py` | U05e: the layer policy of the tap judges under `--contract` ("Taps under a layer") |
| `ui_explore_catalogue_ext.py` | U05e: the optional tables `taps`, `[boot]`, `[[prefix]]` and the pad's `digit_map` |
| `ui_explore_png.py` | the PNG writer |

Selftest: `selftest/ui.sh` steps 8 to 14 and its last step, 16; U05e: `selftest/ui_taps.sh` (run by ui.sh) on the
scene stub `gate/tests/data/ui_explore/stub_scene.py` with its catalogue `scene.events.toml` (scene taps, the layer
policy with and without the canary contract, the digit map, boot seeds, a prefix, the cost refusal and the budget cut;
unit tests `gate/tests/test_ui_explore_scene.py` and `test_ui_explore_boot.py`). The fixtures are the toy probe and three adapters: a
nondeterministic one, a starving one and one with a perpetual tick. The last step checks that no probe process is left.
Unit tests: `gate/tests/test_ui_explore*.py`, with a stub probe (`gate/tests/data/ui_explore/stub_probe.py`, one mode
per misbehaviour, and frame-facts modes that speak the protocol as the C probe does) and its catalogue
(`gate/tests/data/ui_explore/stub.events.toml`, the toy catalogue as U05 sealed it, without taps). Each test module's `tearDownModule` fails if a stub it started is still alive. A stub that would sleep
exits as soon as its parent is gone.

## The CLI

```
rigor ui-explore --probe BIN --catalogue FILE.events.toml --strategy sweep|bfs|walk|replay --out FINDINGS
                 [--contract FILE] [--deadline-ms N] [--budget-s N] [--require C1,C8] [--evidence DIR] [--summary FILE]
                 [--judges ui-scene,ui-fit --contract FILE --today YYYY-MM-DD]
  sweep:  --origin-ms N --seed N
  bfs:    --origin-ms N --seed N --depth D (1..64) --max-states M (1..1000000)
  walk:   --origin-ms N --seed N --walk-seeds S1,S2,... --walk-length L (1..10000) --extra-origins K (0..16)
  replay: --paths FILE (ui-explore-paths/1)
  sweep, bfs, walk: --boot-seeds catalogue in place of --seed (U05e: once per seed of the catalogue's [boot])
  bfs: --prefix NAME (U05e: start after the words of the catalogue's [[prefix]] row NAME)
```

Exit 0: no finding of severity error. 1: at least one. 2: the gate could not decide. That covers:
- an argument that is missing, refused for the strategy, out of range, or written with a leading zero;
- an unreadable or malformed catalogue, paths file or contract (nesting too deep included);
- a probe that is not an executable file or cannot be executed (an exec format error included);
- an output (`--out`, `--summary`) that is the same file as an input or as the other output; this is checked before
  anything is deleted, and nothing is deleted;
- an `--evidence` directory that exists and is not empty;
- catalogue taps for a probe without the tap capability;
- `sweep` on a model without a view domain; `bfs` or `walk` with no sendable event;
- a request in which ONE path's time words could exceed the whole budget (see "Cost");
- `--boot-seeds` with `--seed`, for `replay`, or with a catalogue without `[boot]`; `--prefix` for another strategy, a
  name the catalogue has no `[[prefix]]` row for, or a prefix word that is not a path word;
- a judge's evidence file name that is not `[a-z0-9][a-z0-9_-]*.json`, or is `paths.json`.

Nothing the product does gives exit 2. A probe that cannot greet, one whose capabilities change between launches, and a
budget spent during the first launch are all findings.

`--out` and `--summary` are removed when the run starts and written atomically at the end, so a stale result never
survives an exit 2 or a signal. On SIGTERM, SIGINT or SIGHUP the explorer kills every live probe's process group and
exits with 128 + the signal.

| Option | Meaning |
|---|---|
| `--deadline-ms` (10000) | bounds every reply of the probe, the greeting, and the exit after `quit` |
| `--budget-s` (1800) | the wall-clock budget of the whole run, measured. When it is spent, the run stops: a `bfs` drops the path it cut and ends cleanly with its bound finding `depth-unsaturated` (`reasons` holds `budget`; `detail.budget_cut` true); `sweep`, `walk` and `replay` end with one `ui-explore-timeout` (`observed.kind` = `budget`). Either way `budget_spent` is true, no criterion counts as evaluated (a cut run is never reported as complete), and the exit is 1, never a hang and never 2. Where it stops depends on the host, so such a findings file is not reproducible |
| `--require` | criteria that must be evaluated; each one not evaluated becomes a `ui-coverage-gap` with `observed.evaluated` = false |
| `--contract` | the UI contract (docs/ui-contract.md) handed to the judges; of the built-in judges only the tap judges read it, for the layer policy and the probe grid (U05e, "Taps under a layer") |
| `--judges` | judges of other gates to run as well: distinct names of `ui-scene` and `ui-fit` (docs/ui-judges.md). They need `--contract`, `--today` and a probe that announces `frame-facts` (exit 2 otherwise, the capability right after the greeting). With `ui-scene` and a probe that announces `identity` the explorer also reads the scene identity of every step ("Scene identity"); without that capability ui-scene's identity checks are `check-blocked` |
| `--today` | the date (`YYYY-MM-DD`) the contract's exceptions expire against; only with `--judges`. The judges never read the wall clock, so the same inputs give the same bytes on any day |

Clock origins and seeds are arguments. Deriving them from the verdict's input hash (P004 6.3) belongs to the grade
wiring (U14).

`--summary` (`ui-explore-summary/1`) holds:
- `strategy`, `criteria` (required by the strategy), `evaluated` (judged), `budget_spent`;
- the catalogue and probe sha256;
- `runs`, `abstract_states`, `pairs_exercised`, `domain_count`, `domain_visited`;
- `events`: per input event, `accepted_states`, `refused_states` and `missed_states`;
- `outcomes`: per path word, its outcome types (`fired`, `now`, `past`, `no-deadline`, `deadline-within-a-frame`,
  `no-change`, `changed`, `starving`, `unreachable`, `apply ok|refused|missed`, `tap ok|refused|missed`, ...) with counts. No time outcome is
  silent;
- `cost`: `probe_commands` and `virtual_ms` over both runs of every path;
- the finding counts (`findings`: every check of this gate by name, 0 included; a finding of another gate's judge as
  `<gate>.<check>`) and the strategy detail.

## Paths and time

A path is a list of words:

| Word | Meaning |
|---|---|
| `open <origin_ms> <seed>` | the first word, and only there |
| `domain-at <i>` | move to view-domain entry `i` |
| `settle` | fire the next deadline |
| `wait-change` | fire deadlines until the key changes |
| `at <offset_ms>` | advance to origin + offset |
| a catalogue event id | send that event |

After every word the explorer reads, in this order: `frame`, `semantic`, `patches`, `trace`, `next-due`, `env-inputs`
and (U24, only for a selected judge that needs it) `identity`. The `open` step reads `domain-count` first. Patches and trace fetched during the word (drains and snapshots) come first
in the step's `patches` and `trace`, so nothing is lost and run-twice compares all of it. Frame lines are parsed by the
record grammar (fields split and unescaped), and the verbatim text is kept alongside. From a probe that announces
`frame-facts`, every line must be one of the record types of docs/ui-model.md ("Frame facts") with exactly its field
count (`lvprobe` 3, `frame` 4, `node` 21, `label` 15, `fit` 8, `region` 3, `life` 7; `ink` 8 and `noink` 3 in an
`ink` reply); an unknown type or a wrong count is a protocol finding. From an older probe the lines may have any shape.
Every `err` reply (`no-frame` and `too-large` included) ends the run at that command: nothing more is sent to that
probe, which is killed. A failing command ends the
run at that step and becomes a finding. Nothing is retried, and no run is shortened silently.

**Virtual time.** Every time word is bounded by the catalogue's `max_wait_ms`, which has a hard ceiling of 1 h. A wait
that is longer, or that passes the protocol's clock (2^52), is not taken. The step records it as `timer-unreachable`,
with the target, now, the limit and the reason (`max-wait` or `protocol-limit`). This holds for `fire-due`, `settle`,
`before-due`, `at`, and for the first deadline of `until-change` and `wait-change`. A `next-due` reply takes the full
uint64 range the probe can print; a huge value is simply unreachable.

The time words:
- `before-due` within a frame of now is the outcome `deadline-within-a-frame`; `at` an offset already past is `past`.
- `until-change` and `wait-change` end in one of these outcomes:
  - `changed`;
  - `no-deadline`;
  - `no-change`: a later deadline lies past `max_wait_ms`. This is a quiet state of a perpetual tick, not a finding;
  - `starving`.

  On a ticking product, one notice expiry is then one event.

**Advances** go in spans of at most min(64, `drain_ms` / 16) frames, each ending on the grid `origin + k * 16` or at the
target. Patches and trace are fetched after every span that does not end the advance. `drain_ms` is required: a whole
number of frames, at most 60 000, since the real adapter's logs hold about a minute. The probe's own loop ends every
`uim_step` at each grid boundary and each deadline, so the split calls the model with exactly the same step lengths as
one long advance. It only bounds the work per command, keeping the per-command deadline valid on a slow product, and the
log volume between drains.

**Starvation (L0).** Every deadline firing (`fire-due`, `settle`, and each firing inside `until-change`) is counted
with its virtual time. More than `firings` firings within `window_frames` frames of virtual time is `timer-starvation`:
- the defaults are 32 firings within 64 frames (1024 ms);
- a catalogue may set both: `starvation = { firings, window_frames, provenance }`, where the provenance takes the UI
  contract's forms;
- it is reported once per run, at the firing that crossed the limit, for the state before the first firing of that
  window.

Alternating short and long delays (1 ms, 17 ms) are caught as well as a 0-delay loop. A deadline at or before now (the
probe's `err next-due|advance model-contract`, or a `next-due` that is not after now) is `timer-starvation` with kind
`zero-delay`.

A legitimate perpetual timer with a period of at most 1024 / 33 ms (about 31 ms, so a one-frame animation included)
would be flagged too. Whether the owner allows such timers is an open decision. A stable scene must not have one
(model.h).

**The settle check.** `sweep`, `bfs` and `walk` follow every first run with `settle` words for one starvation window
of virtual time. It ends when no deadline is left inside the window, a wait is unreachable, or the run starves, so
there are at most `firings` + 1 of them. A perpetual 250 ms tick gives 4. The second run executes exactly the words of
the first; `replay` appends nothing.

**Inputs and the refusal check.** Every `apply` and `tap` of a word is checked on its own. Before it the explorer holds
a snapshot: frame records, semantic records, next deadline and env inputs. For the first input of a word that is the
step before's observation; otherwise a fresh one. Every snapshot is read in the order of the step's own observation,
`frame` FIRST (a `frame` runs the product's due work and may retake its snapshot, docs/ui-model.md), then `semantic`,
`patches`, `trace`, `next-due`, `env-inputs`. A `life` line is in the first frame after its event only, so the frame is
compared without its `life` lines, and a `life` line in the frame AFTER an input counts as a change (an object was
created or deleted). After a refused input it takes another snapshot and fetches patches and trace. Anything new, or any
difference, is `probe-internal-error` with kind `contract`, at that input; a refused pad digit that changes the model is
caught at that digit.

A word's outcome is the outcome of its last input, so a pad macro is accepted only when its enter is. `ok apply missed`
(only from a probe that announces `apply-missed`) means the input was delivered but the product did not produce the
intent it was aimed at. It is not a refusal and is not checked; the session continues; it is the finding
`intent-missed`, and it never satisfies `expect = "accept"`.

**Taps** (`u2`, `u3`; a probe that announces `hit-test` and `tap`). A catalogue tap at `x y` is `hit-test x y` (what
LVGL's own search names), then `tap x y` (a press and release through the product's pointer path; the probe then runs
the product's due work, `uim_settle`), then a snapshot (frame first). Only the probe contradicting itself is
`probe-internal-error` kind `contract`: one of the two is `blocked` and the other is not, the tap pressed another node
than the hit query found, or it pressed a node that is not in the frame. The pressed node is read from the frame of the
step before (its `node` record): a screen or layer root (a node with no parent; LVGL screens are clickable by default)
counts as pressing nothing. The step's outcome records `pressed <index> <class> <box> <how>`, `how` being `aimed`,
`other`, `root` or `untargeted`, or `pressed none` / `pressed blocked`.

A `u2` event may declare a `target`, an LVGL class name: the node it aims at is the deepest (then the last drawn) node of
that class whose box holds the point, in the frame of the step before. A `u2` probe tap that pressed a non-root node is:
- `ok` when the model changed (patches, trace, semantic, deadline or env inputs);
- `missed` when it changed nothing: `intent-missed`;
- and in either case `tap-misrouted` when it aims at a node and pressed another non-root node.

A tap that must change nothing (every `u3` complement tap, and a `u2` tap that was blocked or pressed nothing or a root)
is `refused` when nothing changed, frame records included; when something changed it is `ok` and the product finding
`noop-tap-effect` (P004 3.4), and the run goes on.

The finding of a tap that pressed a node carries the node's image `tap-node.png`, read with `crop` AFTER the step is
complete: the outcome and the findings are recorded first, and an evidence error is a finding of its own (on a pseudo
step `evidence`, which ends the run) beside them. The image is the node's box cut to the display and to its top-left 256
x 256 pixels (`IMAGE_SIDE`), read in row bands that each fit one `crop` reply, so a full-screen or very wide node costs
at most a few small crops. The toy's `probe-press` (the button's centre, `target = "lv_button"`) and `probe-blank`
exercise all of this; under the toy's notice its transparent scrim takes `probe-press` (`tap-misrouted` and
`intent-missed`) and `tap-press` is `ok apply missed`: the F3b canary of `selftest/ui.sh`. Matching a scene node
(O2, by key) to the rendered node it should be (O3) beyond the declared target class is the later `ui-input` judge's
work.

**The strict client.** Output nobody asked for is a protocol error. Before every command the client looks once, without
blocking, at what is buffered or readable. Every reply line is capped at 65 536 bytes, and so is a framed reply's
payload; env ids must fit uint32, args int32, and `domain-count` must be at most 65 535. After `ok quit` nothing may
follow, the output must end, and the probe must exit 0 within the deadline. The probe is waited for without being
reaped (pidfd and WNOWAIT), then its whole process group is killed and the probe reaped. A grandchild holding stdout
dies with it, and a reaped pid is never signalled.

**Paths file** (`ui-explore-paths/1`, strict JSON, exactly these keys, no duplicate key, nesting bounded):
`{"schema": "ui-explore-paths/1", "criteria": [<"C1"|"C8">...], "paths": [[<word>...], ...]}`. With `--evidence DIR`,
every finding gets `DIR/<12 hex of its id>/paths.json`, which replays it with the criteria of its strategy. For
`key-too-coarse` it holds the witness path, then the path. A `not-evaluated` finding replays only with the same
`--require`.

## Cost

BFS replays every path from `open`, so a long time word in a prefix is paid by every descendant; this task adds no
prefix caching. The summary reports `cost` (`probe_commands`, `virtual_ms`).

The run is bounded by `--budget-s` on MEASURED wall time (U05e; see the option above): a bfs the budget cuts ends with
`depth-unsaturated` reason `budget`, exit 1, nothing evaluated. Before running, the explorer refuses (exit 2) only a
request that cannot be served at all: one in which a SINGLE path, both runs, could need more virtual time than the whole
budget buys at 16 000 ms of virtual time per wall second (the lockers adapter's ~1 ms per 16 ms step; the first real run
measured ~30 000). The bound of one path is an upper bound by construction (every word at its longest span):
- bfs: 2 x (the prefix's spans + depth bound x the longest span of a sendable event + one starvation window);
- walk: 2 x (length x the longest span + one window);
- replay: 2 x the spans of its longest path.

The longest span of `fire-due`, `before-due`, `until-change`, `settle` and `wait-change` is `max_wait_ms`; of `advance`,
its `ms`; of `at` (a catalogue event or a replay word `at <offset>`), min(offset, `max_wait_ms`); of an input, 0. It
bounds one path, never the number of paths: that is what the budget, measured, is for.

**The lockers numbers** (`max_wait_ms` 300 256, a starvation window of 1024 ms, 110 sendable events, `--budget-s 1200`
= 19.2 M virtual ms). Before U05e the check bounded the whole run: 2 x max_states x the sum over the events of (span +
1024) = 2 x max_states x ~1.42 M, so 6 states were admitted and 7 refused (19 837 356 ms). Now: 2 x (depth x 300 256 +
1024), any `--max-states`: depth 12 needs 7.2 M (admitted), depth 31 19.2 M (admitted), depth 32 is refused. A replay
of four paths of two `at` words (`at 3200`, `at 5200`) needed `--budget-s 600` before (each `at` at 300 256); now its
longest path is 2 x 8 400 ms (admitted at `--budget-s 2`).

**Scene identity (U24).** With `--judges` naming `ui-scene` and a probe that announces `identity`, the explorer sends
one `identity` command per completed step of BOTH runs of a path (read last in the step's observation, after
`env-inputs`; never during a wait, never for the pseudo steps `ink`, `evidence` and `quit`), so the cost is one round
trip per judged step, plus (fix-up 1) a `next-due` and a `semantic` read again right after it, which verify that the
call left the model as it was: three round trips per judged step in all. Measured on the canary probe (release build, 6 identity lines, this 4-CPU host under load): 2000
`identity` commands in one session took 10 ms of probe time over the 6 ms of an `open` alone, about 5 us each, the
same as 2000 `semantic` commands (10 ms); in the canary selftest it is one more line exchange beside the seven of
every step. Without `ui-scene` (`--judges ui-fit,ui-render`) no `identity` is sent (selftest/ui_judges.sh checks the
command log).

## The event catalogue (`ui-events/1`)

One sealed, versioned TOML file per app (P004 4.3 item 2, 8.5): `products/<product>/ui/<app>.events.toml`. The selftest
has three:
- `selftest/ui_product/toy.events.toml`;
- `toy_coarse.events.toml`, a deliberately coarse key;
- `fixture.events.toml`, for the fixture adapters, which accept only the press.

Top level, all required unless marked otherwise, nothing else:
- `schema = "ui-events/1"`;
- `product`, `app`, `version`;
- `max_wait_ms` (1 to 3 600 000);
- optional `requires`: probe capabilities the catalogue needs, distinct names of the eight known ones (any order; kept
  in the greeting's order). A probe whose
  greeting lacks one is the gate's input error (exit 2: "the catalogue requires the probe capabilities ..., which the
  probe does not announce"). The toy catalogue requires all six; an older probe's greeting (no capabilities) only serves
  a catalogue that requires none;
- `drain_ms` (16 to 60 000, a multiple of 16);
- optional `starvation`;
- optional (U05e) `taps`, `[boot]` and `[[prefix]]` (below);
- `[key]`;
- one table per class, each with exactly one key `events`, a list of inline tables. The list may be empty; the table may
  not be absent.

The loader refuses vacuous catalogues. It needs at least one T1 event (states reached only through time must be BFS
nodes) and at least one input event with `expect = "accept"`, so a T1-only or all-`refuse` catalogue is refused. Ids
are `[a-z][a-z0-9-]*`, at most 64 characters, unique, never a reserved path word. Every `apply` event declares
`expect`: `accept` (accepted in at least one reachable state) or `refuse` (refused in every one).

| Class | Meaning (P004 4.3) | Keys | Sent as |
|---|---|---|---|
| `u1` | intent taps | `intent` (uint32), `arg` (int32), `expect` | `apply 3 <intent> <arg> -` |
| `u2` | probe taps through the hit-test | `x`, `y` (0..65535), optional `target` (an LVGL class name) | `hit-test x y`, then `tap x y` ("Taps"), only to a probe that announces `hit-test` and `tap` |
| `u3` | complement taps | `x`, `y` | as `u2`; must change nothing |
| `u4` | code macros with a boundary class | `boundary`, `expect`, and either `via = "wedge"` with `hex`, or `via = "pad"` with `digits`, `enter_intent` and one of `digit_intent` or (U05e) `digit_map` | wedge: `apply 2 0 0 <hex>`; pad: one `apply 3 <digit_intent> <d>` per digit (with `digit_map = { "<d>" = { intent, arg }, ... }`: `apply 3 <intent> <arg>` of that digit; every digit of `digits` must be mapped), then `apply 3 <enter_intent> 0`; one step |
| `u5` | language | `intent`, `arg`, `expect` | as `u1` |
| `e1` | environment replies | `env` (uint32), `arg`, `hex`, `expect` | `apply 1 <env> <arg> <hex>` |
| `t1` | virtual-time events | `kind`: `fire-due`, `before-due`, `until-change`, `advance` with `ms` (at most `max_wait_ms`), or `at` with `offset_ms` | see "Paths and time" |

The `u4` boundary classes are `empty`, `one-digit`, `max-minus-1`, `max`, `max-plus-1`, `valid-visitor`, `valid-staff`,
`unknown`, `expired` and `non-digit`.

**U05e tables.** All optional and strict (an unknown key, a wrong type or range, or a provenance not in the UI
contract's forms is exit 2); a catalogue without them loads and runs exactly as before:
- `taps = { scope, max_per_state, grid_pct, intent_node, provenance }`: `scope` `"scene"` (the state-scoped taps of
  "Scene taps") or `"fixed"` (the catalogue's points only); `max_per_state` (1..4096, required with and only with
  `scene`) caps each class per state; `grid_pct` (1 to 9 increasing integers 0..100, only with `scene`) is the probe grid
  without `--contract` (with one, its `probe_grid_pct` is used); `intent_node` (`"key"` or `"intent"`, optional) says how
  a u1 intent names its scene node (its node key, or its `intent:arg`), which puts u1, u5 and pad-enter inputs under the
  layer policy ("Taps under a layer");
- `[boot]` with `seeds` (1 to 256 distinct integers) and `provenance`: the seeds `--boot-seeds catalogue` runs the
  strategy with, once each, in file order, into one exploration; the findings merge by id (a finding's id does not
  depend on the seed it was found with) and `detail.boot_seeds` lists each seed's detail;
- `[[prefix]]` rows with `name`, `words` (1 to 256 path words, no `open`) and `provenance`: `--prefix NAME` makes a bfs
  start from the state after `open` and those words, so its bound is spent on UI states; the prefix is in every path.

**Capabilities.** A probe's greeting is `ui-probe/1 ready[ <cap>...]` (docs/ui-model.md, "The greeting"). The known
capabilities, in this order: `frame-facts`, `ink`, `hit-test`, `tap`, `apply-missed`, `crop`, `pointer`, `identity`;
the C probe announces the first six, `pointer` when the product's taps go through its own pointer entry (U05c) and
`identity` last when the product reports its scene identity (U24); a probe without any is an older probe of the same
protocol. A catalogue may `require` `identity` (the canary's does: a probe without it is refused, exit 2), so a run
whose identity checks would be blocked cannot start. The probe picks the tap path; a catalogue that `requires`
`pointer` refuses a build whose taps would be injected at LVGL's indev (`selftest/ui_product/toy_pointer.events.toml`),
and only such a catalogue may declare `[ambient]` ("Ambient events"). The path is also a frame fact (the `taps` line of
a session's first frame, docs/ui-model.md): the summary records it as `taps` (`entry`, `indev`, `probe`, or null from a
probe that does not write it), and a run whose taps were injected at the product's OWN pointer indev (`taps indev`, no
`pointer`) gets the info finding `taps-injected` once (its identity: the catalogue's sha256): the product could have
taken the more faithful path. An unknown, repeated or unordered capability is a
protocol error. The first launch fixes the capabilities, and a later launch that announces others is a protocol finding.
Catalogue taps need `hit-test` and `tap`. A probe that cannot greet is reported as such, not as missing
capabilities.

**Ambient events** (U05c). A product's pointer entry may post an event on every sample it receives (a kiosk's input
hook posts `touch`, which restarts its idle deadlines). Through such an entry every tap would "change the model", so a
scrim's tap would be `ok`, not `missed`, and every complement tap `noop-tap-effect`: false findings. The catalogue
declares them, with provenance, in an optional strict table, only together with `requires` containing `pointer`:

    ambient = { trace = ["touch"], trace_provenance = "<provenance>",
                due_restart_ms = 30000, due_restart_provenance = "<provenance>" }   # the last two optional, together

`trace` is a non-empty list of distinct trace types; an unknown key, a duplicate, an empty list, a provenance of the
wrong form or one of the two `due_restart` keys without the other is the input error (exit 2). The rule, in a TAP step
only (`u2`, `u3`; never `apply`, an advance or a frame, where these types are ordinary records):
- a new trace record is AMBIENT iff its type is declared and its time is the tap's instant; only the first record of
  each declared type counts as the tap's own;
- each declared type must appear EXACTLY once on every tap, blocked ones included (the product's entry received the
  sample whether LVGL then processed it or not; the toy posts `touch` on a blocked tap); none is `ambient-missing`,
  more than one `ambient-extra` (both errors, with the types), and the repeat stays an ordinary trace record;
- after the ambient records are set aside, a tap changed nothing only when there is no other new trace record, no new
  patch, the semantic records, the env inputs and (for a `u3` tap, or a `u2` tap that pressed nothing, a root or was
  blocked) the frame are unchanged with no `life` line, and the next deadline is unchanged or exactly the tap's instant
  plus `due_restart_ms` when that is declared. Anything else is a change, as before.

Why this cannot hide an effect: what is set aside is at most one record per declared type, of that exact type, stamped
with the tap's own instant, and it is demanded on every tap (so it cannot appear only when the tap did something); a
second one, any other record, any patch, any scene, env or frame difference, and any deadline but the one declared
restart are still changes (but for a declared countdown restart, below). A product that wants an effect to vanish would have to make it be its ambient record, which
then appears on every tap of every state and carries no information about the tap. The selftest's pointer build with
`touch` declared gives exactly the canary of the injected build (8 `intent-missed`, 4 `tap-misrouted`, no
`noop-tap-effect`); the stub's modes `pnotouch`, `ptwice`, `pchange` and `prestart` give `ambient-missing`,
`ambient-extra` (with the repeat's `noop-tap-effect`), `noop-tap-effect` for a scene change, and no finding for a
declared restart but a `due` change for an undeclared one (gate/tests/test_ui_explore_taps.py, `AmbientTest`).

**Countdown restart** (U05d). A product's sample may also restart a VISIBLE countdown: the kiosk's end-of-shift report
restarts its 5-minute deadline on every touch, by design (the core handles `touch` only in that phase). That is a
patch on the countdown node (`update 6 text 298 сек 300 сек`), a semantic label difference of that node and a frame
difference of that label. `due_restart_ms` cannot express it: `next-due` does not move (the 250 ms tick is nearer than
the restarted deadline), the new deadline is the last tick + 300000 ms rather than the tap's instant + 300000, and the
change is visible only when the displayed seconds change (a tap within about a second of the last restart makes no
patch). Without a declaration every complement or root tap on that screen is a false `noop-tap-effect`, and a `u2` tap
on a non-root node without an intent is `ok` instead of `missed`. The catalogue declares the countdown's scene role in
`[ambient]`, with provenance, the two keys together (one without the other, a role that is not a record field in its
escaped spelling as for `[[key.derived]] role`, or a provenance of the wrong form is the input error, exit 2); they
need `trace`, as every `[ambient]` does:

    ambient = { trace = ["touch"], trace_provenance = "<provenance>",
                countdown_restart_role = "<role>", countdown_restart_provenance = "<provenance>" }

The rule (gate/rigor_lib/ui_explore_restart.py), in a TAP step only, after the ambient trace records are set aside: the
residual change of the step is a DECLARED RESTART, and then counts as "changed nothing", iff ALL of:
- every new patch is `update <key> text <old> <new>` on a key whose semantic records, before and after, all have the
  declared role, and the patches of each key form a chain that agrees with the tree: the first old text is the key's
  old label, each old text is the previous patch's new one, the last new text is its new label (compared unescaped);
- the semantic trees differ only in the label field of exactly those keys (every patched key's label differs; a patch
  with an identical tree is a change): the same records in the same order, no node added or removed, every other field
  of those records and every other record byte-identical;
- where frame records are compared (a `u3` tap, or a `u2` tap that pressed nothing, a root or was blocked): no `life`
  line, the same frame lines in the same order and no change of the `lvprobe` line (the node count); each restarted key
  matches exactly ONE walk index, whose `label` record shows the key's old label before and its new label after and
  whose node keeps its class (an ambiguous or missing match, a decoy label showing the same texts included, rejects);
  of that index the `node` record may differ only in x1, y1, x2, y2, and its box only as its text's laid size does: when
  the box changes, its width and height change by exactly the `label` record's laid_w and laid_h change, and x1 and y1
  each move by at most the absolute width and height change (the label's alignment; a box that only moves, or grows
  more than its text, rejects); the `label` record may differ only in dotted, lines, natural_w/h, laid_w/h, text and
  full_text (font id, line_h, align, align_drawn and long identical); `fit` and `region` freely; of any other index only the `region` record may differ, and only when that index's `node` record is unchanged
  and its box intersects the countdown's box before or after; the `frame` line may differ in its crc only. (A `region`
  is the hash of the pixels inside a node's box and the crc the same hash over the display, docs/ui-lvprobe.md, so when
  the label repaints, the region of every node whose box covers it, the screen, the layers and any container, changes
  with it);
- in every such patch's old and new text and every such node's old and new label there is exactly one run of 1 to 18
  decimal digits (a longer run is no countdown, and is never converted), the text around the run is identical, and the
  new value is at least the old one (a restart never skips a countdown forward);
- there is no other new trace record and no change of `next-due` other than a declared `due_restart_ms`, and the env
  inputs are unchanged.

Anything else stays a change exactly as before. A step that used the rule records the restarts, and the step judge
`ambient-restart` (info) reports one finding per restarted node: identity key before and node key (in its escaped
spelling); `observed` the word, `node`, and the `old` and `new` values as integers, from the node's labels. A sweep
that restarts the same countdown of the same state with many taps gives one finding: the explorer keeps one finding per
id, the one with the shortest path (then the smallest bytes, so the word of the first tap in catalogue order). With the
rule applied, a `u3` or root tap is judged `refused` and a `u2` tap on a non-root node with no intent is `missed`
(`intent-missed`), as on any other screen.

Why this cannot hide an effect: the rule can hide only a text change of a node of the declared role whose number does
not decrease, on a tap, in a catalogue whose sealed `[ambient]` declares it with provenance. A navigation (a node added
or removed, another node's field), a new node, a style or flag change of the countdown itself (in the scene, or in its
`node` or `label` record), a patch of any other kind or node, a patch that disagrees with the tree, a countdown that
jumps forward, a changed text around the number, a second number, a trace record, a deadline or env change, any record
of a node that does not cover the countdown, a covering node's own `node` record and a created or deleted object all
stay changes; the rule never applies on an `apply`, a wait or a frame step, where the same restart is an ordinary
change (a refused input that restarts it is still `probe-internal-error` kind `contract`). The stub's mode `pcount`
(the declared restart, drawn as LVGL draws it: the crc, the screen's region and the label's region follow the text;
both taps of the open state refused, one `ambient-restart`, the shortest path's in either walk order; a `u2` tap under
the notice `intent-missed`), `pdouble` (two countdowns, two findings), its broken variants `pskip`, `pplus`,
`ptworun`, `ptext`, `pnode`, `pflag`, `pframe` (a region of a node that does not meet the label), `plife`, `pbg`,
`pfont` and `pdecoy`, `pcount` without the declaration or with another role, and `pcount` on a refused apply prove
each of these, each rejection with the part of the rule that rejects it (gate/tests/test_ui_explore_restart.py; the
rule's parts one at a time on snapshots, and the frame clause on a real LVGL repaint of the frame toy's title, in
gate/tests/test_ui_explore_restart_rule.py). selftest/ui_restart.sh (run by selftest/ui.sh) runs `pcount` and `pskip`
through `rigor ui-explore`, and the frame clause on the frame toy's probe run live (its title's box shrinks from 47 to
40 pixels as its laid_w does, 47 to 40). Limit: what a covering node's region may hide is a pixel change inside the box
of a node that intersects the countdown's box, before or after, which no other node's box covers and no record field
describes (another node's own records, the scene and the patches must all be unchanged). The countdown's box cannot be
grown on the tap to widen that set: it may change only by its text's own laid size change.
The end-to-end proof on a real LVGL build (an LVGL toy whose countdown a tap restarts) is not in this selftest: no
gate selftest product has such a countdown.

**Scene taps** (U05e; P004 3.4, 4.3 U2/U3; `taps` scope `scene`; gate/rigor_lib/ui_explore_scene.py). Fixed points
mean different things on different screens, so a scene-scoped catalogue derives the taps of every state from that
state's scene and rendered tree (the observation of the step before the tap, read through the judges' vocabulary and
association, docs/ui-judges.md):
- u2 `tap@<key>#<i>`: for every enabled interactive scene node (an intent, enabled, neither `I` nor `D`) associated with
  a shown rendered node, point 0 is the centre of its visible box and points 1.. the other points of the inset grid
  (`probe_points`: x1 + floor(w x p / 100) for p in the grid and 50, the same for y), in sorted order; the node it
  aims at is that rendered node (so `tap-misrouted` names it when another node is pressed);
- u3 `blank#<i>`: the centre of every disabled button or key, one point of every shown scrim outside its card (the first
  grid point of the scrim not in the card), then the grid points of the display in no interactive node and no layer;
  duplicates dropped. Judged as every u3 tap: it must change nothing (unless a layer says otherwise, below).

Order: point index first, then scene order, so every node's centre comes before any node's grid point and a cap keeps
the centres. Each class is capped at `max_per_state`; a state over the cap is the info finding `taps-capped` (identity:
the state's key and the class; `observed` the class, the uncapped count and the cap). A bfs sends, in each state, the
catalogue's sendable events and then that state's own scene words; a walk uses the catalogue's events only. A scene word
is replayable: in a replay it is resolved in the state it is sent in, and a word that names no point there is the
outcome `unbound` (no input is sent, no finding). Fixed u2 and u3 rows stay valid beside them.

**Taps under a layer** (U05e; with `--contract` only; gate/rigor_lib/ui_explore_layers.py). The tap judges read the
layer context the ui-scene judge reads, shared, not copied (ui_judge_context.Context: the association, every layer's
sealed `[[input_layer]]` policy, inertness R7 through `inert_target`, the same probe points as `occluded-target`), built
from the state before the tap. One verdict per tap, in this order:
- **inert**: the tap's target (a u2 row's aimed node, a scene tap's node) is interactive and inert by R7 (it carries
  `I`, or a later painted capture-modal-inert layer's clickable, dimmed scrim covers all its probe points). The tap must
  have NO effect: nothing changed is `refused` (no `intent-missed`, no `tap-misrouted`); any effect is
  `blocked-target-live` (P004 3.4; `observed` the layer, the target, the changed parts). The outcome records
  `layer inert <layer>`;
- **dismiss**: the point lies under a scrim (outside its card's visible box), the topmost layer there, and the sealed
  rows of its card's role say `tap_outside_dismisses = true`. The tap must do exactly that layer's dismiss: the layer's
  records (the scrim, its card and the scene nodes after the card inside the card's rect) leave the scene and every
  other semantic record and the env inputs stay as they were: the outcome `dismissed` (counted as accepted). Anything
  else (nothing, or more, or another change) is `tap-misrouted` with `observed` `expected` (the layer and its intent),
  `pressed` and `changed`;
- **pass**: the point lies under such a scrim whose layer neither blocks nor dismisses, over an interactive, not inert
  node below it. A tap that only removed the layer is `tap-swallowed-first` (`observed` the layer and the node below):
  the layer took the tap the control below should have had. Any other outcome is judged as without a contract.

With `taps` `intent_node`, an intent input (u1, u5, and a pad macro's enter) is judged the same way against its scene
node: inert, an `ok apply missed` is the result `inert` (counted as refused, no `intent-missed`; outcome
`layer inert <key>`), an accepted one `blocked-target-live`. Without `--contract` none of this runs: the taps and
inputs are judged exactly as before (the selftest's `nocontract` step and the unit tests show the same dialog taps
`intent-missed` and `tap-misrouted` without it). The summary counts the three U05e checks only in a run with `taps` or
a contract, so the summary of a run without them keeps its bytes.

**The abstraction key** (P004 4.3 item 3):

```toml
[key]
fields  = [...]   # semantic fields: any of role label x y w h enabled intent flags style importance input_policy wrap_policy
facts   = [...]   # model facts: "deadline" (none | within-frame | pending), "env-inputs"
derived = [...]   # named derived facts (below)
ignore  = [...]   # { field, provenance, reason }: fields left out of the record key-too-coarse compares
```

All four are required. A key with no fields, no facts and no derived facts is refused. An `ignore` entry needs a
provenance in the UI contract's forms and a reason; it may not also be a key field, and no field may be ignored twice.
The key is the sha256 of the canonical JSON of `{"nodes": [[<node key>, <declared fields>] per record, in tree order],
"facts": {<declared and derived facts>}}`, fields in their escaped spelling. It is exact.

**Derived facts** come from a closed set of operators. Each has a `name`, unique and not `deadline` or `env-inputs`, and
its keys are checked strictly:

| `op` | Keys | Value |
|---|---|---|
| `presence` | `node` or `role` | whether a record with that node key or role exists |
| `count` | `node` or `role` | how many |
| `select` | `node` or `role`, `field` | the field's values |
| `bucket` | `node` or `role`, `field`, `measure`, `boundaries` | per record, the `bisect_right` index of the measure, or `none` |
| `bucket` | `model` (`due-in-ms` or `env-count`), `boundaries` | the index, or `none` |

The measures are `value` (the field as a decimal), `length` (its characters: NFC code points of the UTF-8, so Bulgarian
counts right; `none` if it is not UTF-8) and `digits` (the first run of digits). `boundaries` are 1 to 32 strictly
increasing integers.

`node` and `role` are given in the record grammar's escaped spelling, so any key or role the grammar can carry can be
selected, escaped bytes included. They are compared exactly.

A derived fact whose selector matched no record in any visited state is `key-fact-unmatched`: it would be a constant,
not a fact. `ignore` cannot hide a derived fact from `key-too-coarse`: the normalised record holds every derived and
model fact whatever is ignored.

## Strategies

Iteration order is fixed: catalogue order for events, discovery order for states, argument order for seeds and paths.
Required criteria:
- `sweep`: C1;
- `bfs`: C8;
- `walk`: none;
- `replay`: those of its paths file.

What each strategy does:
- **sweep**: `open`, then `[open, domain-at i]` for every `i`.
- **bfs**: from `open`, over (abstract state x sendable event). States beyond `--max-states` are dropped, though they
  are still reachable for C8. It reports `states_per_depth` and stops at the first depth that adds none.
- **walk**: per seed, events chosen by `sha256("ui-explore walk <seed> <j>")[:8]` modulo the event count. It runs at
  `--origin-ms` and at `--extra-origins` more origins, `sha256("ui-explore origin <seed> <k>")[:8]` modulo 2^40.
- **replay**: the paths of a paths file.

## Findings (P004 4.5, 3.7)

`--out` holds one canonical JSON object per line, one per id, sorted by id. The same inputs give the same bytes, also
for a nondeterministic product, because values that vary go to the evidence and no product text appears in `observed`.
Keys: `id` (`ui-explore.<check>/<12 hex of sha256([check, identity])>`), `gate`, `check`, `layer` (`L0` for
nondeterminism, run-twice and starvation; `meta` otherwise), `severity` (`info` for key-too-coarse, taps-injected and ambient-restart, otherwise
`error`), `state` (`{"key", "origin_ms", "projection": {"nodes": [...], "facts": {...}}}` or null), `path`, `observed`,
`blame` (`[]`), `evidence`, `explanation` (null).

| Check | When | Identity | `observed` |
|---|---|---|---|
| `probe-internal-error` | `kind` `protocol`, `fail`, `contract` or `crash` (see "The strict client" and "Inputs") | kind, command, key before, word | `kind`, `command`, `detail` (gate text), `step`; the probe's bytes go to `error.json` |
| `ui-explore-timeout` | no reply within `--deadline-ms`; or the budget spent (`kind` `budget`, identity `["budget", sha, strategy]`) | as above | as above |
| `timer-starvation` | more than `firings` firings within the window; or `zero-delay` | `["window", key]`, or the probe-error identity | `firings`, `limit`, `window_ms`, `first_ms`, `last_ms` |
| `timer-unreachable` | a wait past `max_wait_ms` or 2^52 | key before, word, reason | `word`, `target_ms`, `now_ms`, `max_wait_ms`, `reason` |
| `model-nondeterministic` | the two runs' traces differ | key before, word, `trace` | `step`, `word`, `part`, `item`; both values in `runs.json` |
| `run-twice-mismatch` | the first other differing part, in read order | key before, word, part | as above |
| `intent-missed` | an input's outcome was `missed` (`ok apply missed`, or a `u2` tap that pressed a non-root node and changed nothing) | key before, word | `word`, `applies`; a tap's node image in `tap-node.png` |
| `tap-misrouted` | a `u2` tap aimed at a node (its `target`, or a scene tap's node) pressed another non-root node; or (U05e, `--contract`) a tap under a dismissing layer did not do exactly its dismiss | key before, word | `word`, `pressed` and `aimed` (index, class, box), or `expected`, `pressed`, `changed`; the pressed node's image |
| `noop-tap-effect` | a tap that must change nothing changed the model | key before, word | `word`, `changed` (the parts) |
| `ambient-missing` | a tap did not post a declared ambient event at its instant (U05c) | key before, word | `word`, `types` |
| `ambient-extra` | a tap posted a declared ambient event more than once (U05c) | key before, word | `word`, `types` |
| `ambient-restart` (info) | a tap's residual change was a declared countdown restart and counted as no change; one per restarted node (U05d) | key before, node key | `word`, `node`, `old`, `new` |
| `taps-injected` (info) | the run's taps were injected at the product's own pointer indev: no `pointer` (U05c) | the catalogue | `taps`, `pointer` |
| `ui-coverage-gap` | C1 entry not visited; C8 pair not exercised; an env input that is no `e1` event; a `--require`d criterion not evaluated | `["C1", sha, i]`, `["C8", key, event]`, `["C8-env", key, input]`, `["not-evaluated", criterion, sha]` | criterion-specific |
| `event-never-accepted` | an `accept` event whose outcome was never `ok` | sha, event | `event`, `expect`, per-outcome state counts; `path` is the first refusing send |
| `event-accepted` | a `refuse` event accepted somewhere | sha, event | as above; `path` is the first accepting send |
| `key-fact-unmatched` | a derived fact's selector never matched | sha, fact | `fact`, `node`, `role` |
| `depth-unsaturated` | the last bfs depth added states, the bound dropped some, or the budget cut the bfs (U05e) | `["depth", sha, depth, max_states]` | bounds, `states_per_depth`, `dropped_states`, `reasons` (`last-depth-adds-states`, `state-bound`, `budget`) |
| `blocked-target-live` | U05e, `--contract`: a tap or intent on a target inert under a modal layer (R7) had an effect | `[check, key before, word]` | `word`, `layer`, `target`, `changed` |
| `tap-swallowed-first` | U05e, `--contract`: a tap under a pass-through layer over a control only removed the layer | `[check, key before, word]` | `word`, `layer`, `below` |
| `taps-capped` (info) | U05e: a state had more scene taps of a class than `max_per_state` | `["taps-capped", key, class]` | `class`, `count`, `cap` |
| `key-too-coarse` | equal keys, different normalised records (every semantic field but justified ignores, plus every model and derived fact) | key | `witness_path`, `differs_in`; both records in `records.json` |

**Output nobody asked for.** Timing decides whether a stray line is caught before a command or read as that command's
reply. Such a "line that is not the reply" therefore leaves the command out of the identity and of `observed` (it goes
to `error.json`), and run-twice does not compare which command caught it.

**Replay.** Every finding's `paths.json` replays to the same id. The exceptions are `depth-unsaturated` and the budget
timeout, which describe a run; a `not-evaluated` finding replays only with the same `--require`.

## The judge interface

There are four kinds of judge. The explorer's own build their findings with `ui_explore_judges.make(check, identity,
state, path, observed, evidence=None)`; a judge of another gate (`--judges`) builds findings of the same schema with its
own `gate` and id prefix (`<gate>.<check>/<12 hex>`), and the explorer writes, de-duplicates, counts and replays them
like its own:

| Kind | Signature | Called |
|---|---|---|
| step judge | `judge(step, path, contract)` | once per completed step of every first run |
| run judge | `judge(first, second, contract)` | once per path, with both runs |
| exploration judge | `judge(exploration, contract) -> (evaluated, findings)` | once at the end; registered by criterion in `ui_explore_coverage.CRITERIA` |
| end-of-run hook | `finish(open_word) -> findings` | once at the end of a run whose budget was not spent, after the exploration judges; the `--judges` set's (run-level findings: `exception-unused`, `checks-examined`, `check-vacuous`, `check-blocked`; `path` the open word, `state` null) |

What a step judge receives:
- `step` is a `ui_explore_run.Step`: `index`, `word`, `outcome`, `applies`, `result` (the last input's outcome), `obs`
  (the replies; `frame` holds parsed `Record`s with `raw`, `fields` and `values`; `identity` (U24) the parsed identity
  records when the explorer read them, absent otherwise), `now`, `origin`, `key`, `proj`,
  `key_before`, `proj_before`, `unreachable`, `starved`, `error`.
- `path` is a non-copying view of the earlier steps, so a judge that does not walk it costs O(1) per step.

`contract` is the loaded UI contract or None; a judge that needs it must refuse to run without one.

To attach evidence, a judge passes `evidence={"<name>.json": data}`, where the name matches `[a-z0-9][a-z0-9_-]*.json`
and is not `paths.json`.

The `--judges` set registers one step judge (`ui_judge_findings.JudgeSet.step_judge`) and the end-of-run hook.

Built-in judges:
- step judges: `timer-starvation`, `timer-unreachable`, `intent-missed`, `tap-misrouted`, `noop-tap-effect`,
  `ambient-missing`, `ambient-extra`, `ambient-restart`;
- run judges: the probe errors and run-twice;
- exploration judges: C1, and C8 with env completeness and event acceptance;
- `key-fact-unmatched` and `key-too-coarse`, run by the explorer.

## Evidence images

`ui_explore_png.write_png(width, height, rgba)` writes an 8-bit RGBA PNG with `zlib` and `struct` only. It uses filter
0, level 9 and no ancillary chunk, so the same pixels give the same bytes. `crop(...)` cuts a box out of a frame. A
finding that names a node gets its image: a `u2` tap that is `missed` carries `tap-node.png`, the pressed node's box read
from the probe with `crop` ("Taps"). A judge passes an image as `{"<name>.png": <PNG bytes>}` in its evidence; JSON
evidence stays `{"<name>.json": data}`. Images are evidence only: run-twice does not compare them and they are never in
`observed`.

## Deviations and limits

- **U24: the abstraction key cannot name the state class.** States are keyed as before; the identity is in the step's
  observation (`identity`, compared by run-twice as the part `identity`, after `env`) and read by the judges only. A
  `[key]` fact naming the state class is NOT a small, exact addition, so it is left out: the key is computed for every
  step of every run, judges or not, and also from the fresh observations the waits take (`wait-change`, a t1
  until-change and `base_key` read `semantic`, `next-due` and `env-inputs` between deadlines), so a key fact would make
  `identity` a read of every step and of every wait, need `requires = ["identity"]` in every catalogue that uses it, and
  change the waits' observation; a later engine task may add it.
- **U24: an identity node line that names a key the step's semantic records do not have, a key twice, or a model that
  `identity` changed** (a `next-due` or `semantic` read again after it that differs from the step's) ends the run as
  `probe-internal-error` (kind `contract`, command `identity`), like any other breach the gate sees.
- **P004 3.7's finding names are used where the task contract named others:**
  - `probe-internal-error`, with `observed.kind` `protocol`, `fail`, `contract` or `crash`, for the contract's
    `probe-protocol` and `probe-crash`;
  - `ui-explore-timeout` for `probe-timeout`;
  - `model-nondeterministic` (a differing trace) and `run-twice-mismatch` (any other differing part) where the contract
    named only the first.
- **Product errors reported as protocol errors (known).** `err frame model-contract` and `err frame too-large` (and the
  other `err` replies of the probe that a product causes) reach the explorer as `probe-internal-error` kind `protocol`,
  although the product caused them; telling them apart is left to the judges task.
- **Checks added beyond P004 3.7:**
  - `timer-unreachable`, `event-never-accepted`, `event-accepted` and `key-fact-unmatched`;
  - `intent-missed`. P004 3.4's `tap-misrouted` belongs to the `ui-input` gate and judges hit-test facts (both nodes
    named, per probe point), which this gate does not have. A `missed` apply only says the aimed intent did not happen.
- **The starvation rule (32 firings within 1024 ms) also flags a legitimate perpetual timer of about 31 ms or less;**
  the owner decision is open.
- **U1 taps** are catalogue intents (`apply 3 <intent> <arg>`): the adapter delivers them through the product's own
  path (the toy taps its button through its pointer indev). Probe taps at points of the rendered tree are `u2`.
- **A `u2` tap's aim is a declared LVGL class at its point** (`target`), not a scene node: the scene's geometry is
  relative to each node's parent and keys are not walk indexes, so matching scene keys to rendered nodes is the later
  `ui-input` judge's work.
- **Residual timing dependence.** A stray line that arrives across a step boundary would still change the step it is
  attributed to.
