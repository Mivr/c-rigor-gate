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

**Not yet:** the view invariants (T2G5) and the wiring of the engines into a world's tap (T2G9). Since T2G4 `selftest/sim.sh` runs the tests of all of `//sim/inv/...`
in release and san and judges the four `c_mutants` targets (`frame`, `wire`, `audit`, `events`) with `rigor mutants` at L3.

## Event and storage invariants I1, I2, I9, I10, I15 (T2G4, P330 section 2.2)

`sim/inv/events.{h,c}` (with `events_names.c`) is the second engine of `sim/inv`: pure C, static memory (an `events_t` is about 4 KiB: keep it static), tested through
its header, mutation-tested at L3 (`//sim/inv:events_mutants`, `//sim/inv:audit_mutants`: zero survivors, no approvals). It knows no product: **every record type, payload offset, phase
and timer is configuration** (`events_cfg_t`, which the orchestrator copies from the product's `sim.toml [inv.*]`), and the two things only the product can decode, the
book and the audit file, are read through **callbacks of the world** (`events_world_t`). It decodes frames with `sim/inv/frame.h` and shares nothing with the kiosk.

**API.** `events_init(e, cfg, world)` (returns -1 for a configuration out of range, see the header), then `events_feed(e, rec)` for every record in time order (any kind: `ev fx fr io vw`
are read, others only advance time), `events_power_cut(e, t)` BEFORE `world_crash_restart`, `events_restarted(e, t)` AFTER it, `events_finish(e, t_end)` after the drain.
Results: `events_finding_count`, `events_finding(i)` (`inv`, `rule`, `t_ms`, `record`), `events_has_rule/has_inv/inv_mask`, `events_counts` (the antecedents of the non-vacuity check), and
for the report `events_inv_name` ("I1") and `events_rule_name` ("no-authorisation", kebab case). A finding's **step** is the index of the record that raised it, counting every record
fed to `events_feed` from 0 (`events_finish`, `events_restarted` findings carry the count so far); at most 16 findings are kept, `events_dropped` counts the rest. The judge maps a finding to
`sim-invariant-violated` with the invariant id, the rule, the seed, the virtual time and the step.

| Id | Rules (`events_rule_t`) | What is checked |
|---|---|---|
| I1 | `NO_AUTH`, `OPEN_OVERLAP`, `CORR_REUSED`, `BAD_PAYLOAD`, `HANDOVER_WITHOUT_EFFECT`, `PULSE_WITHOUT_OPEN`, `EXTRA_PULSE` | each opening `fx` is paid for by one authorising `ev` (`auth[]`, up to 4: the visitor's `staged`, the shift reactor's request) and consumes it: a second effect with no new authorisation is the **double pulse**; one effect in flight until its `open_result` (matched by corr when `corr_len` > 0, a result of another corr is a stale one and is ignored); corr unique over the last 256 effects (`corr_shared`, the shift reactor's constant, is exempt); on the wire (`fr` request, flash-on = FC05 at 0x0200..0x021D): no flash-on without a hand-over to the driver, at most `flashes_per_open` per hand-over (a row and a column coil: 2) |
| I2 | `NOT_DURABLE`, `BOOK_UNDECODABLE` | at every flash-on frame of an opening, `book_reserves(ctx, effect_payload, len)` must answer `EV_BOOK_RESERVED` (or `EV_BOOK_EXEMPT` for an inspection, which needs none); `NOT_RESERVED` is `NOT_DURABLE`, a negative answer is `BOOK_UNDECODABLE`. The callback reads the DURABLE image of the world's simfs |
| I9 | `CRASH_BOOK_CHANGED`, `CRASH_BOOK_UNREADABLE`, `CRASH_AUDIT_FORMAT`, `CRASH_AUDIT_GAP`, `OPEN_BEFORE_BOOT` | every durable save of the book (an `io` record of the book file, the call-end operation, outcome 0, durable bit) takes `book_digest`; after a cut the digest of the durable book must equal the last one (the first cut with no save learns it); the audit file is a prefix-valid chain (a final line without newline, a torn tail, is accepted); no opening effect before the boot `ev` of the current boot |
| I10 | `AUDIT_FORMAT`, `AUDIT_GAP`, `AUDIT_BOUND`, `DOOR_WITHOUT_ASSIGNMENT`, `DOOR_WITHOUT_OPEN`, `SHORT_LOCKER`, `LOCKER_TABLE_FULL` | at the end the audit file (`audit_read`) has no torn tail, `"seq":N` rising by exactly one from the first line (any start), and at most `audit_max_bytes`; `door_opened` needs an earlier `locker_assigned` and at most one `door_opened` per opening effect of its locker (64 lockers tracked, more fails closed) |
| I15 | `STUCK_PHASE`, `NO_RECOVERY`, `NOT_IDLE_AT_END` | phase rows select a record (`kind`, `a`) and set the phase 0..7 (0 idle); a stay longer than `limit_ms[phase]` is flagged once per stay (a republished view does not restart it; the check runs on every record, so a late change out of the phase is late); after the relay-clear record, the welcome phase must be entered within `recover_ms`; the run ends idle |

**`io` record layout** (the gate's definition, the world fills it): `a` = operation (bits 0-7) | outcome (bits 8-11, 0 ok) | errno (12-19) | durable bit (bit 20) | disk (24-31); `b` the byte count; the bytes are the file
name. `book_digest` must write its argument when it returns 0; `audit_read` returns the durable bytes of the audit file.

**Spec decisions** (P330 left them open or `[V]`):
* The authorising events are data, not code: `auth[]`. A retry after a failed open is legal exactly when the product's reactor emits a new authorising event for it; the engine never infers one. The product's list is `sim.toml [inv.I1]` (the
  proposal in business-apps `plan/reviews/2026-11-13-sim-toml-proposal.md` section 3: `visit_staged` 17, the shift's inspection and end-of-shift requests, corr `LK_SHIFT_CORR`; the effect and its hand-over are both `fx 26`, told apart by
  `b == 0xFFFFFFFF`: `has_handover = 1`, `handover_b = 0xFFFFFFFF`; two flash-on frames per door: `flashes_per_open = 2`; phase timers choose 30000, opened 8000, lockout 60000 plus the slack of P330 I15).
* The "audit" the invariant reads is the **durable audit file** through `audit_read` (the `io` records name files, not lines), checked after every power cut and at the end; `"seq":N` is the only key the engine needs from a line.
* The book check does not decode the book: `book_reserves` and `book_digest` are the world's, and the product proves them with P1 against its other implementation. Without a callback the check does not run and its antecedent counter
  (`i2_checks`, `durable_saves`, `audit_lines`) stays 0, which the judge reports as a vacuous invariant.
* An opening effect payload over 32 bytes is `BAD_PAYLOAD` (fail closed; the engine keeps 32 bytes for the callback). Corr uniqueness is over the last 256 effects (a day has thousands); a repeat beyond that is not seen.
* A power cut drops the credits, the opening in flight, the boot flag, the phase, and each locker's pending openings; it keeps assignments (they are in the durable book).
* A cut inside a book save: the engine accepts only the last durable digest. If the world's durable image can hold a newer book than its last `io` end record (rename durable before the call returned), the world must emit that record first; if the
  product's reality is different this is the rule to relax with the owner, not silently.

**Fixture product** (`sim/inv/tests/model.{h,c}`, `model_test`): a model of a kiosk that emits the records of a day from a seed (3 to 7 visits, a power cut on every third seed) behind the three callbacks, with three seeded bugs.
It is a trace generator, not a `c_sim` world (the runner does not evaluate invariants until the judge is wired). The correct kiosk is green over 200 seeds; `double-pulse` (a stale second `cmd_open` after the result), `no-save-before-open`
(the first visit pulses before its reservation is durable) and `stuck-phase` (the opened screen is republished and never left) are red on every one of 200 seeds, each with the exact invariant, rule and record index the model recorded.
