# `rigor ui-explore`: the explorer driver (U05, P004 3.7, 4.1 to 4.5)

The machine every UI judge runs on. It starts a probe binary (`c_ui_probe`, docs/ui-model.md), drives it along input
paths through `ui-probe/1`, runs **every path twice in fresh probe processes**, keys the states it reaches by an
owner-declared abstraction key, applies the judges and writes one JSON line per finding. Python, stdlib only:
`gate/rigor_lib/ui_explore*.py` (CLI `ui_explore.py`, probe client `_probe`, catalogue loader `_catalogue`, path
execution and run-twice `_run`, findings, key and judges `_judges`, strategies `_strategies`, PNG writer `_png`).
Selftest: `selftest/ui.sh` steps 8 to 13 on the toy probe; unit tests `gate/tests/test_ui_explore*.py` with a stub probe
(`gate/tests/data/ui_explore/stub_probe.py`).

## The CLI

```
rigor ui-explore --probe BIN --catalogue FILE.events.toml --strategy sweep|bfs|walk|replay --out FINDINGS
                 [--contract FILE] [--deadline-ms N] [--starvation-steps N] [--evidence DIR] [--summary FILE]
  sweep:  --origin-ms N --seed N
  bfs:    --origin-ms N --seed N --depth D (1..64) --max-states M (1..1000000)
  walk:   --origin-ms N --seed N --walk-seeds S1,S2,... --walk-length L (1..10000) --extra-origins K (0..16)
  replay: --paths FILE (ui-explore-paths/1)
```

Exit 0: no finding of severity error; 1: at least one; 2: the gate could not decide (an argument missing, refused for
the strategy or out of range, a number with a leading zero, an unreadable or malformed catalogue, paths file or contract,
a probe that is not an executable file, an `--evidence` directory that exists and is not empty, a catalogue with U2 or
U3 taps, `sweep` on a model without a view domain). On exit 2 the `--out` file is removed. A strategy argument given to
another strategy is refused, never ignored. `--deadline-ms` (default 10000) bounds every reply of the probe, the greeting
and the exit after `quit`. `--starvation-steps` (default 32, at least 2) is the bound of `timer-starvation`; a replay
must use the same value as the run it reproduces. `--contract` (ui-contract/1, docs/ui-contract.md) is handed to the
judges; the built-in judges do not read it. Clock origins and seeds are arguments here; deriving them from the
verdict's input hash (P004 6.3) is the business of the grade wiring (U14).

Stdout: one summary line, the strategy detail (states per depth for `bfs`, domain coverage for `sweep`), then one line
per finding (`<severity> <id>`). `--summary` writes the same as JSON (`ui-explore-summary/1`: strategy, criteria,
catalogue and probe sha256, runs, abstract states, pairs exercised, domain count and entries visited, findings per check,
strategy detail).

## Paths

A path is a list of path words: `open <origin_ms> <seed>` (the first word, and only there), `domain-at <i>`, `settle`
(the gate's own time event: fire the next deadline) or the id of a catalogue event. After every word the explorer reads,
in this fixed order, `frame`, `semantic`, `patches`, `trace`, `next-due` and `env-inputs`; the `open` step first reads
`domain-count`. That is one observation per step. A failing command (`err`, `fail`, end of output, timeout) ends the
run at that step and becomes a finding; nothing is retried and a run is never shortened silently.

**Run-twice (L0).** Every path runs in a fresh probe, then its words run again in another fresh probe, and the two runs
are compared reply by reply. `sweep`, `bfs` and `walk` append `settle` words to the first run while a deadline is
pending (until there is none, a firing leaves the next deadline more than a frame away, or `--starvation-steps`
consecutive firings did not); the second run executes exactly the words of the first. `replay` appends nothing.

**Paths file** (`ui-explore-paths/1`, strict JSON: exactly the keys below, no duplicate key):
`{"schema": "ui-explore-paths/1", "criteria": [<"C1"|"C8">...], "paths": [[<word>...], ...]}`. `criteria` names the
coverage criteria the replay evaluates over what it ran (distinct, from `C1`, `C8`); `paths` is not empty, and every
path is checked word by word (a word that is not a path word or a catalogue event id is exit 2). With `--evidence DIR`
every finding gets `DIR/<12 hex of its id>/paths.json`, the paths file that replays it with the criteria of its strategy
(for `key-too-coarse`: the witness path, then the path).

## The event catalogue (`ui-events/1`)

One sealed, versioned TOML file per app (P004 4.3 item 2, 8.5): `products/<product>/ui/<app>.events.toml`; the toy's are
`selftest/ui_product/toy.events.toml` and the deliberately coarse `toy_coarse.events.toml`. Loader:
`ui_explore_catalogue.py`. Top level, all required, nothing else: `schema = "ui-events/1"`, `product`, `app` (lowercase
names), `version` (an integer >= 1), `[key]`, and one table per class, each with exactly one key `events`, a list of
inline tables (it may be empty, the table may not be absent). Every event has an `id` (`[a-z][a-z0-9-]*`, at most 64
characters, unique over the whole file, never `open`, `domain-at` or `settle`) and exactly the keys of its class:

| Class | Meaning (P004 4.3) | Keys | Sent as |
|---|---|---|---|
| `u1` | intent taps | `intent` (uint32), `arg` (int32) | `apply 3 <intent> <arg> -` |
| `u2` | probe taps through the hit-test | `x`, `y` (0..65535) | refused: ui-probe/1 has no tap command yet |
| `u3` | complement taps | `x`, `y` | refused, as `u2` |
| `u4` | code macros with a boundary class | `boundary` (`empty`, `one-digit`, `max-minus-1`, `max`, `max-plus-1`, `valid-visitor`, `valid-staff`, `unknown`, `expired`, `non-digit`), `via` = `wedge` with `hex`, or `via` = `pad` with `digits`, `digit_intent`, `enter_intent` | wedge: `apply 2 0 0 <hex>`; pad: `apply 3 <digit_intent> <d>` per digit, then `apply 3 <enter_intent> 0`; one step |
| `u5` | language | `intent`, `arg` | as `u1` |
| `e1` | environment replies | `env` (uint32), `arg`, `hex` | `apply 1 <env> <arg> <hex>` |
| `t1` | virtual-time events | `kind` = `fire-due`, `before-due`, or `advance` with `ms` (1..600000) | `fire-due`: advance to `next-due`; `before-due`: to `next-due` minus one frame; `advance`: now + ms (in commands of at most 600000 ms) |

`hex` is lowercase hex of 0 to 256 bytes, none `00` (`""` is the empty text). A `fire-due` or `before-due` with no
deadline, or a `before-due` within a frame of now, does nothing and says so in the step's outcome. A catalogue with any
`u2` or `u3` event is refused at start (exit 2): a tap needs the lvprobe tap seam of a later task, and a check never
skips what it cannot send.

**The abstraction key** (P004 4.3 item 3), in the same file:

```toml
[key]
fields = [...]    # semantic fields in the key: any of role label x y w h enabled intent flags style importance input_policy wrap_policy
facts  = [...]    # named model facts: "deadline" (none | within-frame | pending), "env-inputs" (the enabled env inputs)
ignore = [...]    # fields left out of the normalised tree that key-too-coarse compares; disjoint from `fields`
```

All three are required, without duplicates, and only these names. The key of a step is the sha256 of the canonical JSON
(sorted keys, no spaces, ASCII, LF) of `{"nodes": [[<key>, <declared fields in the order above>] per semantic record, in
tree order], "facts": {<declared facts>}}`, the fields in their escaped record spelling: exact, never a similarity
measure. `deadline` is `none` without a deadline, `within-frame` when it is at most one frame (16 ms) after now,
`pending` otherwise; `env-inputs` is the list of `[id, arg, hex]`. The node `key` field is always part of the key.

## Strategies

Iteration order is fixed: catalogue order for events (class order `u1 u2 u3 u4 u5 e1 t1`, then file order), discovery
order for states, argument order for seeds and paths. Required coverage criteria: `sweep` C1, `bfs` C8, `walk` none (a
supplement), `replay` the criteria of its paths file.

- **sweep**: `open`, then for every `i < domain-count`, `[open, domain-at i]`. C1: every domain entry visited.
- **bfs**: from `open`, over (abstract state x catalogue event); every path is replayed from `open`. A new key is admitted
  while fewer than `--max-states` are; later ones are dropped (still reachable for C8). New abstract states per depth
  are reported (`states_per_depth`, depth 0 is `open`); the search stops at the first depth that adds none.
- **walk**: per seed, `--walk-length` events, the event of step `j` being `sha256("ui-explore walk <seed> <j>")[:8]`
  (big-endian) modulo the number of events; each walk runs at `--origin-ms` and at `--extra-origins` more origins,
  origin `k` = `sha256("ui-explore origin <seed> <k>")[:8]` modulo 2^40. The same on every Python and platform.
- **replay**: the paths of a paths file, nothing appended.

## Findings (P004 4.5, 3.7)

`--out` holds one canonical JSON object per line, one per id, sorted by id; the same inputs give the same bytes. When
several instances share an id the one with the shortest path, then the smallest canonical bytes, is kept. Keys, all
always present:

| Key | Value |
|---|---|
| `id` | `ui-explore.<check>/<first 12 hex of sha256(canonical JSON of [check, identity])>`; the identity names states by key and events by path word (below), never by exploration order |
| `gate`, `check` | `ui-explore`, the check |
| `layer` | `L0` for model-nondeterministic, run-twice-mismatch, timer-starvation; `meta` otherwise |
| `severity` | `info` for key-too-coarse (P004 3.7: I, promoted to E after report-first), `error` for every other check |
| `state` | `{"key": <hex>, "origin_ms": n}` of the state the finding is about, or null (none reached) |
| `path` | the path words that reproduce it |
| `observed` | check-specific, below; never a value that varies between runs |
| `blame` | `[]` (no wiring table yet) |
| `evidence` | with `--evidence`, the files written for it (relative to that directory), else `[]` |
| `explanation` | always null (L7 is not here) |

| Check | When | Identity | `observed` |
|---|---|---|---|
| `probe-internal-error` | the probe broke ui-probe/1 (`kind` `protocol`: a reply or record of the wrong shape, an `err` reply), a model call failed (`fail`), or the probe crashed (`crash`: output ended, start failed, exit status not 0 after `quit`) | kind, command, key before the step, word | `kind`, `command`, `detail`, `step` |
| `ui-explore-timeout` | no complete reply within `--deadline-ms` (the probe is killed) | as above | as above |
| `model-nondeterministic` | the two runs' `trace` replies differ | key before the step, word, `trace` | `step`, `word`, `part`, `item` (first differing record) |
| `run-twice-mismatch` | any other reply, outcome, clock or error differs | key before the step, word, part | as above, `part` the first differing reply |
| `timer-starvation` | `--starvation-steps` consecutive firings of a deadline (`settle` or a `fire-due` event) each left the next deadline at most one frame after now | key before the first of them | `firings`, `frame_ms`, `now_and_next_due` |
| `ui-coverage-gap` | C1: a domain entry not visited; C8: a reachable (key, event) pair not exercised, or an enabled env input that is no `e1` event | `["C1", i]`, `["C8", key, event]`, `["C8-env", key, input]` | `criterion` and the entry, event or input |
| `depth-unsaturated` | bfs: the last depth still added states, or the state bound dropped some | `[depth, max_states]` | bounds, `states_per_depth`, `dropped_states`, `reasons` |
| `key-too-coarse` | two steps with equal keys whose normalised trees (semantic records without the `ignore` fields) differ | key | `witness_path`, `first_differing_node`, both nodes |

The differing values of a run-twice finding vary by nature, so they go to the evidence (`runs.json`: both runs' part),
never into the finding. **Replay**: every finding's paths file replays to the same id (`selftest/ui.sh`, unit test
`test_every_finding_replays_to_the_same_id`), with one exception: `depth-unsaturated` is a property of a bounded search,
not of a path; its `path` reaches the first new state of the last depth, and re-running `bfs` with the same bounds
reproduces it.

## The judge interface

A step judge is a callable `judge(step, path, contract) -> iterable of findings`: `step` is a `StepView` (`index`,
`word`, `step` with its `outcome`, `obs` (the replies) and `now`, `key`, `key_before`, `origin_ms`), `path` the StepViews
before it, `contract` the loaded UI contract or None. It is called once per completed step of the first run of every
path, in path order, and builds findings with `ui_explore_judges.make(check, identity, state_key, origin_ms, path,
observed)`; a judge that needs the contract must refuse to run without one. The explorer owns run-twice, the probe
errors and the run-level checks (coverage, depth, key-too-coarse). Built in: `timer-starvation`
(`starvation_judge(bound)`).

## Evidence images

`ui_explore_png.write_png(width, height, rgba)` writes an 8-bit RGBA PNG with `zlib` and `struct` only (filter 0, level 9,
no ancillary chunk: the same pixels give the same bytes); `crop(width, height, rgba, (x, y, w, h))` cuts a box out of a
frame. No judge draws images yet: the probe's `frame` reply carries no pixels until lvprobe joins its seam.

## Deviations and limits

* Finding names follow P004 3.7 where the task contract used others: a protocol violation, an `err` or `fail` reply and
  a crash are `probe-internal-error` with `observed.kind` (`protocol`, `fail`, `crash`) instead of `probe-protocol` and
  `probe-crash`; a timeout is `ui-explore-timeout`, not `probe-timeout`; a differing trace is `model-nondeterministic`
  and any other differing reply `run-twice-mismatch` (the contract named only the first).
* U1 taps are intents from the catalogue until the rendered tree (lvprobe) exists; U2 and U3 are refused.
* `deadline` and `env-inputs` are the only model facts; others need a later grammar.
