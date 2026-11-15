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
| `ui_explore_png.py` | the PNG writer |

Selftest: `selftest/ui.sh` steps 8 to 14 and its last step, 16. The fixtures are the toy probe and three adapters: a
nondeterministic one, a starving one and one with a perpetual tick. The last step checks that no probe process is left.
Unit tests: `gate/tests/test_ui_explore*.py`, with a stub probe (`gate/tests/data/ui_explore/stub_probe.py`, one mode
per misbehaviour, and frame-facts modes that speak the protocol as the C probe does) and its catalogue
(`gate/tests/data/ui_explore/stub.events.toml`, the toy catalogue as U05 sealed it, without taps). Each test module's `tearDownModule` fails if a stub it started is still alive. A stub that would sleep
exits as soon as its parent is gone.

## The CLI

```
rigor ui-explore --probe BIN --catalogue FILE.events.toml --strategy sweep|bfs|walk|replay --out FINDINGS
                 [--contract FILE] [--deadline-ms N] [--budget-s N] [--require C1,C8] [--evidence DIR] [--summary FILE]
  sweep:  --origin-ms N --seed N
  bfs:    --origin-ms N --seed N --depth D (1..64) --max-states M (1..1000000)
  walk:   --origin-ms N --seed N --walk-seeds S1,S2,... --walk-length L (1..10000) --extra-origins K (0..16)
  replay: --paths FILE (ui-explore-paths/1)
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
- a run whose time words could exceed the budget (see "Cost");
- a judge's evidence file name that is not `[a-z0-9][a-z0-9_-]*.json`, or is `paths.json`.

Nothing the product does gives exit 2. A probe that cannot greet, one whose capabilities change between launches, and a
budget spent during the first launch are all findings.

`--out` and `--summary` are removed when the run starts and written atomically at the end, so a stale result never
survives an exit 2 or a signal. On SIGTERM, SIGINT or SIGHUP the explorer kills every live probe's process group and
exits with 128 + the signal.

| Option | Meaning |
|---|---|
| `--deadline-ms` (10000) | bounds every reply of the probe, the greeting, and the exit after `quit` |
| `--budget-s` (1800) | the wall-clock budget of the whole run. When it is spent, the run stops with one `ui-explore-timeout` (`observed.kind` = `budget`), no criterion counts as evaluated, and the exit is 1, never a hang and never 2. Where it stops depends on the host, so such a findings file is not reproducible |
| `--require` | criteria that must be evaluated; each one not evaluated becomes a `ui-coverage-gap` with `observed.evaluated` = false |
| `--contract` | the UI contract (docs/ui-contract.md) handed to the judges; the built-in judges do not read it |

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
- the finding counts and the strategy detail.

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

After every word the explorer reads, in this order: `frame`, `semantic`, `patches`, `trace`, `next-due`, `env-inputs`.
The `open` step reads `domain-count` first. Patches and trace fetched during the word (drains and snapshots) come first
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

Before running, the explorer refuses (exit 2) a run whose worst virtual time exceeds `--budget-s` x 16 000. The rate
comes from the cost model: about 16 000 ms of virtual time per wall second, the lockers adapter's ~1 ms per 16 ms step.
Worst virtual time, by strategy:
- bfs: 2 x max_states x the sum, over sendable events, of (the event's longest span + one starvation window);
- walk: 2 x seeds x origins x (length x the longest span + one window);
- replay: 2 x the spans of its words.

The longest span of `fire-due`, `before-due`, `until-change`, `settle` and `wait-change` is `max_wait_ms`; of `advance`,
its `ms`; of `at`, min(offset, `max_wait_ms`).

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
- optional `requires`: probe capabilities the catalogue needs, distinct names of the six known ones. A probe whose
  greeting lacks one is the gate's input error (exit 2: "the catalogue requires the probe capabilities ..., which the
  probe does not announce"). The toy catalogue requires all six; an older probe's greeting (no capabilities) only serves
  a catalogue that requires none;
- `drain_ms` (16 to 60 000, a multiple of 16);
- optional `starvation`;
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
| `u4` | code macros with a boundary class | `boundary`, `expect`, and either `via = "wedge"` with `hex`, or `via = "pad"` with `digits`, `digit_intent`, `enter_intent` | wedge: `apply 2 0 0 <hex>`; pad: one `apply 3 <digit_intent> <d>` per digit, then `apply 3 <enter_intent> 0`; one step |
| `u5` | language | `intent`, `arg`, `expect` | as `u1` |
| `e1` | environment replies | `env` (uint32), `arg`, `hex`, `expect` | `apply 1 <env> <arg> <hex>` |
| `t1` | virtual-time events | `kind`: `fire-due`, `before-due`, `until-change`, `advance` with `ms` (at most `max_wait_ms`), or `at` with `offset_ms` | see "Paths and time" |

The `u4` boundary classes are `empty`, `one-digit`, `max-minus-1`, `max`, `max-plus-1`, `valid-visitor`, `valid-staff`,
`unknown`, `expired` and `non-digit`.

**Capabilities.** A probe's greeting is `ui-probe/1 ready[ <cap>...]` (docs/ui-model.md, "The greeting"). The known
capabilities, in this order: `frame-facts`, `ink`, `hit-test`, `tap`, `apply-missed`, `crop`; the C probe announces all
six, a probe without any is an older probe of the same protocol. An unknown, repeated or unordered capability is a
protocol error. The first launch fixes the capabilities, and a later launch that announces others is a protocol finding.
Catalogue taps need `hit-test` and `tap`. A probe that cannot greet is reported as such, not as missing
capabilities.

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
nondeterminism, run-twice and starvation; `meta` otherwise), `severity` (`info` for key-too-coarse, otherwise
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
| `tap-misrouted` | a `u2` tap aimed at a node (its `target`) pressed another non-root node | key before, word | `word`, `pressed` and `aimed` (index, class, box); the pressed node's image |
| `noop-tap-effect` | a tap that must change nothing changed the model | key before, word | `word`, `changed` (the parts) |
| `ui-coverage-gap` | C1 entry not visited; C8 pair not exercised; an env input that is no `e1` event; a `--require`d criterion not evaluated | `["C1", sha, i]`, `["C8", key, event]`, `["C8-env", key, input]`, `["not-evaluated", criterion, sha]` | criterion-specific |
| `event-never-accepted` | an `accept` event whose outcome was never `ok` | sha, event | `event`, `expect`, per-outcome state counts; `path` is the first refusing send |
| `event-accepted` | a `refuse` event accepted somewhere | sha, event | as above; `path` is the first accepting send |
| `key-fact-unmatched` | a derived fact's selector never matched | sha, fact | `fact`, `node`, `role` |
| `depth-unsaturated` | the last bfs depth added states, or the bound dropped some | `["depth", sha, depth, max_states]` | bounds, `states_per_depth`, `dropped_states`, `reasons` |
| `key-too-coarse` | equal keys, different normalised records (every semantic field but justified ignores, plus every model and derived fact) | key | `witness_path`, `differs_in`; both records in `records.json` |

**Output nobody asked for.** Timing decides whether a stray line is caught before a command or read as that command's
reply. Such a "line that is not the reply" therefore leaves the command out of the identity and of `observed` (it goes
to `error.json`), and run-twice does not compare which command caught it.

**Replay.** Every finding's `paths.json` replays to the same id. The exceptions are `depth-unsaturated` and the budget
timeout, which describe a run; a `not-evaluated` finding replays only with the same `--require`.

## The judge interface

There are three kinds of judge. Each returns findings built with `ui_explore_judges.make(check, identity, state, path,
observed, evidence=None)`:

| Kind | Signature | Called |
|---|---|---|
| step judge | `judge(step, path, contract)` | once per completed step of every first run |
| run judge | `judge(first, second, contract)` | once per path, with both runs |
| exploration judge | `judge(exploration, contract) -> (evaluated, findings)` | once at the end; registered by criterion in `ui_explore_coverage.CRITERIA` |

What a step judge receives:
- `step` is a `ui_explore_run.Step`: `index`, `word`, `outcome`, `applies`, `result` (the last input's outcome), `obs`
  (the replies; `frame` holds parsed `Record`s with `raw`, `fields` and `values`), `now`, `origin`, `key`, `proj`,
  `key_before`, `proj_before`, `unreachable`, `starved`, `error`.
- `path` is a non-copying view of the earlier steps, so a judge that does not walk it costs O(1) per step.

`contract` is the loaded UI contract or None; a judge that needs it must refuse to run without one.

To attach evidence, a judge passes `evidence={"<name>.json": data}`, where the name matches `[a-z0-9][a-z0-9_-]*.json`
and is not `paths.json`.

Built-in judges:
- step judges: `timer-starvation`, `timer-unreachable`, `intent-missed`;
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
