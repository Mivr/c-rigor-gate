# perf: deterministic cost counts for performance tests (`c_perf`)

The building block of the `perf` gate (R011, B13). `c_perf` builds a perf binary from a module and a
gate-held generator and driver, runs it on RE and produces a cacheable `perf.jsonl` of **cost counts** at
two or more input sizes. It gives no verdict itself; the `perf` gate (T090, "Judging" below) compares the counts at the
first and the last size with the complexity class the policy declares.

## The rule

```python
load("@gate//rules:c.bzl", "c_perf")
c_perf(name = "parse_perf", module = ":parse", srcs = ["gen.c", "drv.c"], deps = [], sizes = [1000, 4000], seed = 1)
```

- `module` is the `c_library` under test; `srcs` are the gate-held generator and driver sources (plain `.c` names,
  same checks as `c_binary`); `deps` are further libraries.
- Targets: `<name>` (the binary) and `<name>_perf` (the action; its output is `perf.jsonl`).
- **Release only** (`target_compatible_with = toolchains//:release`): `-O2` and the hardened release flags (`docs/toolchain.md`, T139), the sealed warnings. The rule adds the
  `-Wl,--wrap=` flags for the libc list below; the product never sets them.
- `sizes` (2 to 8 positive ints, normally `[n, 4n]`) and `seed` are attributes. Nothing comes from the environment.
- The action succeeds whenever the harness ran and wrote records. It fails only when the harness could not run at
  all (non-zero status, no records).

## Harness API (`ctest/perf.h`, `ctest/perf.c`)

The harness owns `main`. The driver implements:

```c
size_t   perf_gen(uint64_t seed, size_t n, char *out, size_t cap);  /* not counted; PERF_INPUT_CAP = 16 MiB */
uint64_t perf_run(const char *in, size_t len);                      /* counted; PERF_ERR = "input rejected" */
```

For each size the harness forks a child (so a crash is a record), generates the input, then calls `perf_run` 7
times, each in its own counter window. Only the `perf_run` call is counted. `perf_run` must be repeatable (a pure
function of its input; any state it keeps must not change its cost).

## Record format (`perf.jsonl`, one JSON object per size, in `sizes` order)

```
{"name":"lin_p","seed":7,"n":80000,"status":"ok","counter":"perf_event_open","errno":0,
 "input_len":80000,"instructions":460052,"libc_bytes":0,"result":160481880,"wall_ns_median":41234}
```

| field | meaning | deterministic |
|---|---|---|
| `status` | `ok`, `gen-overflow` (generator returned more than `cap` or wrote past it), `run-error` (`perf_run` returned `PERF_ERR`), `crash` (signal in `signal`, or `exit_code`), `timeout` (100 s alarm) | yes |
| `counter` / `errno` | `perf_event_open`/0, or `unavailable` with the errno (and `"why":"multiplexed"` if the PMU time-sliced the event). The action still succeeds so the gate can report `perf-counter-unavailable` | yes (per worker) |
| `input_len` | bytes the generator produced | yes |
| `instructions` | user-mode retired instructions (`exclude_kernel`, `exclude_hv`) of one `perf_run`; `null` when unavailable | within a stated bound (see "Determinism") |
| `libc_bytes` | sum of `len` over the wrapped libc calls during one `perf_run` | yes |
| `result` | what `perf_run` returned | yes |
| `cpu`, `reps` | the CPU model string of the machine, and the 7 per-run instruction counts in run order | **no**: metadata only, nothing reads them for a verdict |
| `wall_ns_median` | median of the 7 runs, wall clock | **no**: depends on the worker and its load; an informational cross-check only |

When `status` is not `ok` the record carries `input_len` (and `signal`/`exit_code`) and **no counts**: never a zero.

## Determinism

`instructions` and `libc_bytes` are the **median of 7 counted runs**. The first run is cold (lazy symbol binding and
first page touches add about 1.5e3 instructions) and is never the median; the warm runs differ by a few
instructions at most (counter skid, see below), so the median is stable. `selftest/perf.sh` builds each fixture twice (two copies whose
sources differ in a comment, so compile, link and run all re-execute) and requires identical `n`, `input_len`,
`libc_bytes` and `result`, and `instructions` by `run_differences` (below) (the nonce is a string constant in each `.c` file, so the
binary differs and the perf run really executes again). R011 measured identical ratios across 10 actions on two farm workers.
Counts are from the same binary; a different CPU model or libc build may shift absolute counts by a small
constant, never the ratio.

**Mixed farm (T130, B35).** Measured 2026-11-10, uncached runs of the selftest fixtures (each run builds a binary
that has not run before, so it executes on whichever worker is free). The record carries, as metadata, the
`cpu` model string of the machine that ran it and `reps`, the instruction count of each of the 7 runs. Every
execution that reached the measurement reported `Intel(R) Xeon(R) CPU E5-2690 v4 @ 2.60GHz` (the Zen 4 worker was
never scheduled in these runs, and the counter is not readable on the Zen 4 workstation, so no Zen count was measured):

| fixture, n | median over executions | spread over executions | per-rep spread inside one run |
|---|---|---|---|
| `lin` 20000 | 115051 | 0 | 0 |
| `lin` 80000 | 460051 | 0 | 0 (one rep 460052) |
| `mmove` 10000 | 3596112 | 0 | 0 (rep 0, the cold one, +1566) |
| `mmove` 40000 | 4927376 to 4927378 | 2 | 0 to 1 |
| `quad` 3000 | 21452986 | 0 | 0 to 1 |
| `quad` 12000 | 342312025 to 342312029 | 4 | up to 4 |

Answers. The count is not constant per CPU model: the same binary on the same model moves by a few instructions from
one execution to the next, so the one-instruction difference between cold runs that failed the selftest (342312029
against 342312028) is not a CPU-family difference we could attribute. The difference is absolute, not proportional to
`n`: windows that last microseconds (`lin`) never move; windows that last tens of milliseconds and more
(`mmove` 40000: 16 ms, `quad` 12000: 46 ms) move by 2 to 4, in both directions, about 1e-8 of the count. That fits an
interrupt or the PMU's own skid landing inside the window (a timer tick every few ms), which no counter attribute removes
(`exclude_kernel`, `exclude_hv` are already set, and the kernel time of the interrupt is not what moves). The enable and
disable edges are not the cause: an empty window (`RESET`, `ENABLE`, `DISABLE`, `read` with nothing between) counted 31
instructions in each of 7 reps of every run, and the cold first rep adds about 1.5e3 (the median skips it).

**Across CPU models (T136, B35 reopened).** The selftest still failed now and then (`mmove: instructions differ beyond
the bound between cold runs: 4927378 vs 4927410`, 32 apart against a bound of 20). The hypothesis was two different CPU
models. Measured 2026-11-10, 200 uncached executions of every fixture (8 and 24 cold copies per build, 9 builds, all on
the farm): **every one reported `Intel(R) Xeon(R) CPU E5-2690 v4 @ 2.60GHz`; no Zen 4 execution happened, so there is
no cross-model count and the 32 difference was not between models.** It was the same-model drift, whose tail the T130
data (a few dozen executions) had not reached. Per CPU model and per fixture (one model, 200 executions each):

| fixture, n | min | median | max | max - min | wall (median) | old bound | new bound |
|---|---|---|---|---|---|---|---|
| `lin` 20000 | 115051 | 115051 | 115054 | 3 | 0.0 ms | 16 | 19 |
| `lin` 80000 | 460051 | 460051 | 460051 | 0 | 0.1 ms | 16 | 30 |
| `mmove` 10000 | 3596112 | 3596112 | 3596114 | 2 | 0.9 ms | 19 | 125 |
| `mmove` 40000 | 4927377 | 4927378 | 4927429 | **52** | 16.7 ms | **20** | 166 |
| `quad` 3000 | 21452986 | 21452986 | 21452988 | 2 | 2.9 ms | 36 | 670 |
| `quad` 12000 | 342312025 | 342312029 | 342312143 | 118 | 45.8 ms | 342 | 10462 |

Between models (not measured; the rule below does not need the numbers): none.

The spread is a few instructions per timer tick that lands in the window (2 to 3 per wall millisecond at the maximum,
a heavy tail: for `mmove` 40000 the median deviation is 1, the 99th percentile 46), so it grows with the time of the
window, not with the count; a window with few instructions and a long time (a libc `memmove` loop) has the largest
relative spread (1.1e-5). The old bound, 16 + 2^-20 of the count, was 2.6 times too small there. **New bound:
`COUNT_ABS + max(a, b) >> COUNT_REL_SHIFT` with `COUNT_ABS = 16`, `COUNT_REL_SHIFT = 15`** (`perf_judge.count_bound`:
16 plus 3.05e-5 of the count). Margin: at least 3 times the largest measured spread in every fixture (`mmove` 40000:
166 against 52; `lin` 20000: 19 against 3, 6 times), and still 3000 times smaller than the 10 % margin of the complexity
classes, so it cannot hide a class change. `libc_bytes`, `result` and `input_len` stay exactly equal.

**The rule.** `perf_judge.run_differences(run_a, run_b)` compares two runs of the same measurement:
- **same `cpu` string**: every `instructions` within `count_bound`, `libc_bytes` equal;
- **different `cpu` strings** (or a record without `cpu`, which is never the same model): raw counts are not compared.
  Per counter, the complexity class (the smallest class that allows the count at the last size) must be the same, and
  the ratio between the first and last size must agree within 1.10, the judge's own margin (`CROSS_MODEL_MARGIN`).

`counts_agree`/`run_differences` are used only by the selftest identity check. A verdict never compares two runs:
`perf-class-exceeded` and `killed-perf` read the records of one `perf.jsonl` (one action, so one CPU model; `judge_target`,
`mutants_perf`), one count per size, and judge the ratio. `tests/test_perf_judge.py` (`VerdictPath`) checks that the
verdict does not depend on the `cpu` field, that targets are judged on their own records, and that no verdict module
mentions the comparison functions. Nothing in the gate compares raw counts across actions, so no other place needed the
rule. The findings carry no counts (see "Findings of the `perf` gate"), so they are byte-identical whichever worker ran the action.

## libc bulk bytes: the wrap list and its limits

Instruction counts are blind to bulk libc work (a quadratic `memmove` compaction has an instruction ratio of about
1.4 and a wall ratio of about 24). The rule links with `-Wl,--wrap=` for `memcpy`, `memmove`, `memset`, `memcmp`,
`strlen` and `strnlen`; `ctest/perf.c` defines the `__wrap_` functions, which add `len` (for `strlen`/`strnlen`, the
returned length) while a counted `perf_run` is active and then call the real function.

Limits, by construction:
- Calls the compiler **inlines or expands** (fixed-size copies, small constant `memset`, `rep movs` idioms) never reach
  the wrapper and are not counted. They are cheap and have a fixed size, so they cannot scale with `n`; the
  instruction counter sees them.
- Only the listed functions. `memchr`, `strchr`, `strcmp`, `strncmp`, `qsort`, `bsearch`, `printf` and friends are not
  byte-counted. Their instructions are user-mode, so `instructions` includes them, but vectorised libc routines
  execute very few instructions per byte, so a quadratic scan through, say, `memchr` is only weakly visible there.
- Calls made from inside the C library (not from the product object code) are not wrapped.
- Loop idioms the optimiser turns into `memset`/`memmove` calls are counted (they are real calls).

## Selftest

`selftest/perf.sh` (registered as the `perf` selftest in `tools/affected.toml` and `tools/validate.sh`): an O(n)
loop (instruction ratio at k=4 in [3.5, 5]), an O(n^2) loop (ratio at least 12), an O(n^2) `memmove` compaction
(byte ratio at least 12, instruction ratio below 6), plus the failure statuses `gen-overflow`, `run-error` and
`crash`, and the cold-run identity check. If the worker has no counter the selftest checks the `unavailable`
record instead of the ratios.

## The perf bundle (`--perf DIR`, T080)

The hidden input of the later `perf` gate: the generators and drivers an implementation is judged against.
`gate/rigor_lib/perf_bundle.py` loads and validates it; `rigor grade --perf DIR` binds it; the `perf` gate judges its
targets as `bundle_<id>` (class `linear` is O(n), `nlogn` is O(n log n); T090, "Judging").

```
<dir>/perf.toml
<dir>/<path named in srcs>        # e.g. gen/json_keys.c
```
```toml
version = 1
product = "annas-c"              # must equal product.toml's name
[[target]]
id = "json-many-keys"            # unique, [a-z0-9-]
module = "//json:json"           # in the product policy, level L3 or above
srcs = ["gen/json_keys.c"]       # generator + driver (ctest/perf.h API), paths inside the bundle
sizes = [1000, 4000]             # exactly two, second = k * first, k >= 2
seed = 1                         # 0 <= seed < 2^64
class = "linear"                 # linear | nlogn
```

Every defect is exit 2 (`InternalError`), like a bad witness bundle: unknown or missing keys, a wrong type, a bad
`version` (only 1), a bad or duplicate `id`, a `module` that is not `//pkg:name`, in the policy or at L3 or above,
bad `sizes` or `class` or `seed`, a `srcs` entry that is absolute, has `.`/`..`/empty segments or is `perf.toml`,
a named file that is missing, a file the manifest does not name, a symlink (also the bundle directory itself), a
special file, an empty directory, a non-UTF-8 name. Targets may share sources. Files are read once, without
following symlinks, and kept in memory.

**Digest.** `perf_sha256` is the witness bundle's scheme (`witness_bundle.entries_digest`): the sha256 of
`canonical_dumps(entries)`, `entries = [["perf.toml", sha256 of perf.toml], ["<path>", sha256 of the file], ...]`:
the manifest first, then every named file by its bundle path, sorted. It does not depend on where the bundle is stored.

**Binding.** Like the witness bundle: `--perf DIR` is copied once into `<work>/inputs/perf` (symlinks and special
files refused), loaded once from the copy and checked against the product (`perf_bundle.check`); that one load is
what the grade holds (`Grading.perf`) and what is hashed. `core.inputs.perf_sha256` is the digest or `null`.
`rigor verify --expect-perf-sha SHA` rejects any other value and a grade without a bundle (`null`); `none` rejects a
grade that has one. Without the option any well-formed value, or `null`, is accepted.

**`gate/tools/perf.py`**
```sh
gate/tools/perf.py check DIR --product products/<p>/product.toml    # prints: ok <perf_sha256>
gate/tools/perf.py digest DIR                                       # format checks only
```
A tiny valid bundle for the selftest product is `gate/tests/fixtures/perf/selftest`.

## Judging: complexity classes and the `perf` gate (T090, G30)

A product cannot declare `c_perf` (the `buckfiles` gate allows no such macro, and the driver must be gate-held). The
gate generates the package `gate-perf/` (`gate/rigor_lib/perf_package.py`: one `c_perf` per target, the sources next to
the BUCK file) from two gate-owned places, and judges each target's `<name>_perf` output.

**The policy shape** (`products/<p>/policy.toml`, read by `gate/rigor_lib/perf_policy.py`; any defect is exit 2). Per module:
```toml
[module."//json:json".perf.lookup]       # name [a-z][a-z0-9_]*; the target is //gate-perf:lookup_perf
class = "O(log n)"                       # O(1) | O(log n) | O(n) | O(n log n)
sizes = [2000, 8000]                     # 2 to 8 increasing positive sizes; the first and the last are judged
seed = 3
[module."//json:json".perf.lookup.srcs]  # generator + driver (ctest/perf.h API): file name -> text
"lookup.c" = '''
...C source, a literal multi-line string...
'''
```
The sources are inside the policy on purpose: the verdict binds the policy snapshot (`<work>/inputs/product`), so the
driver is bound with the class, and the product cannot change either. (The spec for this task wrote
`perf."//x:y_perf"`; target names are generated, hence the name here and the label `//gate-perf:<name>_perf`.) The
perf bundle (`--perf DIR`) adds its targets under the name `bundle_<id>` (ids use `-`, names `_`) with `linear` read
as O(n) and `nlogn` as O(n log n); a name used twice is exit 2. The driver includes its module's public header by
its package path (`#include "core/core.h"`).

**The thresholds** (`gate/rigor_lib/perf_judge.py`). `c1` and `c2` are the counts at the first and the last size
(`n1`, `n2`, `k = n2 / n1`, normally 4), for `instructions` and for `libc_bytes`; either counter above its limit fails:

| class | allowed `c2` |
|---|---|
| O(1) | `floor(1.10 * c1) + 16` |
| O(log n) | the larger of `floor((1 + log2(k) / 4) * c1) + 16` (ratio 1.5 at k = 4: exact for pure log growth from n1 >= 16) and `c1 + max(64, c1 / 10) + 16` |
| O(n) | `floor(1.10 * k * c1) + 16` (4.4 at k = 4) |
| O(n log n) | `floor(1.10 * k * log2(n2) / log2(n1) * c1) + 16` (`log2(max(n1, 2))`; 5.1 for 4000 -> 16000) |

The `+ 16` is the counter's jitter floor (a count of 0 at both sizes is inside every class). The ratio part is the
class's own growth plus 10 %; the classes nest (a lower class's limit is never above a higher class's).
Measured on the `selftest/perf.sh` fixtures (honest class, `instructions`; `libc_bytes` of the same fixtures are either 0
or linear, the same way):

| fixture | class | counts | ratio | limit | headroom |
|---|---|---|---|---|---|
| `flat` (hash set, 64 lookups) | O(1) | 1473 -> 1573 | 1.068 | 1636 | 3.9 % |
| `bsearch` (64 binary searches) | O(log n) | 7816 -> 9053 | 1.158 | 11740 | 22.9 % |
| `lin` (one pass) | O(n) | 11551 -> 46051 | 3.987 | 50840 | 9.4 % |
| `nlogn` (heapsort) | O(n log n) | 401506 -> 1915509 | 4.771 | 2088849 | 8.3 % |
| `quad` (all pairs) | none | 606733 -> 9551984 | 15.743 | | outside all four |

The class matrix is exact on these: each fixture is inside the classes at or above its own and outside the ones below
(`quad` outside all). The O(1) fixture is the tight one: an open-addressing set has a data-dependent probe count, so even
the honest 64 lookups grow 6.8 % from 2000 to 8000 keys; a driver for an O(1) class should do a fixed work whose
probe lengths do not depend on the load (or declare O(log n)).

**Findings of the `perf` gate** (`gate/rigor_lib/perf_gate.py`, after the test gates, before `mutants`):
`perf-class-exceeded` (error: `module`, `target`, `class`, `counter`, `n1`, `n2`; the counts, `ratio` and `limit` are in the metadata, `targets.<label>.exceeded`, because a count can move by a few instructions between workers),
`perf-counter-unavailable` (error: the counter could not be read on the worker, so there is no verdict without counts),
`perf-record-bad` (error: `status` of the first record that is not `ok`, or fewer than two records),
`perf-build-failed` (error). No perf targets: PASS with info `no-perf-targets`. The step writes `gate-perf/` and the root
`PACKAGE` file into the grading tree, builds the targets in `toolchains//:linux_release` (`--no-remote-cache` with
`--uncached`) and removes both again. Metadata: the summarised records of every target, the `exceeded` evidence and the `cpu` of the run.

**Perf kills.** The same targets run for the mutants that survive the tests: `docs/mutate.md`, "Perf kills".
Canary `perf-class-exceeded`: an O(n^2) driver declared O(n) (`canaries/perf-class-exceeded/policy.toml`), red in
`perf` only; `control` has no perf targets and stays green.
