# `rigor ui-explore`: the explorer driver (U05, P004 3.7, 4.1 to 4.5)

The machine every UI judge runs on. It starts a probe binary (`c_ui_probe`, docs/ui-model.md), drives it along input
paths through `ui-probe/1`, runs **every path twice in fresh probe processes**, keys the states it reaches by an
owner-declared abstraction key, applies the judges and writes one JSON line per finding. Python, stdlib only, in
`gate/rigor_lib/`:

| Module | Concern |
|---|---|
| `ui_explore.py` | the CLI, paths files, evidence, summary, signals |
| `ui_explore_probe.py` | the probe client: one process, deadlines, the run budget, typed errors, process groups |
| `ui_explore_grammar.py` | the reply and record grammar and the protocol's limits |
| `ui_explore_catalogue.py` | the catalogue and key loader (`ui-events/1`) |
| `ui_explore_key.py` | projection, key hash, derived facts, normalised record, readable state |
| `ui_explore_run.py` | path words, time, run-twice comparison |
| `ui_explore_judges.py` | findings, step judges and run judges, key-too-coarse |
| `ui_explore_coverage.py` | the exploration (visited graph) and the exploration judges (C1, C8) |
| `ui_explore_strategies.py` | sweep, bfs, walk, replay |
| `ui_explore_png.py` | the PNG writer |

Selftest: `selftest/ui.sh` steps 8 to 14 on the toy probe and three fixture adapters. Unit tests:
`gate/tests/test_ui_explore*.py`, with a stub probe (`gate/tests/data/ui_explore/stub_probe.py`, one mode per
misbehaviour).

## The CLI

```
rigor ui-explore --probe BIN --catalogue FILE.events.toml --strategy sweep|bfs|walk|replay --out FINDINGS
                 [--contract FILE] [--deadline-ms N] [--budget-s N] [--starvation-steps N] [--require C1,C8]
                 [--evidence DIR] [--summary FILE]
  sweep:  --origin-ms N --seed N
  bfs:    --origin-ms N --seed N --depth D (1..64) --max-states M (1..1000000)
  walk:   --origin-ms N --seed N --walk-seeds S1,S2,... --walk-length L (1..10000) --extra-origins K (0..16)
  replay: --paths FILE (ui-explore-paths/1)
```

Exit 0: no finding of severity error. 1: at least one. 2: the gate could not decide. That covers an argument that is
missing, refused for the strategy, out of range, or written with a leading zero; an unreadable or malformed catalogue,
paths file or contract (nesting too deep included); a probe that is not an executable file or cannot be executed (an exec
format error included); an `--evidence` directory that exists and is not empty; catalogue taps for a probe without the
tap capability; `sweep` on a model without a view domain; `bfs` or `walk` with no sendable event.

`--out` and `--summary` are removed when the run starts and written atomically when it ends, so a stale result never
survives an exit 2 or a signal. On SIGTERM or SIGINT the explorer kills every live probe's process group and exits with
128 + the signal.

| Option | Meaning |
|---|---|
| `--deadline-ms` (10000) | bounds every reply of the probe, the greeting, and the exit after `quit` |
| `--budget-s` (1800) | the wall-clock budget of the whole run. When it is spent, the run stops with one `ui-explore-timeout` (`observed.kind` = `budget`), no criterion counts as evaluated, and the exit is 1, never a hang and never 2. Where it stops depends on the host's speed, so such a findings file is not reproducible |
| `--starvation-steps` (32, at least 2) | the bound of `timer-starvation`; a replay must use the value of the run it reproduces |
| `--require` | criteria that must be evaluated; each one not evaluated becomes a `ui-coverage-gap` with `observed.evaluated` = false |
| `--contract` | the UI contract (ui-contract/1, docs/ui-contract.md) handed to the judges; the built-in judges do not read it |

Clock origins and seeds are arguments. Deriving them from the verdict's input hash (P004 6.3) belongs to the grade
wiring (U14).

Stdout: a summary line (which criteria were evaluated, `none` when none were), the strategy detail, then one line per
finding. `--summary` writes `ui-explore-summary/1` with these keys:
- `strategy`, `criteria` (required by the strategy), `evaluated` (judged), `budget_spent`
- the catalogue and probe sha256
- `runs`, `abstract_states`, `pairs_exercised`, `domain_count`, `domain_visited`
- `events`: per sent event, `accepted_states` and `refused_states`
- findings per check, and the strategy detail

## Paths and time

A path is a list of words:

| Word | Meaning |
|---|---|
| `open <origin_ms> <seed>` | the first word, and only there |
| `domain-at <i>` | move to view-domain entry `i` |
| `settle` | fire the next deadline |
| `wait-change` | fire deadlines until the abstraction key changes |
| `at <offset_ms>` | advance to origin + offset |
| a catalogue event id | send that event |

After every word the explorer reads, in this order: `frame`, `semantic`, `patches`, `trace`, `next-due`, `env-inputs`.
The `open` step reads `domain-count` first. One observation per step. Frame-seam lines are parsed by the record grammar
(TAB-split fields, unescaped) and kept verbatim alongside. A failing command ends the run at that step and becomes a
finding. Nothing is retried, and no run is shortened silently.

**Virtual time.** Every time word is bounded by the catalogue's `max_wait_ms`, which has a hard ceiling of 1 h in code.
A wait that is longer, or that passes the protocol's clock limit (2^52), is not taken: the step records it and it is
the finding `timer-unreachable`, with the target, now, the limit and the reason (`max-wait` or `protocol-limit`). Time
words:
- `fire-due` and `settle` advance to `next-due`.
- `before-due` advances to `next-due` minus one frame.
- `advance` (`ms`, at most `max_wait_ms`, checked at load) and `at` advance by or to a fixed time.
- `until-change` and `wait-change` fire deadlines until the key differs from the step before. They end in one of four
  ways:
  - `changed`;
  - `no-deadline`;
  - `no-change`: the next deadline is past `max_wait_ms`. This is a quiet state of a product with a perpetual tick, not
    a finding;
  - `starving`: `--starvation-steps` consecutive firings each left the next deadline within a frame. This is a
    `timer-starvation`.

On a product with a perpetual tick, one notice expiry is then one event, not 32 tick firings.

**Advances are split on the frame grid.** Each `advance` command spans at most 64 frames (1024 ms) and ends on the grid
`origin + k * 16` or at the target. The probe's loop already ends every `uim_step` at each grid boundary and each
deadline, so the split calls the model with exactly the same step lengths as one long advance. What the split buys is
that the per-command deadline holds on a slow product: 64 steps per command, where a 5-minute idle is about 19 000 steps.

**Run-twice (L0).** Every path runs in a fresh probe, then its words run again in another fresh probe. `sweep`, `bfs`
and `walk` append `settle` words to the first run while a deadline is pending. The suffix stops when no deadline is
left, when a firing leaves the next deadline more than a frame away (so on a perpetual 250 ms tick it ends after one
firing), when a wait is unreachable, or after `--starvation-steps` consecutive firings within a frame. The second run
executes exactly the words of the first. `replay` appends nothing.

**What the gate checks itself.** The client is strict about stray output. Bytes left in the buffer before a command is
sent, and anything after `ok quit`, are protocol errors. After `ok quit` the probe must close its output and exit 0
within the deadline. A reply that only says `ok apply refused` must change nothing: empty patches and trace, and the
same semantic records, next deadline and env inputs as the step before. Otherwise it is `probe-internal-error` with
kind `contract`.

**Paths file** (`ui-explore-paths/1`, strict JSON, exactly these keys, no duplicate key, nesting bounded):
`{"schema": "ui-explore-paths/1", "criteria": [<"C1"|"C8">...], "paths": [[<word>...], ...]}`. With `--evidence DIR`,
every finding gets `DIR/<12 hex of its id>/paths.json`. That file replays the finding with the criteria of its strategy;
for `key-too-coarse` it holds the witness path, then the path.

## The event catalogue (`ui-events/1`)

One sealed, versioned TOML file per app (P004 4.3 item 2, 8.5): `products/<product>/ui/<app>.events.toml`. The selftest
has three:
- `selftest/ui_product/toy.events.toml`, the toy's;
- `toy_coarse.events.toml`, a deliberately coarse key;
- `fixture.events.toml`, for the fixture adapters, which accept only the press.

Top level, all required, nothing else:
- `schema = "ui-events/1"`;
- `product` and `app` (lowercase names), `version` (an integer, at least 1);
- `max_wait_ms` (1 to 3 600 000);
- `[key]`;
- one table per class, each with exactly one key `events`, a list of inline tables. The list may be empty; the table may
  not be absent.

At least one T1 event is required: states reached only through time must be BFS nodes. Every event has an `id`
(`[a-z][a-z0-9-]*`, at most 64 characters, unique over the file, never a reserved path word). An event has exactly the
keys of its class, and every event sent through `apply` declares `expect`: `accept` means it must be accepted in at
least one reachable state; `refuse` means it must be refused in every one (for example an empty code line).

| Class | Meaning (P004 4.3) | Keys | Sent as |
|---|---|---|---|
| `u1` | intent taps | `intent` (uint32), `arg` (int32), `expect` | `apply 3 <intent> <arg> -` |
| `u2` | probe taps through the hit-test | `x`, `y` (0..65535) | `tap x y`, only to a probe whose greeting announces `tap` |
| `u3` | complement taps | `x`, `y` | as `u2` |
| `u4` | code macros with a boundary class | `boundary` (`empty`, `one-digit`, `max-minus-1`, `max`, `max-plus-1`, `valid-visitor`, `valid-staff`, `unknown`, `expired`, `non-digit`), `expect`, and either `via = "wedge"` with `hex`, or `via = "pad"` with `digits`, `digit_intent`, `enter_intent` | wedge: `apply 2 0 0 <hex>`; pad: `apply 3 <digit_intent> <d>` per digit, then `apply 3 <enter_intent> 0`, all one step |
| `u5` | language | `intent`, `arg`, `expect` | as `u1` |
| `e1` | environment replies | `env` (uint32), `arg`, `hex`, `expect` | `apply 1 <env> <arg> <hex>` |
| `t1` | virtual-time events | `kind`: `fire-due`, `before-due`, `until-change`, `advance` with `ms`, or `at` with `offset_ms` | see "Paths and time" |

`hex` is lowercase hex of 0 to 256 bytes, none of them `00`.

**Taps.** A probe announces capabilities in its greeting: `ui-probe/1 ready[ <cap>...]`. The only known capability is
`tap`. An unknown, repeated or unordered capability is a protocol error. A catalogue with `u2` or `u3` events is exit 2
until the probe announces `tap`; the C probe does not announce it yet. The explorer reads the greeting in one
capability session before the run. Taps declare no `expect`; their expected outcome comes with the hit-test task.

**The abstraction key** (P004 4.3 item 3):

```toml
[key]
fields  = [...]   # semantic fields: any of role label x y w h enabled intent flags style importance input_policy wrap_policy
facts   = [...]   # model facts: "deadline" (none | within-frame | pending), "env-inputs" (the enabled env inputs)
derived = [...]   # named derived facts (below)
ignore  = [...]   # { field, provenance, reason }: fields left out of the record key-too-coarse compares
```

All four are required. A key with no fields, no facts and no derived facts is refused. An `ignore` entry needs a
provenance of the UI contract's forms (`spec:`, `oracle:`, `literature:`, `design:`, `owner:`; docs/ui-contract.md) and
a reason. An ignored field may not also be a key field, and no field may be ignored twice.

The key is the sha256 of the canonical JSON of `{"nodes": [[<node key>, <declared fields in the order above>] per
semantic record, in tree order], "facts": {<declared facts and every derived fact by name>}}`. The fields are taken in
their escaped record spelling. It is exact, never a similarity measure.

**Derived facts** come from a closed set of operators, so that a field can be bucketed without dropping it everywhere.
Free-form expressions do not exist. Each fact has a `name` (unique; not `deadline` or `env-inputs`), and every key is
checked:

| `op` | Keys | Value |
|---|---|---|
| `presence` | `node` or `role` | whether a record with that node key or role exists |
| `count` | `node` or `role` | how many |
| `select` | `node` or `role`, `field` | the list of that field's values |
| `bucket` | `node` or `role`, `field`, `measure` (`value`: the field as a decimal number; `length`: its unescaped byte length; `digits`: the first run of digits in it), `boundaries` | per record, the bucket index (`bisect_right`), or `none` |
| `bucket` | `model` (`due-in-ms` or `env-count`), `boundaries` | the bucket index, or `none` |

`boundaries` are 1 to 32 strictly increasing integers.

## Strategies

Iteration order is fixed: catalogue order for events (class order `u1 u2 u3 u4 u5 e1 t1`, then file order), discovery
order for states, argument order for seeds and paths. Required criteria:
- `sweep`: C1;
- `bfs`: C8;
- `walk`: none (it is a supplement);
- `replay`: the criteria of its paths file.

What each strategy does:
- **sweep**: `open`, then `[open, domain-at i]` for every `i < domain-count`.
- **bfs**: from `open`, over (abstract state x sendable catalogue event). Every path is replayed from `open`. A new key
  is admitted while fewer than `--max-states` are; later ones are dropped, though they still count as reachable for C8.
  `states_per_depth` reports new states per depth (depth 0 is `open`). The search stops at the first depth that adds
  none.
- **walk**: per seed, `--walk-length` sendable events. The event of step `j` is `sha256("ui-explore walk <seed> <j>")[:8]`
  modulo the event count. Each walk runs at `--origin-ms` and at `--extra-origins` more origins; origin `k` is
  `sha256("ui-explore origin <seed> <k>")[:8]` modulo 2^40.
- **replay**: the paths of a paths file, with nothing appended.

## Findings (P004 4.5, 3.7)

`--out` holds one canonical JSON object per line, one per id, sorted by id. When several instances share an id, the
one with the shortest path is kept, then the one with the smallest canonical bytes. The same inputs give the same bytes,
also for a nondeterministic product. The values that vary go to the evidence, never into `observed`, and product text
appears in no `observed`. The selftest compares two non-empty findings files of the nondeterministic fixture with
`cmp`.

| Key | Value |
|---|---|
| `id` | `ui-explore.<check>/<first 12 hex of sha256(canonical JSON of [check, identity])>` |
| `gate`, `check` | `ui-explore`, the check |
| `layer` | `L0` for model-nondeterministic, run-twice-mismatch and timer-starvation; `meta` otherwise |
| `severity` | `info` for key-too-coarse (P004 3.7: reported first, promoted later); `error` for every other check |
| `state` | `{"key", "origin_ms", "projection": {"nodes": [{"key": ..., <declared field>: ...}], "facts": {...}}}`, or null |
| `path` | the words that reproduce it |
| `observed` | check-specific, below |
| `blame` | `[]` |
| `evidence` | with `--evidence`, the files written for it, relative to that directory |
| `explanation` | null |

| Check | When | Identity | `observed` |
|---|---|---|---|
| `probe-internal-error` | `kind` `protocol` (wrong shape, `err` reply, stray output, a `fail` reply to `next-due`, `domain-count` or `quit`, a protocol bound exceeded: more than 65536 payload bytes, an env id beyond uint32 or an arg beyond int32, a domain count above 65535, an unknown capability); `fail` (a model call failed); `contract` (a refused input changed the model); `crash` (output ended, or exit status not 0 after `quit`) | kind, command, key before, word | `kind`, `command`, `detail` (gate text), `step`; the probe's bytes go to `error.json` |
| `ui-explore-timeout` | no reply within `--deadline-ms` (the group is killed); or the run budget spent (`kind` `budget`, identity `["budget", catalogue sha, strategy]`) | as above | as above |
| `timer-starvation` | `--starvation-steps` consecutive firings each left the next deadline at most 16 ms after now; or a deadline at or before now (`kind` `zero-delay`: the probe's `err next-due/advance model-contract`, or a `next-due` not after now) | `["streak", key]`, or the probe-error identity | `firings`, `frame_ms`, `now_and_next_due`; or the error fields |
| `timer-unreachable` | a time word's wait passes `max_wait_ms` or 2^52 | key before, word, reason | `word`, `target_ms`, `now_ms`, `max_wait_ms`, `reason` |
| `model-nondeterministic` | the two runs' `trace` replies differ | key before, word, `trace` | `step`, `word`, `part`, `item`; both values in `runs.json` |
| `run-twice-mismatch` | the first other part that differs, in read order (domain, outcome, frame, semantic, patches, trace, next-due, env, now, error) | key before, word, part | as above |
| `ui-coverage-gap` | C1: an entry not visited; C8: a reachable (key, event) pair not exercised, or an enabled env input that is no `e1` event; a `--require`d criterion not evaluated | `["C1", sha, i]`, `["C8", key, event]`, `["C8-env", key, input]`, `["not-evaluated", criterion, sha]` | `criterion` and the entry or event, or `undeclared_env_input` [id, arg] (the text goes to `env-input.json`), or `evaluated` false |
| `event-never-accepted` | an `expect = "accept"` event that was refused in every state it was sent in (C8) | catalogue sha, event | `event`, `expect`, `accepted_states`, `refused_states` |
| `event-accepted` | an `expect = "refuse"` event that was accepted somewhere (C8) | catalogue sha, event | as above |
| `depth-unsaturated` | bfs: the last depth still added states, or the state bound dropped some | `["depth", sha, depth, max_states]` | bounds, `states_per_depth`, `dropped_states`, `reasons` |
| `key-too-coarse` | two steps with equal keys whose normalised records differ. The normalised record is every semantic field except the justified `ignore` fields, plus every model fact and every derived fact | key | `witness_path`, `differs_in` (`nodes`, `facts`); both records in `records.json` |

**About the starvation criterion.** A legitimate periodic timer with a period of 16 ms or less would be flagged too:
every firing leaves the next deadline within a frame. Such a timer is an animation, which a stable scene must not have
(model.h).

**Replay.** Every finding's `paths.json` replays to the same id. The unit test `test_every_finding_replays_to_the_same_id`
checks this on more than 20 findings, and `selftest/ui.sh` checks it on the fixture probes. The exceptions are
`depth-unsaturated` and the budget timeout, which describe a run, not a path.

## The judge interface

There are three kinds of judge. Each returns findings built with `ui_explore_judges.make(check, identity, state, path,
observed, evidence=None)`:

| Kind | Signature | Called |
|---|---|---|
| step judge | `judge(step, path, contract)` | once per completed step of every first run, in order |
| run judge | `judge(first, second, contract)` | once per path, with both runs (`ui_explore_run.Run`: `words`, `steps`, `error`) |
| exploration judge | `judge(exploration, contract) -> (evaluated, findings)` | once at the end; registered by criterion in `ui_explore_coverage.CRITERIA` (C1, C8) |

What a step judge receives:
- `step` is a `ui_explore_run.Step`: `index`, `word`, `outcome`, `applies`, `obs` (the replies; `frame` holds parsed
  `Record`s with `raw`, `fields` and `values`), `now`, `origin`, `key`, `proj`, `key_before`, `proj_before`, `streak`,
  `unreachable`, `error`.
- `path` is a non-copying view of the earlier steps (`PathSoFar`). A judge that does not walk it costs O(1) per step,
  and the starvation judge does not walk it.

The exploration (`Exploration`) holds the visited graph: `reachable` (key to path, projection and origin), `edges`
(key before, word, key after), `env`, per-event acceptance (`events`) and the domain. An exploration judge returns
`evaluated` = false when it could not judge (for example C1 without a view domain); the criterion then does not appear
in `evaluated`.

`contract` is the loaded UI contract or None. A judge that needs it must refuse to run without one.

To attach evidence, a judge passes `evidence={"<file>.json": <JSON data>}`. The explorer writes those files next to
`paths.json` and lists them in `evidence`.

Built-in judges:
- step judges: `timer-starvation`, `timer-unreachable`;
- run judges: the probe errors and run-twice;
- exploration judges: C1, and C8 with env completeness and event acceptance;
- `key-too-coarse`, kept by the explorer over every completed step.

## Evidence images

`ui_explore_png.write_png(width, height, rgba)` writes an 8-bit RGBA PNG with `zlib` and `struct` only. It uses filter
0, level 9 and no ancillary chunk, so the same pixels give the same bytes. `crop(width, height, rgba, (x, y, w, h))`
cuts a box out of a frame. No judge draws images yet: the probe's frame seam carries no pixels.

## Deviations and limits

- **Finding names follow P004 3.7.** The contract's `probe-protocol` and `probe-crash` are `probe-internal-error` with
  `observed.kind`, and `probe-timeout` is `ui-explore-timeout`. A differing trace is `model-nondeterministic`; any other
  difference is `run-twice-mismatch`.
- **Checks this task adds**: `timer-unreachable`, `event-never-accepted` and `event-accepted`.
- **U1 taps** are catalogue intents until the rendered tree exists.
- **No tap command yet.** The C probe announces no capability and has no `tap` command.
