# Fuzzing: `c_fuzz` with a corpus, and the judge `rigor fuzz` (T126, P003 §7.2, G23)

Landed, not wired: `rigor grade` does not run the judge yet (`GATES`, `gate/order.txt` and the canaries are the next task).

## The rule: `c_fuzz`

```
c_fuzz(
    name = "fz",
    srcs = ["fz_fuzz.c"],
    deps = ["//parser:parse"],          # the module(s) the harness calls, by their public header
    corpus = glob(["corpus/*"]),        # files of the product; default: none
    runs = 50000,                       # optional budget in runs; default 200000, maximum 2000000 (rules/fuzz.bzl)
)
```

`corpus` is a list of plain relative file paths of the package (never a label, never `..`). `runs` above the sealed
maximum, or not an integer, is a loading error. The rule lives in `rules/fuzz.bzl` (`fuzz_run`, the defaults and the
argument checks); `c_fuzz` in `rules/c.bzl` only forwards.

The run action does, in this order, under the same hermetic symbolizer and fatal sanitizer options as `<name>_results`:

1. **replay**: every corpus file once, one process per file (`-runs=0 <file>`), in the order of the files' sha256
   (independent of file names). A crash here is a regression, and the replay stops at it.
2. **budget**: `-seed=1 -runs=N`, seeded with the corpus. libFuzzer only *fuzzes* when it is given a corpus directory
   (files alone are executed once and nothing is fuzzed), so the action copies the corpus into a private directory of the
   scratch space, which is thrown away: new units are never kept (a nightly campaign will store them, later).

The budget is a number of runs, never a time, so the action is deterministic and cacheable; a wall-clock limit is only the
timeout that fails it. Without a corpus the action behaves as before (same command line, same report).

| Output | Content |
|---|---|
| `[verdict]` | `pass`, or `fail rc=<status>`, written after the target exited; `pass` needs exit 0 and libFuzzer's `Done N runs` |
| `[report]` | the symbolized report; with a corpus a line `replay: K of M corpus files` |
| `[crash]` | the reproducer; empty on a pass. For a replay crash it is the corpus file itself (libFuzzer writes no artifact for it) |
| `[stats]` | `stats.json`, exactly `runs_done`, `corpus_files`, `replayed`, `phase` (`replay` or `budget`, where it stopped), `reproducer_sha256` (empty on a pass). Nothing volatile |
| `[replayed]` | the sha256 of every corpus file replayed without a crash, sorted, one per line (the judge needs it for regression inputs) |

`runs_done` is libFuzzer's `stat::number_of_executed_units` of the budget run (also printed after a crash; a fixed seed
makes it the same on every run); 0 when the replay stopped.

## The judge: `rigor fuzz`

```
rigor fuzz --results DIR --policy P.toml --facts DIR [--regressions R.json] [--out F]
```

Exit 0 PASS, 1 FAIL, 2 on any malformed input (unknown key, stray file, bad JSON, inconsistent stats, a result for
something that is not a `c_fuzz` target of the facts, a policy module without facts).

**Policy** (`policy.toml`, gate-owned; only these keys are read here):

```
[module."//parser:parse"]
fuzz = true            # some c_fuzz target must list the module in `deps`
fuzz_runs = 200000     # optional: the runs a target must complete (default 200000, at most 2000000)
```

A required target is a `c_fuzz` target that lists a `fuzz = true` module in `deps`; its budget is the largest `fuzz_runs`
of those modules. The budget comes from the policy, not from the product, so a product cannot lower it with `runs`.

**Results directory** (flat, nothing else in it): `index.json` = `{"<target label>": "<id>"}`, and per id `<id>.stats.json`,
`<id>.verdict`, `<id>.report`, `<id>.replayed`, and optionally `<id>.crash` (its sha256 must equal `reproducer_sha256`).
These are the outputs of the run action; the caller (the later wiring) collects them.

**Regressions** `R.json` is gate-owned: `{"<target label>": ["<sha256>", ...]}`, the inputs that once crashed.

| Finding | Severity | When |
|---|---|---|
| `fuzz-missing` (`module`) | error | a module with `fuzz = true` that no `c_fuzz` target lists in `deps` |
| `fuzz-harness-no-call` (`target`, `module`) | error | the harness references no symbol that the module defines (symbol facts, as the `symbols` gate reads them) |
| `fuzz-crash` (`target`, `phase`, `reproducer_sha256`, `top_frame`) | error | the run did not pass; `top_frame` is the first symbolized frame of the report (`function file:line:col`), or empty |
| `fuzz-not-run` (`target`) | error | a required target without results |
| `fuzz-short` (`target`) | error | a passing run with fewer `runs_done` than its budget |
| `fuzz-regression-missing` (`target`, `sha256`) | error | an input of `R.json` that is not among the replayed files (also for a target that is gone). Not reported while the replay of that target stopped at a crash: that is `fuzz-crash` already |
| `fuzz-empty-corpus` (`target`) | info | the target has no corpus |

Findings are sorted and byte-identical on rerun; counts (`runs_done`, `corpus_files`, `replayed`) go to `metadata` only.
`DEFAULT_RUNS` and `MAX_RUNS` in `gate/rigor_lib/fuzz_gate.py` equal `FUZZ_DEFAULT_RUNS` and `FUZZ_MAX_RUNS` in
`rules/fuzz.bzl`; a unit test compares the two files.

## What stops a crashing input from being deleted

The reproducer of a crash is committed into the corpus and its sha256 into the gate's `R.json`. Deleting the file from the
corpus then fails the merge with `fuzz-regression-missing`, not silently. Without an entry in `R.json` nothing stops the
deletion, so the entry is part of the fix.

## Limits

- A fixed seed and a fixed budget (200000 runs by default, a few seconds to a minute) find **shallow bugs only**: what a
  coverage-guided fuzzer reaches in that many executions. Gating on a time or on coverage would be noise (the cost per new
  bug grows exponentially); the gate looks at crashes only.
- The corpus is the only thing that grows the reach of the fixed budget. The judge does not check that a corpus is any good
  (`fuzz-empty-corpus` is info only).
- `fuzz-harness-no-call` checks that the harness references an exported symbol of the module, not that the call is
  meaningful or reachable from the input.
- Long campaigns on idle farm capacity, a corpus store bound into the verdict by hash, and differential harnesses are a
  later nightly task, as is wiring this judge into `rigor grade`.
- `docs/toolchain.md` and `docs/ctest.md` still say `fuzz_run` lives in `rules/ctest.bzl` and runs a fixed 200000: it moved
  to `rules/fuzz.bzl` (the paths of this task did not include those two docs).
