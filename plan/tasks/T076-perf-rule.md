# T076: `c_perf` rule: deterministic cost counters for hidden performance tests (R011 task 1, B13)

Repo: `Mivr/c-rigor-gate`. Branch `task/T076`. Read `AGENTS.md` ("Working efficiently"), `rules/c.bzl` (`c_test`, the sealed
flags), `rules/ctest.bzl` (`ctest_results`), `ctest/ctest.h`, `docs/grade.md`, and the R011 design summary
`/var/tmp/cache/T076/R011-report.md`. R011's farm probe is in `/var/tmp/cache/T076/` (`probe.c`, `probe.bzl`, `BUCK`;
read-only, a starting point, not a design).

## Goal
The building block for a later `perf` gate: a Buck2 rule that builds a perf binary from a module, a gate-held
generator and driver, and produces a cacheable `perf.jsonl` of **cost counts** at two input sizes. No gate, no
bundle and no verdict yet; those are later tasks.

## Requirements
1. `c_perf(name, module, srcs, deps = [])` in `rules/c.bzl`, or a new `rules/perf.bzl` loaded from it.
   - `srcs` are the generator and driver sources.
   - It links the module's library and deps with the sealed release flags (`-O2`, same warnings).
   - It is built in **release only**.
   - It produces an RE action `<name>_perf` that runs the binary and writes `perf.jsonl`.
2. A gate-owned C harness `ctest/perf.c` and `ctest/perf.h`. The driver implements
   `size_t perf_gen(uint64_t seed, size_t n, char *out, size_t cap)` and `uint64_t perf_run(const char *in, size_t len)`.
   - The harness generates the input at each size outside the counted region, then counts **only** the `perf_run` call.
   - It records, per size: user-mode **instructions** via `perf_event_open` (`exclude_kernel`, `exclude_hv`);
     **libc bulk bytes** (the sum of `len` over `memcpy`, `memmove`, `memset`, `memcmp`, `strlen`/`strnlen`, through
     `-Wl,--wrap=...` set by the rule, never by the product); and wall nanoseconds (median of 7).
   - Sizes and the seed come from rule attributes (`sizes = [n, 4n]`, `seed`), never from the environment.
3. Fail closed. If `perf_event_open` fails, the record says `"counter": "unavailable"` with the errno, and the action
   still succeeds so the later gate can report `perf-counter-unavailable`. If `perf_gen` overflows `cap`, the run
   crashes, or `perf_run` returns an error sentinel, that is a record with `status` set accordingly, never a silent zero.
4. Determinism: the instruction and byte counts are identical across two cold runs (check it, as R011 did). Put the
   wall time in a separate field, documented as non-deterministic.
5. Selftest: `selftest/perf.sh` builds three small fixtures in a scratch package:
   - an O(n) loop, whose instruction ratio for k=4 is in [3.5, 5];
   - an O(n^2) loop, whose ratio is at least 12;
   - an O(n^2) `memmove` compaction, whose **byte** ratio is at least 12 while its instruction ratio is low.

   Two cold builds must give identical counts. Register it in `tools/affected.toml` and `tools/validate.sh` the
   way the other selftests are.
6. Docs: `docs/perf.md` (rule, harness API, record format, determinism, the libc wrap list and its limits: inlined
   fixed-size copies are not counted).

## Allowed paths
`rules/c.bzl`, `rules/perf.bzl` (new), `rules/ctest.bzl` (only if the runner is shared), `ctest/perf.c`, `ctest/perf.h`,
`ctest/BUCK`, `selftest/perf.sh` (new), `tools/affected.toml`, `tools/validate.sh` (registration only), `docs/perf.md`
(new), `gate/tests/test_affected*.py` (only if registration needs it).
**In flight in parallel:** T070 (`grade_mutants.py`, `selftest/mutate.sh`), T073 (grade pipeline, `order.txt`), T074 (trajectory),
T067 in validation (`mutate/tool.py`). Do not touch their files.

## Acceptance
```sh
selftest/perf.sh            # twice (cold keys), identical counts
selftest/ctest.sh
selftest/gate.sh
```
Report the measured ratios for the three fixtures, the determinism check, the record format, and every deviation.
