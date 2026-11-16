# U05: `rigor ui-explore`, the explorer driver (P004 T1xx.05)

Repo `Mivr/c-rigor-gate`, branch `task/U05`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §3.0, §3.7, §4.1,
§4.3, §4.5, §6.3, §8.5; `plan/metrics/ui-probe-2026-11-13.md` sections 1 to 4; `docs/ui-model.md` and
`ui/model/model.h` (the `ui-probe/1` protocol this drives); `selftest/ui.sh` and `selftest/ui_product/` (the toy
probe); `docs/ui-contract.md`; `gate/rigor_lib/findings.py`, `jsonio.py`, `errors.py`, `cli.py`, and `grade_sim.py`
with `docs/sim.md` for how an existing judge drives a product binary and reports.

## Why
Every UI judge needs the same machine underneath: something that drives the probe along input paths, never trusts
one run, remembers where it has been by an owner-declared key, and writes findings in one schema with a replayable
path. Judges come in later tasks and plug into it.

## Do
Python, stdlib only, `gate/rigor_lib/ui_explore*.py` (split by concern; no file over 500 lines), CLI `rigor ui-explore`.
1. **Probe client**: starts a probe binary, speaks `ui-probe/1` strictly (greeting, framed `lines <n>` replies, the
   one long unframed `env-inputs` line), with a per-command deadline; any protocol violation, `err` reply, early
   exit or timeout is a typed error that becomes a finding (`probe-protocol`, `probe-crash`, `probe-timeout`), never
   a silently shortened run. Records of `semantic`, `patches`, `trace` are parsed and unescaped per the documented
   grammar; frame-seam lines are kept verbatim per frame for judges (their grammar belongs to a later task).
2. **Event catalogue** (P004 §4.3 item 2): a strict TOML loader for a sealed, versioned catalogue file
   (`products/<product>/ui/<app>.events.toml`): classes U1 intent taps, U2 probe taps, U3 complement taps, U4 code
   macros with boundary classes, U5 language, E1 environment replies, T1 virtual-time events. Unknown keys, missing
   classes and duplicate ids are errors. Check in the toy's catalogue under `selftest/ui_product/`.
3. **Abstraction key** (§4.3 item 3): an owner-declared projection of the semantic records plus named model facts,
   declared in the catalogue file, hashed exactly. Never a similarity measure. `key-too-coarse`: two states with
   equal keys whose normalised semantic trees differ.
4. **Strategies**: `sweep` (the `domain-at` enumeration), `bfs` (from `open`, over abstract state x catalogue event,
   depth bound and state bound as arguments, paths replayed from `open`; report new abstract states per depth and
   `depth-unsaturated` when the last depth still adds states), `walk` (seeded random walks; the seed list is an
   argument; each walk also at N extra clock origins), `replay` (a recorded path file). Deterministic iteration
   order everywhere.
5. **Run-twice (L0)**: every path is executed twice in fresh probe processes; any difference in any reply is
   `model-nondeterministic` with the first differing step. No retries anywhere. `timer-starvation`: a model whose
   next deadline never advances past `now` across a bounded number of steps.
6. **Judge plug-in point**: a judge is a function over (step observation, path so far, contract) yielding findings.
   Ship two trivial built-in judges only: the protocol/determinism ones above and `ui-coverage-gap` for criteria C1
   (every domain entry visited) and C8 (every reachable abstract state x catalogue event pair exercised).
7. **Findings and evidence** (§4.5): one JSON line per finding, the schema of §4.5 (`id` stable across runs, `gate`,
   `check`, `layer`, `severity`, `state`, `path`, `observed`, `blame`, `evidence`, `explanation` always null here),
   sorted, byte-identical for identical inputs; a stdlib PNG writer (`zlib`, `struct`) for evidence images from
   RGBA crops; every finding's `path` must replay with `--strategy replay` to the same finding.
8. `docs/ui-explore.md`: the CLI, the catalogue and key schemas, the findings schema, the judge interface.

## Not in this task
The rendered-tree facts and their judges (U05a, U06 to U09); the lockers catalogue and key (a later, owner-sealed
file); wiring into `rigor grade` (U14); scenario replay against the oracle bundle (U12).

## Acceptance
Extend `selftest/ui.sh` (new steps) and add `gate/tests/test_ui_explore*.py`:
- the same inputs twice give a byte-identical `findings.json`;
- a deliberately nondeterministic build of the toy adapter (a second fixture model under `selftest/ui_product/`
  seeded from something outside the interface) gives `model-nondeterministic` naming the first differing step;
- a toy adapter whose deadline never moves gives `timer-starvation`;
- a probe that exits mid-session, one that prints a malformed reply and one that hangs each give their typed
  finding within the deadline (use small stub scripts as fake probes in the unit tests);
- `sweep` on the toy covers C1 = 100%; removing one domain entry from the visit gives `ui-coverage-gap`;
- `bfs` on the toy terminates, reports states per depth, and a too-small depth bound gives `depth-unsaturated`;
- a key that omits a field the toy's states differ in gives `key-too-coarse`;
- a finding's recorded path replays to the same finding id;
- the PNG writer's output is a valid PNG (decode it back with stdlib in the test).
Each check must be seen failing once against a deliberately broken build. `selftest/ui.sh` green twice in a row;
`python3 -I -B gate/tests/run_parallel.py` at baseline; `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/ui_explore*.py`, `gate/rigor_lib/cli.py` (register the subcommand only), `gate/rigor_lib/BUCK`,
`gate/tests/test_ui_explore*.py`, `gate/tests/data/ui_explore/**`, `selftest/ui.sh`, `selftest/ui_product/**`
(add fixtures; do not weaken existing steps or transcripts), `docs/ui-explore.md`, `tools/affected.toml` (new
paths only).
