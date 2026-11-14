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
