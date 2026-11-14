# Whole-app simulation: `c_sim` (T2G1, P330 §1)

`c_sim` is the target kind for the one check that runs the *composition* of an app (reactors, runtime, adapters, clock, files,
network, faults) on simulated ports. T2G1 is the base: the rule, the runner, the world interface and the identity and crash
handling, proven on a fixture product (`selftest/sim`, run by `selftest/sim.sh`). The invariants (T2G3, T2G4), the judge `rigor sim`
and the grade wiring (T2G2), tiers and the real product come later; nothing here checks a safety property yet.

## The rule

```
c_sim(
    name = "lockers_sim",
    srcs = ["world.c"],                   # the WORLD: implements sim/world.h; string literals, never a glob
    deps = ["//apps/lockers/lkapp/wire:wire", ...],
    seeds = 200, run_ms = 3600000, shards = 4,    # optional budgets (int literals); defaults and maxima in rules/sim.bzl
)
```

The gate's runner (`gate//sim:runner`, C, linked in by the rule) owns `main`, the seed loop, the workload and fault driver and
the identity check. The product supplies only the world. The product passes **everything through `sim/world.h`**; the gate does
not depend on any product and vendors none of its code (orchestrator decision on P330 open question 2).

| Target | Content |
|---|---|
| `<name>` | the test: runs every shard and merges them (`rigor_lib/sim_merge.py`); fails unless the verdict is `pass` |
| `<name>[stats]` | `stats.json`, canonical JSON, schema `sim-stats/1`: `count`, `seeds_run`, `distinct_hashes`, `failures` (`seed`, `index`, `rule`, `detail`), `run_ms`, `world_sha256`, `salt_sha256`, `shards` |
| `<name>[hashes]` | one line per finished seed: `index seed trace_hash state_hash` (hex) |
| `<name>[verdict]` | `pass`, or `fail <rule>` |
| `<name>[report]` | the runner's lines and the filtered sanitizer output |
| `<name>__bin`, `<name>__shard<k>` | the runner linked with the world (release and san only); one `sim_run` action per shard of seeds |
| `<name>_facts` (and `_san`, `_msan`, `_tsan`) | the facts of the world's sources, kind `c_sim` |

## Seeds, runs, identity

* `seed_i` = the first 8 bytes (big endian) of SHA-256(`"rigor-sim-v1"` || salt || `world_sha256` || `le64(i)`). **Deviation from P330 §1.3:**
  the third input is `world_sha256` (the sorted content hashes of the world's source files), not the hash of the binary,
  because the release and the san binary differ and seeds 0 to 9 must be the same in both. The salt is `-c rigor.sim_salt=HEX`
  (empty by default; the grader's hidden salt, T2G2).
* One seed is one simulated day: a seeded workload (`sim/workload.c`: intents, faults, power cuts, one decision per 250 ms
  tick) for `run_ms` of virtual time, then a quiet drain of 120 s.
* Each seed runs **twice on fresh worlds in a forked child**; equal trace hash and equal final state hash are required
  (`sim-nondeterministic`, with the record index of the first difference). The trace is the rolling FNV-1a of the records the
  world sends to the tap (`sim/trace_fmt.h`, kinds `ev fx fr io vw st`).
* Release vs san: `sim_merge.py compare RELEASE_HASHES SAN_HASHES` requires the hashes of seeds 0 to 9 to be equal
  (`sim-nondeterministic`); a seed missing in one mode is a finding too.
* Distinctness: fewer distinct trace hashes than seeds (2 or more) is `sim-vacuous`.

## Fail closed

Every way of not finishing is a rule in `stats.json` and a failed test, never a skip: a world that does not build fails the
build; a crash, sanitizer report or non-zero exit of the child is `sim-crash`; the real-time alarm of the child (120 s), the step
limit counted by the world (50,000,000) or a stuck clock is `sim-timeout` / `sim-deadlock`; zero seeds (count 0, a missing or short shard) is
`sim-no-seeds`. The runner exits 2 on a usage error or when it cannot write its outputs (the action then fails).

## Kind matching: a world is product code

The facts of a `c_sim` have kind `c_sim`, which every gate treats as a **product** kind (`facts_data`, `policy_check.PRODUCT_KINDS`,
`structure_data` / `grade_structure` KINDS, `guards_gate.MODULE_KINDS`; not a test kind, so `mutable-data` and the profile floors apply). A world needs
a policy entry (`module-not-in-policy` otherwise), its sources go through the semantic and symbols gates (a denied symbol in a world is
`denied-symbol`, `selftest/sim.sh` step "kind matching"), `buckfiles` accepts `c_sim` with literal `srcs` and int-literal `seeds`, `run_ms`,
`shards` only, and the mutation layout skips `<name>__bin` like a fuzz binary. The runner and `sim/world.h` are gate code and are no facts dep of a world.

## `sim/world.h`

`world_init(cfg, seed, tap, ctx)` (the one static world instance, re-initialised), `world_run_until(t_ms)`, `world_now_ms`, `world_apply(intent)`,
`world_fault(fault)`, `world_crash_restart`, `world_stats`, `world_state_hash`. All time is virtual; no function reads a real clock,
the environment, a file or a socket. P330 §1.2 has the full contract; this header is the T2G1 subset (the fault catalogue grows in T2G3).

## Nothing depends on a `c_sim`

`rigor buckfiles` refuses (`bad-argument`, why `sim-target`) any dep, from any macro, on a `c_sim` target or a target it derives
(`__bin`, `__shard<k>`, `__facts_unit`, `_facts`, `_facts_san`, `_facts_msan`, `_facts_tsan`). Resolution is the one used for `c_test` targets.

## Canaries

`canaries/sim-crash` and `canaries/sim-nondeterministic` (shared files in `canaries/_sim/files`) put a one-file world into the
base product. They carry `"pending": "T2G2"`: today the grade passes them (every existing gate accepts the world, which also
proves a world is graded like a library: running them found that `c_structure` did not know kind `c_sim`, fixed here), and they
turn red in gate `sim` once T2G2 wires it into `rigor grade`. There is no `sim-no-seeds` canary: the macro refuses `seeds < 1` at load time and the
runner/merge produce `sim-no-seeds` only for a run that did not execute, which a product cannot author; that rule is covered by
`gate/tests/test_sim_merge.py` and `selftest/sim.sh` (`--count 0`). T2G2 owns `sim-seeds-short` and `sim-missing-target`.

## Wire invariants I3 to I6b (T2G3, P330 §2.1)

`sim/inv` is the part of the judge that decides the hardware-safety rules, and it shares **nothing** with the kiosk or the board simulator:
`sim/inv/frame.{h,c}` is a Modbus RTU decoder written from the rules and the framing alone (CRC-16, FC01, FC03, FC05, FC0F), and
`sim/inv/wire.{h,c}` models the 30 coils itself from the bytes it sees. Pure C, static memory (the caller owns a `wire_t`), tested through
the public headers, mutation-tested at L3 (`//sim/inv:frame_mutants`, `//sim/inv:wire_mutants`: zero survivors, no approvals).

Input is `fr` records (`sim/trace_fmt.h`): `a` = 0 a frame the kiosk sent, 1 a frame the board sent, `t_ms` its virtual time at the tap, the bytes
one whole frame. `wire_feed` takes records in time order, `wire_finish(t_end)` raises the deadlines that passed without an event.

| Id | Rules (`wire_rule_t`) | What is checked |
|---|---|---|
| I3 | `ON_FRAME`, `TWO_ENERGISED` | no FC05 `0xFF00` or `0x5500` at any address (all-ON included), no FC0F with a set bit; at most two coils on, and two only from one flight |
| I4 | `UNITS` | every flash-on (FC05 at `0x0200..0x021D`) has 1 to 8 units |
| I5 | `NO_PREREAD`, `BEFORE_VERIFY`, `GAP`, `VERIFY_LATE` | a fresh all-30-off read before each flight (the verify read of the last flight is not one); a flash-on while the last flight is not verified; 300 ms between the verified-off answer and the next flight; the verified-off answer by first flash + 900 + 150 ms |
| I6 | `WATCHDOG`, `BURN` | an all-off at or before first flash + 900 ms once a read showed a coil on at or after min(units x 100 + 150, 900) ms; no coil on for 1000 ms in the model |
| I6b | `UNSAFE_FRAME` | every request in the allow-list (slave 1; FC01 read of 1..30 coils from 0..29; FC03 of `0x8000` or `0x4000`, 1 register; FC05 flash-on 1..8 units on channels 0..29; FC05 `0x00FF` value 0) with a valid CRC |

A flight is the first flash-on and a second one before the verified-off read (row, then column); `wire_flight_count` and `wire_record_count` are the
antecedents for the judge's non-vacuity check. The model: a flash-on of N units turns the coil on at the frame and lets the device turn it off between
N x 100 - 30 and N x 100 ms later; a coil read is authoritative for the coils it covers; an all-off frame turns the model off but does not end the burn
chain (only a read that shows the coil off does), so a coil that ignores the all-off and is read on again past 1000 ms is a burn. The board cross-check
`wire_crosscheck(w, board_violations)` returns `WIRE_XC_BOARD_ONLY` or `WIRE_XC_ENGINE_ONLY` (`sim-model-divergence`) when the board simulator's list
and the engine's board-observable rules (`ON_FRAME`, `TWO_ENERGISED`, `UNITS`, `BURN`) disagree.

**Constants** are in `policy/sim_constants.toml`, each with the section of `hardware-safety.md` it comes from; `sim/inv/wire_consts.h` carries the same
values and `gate/tests/test_sim_wire_data.py` fails if the two differ. One constant has no source in that file, and says so: `VERIFY_SLACK_MS` (the "frame
deadline" of P330 §2.1 I5; 150 ms is the kiosk's own `FRAME_DEADLINE_MS`), open for the owner to confirm.

**Boundaries pinned by tests:** gap 299/300 ms, units 8/9 (and 0), all-off at 899/900/901 ms, deadlines 249/250 (1 unit), 649/650 (5), 849/850 (7), 899/900 (8),
verified-off answer at 2050/2051 ms for a flash at 1000, burn at 999/1000 ms, a coil's earliest and latest off time.

**Positive control** (`selftest/sim/data`, sha256 in `SHA256SUMS`, source in `SOURCE`): the recording of the real board and the one of the club-apps
simulator, converted by `tools/sim/fixture_to_fr.py` into `sim/inv/tests/fixtures_data.{h,c}` (generated; the unit test `test_sim_wire_data.py`
regenerates and compares), PASS I3 to I6b. The recorded script paces its three flights 10 ms apart and reuses each verify read as the read before the
next flash, so the control is checked per flight; the **uncut** recordings are pinned to FAIL I5 (`GAP` and `NO_PREREAD`, nothing else). Both files contain no
IPv4 address; the converter never copies `host` or `port` and refuses output that matches an address.

**Not yet:** the event and view invariants (T2G4, T2G5) and the wiring of the engine into a world's tap (T2G9). `selftest/sim.sh` does not run these tests
(T2G3 did not own it): `buck2 test //sim/inv/...` and the two `c_mutants` targets are the acceptance commands until a later task adds the step.
