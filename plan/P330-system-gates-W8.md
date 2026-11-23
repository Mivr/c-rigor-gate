# P330: system gates (W8): `c_sim`, invariants, soak and `oracle` replay

Design only: no gate code, no product change, no farm run. It turns work package **W8** of `plan/P003-gate-v2.md`
(§7.4 whole-app simulation, §7.5 oracle trace replay, §9 tiers, §11 and §12 tables, §13 W8) into tasks small enough for
one Sonnet lane each. Read against gate `7ec88c7`, business-apps `4f5e1b5` (2026-11-13) and club-apps `146f1f0`.
Sources read: `business-apps/docs/design.md` (P2 and P7 rows, `simhost`, `trace`, M5), `docs/lockers/hardware-safety.md`,
`apps/lockers/lksim/board/board.h`, `apps/lockers/lkapp/runtime/runtime.h`, `apps/lockers/lkapp/wire/wire.h`,
`apps/lockers/lkrx/vstate/vstate.h`, `docs/lockers/ui-rules.md`, `lib/sim/*/*.h`; club-apps `viewmodel/lockers*`,
`ports/lockers`, `tools/e2e`, `tools/conformance`, `sim/waveshare-relay`.

**Why now.** The owner requires W8 and `c_proof` (W7) before the kiosk touches the real relay board. `c_proof` proves the
relay modules in isolation; W8 is the only check that exercises the *composition*: reactors, runtime, adapters, opener,
board simulator, clock, files, network, with faults. Three facts about the repositories today set the scope:

1. **The whole-app simulation does not exist.** `lib/sim/simhost` has no caller outside its own tests [M: `grep -rl simhost`
   over business-apps lists only `lib/sim/*`, `runtime.h` and `ports.h`]. `lk_wire_io_t` (the port bundle of the
   composition root) has only real implementations (`lkapp/posixio`, `lkapp/checkconfig`). `apps/lockers/itest/runtime/tests/chain_test.c`
   is the nearest thing: real folds and reactors behind the runtime, but no board, no network, no faults, no virtual time.
2. **No Rust trace corpus exists.** The plan names club-apps T182 to T185 (`docs/lockers/p001-lockers-c-plan.md` lines 506
   to 509) and club-apps has none of them (its `plan/tasks` ends at T180; there is no `tools/vm-trace`).
3. **The two defects W8 must catch are reproducible only with machinery that is not there**, see §5.

**Evidence tags** as in P003: **[M]** measured in a repository (path given), **[P]** proposal or starting number to be
re-derived from data by P003 §14, **[V]** to be verified by the named task before it relies on it (nothing tagged [V] is
a finding).

## Summary

| Part | What | Where it lives |
|---|---|---|
| §1 `c_sim` | One simulation target per app: a gate-owned runner over a product-supplied *world* (real composition, simulated ports, injected clock, seeded faults). Gate-owned workload, fault schedule and invariants | gate `rules/sim.bzl`, `sim/` (C, gate-owned), `gate/rigor_lib/grade_sim.py` |
| §2 invariants | 15 predicates over a gate-defined event and frame trace, each with its observation point in the C code | gate `sim/inv/*` |
| §3 `oracle` | Byte-identical replay of Rust viewmodel traces through the real C wiring; visible corpus in the product, hidden corpus gate-held | club-apps `tools/vm-trace`; business-apps replayer; gate judge |
| §4 gates | `sim` and `oracle` in `gate/order.txt` after `fuzz`; tiers, budgets, results schema | gate |
| §5 canaries | Historical canaries: real defects re-introduced into the real product by a gate-held patch | gate `canaries/hist-*` |
| §6 tasks | 19 tasks: 9 gate, 8 business-apps, 2 club-apps | below |

---

## 1. The `c_sim` rule

### 1.1 What a simulation target is

A `c_sim` target is a **test binary over the real composition root** with every port bound to its simulation. It is
built from three parts that differ in who owns them:

| Part | Owner | Content |
|---|---|---|
| **Runner** | gate (`gate//sim:runner`, C, linked in) | `main`: seed loop, virtual-time loop, workload driver, fault injector, invariant engine, trace writer, report writer. The product cannot change it |
| **World** | product (`srcs` of the `c_sim` target) | One C file implementing the gate header `sim/world.h`: build the app from `lk_wire_io_t` of simulated ports, step it, expose observation taps, apply abstract intents. It contains no invariant and no workload |
| **Spec** | gate (`products/<p>/sim.toml`, sealed, not a product file) | Workload mix, fault catalogue and rates, run lengths, coverage floors, soak assertions, constants (`pulse_cap_ms`, `gap_ms`, `watchdog_cap_ms`, from `docs/lockers/hardware-safety.md`) |

Why the split: a test author who writes the workload, the faults and the invariants grades their own homework. P003 says
the invariant list is gate-owned and written against events, not internals (§7.4); the same holds for the workload
(a benign workload passes any invariant) and the fault schedule (§7.4 "come from the seed").

```
c_sim(
    name = "lockers_sim",
    srcs = ["lockers_world.c"],          # implements sim/world.h
    deps = [":sim_world_libs", ...],     # the real composition and the simulators, by public header
)
```

`c_sim` is a macro in `rules/sim.bzl`, forwarded from `rules/c.bzl` exactly as `c_fuzz` is (`rules/fuzz.bzl`).
It follows the discipline of every gate macro: literal lists only, no `compiler_flags`, checked by `rigor buckfiles`,
and it defines `<name>_facts` so the `symbols` and `layering` gates see it. Layering: the world may depend on anything the
composition root (`apps/lockers/lkapp/wire`) may depend on, plus `lib/sim/*` and `apps/lockers/lksim/*`; nothing in
`lib/**` or `apps/**` outside `lkapp/sim` and `lksim` may depend on a `c_sim` target (`architecture.toml` row).

### 1.2 The world interface (`sim/world.h`, gate-owned)

All time is virtual, every function is non-blocking, and no function reads a real clock, `getenv`, a file or a socket.

| Function | Meaning |
|---|---|
| `world_init(w, cfg, seed)` | Build the whole app: simfs (empty or the crashed image of the last run), simnet with the board peer `lksim/board` and the simulated servers (codes list, sync endpoint), simclock at `cfg.start_ms`, `simhost` with the three step tasks (`lkrt_core_step`, `lkrt_opener_step`, `lkrt_net_step`). `cfg` carries the config text of the app (a gate-written, hardware-free config) |
| `world_run_until(w, t_ms)` | `simhost_run_until`. Returns when virtual time reaches `t_ms`; DEADLOCK from simhost is a FAIL `sim-deadlock` |
| `world_apply(w, intent)` | Post one abstract intent on the UI lane (`lkrt_ui_post`): `digit d`, `backspace`, `submit`, `scan text`, `choose_size k`, `cancel`, `dismiss which`, `dismiss_report`, `ack_opened`, `lang bg\|en`, `staff_scan`. The mapping onto `lk_ev_*` events is the world's and is itself checked by the oracle |
| `world_fault(w, fault)` | Apply one fault from the catalogue (§1.4) to the simulated ports (`simfs` fault table, `simnet_fault`, `lkboard_apply_config`, `simclock` jump, power cut) |
| `world_crash_restart(w)` | Power cut: drop all volatile state, keep the *durable image* of simfs, rebuild from `world_init` with that image. The new boot must pass through the normal boot path |
| `world_tap(w, tap)` | Install the gate's observer (§1.5). The world must wire it into every observation point of §2; a missing point is detected by the invariant's own vacuity check (§1.6) |
| `world_stats(w, out)` | The runtime counters (`lkrt_stats`: `rx_push_lost`, `result_lost`, `net_full`, `no_free_blob`, `opener_full`, `runaway`, `scene_failed`, `audit_failed`, `book_failed`) and the capacity gauges the soak assertions read |

### 1.3 Seeds, runs and the identity check

* **Seed derivation (gate-owned, not product-controlled).** `seed_i = first 8 bytes of SHA-256("rigor-sim-v1" || salt || binary_sha256 || le64(i))`,
  `i = 0..N-1`. `binary_sha256` is the hash of the `c_sim` binary, so an unchanged binary has unchanged seeds and the
  shard actions stay cacheable. `salt` is a gate input like the witness bundle: the **lane tier** uses the public salt
  (`products/<p>/sim-salt.public`, in the gate repo, readable by implementers) so an agent can reproduce any failure;
  the **grader** passes `rigor grade --sim-salt FILE` (hidden, only its sha256 enters the verdict). An implementer
  therefore cannot tune the product to the graded seeds; a failure on a hidden seed prints the seed, and the seed joins
  `products/<p>/sim-regressions.json` (public from then on, replayed in every tier; same rule as the fuzz regression
  list, `docs/fuzz.md`).
* **One seed = one simulated club day** (`run_ms` from the spec, default 24 h of virtual time): a seeded stream of
  visitors and staff actions (the workload) interleaved with the seeded fault schedule, ending with a quiet drain
  (no new input, no new fault, 120 s) after which the end-of-run invariants are evaluated.
* **Identity check (P003 §7.4, design P7).** The runner runs each seed of a shard twice in one process on fresh worlds
  and requires equal trace hash and equal final state hash. Seeds `0..9` of every build are additionally run by the
  `linux_release` build of the same target and the trace hashes must equal the `linux_san` hashes: this catches behaviour that
  depends on undefined behaviour or uninitialised memory, which the same-binary check cannot. A mismatch is
  `sim-nondeterministic` (seed, the two hashes, `trace_first_diff` line and byte).
* **Distinctness.** Over the 200 seeds the number of distinct trace hashes must be 200; fewer means the seed does not
  reach the product (`sim-vacuous`, §1.6).
* **Trace** = `lib/sim/trace` canonical JSON lines (`ev`, `fx`, `vw` records) plus the gate's own `fr` (wire frame) and
  `io` (simfs operation) records, defined in `sim/trace_fmt.h`. The hash is the rolling FNV-1a of `trace_t`.

### 1.4 The fault catalogue (gate-owned, `sim.toml [fault.*]`)

Each fault has a kind, a seeded trigger (time, or "the n-th call of port X") and a duration. The set is the union of
P003 §7.4, design P7 and the board knobs of `lksim/board`:

| Fault | Injection point | Source |
|---|---|---|
| `disk_full`, `io_error`, `read_error` on the book, audit or codes file | `simfs` fault table | simfs |
| `torn_write` and `power_cut` at a seeded operation (the crash image keeps only what was fsynced) | `simfs` + `world_crash_restart` | design P7 |
| `dns_dead`, `tls_reset`, `http_5xx`, `http_slow`, `link_flap` on the codes and sync endpoints | `simnet` | P003 §7.4 |
| `relay_silent` (`silent_reads`), `relay_stuck_coil` (`ignore_flash`: the coil stays on), `relay_late_reply` (`reply_delay_ms`), `relay_half_frame`, `relay_drop_after_flash`, `relay_link_close` | `lkboard_apply_config`, `simnet` | board.h |
| `clock_jump` (wall forward and back; monotonic never back) | `simclock` | design P7 |
| `stale_result`: re-deliver an *earlier* result event (`book_saved`, `open_result`, `relay_status`, `salt_ready`) on its lane after a seeded delay, and `dup_tick` | core inbox, lanes 0 and 1 | §5.2 (GAP-V2), design P7 "duplicate ticks are idempotent" |

`stale_result` is the one fault that is not a physical event: the mailbox does not duplicate messages. It is the
robustness property "a fold tolerates any event in any phase" turned into a fault, and it is the only way a seeded
run reaches GAP-V2 deterministically (§5.2). It stays in the catalogue for all products with reactors.

### 1.5 Observation: where the checker looks (not where the product reports)

The invariants are evaluated by the gate's engine over records it creates itself from **taps** it installs in
simulation-only seams. The product does not write trace records. Three kinds of tap, in order of trust:

1. **Wire tap (highest trust).** The raw bytes of every simnet lane and their virtual time. The engine decodes frames
   with its **own** minimal Modbus-RTU decoder and models coil state itself from the flash-on units it sees. It does
   not call `relay/frame`, `relay/frame_is_safe`, `relay/pulse` or `lksim/board`, so a bug shared by the kiosk's frame code
   and the board simulator cannot hide (the design's rule for `frame_is_safe`: independent implementation). The board's
   own violation list (`lkboard_violations`) is read as a cross-check: it must be empty and must agree with the engine's
   model (a disagreement is `sim-model-divergence`: one of the two is wrong).
2. **File tap.** The operation log of `simfs` (open, write, fsync, rename, unlink, with virtual time) and its *durable
   image* (what a power cut now would leave). New in simfs if missing [V].
3. **Runtime tap.** A function pointer in the runtime config (`lkrt_cfg_t.tap`, NULL in the release composition and
   forbidden by `symbols` there) called by `lkrt_core_step` for every event it takes from rx (`rx_step`) and for every
   effect before the adapter call (C4), by the scene publication (C5) with the view snapshot, and by
   `lkrt_opener_step` for every command it hands to the driver and every result it posts. This is the weakest tap
   (it is product code), so no safety invariant rests on it alone: `cmd_open` is always confirmed by the wire tap.

### 1.6 Non-vacuity (a sim that checks nothing must fail)

A PASS is worth something only if the run reached what the invariants talk about. The judge requires, from the
`stats.json` of every shard (floors in `sim.toml [coverage]`, [P] values to be set by measurement in T2G9):

* every invariant's *antecedent* occurred at least `k` times over the run: pulses sent (I3 to I6), `staged` events (I1),
  durable book saves (I2), notices shown (I7), sync uploads (I11), and so on. An invariant never exercised is
  `sim-vacuous` (invariant id, count 0);
* every fault kind fired at least once and its *effect* was observed (a `disk_full` fault with no failed save is a bug in
  the injection, not a robust app): `fault-not-observed`;
* every screen of the closed screen set (`splash`, `welcome`, `choose`, `opened`, `shift`, `report`, `lockout`,
  `fault_storage`, `fault_relay`) and every notice kind reached;
* 200 distinct seeds gave 200 distinct trace hashes;
* every module of profile `wiring`, `ui` or `safety` in the policy is in the link closure of some `c_sim` target
  (`sim-module-unreached`), and in the one `cov`-mode shard has at least one executed line (`sim-module-unexercised`).

The seeded-bad-driver canaries of §5.1 prove each floor can turn red.

### 1.7 Budgets and execution on RE

| Item | Merge tier | Nightly tier | Lane tier (agent loop) |
|---|---|---|---|
| Seeds | 200 (hidden salt at the grader) | 2,000 | 20 public seeds + the regression list |
| Run length per seed | 1 simulated day | 1 simulated day | 1 simulated day |
| Soak | none | 400 simulated days, one seed, plus 3 crash-storm seeds | none |
| `oracle` | visible corpus (product test) + hidden corpus | same | visible corpus only |
| Wall budget [P] | sim 60 s of wall on 10 RE shards, inside P003's 10 min merge budget | 30 min of the 2 h nightly | 60 s |
| Per-seed guards | virtual limit 25 h; step limit 5,000,000; real-time limit 20 s | same | same |

* **Shards.** `c_sim` expands into `ceil(seeds/20)` test actions per mode, each hermetic, input-addressed (binary, spec,
  salt id, seed range), one core, 1 GiB, timeout 300 s; the soak is one action with timeout 900 s (it is sequential state;
  it cannot be sharded). All outputs are cacheable: an unchanged binary and spec is a cache hit, so the merge cost
  is the cost of *changed* products (the property T123 gave mutation).
* **Mode.** Seeds run in `linux_san` (ASan + UBSan, `-fno-sanitize-recover`), so an out-of-range write or signed overflow
  inside the app is a `sim-crash` with the sanitizer report. The release build runs seeds `0..9` for the identity check
  (§1.3), and nothing else.
* **Timeouts are FAILs** (P003 §9): the three guards above end a seed with `sim-timeout` (kind: virtual, steps, real),
  never with a skip. A hang in the host is caught by the action timeout and reported as `sim-timeout` by the judge.
* **Soak sizing rule (derived, not chosen).** For every fixed-capacity counter the product declares in `sim.toml
  [soak.capacity]` (name, bound, event it counts), the soak must be long enough to exceed `2 * bound` events at the
  production rate; the judge refuses a shorter soak (`soak-too-short`). For the snapshot pool of §5.3: bound
  `2 slots * 65535 = 131,070` uploads, rate `1440` per day at `sync_interval_secs = 60`, so the death comes at
  `131,070 / 1,440 = 91.0` days and the 400-day soak sees `576,000` uploads, 4.4 times the bound.
* **Costs [P]:** one simulated day is about `10^4` to `10^5` simhost steps (visits are a few hundred events, the rest is
  idle time that `simhost` jumps over), so a san shard of 20 seeds should take seconds. The 400-day soak is about `10^7`
  steps (576,000 sync ticks times a handful of steps), minutes under san. T2G9 measures both on RE and replaces these
  numbers; the budget table is then a ratchet that may only go down without orchestrator sign-off.

### 1.8 Reporting to `rigor grade`

New gate **`sim`** (and the sibling **`oracle`**, §3.4), placed after `fuzz` in `gate/order.txt`. NOT_RUN under the same
conditions as `fuzz` (no clean release results, `toolchain` not passed). The mechanics copy `docs/fuzz.md`:

* `rigor grade` builds every `c_sim` target's shard outputs and collects them into a flat results directory:
  `index.json` = `{"<target>": "<id>"}` and per id `<id>.stats.json`, `<id>.verdict`, `<id>.report`, `<id>.hashes`
  (one `seed trace_hash final_hash` line per seed, sorted), and on failure `<id>.failure.trace` (the last 200 trace
  lines before the first violation, capped at 64 KiB; a reproducer is `seed + salt id`).
* `rigor sim --results DIR --policy P.toml --spec S.toml --facts DIR --salt-id H [--regressions R.json] --out F`
  judges. Exit 0 PASS, 1 FAIL, 2 on any malformed input (unknown key, stray file, a result for something that is not a
  `c_sim` target of the facts, a policy module without facts), like `rigor fuzz`.
* The **judge recomputes** what it can and trusts nothing the runner says about itself: it recomputes the seed list from
  salt and binary hash and requires `seeds_done == N` and the hash file to name exactly those seeds; it recomputes the
  required budget from the policy and the tier, never from the product; it checks that every invariant id of the
  gate's catalogue appears in `stats.invariants` with `checked > 0` (non-vacuity) and `violated == 0`.
* **Findings** (`rule`, with fields): `sim-invariant-violated` (`invariant`, `seed`, `step`, `at_ms`, `detail`),
  `sim-nondeterministic`, `sim-model-divergence`, `sim-crash` (`seed`, sanitizer report digest), `sim-deadlock`,
  `sim-timeout` (`kind`), `sim-vacuous`, `fault-not-observed`, `sim-module-unreached`, `sim-module-unexercised`,
  `sim-seeds-short`, `soak-assertion` (`assertion`, `day`), `soak-too-short`, `sim-missing-target` (a policy
  `[sim] required = true` product without a `c_sim`), `sim-stats-counter` (a runtime counter that must stay 0, §2 I13).
  Volatile data (wall time, sanitizer addresses) lives only in `metadata`.
* **Verdict binding.** `core.inputs` gains `sim_spec_sha256`, `sim_salt_id` (sha256 of the salt, never the salt),
  `sim_seed_digest` (sha256 of the sorted `<id>.hashes` of all shards) and `tier`. So the verdict commits to which seeds
  ran and what they did, and `rigor verify` can refuse a verdict graded with another salt or spec.
* **Policy** (`products/<p>/policy.toml`, new table; gate-owned): `[sim] required = true`, `target = "//apps/lockers/lkapp/sim:lockers_sim"`,
  `profiles = ["wiring", "ui", "safety"]` (modules that must be exercised), seed and soak minimums per tier (the numbers
  of §1.7), and the `[soak.capacity]` rows. P003's ordering rule applies: the profiles `wiring` and `ui` lose their
  mutation gate only in the commit that turns `sim` and `oracle` on (and W9 is merged).

---

## 2. The invariant catalogue

Every invariant is a pure predicate over the gate trace (`sim/trace_fmt.h`): a sequence of records with a virtual time
`t` (ms), a kind and fields. Each has an id, an *antecedent* (for non-vacuity), an observation point in the C code, and a
canary (a bad driver, §5.1). Constants come from `sim.toml` and trace to `docs/lockers/hardware-safety.md`:
`PULSE_CAP_UNITS = 8` (800 ms), `GAP_MS = 300`, `WATCHDOG_MARGIN_MS = 150`, `WATCHDOG_CAP_MS = 900`, `BURN_MS = 1000`.

Record names used below: `ev` (event taken by rx, with type and `corr`), `fx` (effect executed), `fr` (a frame on the
wire: direction, bytes decoded by the engine, `t`), `io` (simfs operation), `vw` (view published), `st` (stats).

### 2.1 Relay and wire (hardware safety; observed on the wire tap)

| Id | Predicate (every run, every seed) | Antecedent | Observed in the C code |
|---|---|---|---|
| **I3** one coil pair | At every instant the engine's model has at most one *energised locker* (row coil and column coil both on) and at most two coils on. The model turns a coil on at a flash-on frame and off at `t + units*100 - 30 ms .. + units*100` (the board's early-off window, `board.h` Flash) or at an all-off frame or a coil read showing it off. Any FC05 `0xFF00` or `0x5500` frame, any FC05 at `0x00FF` with `0xFF00`, any FC05 below `0x0200` with value `0xFF00`, any FC0F with a set bit: violation (**no ON frame ever**, rules 1 and 5) | a flash-on frame | wire: `apps/lockers/relay/driver` through `lkadp/relaytcp` onto the simnet lane of `lksim/board`; board cross-check: `lkboard_violations()` empty |
| **I4** pulse cap | Every flash-on frame has duration units in `1..PULSE_CAP_UNITS` (0 is rejected, 9 or more is a violation) | same | wire (`relay/pulse` is the producer) |
| **I5** read-off, pulse, verify-off, gap | Per flash-on frame at `t_f`: there is a coil read (FC01) in the same flight at `t_r < t_f` whose reply shows all 30 coils off (rule 3 "before each pulse"); after the pulse there is a coil read showing all off at `t_v` with `t_v <= t_f + WATCHDOG_CAP_MS + frame deadline`; the next flash-on frame of *any* locker is at `>= t_v + GAP_MS`. A flash-on while a previous flight has no verified-off yet is a violation | same | wire. In C: `relay/opener_sm` + `relay/driver` (the single opener queue, `runtime.h` O1) |
| **I6** watchdog | If any coil read after a flash-on at `t_f` shows a coil on at `t >= t_f + min(units*100 + WATCHDOG_MARGIN_MS, WATCHDOG_CAP_MS)`, an all-off frame (FC05 `0x00FF` value `0x0000`) is sent at `t_w <= t_f + WATCHDOG_CAP_MS`; and **independently** no coil is on in the model for `>= BURN_MS` (the model is fed by wire bytes only, so a stuck coil the app never read still counts) | a flash-on under `relay_stuck_coil` or `relay_late_reply` | wire; `relay/opener_sm` watchdog branch. **[V]** `hardware-safety.md` note N7 says Rust and C send the all-off when a completed read returns, which can be after the deadline; T2G3 must measure whether the C opener meets `t_w <= t_f + 900` under `relay_late_reply`. If it cannot, the invariant stays as written and the finding is a product defect for the owner, not a threshold to loosen |
| **I6b** safe frames | Every frame the kiosk sends is in the gate's own allow-list: slave id 1, FC01 read of 1..30 coils, FC03 read of address `0x8000` or `0x4000`, FC05 flash-on `0x0200..0x021D` with valid units, FC05 `0x00FF` value `0x0000` (all off), valid CRC. Anything else is a violation. (The allow-list is a gate file written from `hardware-safety.md`, not copied from `relay/frame_is_safe`.) | any frame | wire |

### 2.2 Visits and storage (the double pulse and the lost reservation)

| Id | Predicate | Antecedent | Observed in the C code |
|---|---|---|---|
| **I1** one open per authorisation | Every `fx cmd_open` has a unique `corr`, and a distinct *authorising* `ev` before it: `staged` (visitor visit) or the shift reactor's inspection request, consumed by it. Between two `fx cmd_open` there is an `ev open_result` for the first, and a new authorising event after the first `cmd_open`. Hence **at most one `cmd_open` per staged visit.** A second `cmd_open` without a new `staged` is the double pulse. Also on the wire: the number of distinct flights (I5) equals the number of `cmd_open` that reached the driver | a `staged` event | rx cascade in `lkapp/runtime/src/core.c` (C3 instant loop) and effects in `lkapp/runtime/src/effects.c` C4 `cmd_open` post; reactors `lkrx/visit` and `lkrx/fold_core/src/session.c`. **[V]** T2G4 reads `visit.h` (V-rules, OPENING/PULSE) and the shift rules for every legitimate re-open (is a retry after `open_failed` a new `staged`?) and records the exact authorising events in `sim.toml [inv.I1]`; the predicate is not loosened beyond what `visit.h` states |
| **I2** durable save before open | At the virtual time of every flash-on frame for locker L (the frame, not the command), the **durable image** of the book file on simfs decodes (with the product's `lk/booktext`, validated by P1 against Rust) to a book in which L is reserved by the visit being opened. "Durable" = written, fsynced and renamed per `lkadp/bookfile`'s sequence, as the simfs op log shows; a power cut at that instant would have kept it | a flash-on frame for a visitor visit | `lkapp/runtime/src/effects.c` C4 `cmd_book_save` -> `lkadp/bookfile` -> simfs; wire tap for the frame. In C: `visit.h` "save BEFORE open" |
| **I9** crash consistency | After every `world_crash_restart`: the book decoded from the durable image equals the book of the last `book_saved` result before the cut (or the previous durable book when the cut tore a write), the audit file is a prefix-valid JSONL whose `seq` increases by 1 with no gap, and the boot path runs (`app_started`) before any `cmd_open` | a power cut | simfs durable image; `lkadp/bookfile`, `lkadp/auditfile` |
| **I10** audit | Audit `seq` strictly increases by one; every `door_opened` has an earlier `locker_assigned` and `cmd_open` for the same locker; the retained bytes stay within the configured bound; at most one `door_opened` per `cmd_open` | audit lines | simfs op log of the audit file; mapping in `runtime.h` A-rules |
| **I15** liveness | No session phase other than IDLE lasts longer than its screen timer plus `slack` (choose 30 s, opened 8 s, lockout and report per `docs/lockers/ui-rules.md`; `slack = 2 * 250 ms` tick + one flight 2 s); after a relay fault clears, `welcome` is reached within `relay_probe_period + 5 s`; the end-of-run drain ends in IDLE with no notice. A kiosk stuck in OPENING or on a fault screen forever is a violation | any visit | `vw` stream (C5) plus `ev` for phase changes (`fold_core/src/session.c`) |

### 2.3 UI rules over every trace (`docs/lockers/ui-rules.md`, AGENTS.md rules 1 to 3)

| Id | Predicate | Antecedent | Observed in the C code |
|---|---|---|---|
| **I7** view schema and rules | Every `vw` snapshot parses under the **closed** schema of `vstate.h` "CANONICAL FORM" (unknown key, unknown enum text, float, whitespace: violation). `screen` is in the closed set; **no full-screen message** (a message exists only as `notice` or `banners`, which sit over a screen); every `notice` has `dismiss` not `none`; a notice with a countdown shows `countdown_ms` non-null and positive; every banner has a dismiss intent; banner ids ascending; `lang` is `bg` or `en`; after idle (I15 timer) `lang` equals the configured default; every `phrase` is in the product catalogue and has a non-empty `bg` text (read from `lkui/catalog`; I7 does not check fit, that is W9) | a published view | scene publication in `lkapp/runtime/src/core.c` C5: `lk_view_canonical` over `view2.v1` (`lkrx/vstate`) |
| **I8** dismiss works | Metamorphic: for every `vw` with a notice, the engine re-runs the trace prefix on a fresh world (deterministic), applies the notice's dismiss intent, runs 1 tick, and requires `notice` null or a different notice, and the screen unchanged under it; and "dismiss vs countdown end give the same ViewState" (design P7). Evaluated on a sample (every 50th notice) to bound cost | a notice shown | `world_apply(dismiss)` through `lkrt_ui_post`, reactor `lkrx/notice` |

### 2.4 Capacity and long run (nightly soak)

| Id | Predicate | Antecedent | Observed in the C code |
|---|---|---|---|
| **I11** snapshots keep arriving | The simulated sync server records every snapshot it receives with its `taken_at`. While the sync link has been healthy for the last `3 * sync_interval_secs` and the book changed since the last accepted snapshot, `now - latest_snapshot_taken_at <= 2 * sync_interval_secs + fault_allowance`. Also: an upload carries a snapshot (`snapshot_blob != 0`) whenever one was asked for; an "events only" upload when a snapshot was requested is counted and bounded by the number of injected faults (zero by default) | a sync upload | `lkapp/runtime/src/effects.c` C4 `cmd_sync_upload` (the silent degrade: "otherwise the blob is released and the command is posted with snapshot_blob = 0"), `lkapp/wire/src/snapshot.c`, `lib/ds/blob` -> `lib/ds/pool`; `lkadp/synchttp` |
| **I12** capacity gauges | No fixed-capacity counter saturates or retires: for every row of `sim.toml [soak.capacity]` the gauge read through `world_stats` stays below `bound` (pool free slots equal pool capacity whenever idle; `pool_alloc` never returns false while `pool_used < cap`, the exact retirement signature in `pool.h`); audit log bytes within bound; `tlog` sequence not within `2^20` of wrap; `elog` drops of durable events zero | any run | `lib/ds/pool` (`pool_used`, `pool_cap`; a gauge to be added), `lib/rt/elog`, `lkadp/auditfile` |
| **I13** impossible counters stay zero | `rx_push_lost`, `result_lost`, `net_full`, `no_free_blob`, `opener_full`, `runaway`, `scene_failed` are zero at the end of every seed, and `rx_faults` is zero except under the faults documented to cause them (list in `sim.toml`). These are the runtime's own "impossible by design" counters (`runtime.h` C1 to C5) | any run | `lkrt_stats` in `lkapp/runtime/src/{core,opener,net}.c` |
| **I14** identity | Same seed twice: equal trace and state hash; release and san hashes equal on seeds 0 to 9; 200 seeds, 200 distinct hashes (§1.3) | every seed | runner only |

Not in the catalogue on purpose: "no trap" is covered because every seed runs under san with `-fno-sanitize-recover`
(a trap or UB report is `sim-crash`); string fit is W9; golden frames are W9/P004.

### 2.5 How the engine itself is trusted

The engine (`sim/inv`) is gate C code under the same rules as `ctest` (pure, static memory, tested through its public
header, mutation-tested, `symbols` allow-list) and has three calibration inputs, all gate-held:

* **Positive control from real hardware:** the frame log of the real board in club-apps
  `tools/conformance/fixtures/real-board-2026-10-07.json` (healthy one-shot flashes) and the simulator's
  `sim-docker-2026-10-07.json`, converted by a gate script into `fr` records, must PASS I3 to I6b. This ties the
  independent model to the real device, not to our simulator.
* **Negative controls:** hand-built frame traces for each violation (a plain ON, two energised lockers, a 9-unit pulse, a
  flash before verified-off, a gap of 299 ms, a stuck coil with no all-off at 901 ms), each must fail with the exact
  rule. Boundary pairs (299 / 300 ms, 8 / 9 units, 899 / 901 ms) pin the constants.
* **Seeded bad drivers** (§5.1) at whole-app level.

---

## 3. `oracle`: Rust trace replay

### 3.1 What is compared and why this layer

P2 of the plan: the Rust `viewmodel/lockers` driven by scripted fake ports gives, per step,
`{intent | port reply | tick} -> ViewState` and the port calls it made. The C app replays the same inputs through the
**real wiring on `simhost`** (`runtime` + folds + reactors + `view` + `vstate`), so the replayer is the app, not a
re-implementation of it. This layer compares the *behaviour of the state machine*; relay frames are compared elsewhere (P5:
`tools/conformance/fixtures`, 77 exchanges, frame for frame, an orchestrator step; and the wire invariants of §2.1).

### 3.2 The Rust side: producer (club-apps tasks T2C1 and T2C2)

Today the Rust fakes exist only as private `#[cfg(test)]` code inside `viewmodel/lockers/src/spec_scenarios.rs`
(`FakeClock`, `FakeCodes`, `FakeStore`, `FakeOpener`, ... [M]) and `ViewState`
(`viewmodel/lockers-state/src/lib.rs:184`) has no serialiser. So the dump is a **new tools crate**,
`tools/vm-trace`, built by Buck2, depending on `viewmodel/lockers`, `viewmodel/lockers-state`, `ports/lockers` and
`domain/*` and on no third-party crate (the canonical JSON is written by hand, in the exact form of
`lkrx/vstate/vstate.h`; `viewmodel` and `ports` stay free of serde and of the tool).

* **Format** (`vm-trace/1`, JSON lines, one file per scenario, LF only, compact, keys in the order shown):
  ```
  {"k":"cfg","v":"vm-trace/1","id":"...","src":"<club-apps sha>","seed":N,"start_ms":N,"lang":"bg",
   "inventory":{"sizes":[...],"lockers":[{"id":N,"size":N,"row":N,"col":N}]},"codes":[{"code":"123456","role":"visitor"}],
   "pulse_units":5,"min_free_mb":N,"offline_age_ms":null}
  {"k":"in","t":N,"op":"digit","d":3}      also: backspace, submit, scan{text}, choose{size}, cancel, dismiss{intent},
                                           dismiss_report, ack_opened, lang{bg|en}, tick{adv_ms}, set_codes_offline,
                                           fail{port,count,err}   (arms the next `count` calls of a fake port)
  {"k":"fx","t":N,"port":"opener.open","row":N,"col":N}   one line per port call made while handling the input, in call
                                           order; ports: opener.open, store.save, store.load, audit.append{kind},
                                           codes.role_of, coils.read, volume.free_mb, sync.note
  {"k":"vw","t":N,"s":{...canonical ViewState...}}       after the input (and after its fx lines)
  ```
  `s` is exactly the canonical text `lk_view_canonical` produces for the equivalent `lk_view_t`
  (`{"screen":S,"lang":L,"countdown_ms":C,...,"notice":N,"banners":[...]}`), so the byte comparison needs no mapping layer;
  durations are integer milliseconds; locker, size and fault names are the `LKS_*`, `lk_fault_name` and `LK_DOOR_*` texts
  already used by `vstate.h`. Where a Rust variant has no C text, T2B7 reports it and a business-apps task adds it to the
  C closed set; the Rust side never invents a Rust-only name.
* **Scenarios**: (a) the 10 cases of `spec_scenarios.rs` as scripted traces; (b) a scenario DSL file format and the other
  Rust tests re-expressed where P3 says a Rust test "becomes a P2 scenario"; (c) seeded random intent and fault
  sequences: **at least 10,000** (P001 P2), generated from a seed range given as a CLI argument (the tool has no default
  range). The generator is a small deterministic PRNG in the tool (no `rand` crate).
* **Determinism**: running the tool twice gives byte-identical files; `manifest.json` lists `{file, sha256, steps}` and the
  club-apps commit.
* **Visible vs hidden**: the orchestrator runs the tool on sb-ws with two seed ranges. Range A (public) is committed into
  business-apps as product test data `parity/p2/` (small files: about 1,000 sequences plus the 10 scripted cases; anyone can
  regenerate it). Range B (about 9,000 sequences) goes to the gate-held bundle `products/business-apps/oracle/` outside
  implementers' reach, bound by hash exactly like the witness bundle (`docs/witness.md` "Bundle format": `oracle.toml` plus
  `files/`, sha256 into the verdict, defects are exit 2). Agents never receive range B or its seeds; the tool refuses to run
  without an explicit `--seed-range`, and the range is chosen by the orchestrator.

### 3.3 The C side: replayer (business-apps task T2B7)

`apps/lockers/lkapp/sim` gains `oracle` mode: the **same world** (§1.2) with the ports that Rust faked replaced by scripted
ones, so a port reply of the trace becomes the corresponding C injection:

| Rust port outcome in the trace | C injection |
|---|---|
| `store.save` / `store.load` error class | simfs fault on the book path (`io_error`, `disk_full`) |
| `opener.open` result (`Ok`, `Err(kind)`) | a scripted opener step that answers the `cmd_open` with `open_result{fault}` (the relay driver is **not** in P2; its frames are P5) |
| `codes.role_of`, codes service failure | the codes slice fed by `codes_loaded` / offline events as the net step would |
| `audit.append` error | simfs fault on the audit file |
| `coils.read` | `relay_status` event |
| `volume.free_mb` | `disk_status` result |
| `tick{adv_ms}` | `simclock_advance`, then run to quiescence, one 250 ms tick at a time |

Each Rust outcome with no honest C injection is listed in `products/business-apps/oracle-excluded.toml` (`trace_id`,
`reason`, decision id), a gate file that is a ratchet: it may only shrink without orchestrator sign-off.

**Settling rule.** Rust handles an intent synchronously (blocking port calls); C handles it as a chain of instants that
`runtime.h` C3 and the design's "instants jump the queue" rule make equivalent. So after each `in` line the replayer
runs the core step until `rx_pending == 0` and the opener inbox is empty, with virtual time *not* advanced, and only then
reads the published view. (If OPENING waits on the scripted opener, the scripted answer is delivered inside that
settle.) A step that does not settle within `LKRT_CORE_MAX_INSTANTS * 4` core steps is `oracle-no-settle`.

### 3.4 What "equal" means, and the judge

For each trace and each step, after the gate-owned normalisation table (`products/business-apps/oracle-normalise.toml`):

1. the `vw.s` text is **byte-identical** (compared with `trace_first_diff`; no JSON-level tolerance);
2. the ordered list of `fx` lines equals the Rust list, where the C side's `fx` are the adapter calls the runtime made in
   effect order (`runtime.h` C4: "an effect never overtakes an earlier one"), mapped to the Rust vocabulary; and the number
   of steps is equal;
3. time behaviour is equal: `countdown_ms` values match after the table's rounding row (below).

The **normalisation table** starts **empty** and every row needs a decision id and a reason; rows can only be removed
without sign-off. Candidates already visible in the sources, each to be decided when first hit, not now: the 250 ms tick
quantisation of `screen_countdown` versus Rust's per-`tick()` countdown, audit `at` (dropped, as P5 does), and the
`locker` field of faults where Rust has `Option`. A row is **never** added to make a trace pass without an entry in
business-apps `docs/decisions.md` (D8: Rust wins unless the decision says otherwise).

`rigor oracle --bundle DIR --results DIR --policy P.toml --out F`, gate `oracle` (merge tier, P003 §11): the replayer
runs as one `c_sim`-style action over the hidden bundle (and the visible one: a product test runs it too, so an
implementer sees the same diff); results `<id>.report` with one line per diverging trace: `trace_id step first_diff_line
byte rust_text c_text`. Findings: `oracle-divergence` (trace, step, line, byte), `oracle-no-settle`, `oracle-bundle-missing`
(a policy trace id not in the bundle), `oracle-count-short` (fewer traces replayed than the bundle holds),
`oracle-excluded-grew`. A divergence is a FAIL; a Rust bug faithfully reproduced is not found (accepted cost, P003 §14).

---

## 4. Tiers, results and the order of landing

| Tier | `sim` | `oracle` |
|---|---|---|
| Lane (`tools/lanes`) | `rigor sim --lane`: 20 public seeds + regressions, san | visible corpus (a product test) |
| Merge | 200 seeds, hidden salt, identity, coverage floors | visible + hidden corpus |
| Nightly | 2,000 seeds, 400-day soak, 3 crash-storm seeds | same |
| Release | the nightly PASS on the exact commit | same |

`tier` is already one string in `grade_tier.tier_of` (T137); T2G6 adds the rows to the table in `docs/grade.md`
("Grade tiers") and nothing else; it does not invent a second mechanism.

**Order.** The gate side lands first (T2G1 to T2G5) against a **fixture product** (`selftest/sim`, a ~300-line toy
"locker with a relay" with deliberate bugs), so the gate is proven before the real product has a world. The real
`lkapp/sim` world (T2B2 to T2B5) then plugs in. W8 acceptance (§5.4) is the last step.

---

## 5. Historical canaries: the two defects W8 must turn red

### 5.1 Two kinds of canary

* **Synthetic (fast, `selftest/sim` and `canaries/sim-*`)**: seeded bad drivers on the fixture product, one per
  invariant and per coverage floor (`double-pulse`, `plain-on`, `two-coils`, `no-save-before-open`, `no-verify-off`,
  `gap-299`, `pulse-9-units`, `watchdog-901`, `stuck-phase`, `full-screen-message`, `notice-without-dismiss`,
  `pool-retires-at-3`, `sim-checks-nothing`, `nondeterministic-clock`, `unreached-module`). P003: every new gate ships
  at least one canary that must turn it red.
* **Historical (slow, on the real product, `canaries/hist-*`)**: the real defect is re-introduced into the real product at
  a pinned commit by a gate-held patch and `sim` (and `oracle`) must FAIL with the named rule. P003 W8 asks for
  exactly this: "the pool retirement and GAP-V2 reproduce as FAILs on the commits that had them".

**Why a patch and not a checkout of the old commit.** At the commits where the defects lived there was no `c_sim`
harness (intro, point 1). A historical canary therefore takes a *base* commit that has the harness (the first business-apps
commit with `apps/lockers/lkapp/sim` merged, chosen at T2G9) and applies a **regress patch**: the reverse of the fix,
restricted to the hunks of the defect. `tools/hist_canary.py verify` proves provenance: every hunk of the patch is, up to
line numbers, the reverse of a hunk of `git diff <fix>^ <fix>` of the cited commit (so a canary cannot be invented),
`git apply --check` passes on the base (otherwise the canary is `stale` and the pack fails closed), and the base without
the patch is the control (green). Layout: `canaries/hist-<id>/{pin.toml, regress.patch, expect.json}`;
`pin.toml` has `product`, `base`, `bug_commit`, `fix_commit`, `paths`.

### 5.2 GAP-V2: the double pulse

* **Defect.** A stale second pre-save `book_saved` while the session is OPENING/PULSE made the visit reactor emit a second
  `cmd_open` (a second door pulse for one visit). Found by a test author reading the Rust viewmodel (L216, tests only),
  not by mutation (omission: mutation rates code that exists, P003 §1.3).
* **Commits (business-apps), verified with `git log`/`git show`:**
  * `b344d10` (L192, 2026-11-08) `lkrx/visit` header with GAP-V2 recorded; `98b822e` (L176, 2026-11-08) `lkrx/fold_core`
    implementation (session fold); `31ca6b6` (L198, 2026-11-08) `lkrx/visit` implementation. From these the defect is live in `src`.
  * `678a992` (L246) runtime and `8b11f02` (L262) wire: from here the whole chain from UI to opener exists; both are
    ancestors of the bug commit below.
  * `60830d1` (L216, 2026-11-08) tests that fail on purpose; task `plan/tasks/L216-shift-visit-gaps-tests.md`, item 5.
  * **Bug commit: `b2f250d`** (= `d7a4563^`): the last commit with the defect in `src` (the header already says "CLOSED", the L216 tests are red).
  * **Fix commit: `d7a4563`** (L222, 2026-11-08, `plan/tasks/L222-gaps-round2a-impl.md`). The GAP-V2 hunks: in
    `apps/lockers/lkrx/fold_core/src/session.c` the new `on_cmd_open` (sets `LK_OP_WAIT` after `cmd_open`), the changed
    guard in `on_open_result` (accepts `LK_OP_PULSE` and `LK_OP_WAIT`), and `case LK_EV_CMD_OPEN: on_cmd_open(s)` in
    `rows_scan`; and in `apps/lockers/lkrx/catalog/src/wiring.c` the first hunk (`LK_EV_CMD_OPEN` added to the session
    fold's input list). The other hunks of `d7a4563` (GAP-F, GAP-S4, GAP-H, GAP-V1) are not part of this canary.
* **How the gate reproduces it.** The canary patch removes those hunks. Reaching the bug needs a second `book_saved` for
  the same visit while OPENING. The generic fault set does not produce one by itself (the mailbox delivers each result
  once), so the `stale_result` fault of §1.4 is what makes the run reach it: a `book_saved` replayed 1 to 200 ms after the
  first. With the fix the fold ignores it (sub-phase `LK_OP_WAIT`); without it a second `cmd_open` is emitted, **I1** fails
  (`sim-invariant-violated`, second `fx cmd_open` for the same authorising `staged`), and on the wire **I5** fails too (a
  second flash-on before verified-off, or a second flight). `oracle` also: the Rust trace of the visit ignores the stale save,
  the C `fx` list differs.
* **Acceptance (T2G9):** on the base with the patch, `rigor sim` exits 1 with `I1` within the 200 merge seeds and, where the
  corpus holds a duplicate-result trace, `oracle` reports a divergence; without the patch both PASS. If no seed of the 200
  reaches it, the fault catalogue or its rate is wrong and the task fixes the **catalogue**, never the invariant or the canary.
  **[V]** Whether Rust's viewmodel can see a duplicate `book_saved` at all (the Rust app is synchronous) decides whether the
  oracle half can fire; the sim half does not depend on it.

### 5.3 Pool retirement: the "91-day pool death"

* **Defect.** `lib/ds/pool` retires a slot after 65,535 uses (`pool.h` "Generations": the slot is never handed out again so
  the 16-bit generation never wraps). The composition's snapshot pool has `LK_WIRE_SNAP_BLOBS = 2` slots
  (`apps/lockers/lkapp/wire/wire.h:278`, `src/objects.c:26` `blob_init`), one blob per snapshot upload
  (`runtime.h` C4 `cmd_sync_upload`). After `2 * 65535 = 131,070` uploads both slots are retired, `blob_take` fails and the
  runtime **silently** posts the upload with `snapshot_blob = 0` ("events only"). At `sync_interval_secs = 60`
  (default) that is `131,070 / 1,440 = 91.0` days: the kiosk keeps running and the server's snapshot goes stale.
  (`stats.no_free_blob` counts the case; nothing in the product reads it.) **[V]** T2B1 measures the real snapshot cadence
  (every sync tick, or only after a book change); the soak sizing rule of §1.7 is derived from that number, so a slower
  cadence lengthens the soak, it does not weaken the check.
* **Commits (business-apps).** `73ba467` (L012, 2026-11-07) `lib/ds/pool` header with the retirement rule; `4c3d8d3` (L014,
  2026-11-07) pool implementation (`lib/ds/pool/src/pool.c:3`); `594508a` (L037) `lib/ds/blob` on top of it; `678a992`
  (L246, 2026-11-08) runtime with `snap_blobs`; `8b11f02` (L262, 2026-11-08) wire with the 2-blob pool (the first commit in
  which the defect is reachable from the app); `e507436` (2026-11-09) the commit P003 was written against; **still live at
  `4f5e1b5` (2026-11-13)**: `lib/ds/pool` has not changed since `003b899` (2026-11-07). There is **no fix commit**.
* **How the gate reproduces it.** I11 plus I12 under the 400-day soak: from day 91 `pool_alloc` returns false with
  `pool_used < pool_cap` (I12) and the simulated server's latest snapshot ages past `2 * interval + allowance` (I11), with
  `stats.no_free_blob` growing (I13).
* **Acceptance (T2G9), two stages because there is no fix yet:**
  1. **Live-defect run:** the nightly `sim` on the first `main` that has the world must exit 1 with `soak-assertion`
     (`I11`, day 91 or 92) and `sim-invariant-violated` `I12`. That is "reproduces as FAIL on the commits that had them".
     The orchestrator records that FAIL as the expected state of `main` until T2B8 lands.
  2. **Fix task T2B8** (business-apps; options in the task; it must not weaken the stale-handle guarantee of `pool.h`). After it the
     nightly passes and `hist-pool-retire` is generated from T2B8's own diff (reverse patch; `hist_canary.py make` with
     `fix_commit` = T2B8's merge). Until then `canaries/hist-pool-retire` is `pending` (the canary pack has the `pending`
     state, `docs/canaries.md`) with `pin.toml` naming `bug_commit = 4c3d8d3`; **the pending state is itself a ratchet that must reach zero.**
* **Cheap companion (not W8):** `limits` (W9) flags the declared capacity statically; W8 is the dynamic proof and is not replaced by it.

### 5.4 The one acceptance sentence

W8 is done when (a) every row of §2 has a synthetic canary red, (b) `hist-gap-v2` is red and its control green, (c) the
nightly on `main` is red on I11/I12 until T2B8, then green, and `hist-pool-retire` is red and green likewise,
(d) the visible and hidden oracle corpora replay with zero divergence and `oracle-excluded.toml` is a reviewed, shrinking
list, and (e) the merge tier fits its budget on ten real merges (shared with W10).

---

## 6. Tasks

Numbers are placeholders (`T2xx`); the orchestrator assigns real ones. `G` = gate repo, `B` = business-apps, `C` = club-apps.
Each task is one lane. "Allowed" paths are the contract (a diff outside them is rejected whole). The rules of the task's
repo apply in full (AGENTS.md; for B tasks also `gate/AGENTS.md` and `docs/dev.md`; for C tasks club-apps `CLAUDE.md`:
Buck2 only, no cargo, never the real board).

**Dependencies.** `G1 -> G2 -> G6`; `G1 -> G3, G4, G5 -> G6`; `G7` after `G1, G2`; `G8` after `G1`;
`B1 -> B2 -> B3 -> B4 (-> B5)`; `C1 -> C2`; `B7` after `C2, B3`; `G9` after `B4, G6, G7, G8` (and `B7` for the oracle half); `B8` after `G9` stage 1.
Parallel from day one: `G1`, `B1`, `C1`.

### Gate tasks

**T2G1: `c_sim` rule, runner skeleton and `sim/world.h` (fixture product; identity and crash only).**
* *Why:* everything else needs the target kind, the runner and the trace format; identity and seed derivation are the base.
* *Do:* `rules/sim.bzl` (`c_sim`, its `_facts`, shard expansion, san and release outputs, timeouts, `cov` shard); `rules/c.bzl`
  forwards; `sim/world.h`, `sim/runner.c` (seed derivation of §1.3, run loop, virtual/step/real limits, two runs per seed,
  release-vs-san identity on seeds 0 to 9, `stats.json`, `<id>.hashes`), `sim/trace_fmt.h` (`fr` and `io` records on top of
  `lib/sim/trace`'s format; the gate repo may not depend on business-apps, so it vendors the few small parts it needs under
  `sim/` with a sha256 pin and a note, or takes a `trace` sink through `world.h`: open question 2); `selftest/sim/` fixture
  product (toy locker plus simulated relay line, ~300 lines) and `selftest/sim.sh`; `rigor buckfiles` accepts `c_sim`.
* *Not:* invariants, the judge, grade wiring, tiers, the real product.
* *Acceptance:* `selftest/sim.sh` twice in a row. The fixture shows: 200 seeds PASS in the runner; a nondeterministic variant
  (reads a real clock through a port the world exposes) gives `sim-nondeterministic` in the runner's stats; a UB variant gives
  `sim-crash`; a step-limit variant gives `sim-timeout`; `selftest/gate.sh` still passes; canaries `nondeterministic-clock`,
  `sim-crash`, `sim-timeout`.
* *Allowed:* `rules/sim.bzl`, `rules/c.bzl`, `sim/**`, `selftest/sim/**`, `selftest/sim.sh`, `docs/sim.md` (new), `gate/tests/test_sim_*.py`, `canaries/sim-*/**` (and the canary catalogue file if one lists them).

**T2G2: the judge `rigor sim` and its grade wiring.**
* *Why:* `sim` has to be a gate with a verdict binding, not a script.
* *Do:* `gate/rigor_lib/sim_judge.py`, `grade_sim.py` (collect, like `grade_fuzz.collect`), the `rigor sim` subcommand; policy parser for
  `[sim]` and `[soak.capacity]`; salt handling (`--sim-salt`, public salt file, `sim_salt_id`), seed recomputation, budget by tier,
  regressions file, the findings of §1.8, `sim` in `gate/order.txt` after `fuzz`, NOT_RUN conditions, `core.inputs` additions
  (`sim_spec_sha256`, `sim_salt_id`, `sim_seed_digest`), `rigor verify` prints them; rows in `docs/sim.md`, `docs/grade.md`, `docs/gate.md`.
* *Not:* invariants (the judge only requires that the stats name them), the real product.
* *Acceptance:* unit tests with synthetic result directories for every finding and every malformed input (exit 2); a salt swap changes
  the digest; `selftest/gate.sh`; one full `rigor grade` of the fixture product with `sim` PASS; canaries `sim-seeds-short`,
  `sim-vacuous` (a fixture world whose workload does nothing), `sim-missing-target`.
* *Allowed:* `gate/rigor_lib/{sim_judge,grade_sim,grade,verdict_inputs}.py` and the policy loader, `gate/rigor`, `gate/order.txt`, `gate/tests/**`, `docs/{sim,grade,gate}.md`, `products/selftest/**`, `selftest/**`, `canaries/**`.

**T2G3: wire invariants I3 to I6b and the independent frame model.**
* *Why:* the hardware-safety rules are the reason for the gate; they need an implementation that shares nothing with the kiosk's.
* *Do:* `sim/inv/wire.{h,c}`: gate-owned Modbus RTU decoder (CRC, FC01/03/05/0F), coil model with the board's flash semantics
  (`board.h` "Flash": early-off window), the five predicates, constants from `sim.toml` each with its source line in
  `hardware-safety.md`, the board cross-check hook; unit tests through the public header with hand-built violating and boundary
  traces (299/300 ms, 8/9 units, 899/901 ms); the **positive control**: `tools/sim/fixture_to_fr.py` converting the club-apps
  `real-board-2026-10-07.json` and `sim-docker-2026-10-07.json` (copied read-only into `selftest/sim/data/` with sha256 and a
  source note; check that no real LAN address is in them) into `fr` records that PASS. Zero unexplained mutation survivors.
* *Not:* event and view invariants; wiring into a world.
* *Acceptance:* the module's tests and mutants through `tools/buck2`; both fixtures PASS; each negative trace FAILS with the right id.
* *Allowed:* `sim/inv/**`, `selftest/sim/data/**`, `tools/sim/**`, `policy/**` (sim constants file), `docs/sim.md`.

**T2G4: event and storage invariants I1, I2, I9, I10, I15.**
* *Why:* the double pulse and the lost reservation.
* *Do:* `sim/inv/events.{h,c}` over `ev`, `fx`, `io`, `fr`, `vw` records: authorisation matching for I1 (names from `sim.toml [inv.I1]`),
  durable-image check for I2 (through a `book_decode` callback supplied by the world, because the book format is the product's; the
  callback is named in the policy and is itself covered by P1), crash consistency, audit chain, liveness timers from `sim.toml`;
  hand-built traces and fixture bugs `double-pulse`, `no-save-before-open`, `stuck-phase`.
* *Not:* UI invariants; the product's rule list (T2B3 proposes it, the orchestrator copies it into `sim.toml`).
* *Acceptance:* as T2G3; the three fixture bugs red with the exact id and step; the correct fixture green over 200 seeds.
* *Allowed:* `sim/inv/**`, `selftest/sim/**`, `canaries/sim-*/**`, `docs/sim.md`.

**T2G5: UI invariants I7, I8 and the closed `ViewState` schema validator.**
* *Why:* UI rules over every trace, deterministically.
* *Do:* `sim/inv/ui.{h,c}`: a strict parser of the canonical form of `vstate.h` (closed keys and enums, no floats), the I7 rules, the I8
  re-run-and-dismiss metamorphic check, phrase catalogue lookup through a callback; fixture bugs `full-screen-message`,
  `notice-without-dismiss`, `countdown-null`, `lang-not-reset`.
* *Not:* text fit and goldens (W9, P004).
* *Acceptance:* as T2G3; every canary red.
* *Allowed:* `sim/inv/**`, `selftest/sim/**`, `canaries/sim-*/**`, `docs/sim.md`.

**T2G6: soak, capacity gauges, coverage floors and tiers (I11 to I14, `soak-too-short`).**
* *Why:* the pool death and the non-vacuity rules.
* *Do:* soak runner mode (one seed, long run, daily checkpoints), I11 (server-side snapshot age), I12 (gauges from `world_stats`), I13,
  the sizing rule of §1.7, the coverage floors of §1.6 (antecedent counters, fault observed, screens, distinct hashes), the `cov`
  shard and `sim-module-unreached/unexercised`, tier rows in `docs/grade.md`, `--tier` handling for seeds and soak; fixture bug
  `pool-retires-at-3` (a pool that retires after 3 uses, soak of the fixture over 50 virtual days).
* *Not:* the real product, measured budgets.
* *Acceptance:* the fixture soak reds on I11 and I12 on the day the arithmetic says; a soak shorter than the rule gives `soak-too-short`;
  the merge tier runs no soak; canary `sim-checks-nothing` red.
* *Allowed:* `sim/**`, `gate/rigor_lib/{sim_judge,grade_sim,grade_tier}.py`, `gate/tests/**`, `selftest/sim/**`, `canaries/sim-*/**`, `docs/{sim,grade}.md`.

**T2G7: `oracle` gate and bundle.**
* *Why:* P2 byte-identical replay with a hidden half.
* *Do:* bundle format `oracle.toml` + `files/` mirroring `witness_bundle.py` (no symlinks, exact keys, sha256, `--oracle DIR` on
  `rigor grade`, hash into `core.inputs`); `vm-trace/1` reader (§3.2); normalisation table loader (empty by default) and the
  `oracle-excluded.toml` ratchet; `rigor oracle`; `trace_first_diff` semantics for the report; the findings of §3.4; a tiny fixture bundle
  and fixture replayer in `selftest/sim`; canaries `oracle-divergence`, `oracle-bundle-missing`.
* *Not:* producing real traces (C tasks), the real replayer (T2B7).
* *Acceptance:* unit tests with a tampered bundle (every defect exit 2); the fixture replays with zero divergence; a one-byte change in a
  trace is `oracle-divergence` at the right line and byte.
* *Allowed:* `gate/rigor_lib/{oracle_bundle,oracle_judge,grade_oracle,grade,verdict_inputs}.py`, `gate/rigor`, `gate/order.txt`, `gate/tests/**`, `docs/{oracle,grade,gate,witness}.md`, `selftest/**`, `canaries/**`, `products/selftest/**`.

**T2G8: historical canary tool.**
* *Why:* §5.1: real defects as permanent, provenance-checked canaries.
* *Do:* `tools/hist_canary.py` (`verify`; `make`: build `regress.patch` from `fix_commit` and a hunk selection, prove each hunk is the reverse of
  a hunk of the fix diff, `git apply --check` on the base), the canary layout and the extension of `canaries/runner.py` (clone the product at
  `base`, apply, run `rigor grade --only sim,oracle`, compare with `expect.json`, `pending` and `stale` states, control = unpatched base),
  a docs section; a selftest on the fixture product with its own tiny git history.
* *Not:* the two real canaries (T2G9).
* *Acceptance:* the fixture's historical canary is red and its control green; a patch whose hunk is invented is refused; a stale patch fails the pack closed.
* *Allowed:* `tools/hist_canary.py`, `canaries/runner.py`, `canaries/hist-selftest/**`, `selftest/**`, `docs/canaries.md`, `gate/tests/**`.

**T2G9: bind the real product: policy, spec, budgets and the two historical canaries (W8 acceptance).**
* *Why:* turn W8 on for business-apps and prove it on the real defects.
* *Do:* `products/business-apps/{sim.toml,sim-salt.public,policy.toml additions,oracle-normalise.toml,oracle-excluded.toml,sim-regressions.json}`;
  measure on RE the real cost of the 200-seed merge tier and the 400-day soak (seconds per shard, steps per day, uploads per day), replace the
  [P] numbers of §1.6 and §1.7, record the table in `plan/metrics/`; create `canaries/hist-gap-v2` (§5.2) and `hist-pool-retire` as `pending` (§5.3);
  run both stages of §5.3; update P003 §13.1 and `plan/HANDOFF.md`.
* *Not:* fixing the pool (T2B8) or the world (T2B*).
* *Acceptance:* the commands of §5.2 and of §5.3 stage 1 with their output; one `rigor grade --tier merge` and one `--tier nightly` of the product
  with the exact expected FAIL findings; merge wall time within budget, or a written decision to change it.
* *Allowed:* `products/business-apps/**`, `canaries/hist-*/**`, `plan/**`, `docs/{sim,oracle,products}.md`.

### Business-apps tasks (`Mivr/business-apps`; normal L-series tasks, test-author and implementer roles as that repo uses them)

**T2B1: observation taps.**
* *Why:* the checker needs taps (§1.5) that are absent from release builds.
* *Do:* `lkrt_cfg_t.tap` in `lkapp/runtime`, called for every rx event, every effect before its adapter call, every scene publication, every
  opener command and result; NULL in `lkapp/wire`'s release composition, with a guard test that the wire never sets it; `simfs` operation log and
  durable-image accessors (`lib/sim/simfs`); `simnet` lane byte tap with virtual time (`lib/sim/simnet`); a `pool_used`/`pool_cap` gauge in
  `lib/ds/pool` and `lib/ds/blob`; an `lkrt_stats` read accessor; measure and report the real snapshot cadence. Tests per module through its
  header; mutants to zero survivors.
* *Not:* any simulation world, any invariant.
* *Acceptance:* module tests and mutants through `gate/tools/buck2`; `symbols` and `layering` pass (the release composition has no reference to the tap).
* *Allowed:* `apps/lockers/lkapp/runtime/**`, `lib/sim/{simfs,simnet}/**`, `lib/ds/{pool,blob}/**`, `apps/lockers/lkapp/wire/{wire.h,tests/**}` (guard only).

**T2B2: simulated `lk_wire_io_t` (simfs, simnet, clock).**
* *Why:* the composition root takes a port bundle; there is no simulated one.
* *Do:* new package `apps/lockers/lkapp/sim` (module `simio`): `lk_wire_io_t` over `simfs`, `simnet` (board lane + endpoints), `simclock`, `simhost` osal;
  the config text of the sim app (no real address: the board address is a placeholder resolved by simnet, never a `192.168.237.` literal); tests through the header.
* *Not:* servers, the world, faults.
* *Acceptance:* `lk_wire_init` succeeds over it and the app reaches `welcome` on `simhost` in a test; the existing safety guard equivalents pass (no ON frames, no real LAN literals).
* *Allowed:* `apps/lockers/lkapp/sim/**` (new), `apps/lockers/lkapp/wire/**` only to export what the sim needs (no behaviour change), `docs/architecture.json` rows.

**T2B3: simulated servers, the world, and the `sim.toml` proposal for lockers.**
* *Why:* codes list and sync endpoint with snapshot recording (I11); the world of §1.2.
* *Do:* `apps/lockers/lksim/server` (codes worker stub with a seeded list; D1 sync endpoint recording events and snapshots with `taken_at`; HTTP and TLS as the
  adapters need over `simnet`), `lkapp/sim/world.c` implementing `sim/world.h` (until T2G1 lands, build a local copy of the header and say so; T2G9 reconciles),
  intent mapping, `world_crash_restart`, the `book_decode` callback, and a **proposal file** `docs/lockers/sim-spec-proposal.toml` (authorising events for I1 read from
  `visit.h`/`shift.h`, timers for I15 from `ui-rules.md`, capacity rows) which the orchestrator copies into the gate.
* *Not:* faults beyond what simnet/simfs already offer; invariants.
* *Acceptance:* a scripted day (no faults) of 50 visits runs on `simhost`, the sync server holds snapshots, and the same seed twice is byte-identical.
* *Allowed:* `apps/lockers/lksim/server/**`, `apps/lockers/lkapp/sim/**`, `docs/lockers/sim-spec-proposal.toml`, `docs/architecture.json`.

**T2B4: fault injection in the world and the `c_sim` target.**
* *Why:* the catalogue of §1.4 bound to the real ports, including `stale_result`.
* *Do:* `world_fault` for every kind, the seeded schedule hooks, `stale_result` re-delivery on the core inbox, power cut with torn-write semantics from simfs,
  and `apps/lockers/lkapp/sim/BUCK` with the `c_sim` target `//apps/lockers/lkapp/sim:lockers_sim`.
* *Not:* invariants (gate), oracle mode.
* *Acceptance:* each fault, injected by a test, has its visible effect (so `fault-not-observed` cannot fire); the target builds in san and release.
* *Allowed:* `apps/lockers/lkapp/sim/**`, `lib/sim/**` only for missing fault kinds (with tests).

**T2B5: board exposure for the cross-check (small; the orchestrator may fold it into T2B4).**
* *Why:* the engine cross-checks `lkboard_violations`; the board must expose them and the frame log through the world.
* *Do:* make `lkboard_violations`, `lkboard_warnings`, `lkboard_energised` and the frame log reachable from the world; test that a kiosk flash and verify sequence leaves them empty.
* *Allowed:* `apps/lockers/lksim/board/**`, `apps/lockers/lkapp/sim/**`.

**T2B6: reach gaps (conditional).** Only if T2G9 stage 1 reports `sim-module-unreached` or `sim-module-unexercised`: tests or wiring so every
`wiring`, `ui` and `safety` module is reached by the world. Not scheduled until the finding fires.

**T2B7: oracle replayer and the visible corpus.**
* *Why:* P2 on the real wiring (§3.3).
* *Do:* `oracle` mode in `lkapp/sim` (scripted opener, injection table of §3.3, settling rule), a reader for `vm-trace/1`, the product test that replays
  `parity/p2/` and prints the first diff; commit the visible corpus delivered by the orchestrator from T2C2 (**do not generate it**); report every Rust name
  that has no C text.
* *Not:* the hidden corpus; normalisation rows (a proposal is a report item, not a commit).
* *Acceptance:* the 10 scripted cases replay byte-identical, or each divergence is listed with its Rust and C text and the decision it needs; no row is added to any table.
* *Allowed:* `apps/lockers/lkapp/sim/**`, `parity/p2/**`, `docs/lockers/oracle.md`.

**T2B8: pool generation exhaustion (the fix for §5.3).**
* *Why:* the 91-day death.
* *Do:* choose and implement a design that keeps `pool.h`'s guarantee (no handle value is ever valid twice, O(1), no allocation) without losing capacity,
  for example a 32-bit generation (64-bit handle), or a generation reset when the slot provably has no outstanding handle; header contract first (test
  author), then the implementation; the handle type change ripples through `blob` and the runtime; record the decision in `docs/decisions.md`.
* *Not:* any change to what the sim or the gate checks.
* *Acceptance:* module tests and mutants; the nightly soak of T2G9 passes; `hist-pool-retire` generated from the diff.
* *Allowed:* `lib/ds/{pool,blob}/**`, the callers' BUCK files and call sites (`apps/lockers/lkapp/{runtime,wire}/**` as needed), `docs/decisions.md`.

### Club-apps tasks (`Mivr/club-apps`; Buck2 only, no cargo; contributors never touch the real board)

**T2C1: `tools/vm-trace`: recorder, trace format `vm-trace/1`, scripted scenarios.** (business-apps plan name: club-apps T183)
* *Why:* the Rust oracle has no dump (§3.2).
* *Do:* new crate `tools/vm-trace` with its BUCK, zero external crates: a world of fake ports written against `ports/lockers` and `domain/*` (not copied from the
  private test module; behaviour scripted by `fail{port,count,err}` inputs), the recorder that appends `cfg/in/fx/vw` lines, a hand-written canonical JSON
  writer for `ViewState` in the exact form of `vstate.h`, the scenario DSL (a plain line format parsed in the tool), the 10 cases of `spec_scenarios.rs`
  as scenario files, the `manifest.json` writer. Unit tests through the tool's public API; mutants to zero survivors, or a sign-off request in the report
  (never an edit of `tools/mutants-exclusions.md`).
* *Not:* the random generator, the bundle split, any change to `viewmodel` or `ports` (if a hook is needed, stop and report).
* *Acceptance:* `buck2 test //tools/vm-trace/...`; `tools/mutants.sh //tools/vm-trace:...`; two runs over the 10 scenarios give identical files and manifest; `tools/gate.sh` passes (layering: a tool may depend on viewmodel, ports and domain, never the reverse).
* *Allowed:* `tools/vm-trace/**`, workspace `Cargo.toml` members and the `tools/guards/` rows the new crate needs, `docs/vm-trace.md`.

**T2C2: seeded random traces, bundle writer, held-back range.**
* *Why:* at least 10,000 sequences, deterministic, with a hidden range.
* *Do:* deterministic generator (splitmix64 in the tool): random intents (digits, scans of valid, invalid and staff codes, size choices, cancel, dismiss, language,
  ticks of 0 to 40 s) interleaved with port faults armed through `fail`; `--seed-range A..B` required (no default), `--out DIR`, per-file sha256 in the manifest, a
  `--check DIR` mode that verifies a bundle; a generator test with a pinned sha256 of the first 100 sequences of a fixed range. **The task never generates the hidden range.**
* *Not:* choosing the ranges or touching the gate.
* *Acceptance:* `buck2 test` and mutants as T2C1; two runs over `--seed-range 0..200` give identical bytes; a mutation of the generator changes the pinned hash.
* *Allowed:* `tools/vm-trace/**`, `docs/vm-trace.md`.

### Counts

19 tasks: 9 gate (T2G1 to T2G9), 8 business-apps (T2B1 to T2B8; T2B5 may fold into T2B4, T2B6 is conditional), 2 club-apps (T2C1, T2C2).
The business-apps plan's club-apps T182 (P1 corpora), T184 (P3 test list) and T185 (P4 external binary) are not needed for W8 and are not in this package.

---

## 7. Open questions (none blocks T2G1 to T2G3)

1. **Does the C opener meet the watchdog send deadline under `relay_late_reply`?** `hardware-safety.md` N7 documents that Rust (and C) send the all-off when the
   read completes, possibly after `min(units*100+150, 900)`. I6 is written at the rule's value; if it cannot hold, the owner decides (a product change or a
   signed note), not a gate task.
2. **Sharing code between repos.** The gate repo must not depend on business-apps. T2G1 either vendors the `trace` interface it needs under a sha256 pin, or
   takes a trace sink through `world.h`; the second is cleaner but ties the runner to the product's clock type. Decide before T2G1.
3. **Hidden salt custody.** `rigor grade --sim-salt` needs a hidden file on the grader, like the witness bundle. A nightly grader on a read-only cache (G21) must receive it too.
4. **I1's authorising events.** The exact list (staged, shift inspection, any retry path) is read from `visit.h` and `shift.h` in T2B3/T2G4 and may reveal a legal second
   `cmd_open` that the predicate must model, never ignore.
5. **Stale-result realism.** `stale_result` is a robustness fault; if a duplicate result can never occur in production, GAP-V2 is still a hole in the fold (the Rust
   viewmodel tolerates it), but reports should class the finding as "robustness". No change to the predicate.
6. **Numbers.** Every [P] number in §1.6 and §1.7 is a starting point for T2G9 to replace by measurement (P003 §14 rule).
