# P003: gate v2 — cheap where C is strong, light where the evidence is weak, strong where the bugs are

Design only: no gate code, no product change, no farm run. Read against gate `ea88e09` (T123 merged), business-apps
`e507436`, `business-apps/plan/metrics/lead-time-2026-11-09.md`, and the read-only review of 2026-11-09 (gate,
lockers source, lockers tests). It implements, for C, what `ai-code-rigor/docs/rigor-levels.md` already specifies
(P5, P9, P10, §3.5, §4.1–4.4), and it delivers the planned items G12, G16, G23, G27, G28 and G29 of the lockers plans.

> **Status 2026-11-10.** T124 measured the mutation engine of §5 on five business-apps modules and the result is
> **no-go** (§5.6): the schema engine is not faster than v1 as v1 stands after T121–T123. §5.2–§5.4 are kept as the
> record of what was tried, not as the plan. Everything else stands; §13 and §14 are re-ordered accordingly.

**Evidence tags.** **[M]** measured in our own repos (path given). **[E]** published evidence (see References; ✓ =
re-checked by search on 2026-11-09, † = taken from the `ai-code-rigor` research corpus and not re-checked here).
**[P]** a proposal or a starting number, to be re-derived from data by the rule in §14. Nothing tagged [P] is a finding.

## Summary

| # | Change | Why | Tag |
|---|---|---|---|
| 1 | ~~**Mutation engine v2** (one schema object per source, linked once per test, forked per mutant, reach-filtered)~~ **Rejected by measurement** (T124, §5.6): keep the v1 engine. The cost lever is the scoped merge tier (row 9) and running report-level mutation nightly only | Mutation was 49% of agent wall time before T121–T123; the prototype was slower on 2 of 5 modules and on build wall time on 4 of 5 | [M] |
| 2 | **Profiles**: a module declares *what kind of code it is* (pure, parser, adapter, concurrent, wiring, ui, safety); the profile picks the techniques, the level picks how much | v1 levels only tune mutation; the bugs found sit in code kinds mutation does not fit | [M] [E] |
| 3 | **`rigor_require`** (gate-owned guard) with a ratcheted guard budget | The zero-survivors rule deleted a bounds check (`2975620`) | [M] |
| 4 | **Sanitizer matrix**: add `msan` and `tsan` modes; a hardened release profile | Uninitialised state and the one cross-thread primitive are untested; extra modes are cheap in C | [M] |
| 5 | **Fuzz in the verdict** (corpus replay + fixed budget on PR; long runs nightly) | 0 fuzz targets on 8 hand-written parsers | [M] [E] |
| 6 | **`c_proof` (CBMC)** for the safety profile only; also discharges equivalent mutants and unreachable guards | L4 equals L3 today; the relay modules are small and finite | [M] [E] |
| 7 | **System gates**: seeded whole-app simulation with invariants, virtual-time soak, Rust-oracle trace replay, catalogue fit, alloc-after-init trap | A double pulse, a 91-day pool death and unfittable strings passed every module gate | [M] |
| 8 | **Lowered**: no mutation gate on adapters, wiring and ui; structure caps become hygiene caps; the 400-mutant module budget goes; trajectory audit replaced by the sandbox; witness only where it pays | Size metrics do not predict defects; most adapter mutants are unproductive; detection is weaker than enforcement | [E] |
| 9 | **Tiers**: lane (seconds), merge (minutes, scoped), nightly (full, uncached), release (gate-signed) | Whole-repo zero-survivor grading on every merge is the 4.5 h of the 11.7 h | [M] [E] |
| 10 | **Trust without a human**: a check wherever one exists; otherwise a refutable claim signed by a separate arbiter identity, under a debt cap, in an append-only ledger | `gate/allowed_signers` trusts only `orchestrator`, which also requests and merges | [M] |

## 1. The evidence this design answers

### 1.1 Where the time goes [M]

`business-apps/plan/metrics/lead-time-2026-11-09.md`, 11.7 h of agent wall time over 24 tasks:

| Share | What |
|---|---|
| 49% | mutation testing |
| 23% | waiting on gate jobs |
| 14% | build |
| 13% | model |
| 5% | grade, shell, other tools |

Building C is not the bottleneck. The gate's mutation run stage is: for every live mutant and every test, the test is
relinked with the mutated object and run in a fresh process (`docs/mutate.md`, step 4). Before T121, 78,126 of about
86,800 test runs of one module ran after the mutant was already dead. The whole-repo grade is about 42k actions.

### 1.2 What v1 enforces [M]

In the verdict: ASan/UBSan/LSan on unit tests, mutation at L3+ (info at L2), default-deny symbols, structure limits,
perf classes on 2 targets. Not in any verdict: fuzz (0 targets in business-apps), CBMC, TSan, MSan, a coverage
threshold, a static analyser. `gate/rigor_lib/mutants_gate.py`: "L3, L4 and L5 are equally strict here".

### 1.3 What escaped v1 [M]

| Escape | Where | Kind of gap |
|---|---|---|
| A stale second `book_saved` emitted a second `cmd_open` (double pulse); found by a test author reading Rust | `business-apps/plan/tasks/L216-*.md` GAP-V2 | omission: mutation only rates code that exists |
| The range check in `durable()` was deleted as an unkillable guard | commit `2975620`, `lkapp/runtime/src/effects.c` | zero-survivors versus defence in depth |
| A pool slot is retired after 65,535 uses; the 2-slot snapshot pool dies after about 131k uploads | `lib/ds/pool/src/pool.c`, `LK_WIRE_SNAP_BLOBS` | long-run behaviour of a fixed capacity |
| `LVR_TEXT_MAX` is 128 bytes; three Bulgarian strings are 168, 135 and 128 | `lib/ui/lvrender/lvrender.h`, `lkui/catalog/i18n/bg/lockers.po` | cross-module contract |
| `mbox` copies outside the lock; `wire` atomics never run by two threads | `lib/rt/mbox/src/mbox.c:196,213` | concurrency |
| `rx_init` leaves two fields unset | `lib/rt/rx/src/rx.c:40-51` | uninitialised state |
| `getaddrinfo`, `fdopendir` allocate after init | `lib/io/posix_net`, `lib/io/posix_fs` | the static-memory claim stops at libc |
| `kv` is L3 and used by nothing; 23 modules are unreachable from the kiosk | review | rigor spent on dead code |

## 2. Principles (all from `ai-code-rigor/docs/rigor-levels.md`, restated for C)

1. **Independence comes from diverse methods, not diverse agents** (P5). A second Sonnet context is not a second
   opinion: independent versions fail together (Knight & Leveson 1986 ✓), and LLMs agree on the same wrong answer far
   above chance (Kim et al. 2025 ✓). v2 adds *methods* (fuzz, proof, simulation, oracle replay), not reviewers.
2. **Zero unexplained survivors in a defined scope, never a score** (P9). Kept. The scope is narrowed to code where a
   mutant is a meaningful question (§4).
3. **Size metrics are hygiene caps** (P10). Kept as caps, removed as evidence.
4. **Spend machine time where it finds defects per CPU-second** (§3.5). Timeouts fail; budgets are fixed.
5. **Bugs sit at the boundary of what is checked** (Fonseca et al. 2017 ✓: all 16 bugs in three verified systems were
   at the interface to unverified code). So the boundary gets its own gates (§7) instead of more unit rigor.
6. **Enforce, then detect.** A sandbox the agent cannot leave replaces a transcript audit that guesses what it did.

## 3. The C strengths v2 exploits

| Strength of C here | How v2 uses it |
|---|---|
| One edit recompiles one translation unit in milliseconds; 2 CPU-s per core edit against 48 for tuned Rust (`lang-bench/REPORT.md`) [M] | Per-mutant standalone compile stays (TCE is nearly free); two more build modes (`msan`, `tsan`) and a hardened release cost little |
| Static, tiny, runtime-free binaries that start in microseconds; no heap | `fork()` per mutant from a warm test process; thousands of simulation seeds per second; a year of virtual time in one nightly run |
| Static memory: bounded state, no heap model | CBMC stays tractable; fuzzing is deterministic; exhaustive enumeration is often a proof; a RAM budget is a constant |
| Object code identity is meaningful | TCE for equivalent and duplicate mutants (kept); bounded equivalence proofs for the rest |
| One pinned LLVM carries ASan, UBSan, MSan, TSan, libFuzzer and source-based MC/DC | All become build modes of the same sealed macros; no second toolchain |
| Symbols are visible to `llvm-nm`, and the allocator can be interposed at link time | Default-deny symbol policy (kept); the alloc-after-init trap (§7.7) |

## 4. Profiles and levels

`policy.toml` gets one more key per module: `profile`. The **profile** says what kind of code it is and therefore
which techniques apply. The **level** (L1–L4, unchanged meaning: risk) says how much of each. A module without a
profile is `level-missing`-style error `profile-missing`. Profiles are gate-owned; changing one is a policy change (§10).

| Profile | Code | Examples (business-apps) |
|---|---|---|
| `pure` | Domain rules, containers, encoders, folds, reactors: no IO, no threads | `lk/*`, `lkrx/*`, `lib/ds/*`, `lib/rt/rx`, `lib/ui/scene*` |
| `parser` | Anything that reads bytes it did not write | `lib/fmt/j*`, `http*`, `url`, `mbrtu` decode, `lk/config`, `lk/booktext` |
| `adapter` | Thin code over a syscall or a third-party library | `lib/io/posix_*`, `tls_stream`, `lvrender`, `lkadp/*` |
| `concurrent` | Code shared between threads | `lib/rt/mbox`, `lib/io/osal`, `lkapp/wire` host |
| `wiring` | Composition: tables, roots, shells, effect dispatch | `lkapp/runtime`, `lkapp/wire`, `catalog/wiring`, `shell_linux` |
| `ui` | Layout and text | `lkui/*`, `lib/ui/uikit` |
| `safety` | Code whose failure moves hardware | `relay/*`, `mbrtu` encode |

A module may carry two profiles (`parser` + `pure`); it then gets the union.

### 4.1 Technique matrix

`●` gates the verdict, `○` is reported, blank is not run. "merge" and "nightly" are the tiers of §9.

| Technique | pure | parser | adapter | concurrent | wiring | ui | safety |
|---|---|---|---|---|---|---|---|
| Tests in `release` and `san` (ASan+UBSan+LSan) | ● | ● | ● | ● | ● | ● | ● |
| `msan` mode | ● | ● | ○ | ○ | | | ● |
| `tsan` mode on real-thread tests | | | | ● | ● | | |
| Mutation, zero unexplained survivors | ● L3+ | ● L3+ | ○ | ○ | | | ● |
| Pseudo-tested functions = 0 (body replaced, tests still pass) | ● L2+ | ● L2+ | ● L2+ | ● | ● | ● | ● |
| Model or property test present | ● L3+ | ● (round trip) | | | | | ● |
| Fuzz: corpus replay + fixed budget | | ● | ● if it parses | | | | ● (decoders) |
| Fault-injection sweep over every port call | | | ● | | | | ● (driver) |
| Real-OS tests | | | ● | ● | | | |
| `c_proof` (CBMC): no undefined behaviour on the public API | | ○ L3, ● L4 | | | | | ● |
| `c_proof`: stated safety properties | | | | | | | ● |
| MC/DC measured | | | | | | | ● L4, [P] threshold |
| Whole-app simulation invariants | | | | | ● | ● | ● |
| Oracle trace replay | | | | | ● | ● | |
| Catalogue fit, layout checks | | | | | | ● | |
| Perf class | ● where declared | ● | ● per operation | | | | ● |
| Structure caps (hygiene) | ○ | ○ | ○ | ○ | ○ | ○ | ● L4 |

### 4.2 Why each profile gets what it gets

- **`pure`: mutation fits.** A mutant here is a real question about a rule, and tests are cheap. Mutation is most
  valuable in the high-score regime (Chekam et al. 2017 ✓), so the bar stays at zero unexplained survivors.
- **`parser`: fuzzing and differential tests find what examples do not.** The review's ad-hoc fuzz of the parsers ran
  1.4M executions clean in minutes; that evidence should be in the verdict, not in a review.
- **`adapter`: mutation is the wrong tool.** At Google, developers first judged 85% of surfaced mutants unproductive,
  which is why mutants in logging and glue-like "arid" code are suppressed there (Petrović et al. 2021 ✓). Our data
  agrees: the L2 adapters hold 406 informational survivors, and `posix_fs`, `wire` and `runtime` show 30% over-pinning
  (syscall-letter logs, log arguments pinned after the implementation) [M]. What does find adapter bugs is what
  `posix_fs` already has: an every-call fault sweep plus tests on the real kernel.
- **`concurrent`: only a race detector and real threads are evidence.** A scripted fake of a mailbox proves the
  protocol, not the absence of a data race.
- **`wiring` and `ui`: the unit is the wrong size.** The double pulse and the unfittable strings are properties of
  several modules together. They are checked on the assembled app (§7.4–7.6).
- **`safety`: everything, plus proof.** These modules are small (1,557 lines in total) and their input domains are
  finite, so proof is cheap here and nowhere else.

## 5. Mutation engine v2

### 5.1 What stays

`mutate/gen.py`, the 14 operators, content-bound ids, accounting of every function, the `-O2`/`-O0` object identity
check (TCE), `unviable-ratio`, `crash-kill-ratio`, the per-function assert-kill rule, the verdict derivation in
`rigor mutants`, and the standalone compile of every mutant (steps 1–3b of `docs/mutate.md`). TCE removed 7% of
mutants as equivalent and 21% as duplicates on large C programs (Papadakis et al. 2015 ✓); in C that pass costs one
small compile per mutant, so it runs **first**, not on survivors as the Rust-oriented §3.5 of the ladder suggests.

### 5.2 What was proposed for the run stage (not adopted, see §5.6)

| Step | v1 | v2 |
|---|---|---|
| 4a schema | — | Per source, one **schema object**: every viable, non-equivalent, non-duplicate, schema-eligible mutant is compiled in, guarded by `rigor_mut_active == <n>`. One compile per source. |
| 4b link | relink per mutant and test | Each test is linked **once** against the schema objects and a 40-line runtime (`mutate/rt.c`: the active id, the reach bitmap, the fork loop). |
| 4c reach | — | Each test runs once with no mutant active. It must reproduce the baseline results, and it records which mutant guards it **executed**. |
| 4d kill | fresh process per mutant per test, after a relink | Per test, one action: for each reached mutant, `fork()`, set the id in the child, run the tests under the existing ctest limits, record the result. A mutant no test reaches skips this step (reason `unreached`). Stop at the first kill stays (T121 order). |
| 4e confirm | — | Every mutant that 4d did not kill, unreached ones included, is run through the v1 path (standalone object, relinked). Only that run can produce the verdict `survived`. The lane tier may skip 4e and report such mutants as provisional survivors. |
| 4f sanitizer pass [P] | not done ("doubles the compile and link work") | Mutants that survived in release run once more against the schema linked in `san` mode. An ASan/UBSan abort is `killed-sanitizer`: it counts as killed, never as an assert kill. |

**Schema-eligible** is decided from the AST parent of the mutated node. Not eligible, and therefore run through the
v1 path unchanged: a mutation in a constant-expression context (case label, array bound, `_Static_assert`, an
initializer of a `static` local), a string literal that initialises an array, and anything `gen.py` cannot wrap as
`(rigor_mut_active == n ? mutated : original)` or `if (rigor_mut_active != n) { statement }`.

### 5.3 Why the verdict does not get weaker

- A **survivor** is only ever declared by the v1 path (4e), so a `survived-mutant` finding and an approval mean
  exactly what they mean today.
- A **kill** under the schema says the tests are sensitive to that source change. The schema and the standalone mutant
  have the same source semantics for defined behaviour; they can differ only under undefined behaviour or a compiler
  defect. That is audited: a deterministic sample of schema kills (by hash of the mutant id; [P] 2%, at least 16 per
  module) is re-run through the v1 path nightly. A disagreement is the finding `schema-divergence`, a gate defect that
  fails the nightly grade.
- The v1 engine stays in the tree as the **reference engine**. It replaces the Mull cross-check that phase 1 planned
  and never ran (`docs/mutate.md`, "Limits").
- New canaries: a schema that silently drops a mutant (`schema-drops-mutant`), a reach bitmap forged to all zeros
  (`reach-forged`), a mutant only killable in the standalone build (`schema-only-survivor`), and the existing
  `batch = 1` byte-identity selftest extended to `engine = v1` versus `engine = v2` on the selftest modules.

### 5.4 Expected cost (the expectation §5.6 refutes)

Run actions fall from one per (mutant batch × test group) to three per test (link, reach, kill) plus the confirm runs
of survivors, which a zero-survivor module does not have. Published speed-ups for schemata in C and C++ are 2× to 30×
overall and about 5× from schemata alone, depending on the compile-to-run ratio (Vercammen et al. 2024 ✓); the ladder
cites a per-mutant-rebuild engine at a median of 1.6 h where a schema engine took 13–23 s (Lévai et al. 2026 †). Our
ratio is unusually favourable because v1 pays a **link** per mutant and test, which neither study's baseline did. No
number is promised here: W1 measures it on five modules before anything else is built (§13).

### 5.5 Scope per tier

- **Merge:** mutants in changed functions, plus a fixed-seed sample of mutants in modules one dependency hop away.
  Diff-only mutation misses most commit-relevant mutants (Ojdanic et al. 2022 †), and seeded random sampling is close
  to the best selection (Gopinath et al. 2016 †).
- **Nightly:** every mutant of every mutated module, uncached on the grader.
- Table initialisers (G29) become mutable in v2 through the v1 path, since they are constant expressions.

### 5.6 What W1 measured (T124, 2026-11-10): no-go

`plan/metrics/schema-engine-proto-2026-11.md`; the prototype is kept on branch `park/T124-schema-engine`. Five
business-apps modules, cold builds without the remote cache, one build per cell on the shared farm.

| Module | v1 exec s | schema exec s | v1 build wall s | schema build wall s |
|---|---:|---:|---:|---:|
| `lib/ds/fmap` | 456 | 1377 | 30 | 677 |
| `lib/fmt/jpull` | 387 | 859 | 58 | 236 |
| `relay/frame` | 92 | 62 | 26 | 36 |
| `lk/audit` | 214 | 144 | 47 | 52 |
| `lib/io/posix_fs` | 3828 | 3203 | 739 | 1130 |

- **The mechanism works**: 1,780 eligible mutants, every baseline reproduced, no mutant lost, 1,776 agree with v1 on
  the kill class and the other four are kill against kill.
- **It is not faster.** My premise in §1.1 and §5.4 was that the per-mutant relink dominates. It does not: the
  **test run time** does, and v1 already batches 16 mutants per action, stops at the first kill (T121) and spreads
  the work over the farm. The prototype has neither the stop rule nor sharding; the lane estimates that with both it
  would reach 1.5× to 2× on some modules and stay worse on `fmap`. That estimate is unmeasured.
- **It would also change verdicts at the edge.** Four mutants flip between `killed-assert` and `killed-crash`, which
  the per-function assert-kill rule and `crash-kill-ratio` read.
- **Reach filtering saves less than hoped.** Before the stop rule, the tests that reach a mutant are 31% to 88% of
  the (mutant, test) pairs v1 would run (`frame` 398 of 1,284; `fmap` 585 of 664).

**Decision.** W2 is cancelled. v1 stays the only engine. What remains from §5: the scope per tier (§5.5), a
sanitizer run for **surviving** mutants only (cheap, because there are few), and `equivalent-proved` (§7.3). The
cost work moves to what the data now points at: the scoped merge tier (W10), report-level mutation in the nightly
tier only (`posix_fs`, an adapter, costs ten times the other four modules for mutants that only inform), and a new
lead-time snapshot, since the 49% figure predates T121–T123.

## 6. Guards: `rigor_require` and the guard budget

**Problem.** In C a defensive bounds check is the only thing between an invariant broken elsewhere and memory
corruption. If the invariant holds, no test can kill a mutant of the check, and v1 answers "delete it".

**Design.**
- A gate-owned header `gate//rt:require` provides `rigor_require(cond)`. In every mode a false condition stops the
  process (`__builtin_trap()`; [P] or a product-chosen fail function, decision D4). It has no other effect, so it
  cannot hide logic.
- `ctest` gets `CHECK_TRAPS(t, expression)`: the expression must die by the trap in a child process.
- A guard that a test can reach through the public API is ordinary code: its mutants must be killed, normally by a
  `CHECK_TRAPS` test at the boundary.
- A guard that no public call can make false is declared in the module's policy as `guards = N`. Its mutants are
  reported as `guard` and are not survivors. `N` may fall freely. It may rise only inside a density cap ([P] one declared
  guard per 40 lines of the module), with no signature: a guard has no effect but the trap. The reach pass (4c) must show every guard **executed**; an unexecuted guard is `dead-guard`.
- At the `safety` profile and at L4 a declared guard must be **proved** unreachable by `c_proof` under the module's
  stated preconditions. A guard the proof can reach is a missing test, not a guard.
- A trap in any test, fuzz run or simulation outside `CHECK_TRAPS` is a failure. Guards therefore turn every other
  technique into an oracle: fixed limits plus assertions are what make fuzzing effective in static-memory designs
  (TigerBeetle ✓), and higher assertion density went with lower fault density in two Microsoft components
  (Kudrjavets et al. 2006 ✓, abstract only).

**Hardened release profile [P].** `-ftrivial-auto-var-init=zero`, `-fsanitize=bounds` with
`-fsanitize-trap=bounds`, `-fstack-protector-strong`, `-D_FORTIFY_SOURCE=3`, `-fstrict-flex-arrays=3`. All exist in the
pinned LLVM 19.1.7. Fixed arrays inside static structs, which is most of this codebase, become bounds-checked in the
shipped binary. Cost is measured by the existing `c_perf` targets before it is sealed. `-fbounds-safety` would check
every `(pointer, capacity)` pair, which is exactly the S1 convention, but it is not complete in upstream Clang yet (✓,
upstreaming in progress in 2026); revisit at the next toolchain bump (G20).

## 7. Evidence v2 adds

### 7.1 Sanitizer matrix

- **`msan`**: `-fsanitize=memory -fsanitize-memory-track-origins`. Pure and parser modules call only `mem*` and
  `str*` from libc, which MSan intercepts, so no instrumented libc should be needed; W5 confirms that on the pinned
  toolchain. It targets the class of `rx_init`'s unset fields.
- **`tsan`** (G12): only for `c_test`s tagged `threads = True`, which must start at least two real threads (a facts
  check, so the tag cannot be vacuous). `mbox`, `osal`, `wire` host and one whole-app run under real threads. P001
  notes that the presence of `libclang_rt.tsan` in the pinned archive is not yet checked.
- `MODES` in `gate/rigor_lib/grade_context.py` becomes `("release", "san", "msan", "tsan")`; `mode-divergence` compares
  all of them. The known hole (a product macro wrapping `__has_feature`) is closed by evaluating `__has_feature` and
  `__SANITIZE_*__` uses on preprocessed text in every mode, not by name.

### 7.2 Fuzz (G23)

- `c_fuzz` already exists (`rules/c.bzl:364`). v2 puts it in the verdict: a `parser` module without a fuzz target is
  `fuzz-missing`.
- **Merge:** replay the gate-held corpus, then a fixed budget per target ([P] 60 s). Gate on crashes only, never on
  coverage or time fuzzed (Klees et al. 2018 †; Böhme & Falk 2020 †: the cost per new bug grows exponentially).
- **Nightly:** long runs on idle farm capacity; new corpus entries are stored in the gate's corpus store, bound into
  the verdict by hash like the witness bundle. A crash found nightly is committed as a regression input and fails
  merges until fixed.
- Harness rules: a fuzz target calls only the module's public header; where two implementations exist (`jpull` and
  `jdom`) the harness is differential.

### 7.3 `c_proof` (G16)

- CBMC pinned by sha256 as a toolchain member; a `c_proof` macro; unwind bounds, object bits and a resource limit in
  gate policy; unwinding assertions always on; `unknown` or a timeout fails.
- **Vacuity is the main risk**: 28–31% of LLM-written Kani specs that passed were incomplete or vacuous (KaPilot,
  Wang et al. 2026 †; Kani runs on CBMC). Each harness must
  pass three probes: every `__CPROVER_assume` is satisfiable, a cover statement at the end of the function under proof
  is reachable, and an injected false assertion fails.
- **Scope is deliberately small**: the `safety` profile, and L4 parsers. For `relay/frame_is_safe` (57 lines) the
  property is total: for every 8-byte input, "safe" implies membership of the 243-frame allowlist. For `opener_sm`:
  for every input sequence up to the bound, no flash without a preceding good all-off read, and every pulse ends in
  the all-off ladder. AWS reports such proofs of low-level C as routine engineering with predictable effort (Chong et
  al. 2021 ✓); CBMC still has a tail of tens of minutes and tens of GB (†), which is why it is not spread wider.
- **Two more uses.** (1) *Equivalent mutants:* before any signature, the gate tries a bounded equivalence proof of the
  mutated function against the original; success is the verdict `equivalent-proved` and needs no approval. (2)
  *Unreachable guards* (§6). Both replace a judgement with a check.

### 7.4 Whole-app simulation

`lib/sim/simhost` exists and nothing outside its own module calls it [M]. v2 makes it a gate input:

- A product declares one `c_sim` target per app: the real composition with every port bound to its simulation.
- **Merge:** [P] 200 seeds; the same seed twice must give a byte-identical trace hash.
- **Invariants** are a gate-owned list checked on every step, written against events, not internals. For lockers: at
  most one `cmd_open` per staged visit; no `cmd_open` without a durable book save before it; every pulse is followed
  by a verified all-off; no frame leaves that `relay_frame_is_safe` rejects; no trap.
- **Fault schedules** come from the seed: disk full, torn write, DNS dead, TLS reset, relay silent, relay stuck coil.
- **Virtual-time soak (nightly):** [P] 400 simulated days at production intervals, asserting that sync keeps
  delivering snapshots, the audit log stays within its bound and no capacity counter saturates. This is the check
  that finds the pool retirement, and it costs seconds because the binary is small and the clock is virtual.

Deterministic simulation with fault injection is the practice FoundationDB and TigerBeetle credit for their
reliability (†); it is required from L3 in the ladder.

### 7.5 Oracle trace replay

The Rust app is the behaviour oracle, but today its behaviour reaches the tests by hand transcription: 185 of 822
test files cite Rust and no dumped corpus is committed [M].

- A gate-held bundle of traces recorded from the Rust viewmodel: input events in, ViewState and adapter calls out.
- The gate replays each trace through the C app in the simulator and requires zero divergence, modulo a gate-owned
  normalisation table. In a comparable study, differential testing against a reference found 21 bugs where proofs
  found 4 (Disselkoen et al. 2024 †).
- The bundle is produced by a club-apps task, bound by hash, never visible to implementers (same handling as the
  witness bundle).

### 7.6 UI and capacity checks

- **Catalogue fit:** for every phrase, language and screen, the rendered text fits the renderer's buffer and its box.
  The domain is finite, so this is exhaustive.
- **Golden frames:** one frame per screen and language from the software renderer under Xvfb, compared by hash;
  changing a golden needs the layout checks to pass and an arbiter claim (§10). business-apps D7 asked for one visual
  sign-off; that sign-off is no longer part of the gate (§16).
- **Limit tests:** every capacity constant in a public header (`*_CAP`, `*_MAX`) must be named by a test that fills it
  and checks the documented behaviour (design rule S3). A facts check finds the constants; an untested one is
  `limit-untested`.

### 7.7 Alloc-after-init trap and reachability

- The gate observes the process allocator at run time. In `san` builds it installs the sanitizer's allocation hooks
  (`__sanitizer_install_malloc_and_free_hooks`); in release-mode simulation builds it links a gate-owned `malloc`
  family into the executable, which glibc's interposition rules make the allocator for libc's own calls too. A
  linker `--wrap` is not enough: it rewrites only our objects' references, and those are already denied by `symbols`.
  After the product calls `rigor_init_done()`, an allocation is a failure with a backtrace. This turns "no allocation
  after init" from a symbol rule on our own objects into a run-time fact that includes libc and third-party code.
  `getaddrinfo` and `fdopendir` would be reported; each needs a fix or a signed, listed exception.
- G28 (no blocking call, allocation or lock reachable from the opener step) is the static counterpart, from the
  call graph the `structure` gate already builds.
- **Dead modules:** a module no `c_binary` and no declared library root reaches is `unreachable-module` (info, with a
  ratcheted count). Rigor is not spent on code nothing uses.

## 8. What v2 lowers, and on what evidence

| v1 | v2 | Evidence |
|---|---|---|
| Mutation on every module at L2+ | Gate only for `pure`, `parser`, `safety`; report for `adapter`, `concurrent`; none for `wiring`, `ui` | Petrović et al. 2021 ✓ (85% of mutants first judged unproductive; arid nodes); 406 informational L2 survivors [M] |
| Whole-repo zero survivors on every decisive grade | Changed functions + 1-hop sample at merge; everything nightly | Ojdanic et al. 2022 †; Gopinath et al. 2016 †; the whole-repo grade is 4.5 h of 11.7 h [M] |
| Functions ≤ 50 lines, cyclomatic ≤ 15, nesting ≤ 4 as L3 errors | Hygiene caps, reported; an error only at `safety` L4. [P] caps re-derived as percentiles of our own code | Size explains static metrics at R² 0.95–0.97 (Gil & Lalouche 2017 †); cyclomatic adds nothing over size (Landman et al. 2016 †); only 9 of 72 MISRA C:2004 rules beat a random predictor (Boogerd & Moonen 2008 ✓, secondary source) |
| At most 400 mutants per module (design rule S9), which split JSON into 5 modules and HTTP into 3 | No mutant budget; the limit was a cost limit, and §5 removes the cost | Opening a door crosses about 35 modules and 13 events [M]; very small components show higher fault density (Hatton 1997 ✓, contested) |
| Unkillable guards deleted | `rigor_require` and a guard budget (§6) | commit `2975620` [M] |
| Equivalent mutants signed by judgement | TCE, then a bounded equivalence proof, then a refutable arbiter claim under a debt cap (§10) | Equivalence is undecidable in general; 145–152 approvals staged for business-apps [M] |
| Witness for every module, in series | Required for `pure` and `safety` at L3+; optional elsewhere; always in parallel with the implementer | A same-model witness is not independent (P5); post-agent time is 27–96 min of sequencing [M] |
| Trajectory audit (6,181 lines; about 14% of gate commits; not in the verdict) | Replaced by the sandbox of B5/G3: separate uid, no network, no credentials. A minimal audit stays for what a sandbox cannot see | Monitors caught 42–65% of test-exploiting agents on complex tasks (Zhong et al. 2025 ✓); documented false negatives in `docs/trajectory.md` [M] |
| Tests grown by kill rounds | A property and model-test API in `ctest` (`ctest/prop.h`: seeded generators, shrinking); one model test replaces many example tests | 19% of test lines repeat verbatim within a module [M]; Goldstein et al. 2024 † |

What v2 does **not** lower: fail-closed results, the sealed grading tree, canaries and tripwires, default-deny
symbols, the stub-must-fail check, per-function assert kills, and zero unexplained survivors where mutation applies.

## 9. Tiers and budgets

| Tier | When | Scope | Cache | Budget [P] |
|---|---|---|---|---|
| **Lane** | inside an agent's loop | The module being edited: build, tests in all modes, its mutants through the grade's own action keys (T123) | shared | seconds to 2 min |
| **Merge** | every merge to `main` | Affected targets from the Buck2 graph; mutation scope of §5.5; fuzz replay + 60 s; 200 simulation seeds; oracle replay; proofs of changed `c_proof` targets | shared | 10 min wall |
| **Nightly** | once a day on `main` | Everything: full kill matrix, schema audit sample, long fuzz, soak, all proofs, full canary pack | grader, uncached | [P] 2 h |
| **Release** | before a field deploy | A nightly PASS on the exact commit, the RAM budget, golden frames, hardware conformance (orchestrator-run, business-apps D13) | grader, uncached | signed by the gate identity |

- Target-level test selection from the build graph is safe (Gligoric et al. 2015 †).
- A nightly FAIL on `main` blocks every merge except its fix. That is the price of not grading the whole repository on
  every merge, and it is why the nightly budget is a hard budget.
- A timeout at any tier is a FAIL, never a skip.
- Techniques that only **report** for a profile (`○` in §4.1, for example mutation of adapters) run in the nightly
  tier, never at merge: they cannot change a merge verdict, so they should not cost merge time.
- The B4 problem (a client-writable action cache) is solved for the tier that decides releases: nightly and release
  run on a grader instance whose cache clients can only read (G21). Merge-tier verdicts are advisory against a forged
  cache until then, which the nightly run bounds to one day.

## 10. Trust without a human in the loop

Owner direction (2026-11-09): the system is made by and for agents; no human approves anything. Today one identity,
the orchestrator, requests, signs, merges and holds the only trusted key [M]. v2 replaces "a trusted signer" with
five mechanisms, in this order of strength.

### 10.1 A check instead of a signature

Most of what v1 signs can be decided by a program. v2 removes the signature wherever that is true.

| What v1 signs or rules by hand | v2 rule | Signature |
|---|---|---|
| Equivalent mutant | TCE, then a bounded equivalence proof (`equivalent-proved`) | none |
| Guard budget | density cap, every guard executed, never fires in tests, fuzz or simulation; proved at L4 (§6) | none |
| Test removal | allowed when the kill matrix without the test kills the same mutants and every other gate still passes | none |
| Profile | a **floor** computed from facts: syscall or third-party symbols → `adapter`; thread or atomic symbols → `concurrent`; a public function taking a byte buffer and a length → `parser`; mutable static data → `wiring`. Policy may add profiles, never drop below the floor | none |
| Level | a floor from the dependency rule (a module is at least the level of every module that depends on it, `data` and `port` edges exempt) and from the product's declared risk roots. Lowering to the floor is free; lowering below it is impossible | none |
| RAM, perf, guard, unreachable-module counters | ratchets through the existing `ratchet` subcommand, which no `grade*.py` calls today | none |

The `e2eclock` move from L3 back to L2 (T120, "orchestrator ruling") is decided by the level floor under v2, not by a ruling.

### 10.2 What no program can decide is a refutable claim

Three things remain: a mutant whose equivalence proof times out, a golden frame, and a change to the gate itself.
Each becomes a **claim**: a signed statement that stays open to refutation by *executable* evidence.

- **Arbiter.** A headless agent started per request in a fresh context that holds only the request, the evidence
  bundle and the gate docs. It cannot write to any repo. It holds the only key `allowed_signers` trusts for
  approvals. [P] It runs on a different model family from the contributor where one is available; that is credited
  as defence in depth only, never as independence (P5).
- **Orchestrator.** Files requests and merges. Its key is removed from `allowed_signers`. It can no longer make its
  own grade green.
- **Refuter.** A nightly agent whose only task is to break standing claims: write a test that passes on the original
  and fails on an approved "equivalent" mutant; find an input that fires an "unreachable" guard; make a canary pass.
  The gate runs the refutation. If it holds, the claim is **revoked mechanically** and the finding returns. An
  LLM's opinion is never evidence here; its test is.
- **Debt cap.** Unproved equivalents are debt: [P] at most 2% of a module's mutants, and the count is a ratchet. A
  module at its cap has to change its code or its tests.

### 10.3 The gate may change only under the previous gate

A change to the gate repo, a product policy, a canary or a tripwire is graded by the **previous** gate commit: every
old canary is still red, every tripwire still red, the selftests pass, and the canary count did not fall. Opus line
review stays, as advisory. A gate change counts for the merge tier at once and for the release tier only after one
nightly PASS that includes the refuter run.

### 10.4 An append-only ledger

Every claim, revocation, ratchet move and gate change is one line in a hash-chained ledger (`ledger/*.jsonl`). Each
verdict binds the ledger head in `core.inputs`, so a rewritten history breaks `rigor verify`. A weekly digest
(`plan/metrics/ledger-<date>.md`) is generated for whoever wants to read it; nobody has to.

### 10.5 Tighten-only mode

Three events switch the gate to accepting no new claims until a gate task fixes the cause: a tripwire turns green, a
canary passes, or the refuter revokes more than [P] 5 claims in a week. This is the automatic stand-in for a human
noticing that something is wrong.

### 10.6 What this does and does not give

Separation of duties, refutation by execution and the previous-gate rule do not depend on any agent being right.
The arbiter does, and it is an LLM. Until the sandbox of W11 exists, the identities also share a uid and a host, so
the separation is detective, as B5 already records. The mechanical rules of §10.1 carry the assurance; the claims of
§10.2 are bounded debt.

## 11. The gate list after v2

Unchanged: `clone`, `contract`, `suppressions`, `assemble`, `toolchain`, `buckfiles`, `semantic-suppressions`,
`symbols`, `layering`, `build`, `mode-divergence`, `tests-release`, `tests-san`, `tests-stub`, `perf`, `mutants`,
`witness-tests`, `mutants-witness`.

| New or changed gate | Tier | Fails on |
|---|---|---|
| `policy-ratchet` | merge | a level or profile below its computed floor; a ratchet that regressed; a claim over the debt cap; a broken ledger chain |
| `structure` (changed) | merge | recursion, layering; size caps only where the profile says so |
| `tests-msan`, `tests-tsan` | merge | any report; a `threads` test that starts fewer than two threads |
| `guards` | merge | `dead-guard`, guard count over budget, a trap outside `CHECK_TRAPS` |
| `mutants` (changed) | merge / nightly | as today, with verdicts `killed-sanitizer`, `equivalent-proved`, `guard`; `schema-divergence` nightly |
| `fuzz` | merge / nightly | `fuzz-missing`, any crash |
| `proofs` | merge / nightly | a failed, unknown or timed-out proof; a failed vacuity probe |
| `sim` | merge / nightly | an invariant violation, a non-reproducible seed, a soak assertion |
| `oracle` | merge | any divergence from the trace bundle |
| `ui-fit` | merge | a phrase that does not fit; a golden mismatch without approval |
| `limits` | merge | `limit-untested`, alloc after init, `unreachable-module` over its ratchet |

Every new gate ships with at least one canary that must turn it red, as phase 1 requires.

## 12. Check against the review of 2026-11-09

| Finding | Caught by v2? | By |
|---|---|---|
| Double pulse (GAP-V2) | Yes | `sim` invariant "one `cmd_open` per staged visit"; `oracle` |
| Bounds check deleted in `durable()` | Yes | `guards`: it becomes a `rigor_require`, kept within budget |
| Pool retirement after 65,535 uses | Yes | `sim` soak; `limits` |
| Bulgarian strings over `LVR_TEXT_MAX` | Yes | `ui-fit` |
| `mbox` unlocked copy, `wire` atomics | Likely | `tests-tsan`, if the real-thread test makes a reader be overtaken |
| `rx_init` unset fields | Likely | `tests-msan`, if a test reads them before they are first written |
| `getaddrinfo` / `fdopendir` allocate | Yes | `limits` (alloc-after-init trap) |
| `getaddrinfo` blocks past the deadline | Partly | `sim` only if the DNS fault is modelled; G28 flags the blocking call on the opener path |
| Audit append re-reads every day file | Yes, if declared | `perf` class on the append operation with growing history |
| A 304 with `Content-Length` is a hard error | Partly | `fuzz` finds crashes, not wrong refusals; needs the `oracle` or a negative test |
| SIGPIPE on a dead log pipe | No | needs a real-OS test someone thinks to write |
| `kv` at L3, used by nothing | Yes | `limits` (`unreachable-module`) |
| Style not rendered, banner scrim | Partly | golden frames pin it; nothing in the gate says the first golden is right |

Two rows are "likely" and four stay "partly" or "no". v2 narrows the gap between "every module is green" and "the kiosk works"; it does
not close it.

## 13. Work packages

In dependency order. Each is one or more ordinary gate tasks (Sonnet builds, Opus reviews gate code line by line).

| # | Package | Acceptance | Depends on |
|---|---|---|---|
| W1 | **Measure first.** Prototype steps 4a–4d by hand on five modules (`fmap`, `jpull`, `relay/frame`, `lk/audit`, `posix_fs`): actions, CPU-s and wall, v1 against v2; count mutants that are not schema-eligible | A table in `plan/metrics/`; go or no-go on §5 | — |
| W2 | ~~Mutation engine v2~~ **Cancelled by W1** (§5.6). Replaced by: surviving mutants run once in `san` (`killed-sanitizer`) on the v1 engine | The verdict of the selftest modules is unchanged except for sanitizer kills of former survivors | W1 |
| W3 | `profile` key with computed floors, level floors, technique matrix, `policy-ratchet` | business-apps policy migrated; a parser declared `adapter` and a level below its floor each reproduce as a FAIL | — |
| W3b | Arbiter and refuter roles, debt cap, ledger, previous-gate rule, tighten-only mode | The orchestrator key no longer verifies; a refuted claim is revoked in a selftest; a ledger edit fails `rigor verify` | W3, W7 for proof-based equivalence |
| W4 | `rigor_require`, `CHECK_TRAPS` (T128), then the `guards` gate: guard count and density cap, every guard executed (from the `cov` build), trap allowance bound to the gate cell, `rigor_require` a reserved name | `durable()` restored with its check; canary `guard-hides-logic` red | — |
| W5 | `msan`, `tsan` modes; hardened release profile behind a flag | `rx_init` and `mbox` reported; `c_perf` deltas recorded | — |
| W6 | `fuzz` gate and corpus store | A target for each of the 8 parsers of G23; a seeded-crash canary red | — |
| W7 | `c_proof` with vacuity probes; equivalence and guard discharge | Proofs for the five relay modules; canaries `vacuous-assume` and `unwind-too-small` red | W4 |
| W8 | `c_sim`, invariants, soak; `oracle` replay | The pool retirement and GAP-V2 reproduce as FAILs on the commits that had them | club-apps trace dump task |
| W9 | `ui-fit`, `limits` (limit tests, alloc trap, dead modules) | The three Bulgarian strings and the two libc allocations reproduce as FAILs | W5 |
| W10 | Tiers: scoped merge grade, nightly grader on a read-only cache | Merge grade inside its budget on ten real tasks; nightly inside its budget | G21 for the nightly cache only |
| W11 | Sandbox (B5/G3), then retire the trajectory rules it makes redundant | Red-team task: zero successful escapes; rule table reduced | — |

W1, W3, W5, W6 and W11 can start at once and touch different files.

**Ordering rule.** A profile loses its mutation gate only in the gate commit that turns on its replacement gates:
`adapter` after W5, W6 and the fault-sweep check; `concurrent` after W5; `wiring` and `ui` after W8 and W9. Until
then their mutants stay informational exactly as at L2 today, so no module is ever checked by less than v1.

### 13.1 Implementation status (2026-11-10)

| Package | Task | State |
|---|---|---|
| W1 engine measurement | T124 | Done: **no-go** (§5.6); prototype on `park/T124-schema-engine` |
| W2 engine v2 | — | Cancelled by W1 |
| W3 profiles and floors | T127 | Merged: library and `rigor policy-check`; **not yet a gate**, no product policy migrated |
| W3b trust | T132 | Merged: signer roles, ledger, debt cap, tighten-only switch as an opt-in library; **nothing wired**: `orchestrator` still signs every kind |
| W4 guards | T128, T131 | Merged: `gate//rt:require`, `CHECK_TRAPS`, cell-bound trap allowance, reserved name, guard facts, `rigor guards`; **not a gate**, declared guards are not yet exempt from mutation, nothing checks a guard was executed |
| W5 sanitizer modes | T125 | Merged: `msan` and `tsan` modes, proven on the farm (0 of 30 start failures each). Farm prerequisite: the workers' seccomp profile allows `personality(ADDR_NO_RANDOMIZE)` (applied by the owner). Gates: T138, in flight |
| W5 hardened release | — | Not started |
| W6 fuzz | T126, T129, T135 | Merged: the `fuzz` gate runs in every grade; products can carry a corpus and a budget; regression list bound into the verdict. Nothing writes the regression list yet; no nightly campaign |
| W7 `c_proof` | — | Not started |
| W8 simulation, oracle replay | — | Not started (needs business-apps and club-apps tasks) |
| W9 UI fit, limits, alloc trap | — | Not started |
| W10 tiers | T137 | Merged: `--tier merge|nightly`, report-only mutation deferred at merge, tier bound into the verdict. The nightly grader on a read-only cache (G21) is a farm change and not started |
| W11 sandbox | — | Not started |
| Found on the way | T130, T136 | Merged: perf counts drift on one CPU model; bound derived from 200 runs; counts out of findings (B35) |
| Found on the way | T133 | Merged: a product directory could pass as gate third-party code and hide suppressions from the semantic scan; path decisions anchored, canary `vendor-path-spoof` |

Two expectations of this document were wrong and were corrected by measurement: the mutation engine (§5.6) and, in
the perf work, the cause of the count differences (twice). No product has been regraded under any of the new gates:
`business-apps` pins an older gate commit.

## 14. Measurement plan

1. **Cost.** Re-run `timeline.py` now (the 49% predates T121–T123), and again after W10, on comparable tasks. Target [P]: mutation plus waiting under
   25% of agent wall time (72% today), with the model share rising accordingly.
2. **Fidelity.** v1 and v2 kill matrices byte-compared on the selftest modules on every gate change (a selftest), and
   on the nightly sample for products.
3. **Yield.** For each new gate, count distinct real defects found on business-apps in its first month, per CPU-hour.
   A gate that finds nothing and costs more than [P] 5% of the nightly budget is demoted to nightly-only or removed.
   This is how rigor keeps being lowered where it does not pay.
4. **Escapes.** Every defect found in the field or by review is classified by which gate should have caught it; a
   defect no gate could have caught opens a gate task.

## 15. Decisions

The owner answered three on 2026-11-09 and asked for no human in the loop. The rest are therefore set here to a
default with a rule for revising it from data (§14); the owner can override any of them.

| # | Decision | Status |
|---|---|---|
| D1 | Profiles; mutation gates only `pure`, `parser`, `safety` | **Accepted by the owner** ("if the science supports it"): §4.2, §8 |
| D2 | Scoped merge grade with a blocking nightly | **Accepted by the owner** |
| D8 | Root of trust | **Owner: no human in the loop.** §10 |
| D3 | `killed-sanitizer` counts as a kill, never as an assert kill | Default: yes |
| D4 | `rigor_require` failure | Default: trap in libraries; an app may route it to a logged exit. Pulses are device-timed, so a restart cannot hold a solenoid |
| D5 | Hardened release flags | Default: adopt when the declared `c_perf` targets move by under 3% instructions; otherwise keep in `san` only |
| D6 | Budgets: 10 min merge, 2 h nightly, 60 s fuzz per target, 200 seeds, 400 soak days | Default: start there; re-derive weekly from the lead-time and yield tables |
| D7 | MC/DC threshold at `safety` L4 | Default: the value measured at the first PASS becomes the floor; ratchet upward only |
| D9 | Witness required only for `pure` and `safety` at L3+ | Default: yes |
| D10 | Retire trajectory rules once the sandbox passes its red team | Default: yes |
| D11 | Unreachable modules (`kv`, `httpredir`, `fsm`, `winpolicy`) | Default: delete in a business-apps task; business-apps D2 already says a library module is built when lockers first needs it |

## 16. Known limits of this design

- **No human checks the result.** Where the gate cannot say whether something is *right* (the first golden frame, a
  missing simulation invariant, a spec the Rust oracle also gets wrong), nothing does. That is the accepted cost of
  an agent-only system; §14 item 4 is how such escapes turn into gates.

- **The one thing measured so far refuted its section.** W1 rejected the mutation engine of §5 (§5.6). The other cost
  and yield expectations in this document are still unmeasured; §14 is how each gets a number.
- **The oracle only covers what the Rust app does.** Behaviour the Rust app gets wrong is reproduced faithfully.
- **Simulation invariants are written by someone.** A missing invariant is a missing check; the list is gate-owned
  and reviewed by Opus, which is advisory evidence only (P5).
- **CBMC proofs are bounded.** They hold up to the unwind bounds in gate policy and say nothing about the compiler,
  the libc or the hardware.
- **Sanitizers and fuzzing see only what executes.** A hardened release build narrows this for bounds; it does not
  make C memory-safe.
- **Third-party code stays outside.** mbedTLS and LVGL are checked by the alloc trap, the fuzz targets that pass
  through them and nothing else.
- **The merge tier trusts the shared cache** until G21.
- **Profiles can be mis-assigned.** Calling a parser an adapter removes its mutation gate; that is why the profile
  floor is computed from facts and cannot be lowered by policy (§10.1). The floor rules are heuristics and can miss.

## References

Re-checked on 2026-11-09 (✓):
- Boogerd & Moonen, "Assessing the Value of Coding Standards: An Empirical Study", ICSM 2008 (via secondary summary).
- Chekam, Papadakis, Le Traon, Harman, "An Empirical Study on Mutation, Statement and Branch Coverage Fault
  Revelation that Avoids the Unreliable Clean Program Assumption", ICSE 2017.
- Chong et al., "Code-Level Model Checking in the Software Development Workflow at Amazon Web Services", SPE 2021.
- Fonseca, Zhang, Wang, Krishnamurthy, "An Empirical Study on the Correctness of Formally Verified Distributed
  Systems", EuroSys 2017.
- Hatton, "Reexamining the Fault Density–Component Size Connection", IEEE Software 1997.
- Kim, Garg, Peng, Garg, "Correlated Errors in Large Language Models", ICML 2025.
- Knight & Leveson, "An Experimental Evaluation of the Assumption of Independence in Multiversion Programming",
  IEEE TSE 1986.
- Kudrjavets, Nagappan, Ball, "Assessing the Relationship between Software Assertions and Faults", ISSRE 2006
  (abstract of the technical report).
- Papadakis, Jia, Harman, Le Traon, "Trivial Compiler Equivalence", ICSE 2015.
- Papadakis, Shin, Yoo, Bae, "Are Mutation Scores Correlated with Real Fault Detection?", ICSE 2018.
- Petrović, Ivanković, Fraser, Just, "Practical Mutation Testing at Scale: A View from Google", IEEE TSE 2021.
- TigerBeetle, "A Database Without Dynamic Memory Allocation", 2022.
- Vercammen et al., "Mutation Testing Optimisations Using the Clang Front-End", STVR 2024.
- Zhong, Raghunathan, Carlini, "ImpossibleBench: Measuring LLMs' Propensity of Exploiting Test Cases", 2025.
- LLVM `-fbounds-safety` upstreaming status (LLVM Discourse and commit lists, 2025–2026).

From `ai-code-rigor/docs/research/references.md`, not re-checked here (†): Böhme & Falk 2020; Disselkoen et al. 2024;
Gil & Lalouche 2017; Gligoric et al. 2015; Goldstein et al. 2024; Gopinath et al. 2016; Klees et al. 2018; Landman et
al. 2016; Lévai et al. 2026; Ojdanic et al. 2022; Wang et al. 2026 (KaPilot); the FoundationDB and TigerBeetle
simulation reports.

Our own measurements: `business-apps/plan/metrics/lead-time-2026-11-09.md`; `lang-bench/REPORT.md`;
`business-apps/plan/HANDOFF.md`; `docs/mutate.md`; commits `2975620`, `d7d286c`; `plan/tasks/L216-*.md`.
