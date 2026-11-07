# perf: deterministic cost counts for performance tests (`c_perf`)

The building block of the later `perf` gate (R011, B13). `c_perf` builds a perf binary from a module and a
gate-held generator and driver, runs it on RE and produces a cacheable `perf.jsonl` of **cost counts** at
two or more input sizes. It gives no verdict; a later gate compares the counts at `n` and `4n`.

## The rule

```python
load("@gate//rules:c.bzl", "c_perf")
c_perf(name = "parse_perf", module = ":parse", srcs = ["gen.c", "drv.c"], deps = [], sizes = [1000, 4000], seed = 1)
```

- `module` is the `c_library` under test; `srcs` are the gate-held generator and driver sources (plain `.c` names,
  same checks as `c_binary`); `deps` are further libraries.
- Targets: `<name>` (the binary) and `<name>_perf` (the action; its output is `perf.jsonl`).
- **Release only** (`target_compatible_with = toolchains//:release`): `-O2`, the sealed warnings. The rule adds the
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
| `instructions` | user-mode retired instructions (`exclude_kernel`, `exclude_hv`) of one `perf_run`; `null` when unavailable | yes (see below) |
| `libc_bytes` | sum of `len` over the wrapped libc calls during one `perf_run` | yes |
| `result` | what `perf_run` returned | yes |
| `wall_ns_median` | median of the 7 runs, wall clock | **no**: depends on the worker and its load; an informational cross-check only |

When `status` is not `ok` the record carries `input_len` (and `signal`/`exit_code`) and **no counts**: never a zero.

## Determinism

`instructions` and `libc_bytes` are the **median of 7 counted runs**. The first run is cold (lazy symbol binding and
first page touches add about 1.5e3 instructions) and is never the median; the warm runs differ by at most 1
instruction (counter skid), so the median is stable. `selftest/perf.sh` builds each fixture twice (two copies whose
sources differ in a comment, so compile, link and run all re-execute) and requires identical `n`, `input_len`,
`instructions`, `libc_bytes` and `result`. R011 measured identical ratios across 10 actions on two farm workers.
Counts are from the same binary on the same CPU model; a different CPU model or libc build may shift absolute counts
by a small constant, never the ratio.

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
`gate/rigor_lib/perf_bundle.py` loads and validates it; `rigor grade --perf DIR` binds it; nothing judges it yet.

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
