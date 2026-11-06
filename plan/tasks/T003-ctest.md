# T003: `ctest` framework, test results as cached build artifacts

Repo: `Mivr/c-rigor-gate`. Branch `task/T003`. Read `AGENTS.md`, `plan/phase1.md`, `docs/toolchain.md` first.
T002 (Python gate driver, `gate/**`) runs in parallel; do not touch its paths.

## Goal
A tiny C17 test framework whose results are machine-readable, fail closed, and produced as a **Buck2 build
artifact** (so a verdict is cached until an input changes, like club-apps' mutant verdicts), consumed later
by `gate/rigor tests`.

## Allowed paths
`ctest/**`, `rules/**`, `examples/**`, `selftest/ctest.sh`, `docs/ctest.md`.
Do not weaken anything in `selftest/toolchain.sh` (you may extend it only if a rules change requires it).

## Framework (`ctest/ctest.h`, `ctest/ctest.c`, built with the T001 macros and sealed flags)
- Tests are plain functions `static void t_<name>(ctest_t *t)`. Registration is an **explicit table** in the
  test file: `CTEST_SUITE("suite", { "name", t_name }, ...)` which defines `main`. No constructors, no linker
  sections, no global registry.
- Checks: `CHECK(t, cond)`, `CHECK_EQ_I64(t, a, b)`, `CHECK_EQ_U64`, `CHECK_EQ_STR(t, a, b)` (NUL-terminated),
  `CHECK_EQ_MEM(t, a, alen, b, blen)`. Each executed check increments the test's assert count; a failed check
  records file:line and the values, and the test continues (so one run reports all failures).
- **There is no skip, no expected-failure, no way to mark a test as passing other than its checks.**
- Each test runs in its own `fork()`ed child with a per-test timeout (default 10 s, fixed, not configurable from
  the test file). The parent records `pass` only if the child exited 0 **and** reported its counts back over a
  pipe and had no failed check. Crash (signal), sanitizer abort, `exit()` from inside the test, timeout, or a
  missing report is `fail` with a reason field. A test whose child calls `_exit(0)` early must not pass.
- Order: tests run in an order shuffled by `--seed N` (deterministic PRNG, default seed 1).
- Output: JSON Lines to the path given by `--out FILE` (required when run by the results rule, stdout otherwise):
  `{"id":"<suite>/<name>","status":"pass"|"fail","asserts":N,"reason":"..."}` per test, then
  `{"summary":{"total":N,"passed":M}}`. This is the exact format `gate/rigor tests` parses (see
  `plan/tasks/T002-gate-kernel.md` item 3): `id`, `status`, `asserts`, and `summary` with `total`/`passed`.
  Strings JSON-escaped correctly (test names are restricted to `[a-z0-9_]+`; reject others at startup).
- Exit code: 0 iff all tests passed; 1 otherwise; 2 on usage or framework error.
- The framework itself stays within the AGENTS.md C rules (small functions, no recursion, no malloc).

## Rules integration (`rules/c.bzl`)
- `c_test(name, srcs, deps)` links `ctest` automatically and additionally defines `<name>_results`: a build
  action that runs the test binary **on RE** with `--seed 1 --out results.jsonl` and outputs that file.
  The action must succeed (and still emit the file) when tests fail, so the gate sees the failure rather than a
  missing artifact; the gate decides. It must fail only if the binary could not run at all.
- `<name>_results` exists in `release` and `san` modes (`buck2 build --target-platforms ...` selects); `buck2 test`
  on `<name>` keeps working as today.
- Port `examples/hello`'s test to ctest.

## Self-test `selftest/ctest.sh` (bash + stdlib Python)
Build a throwaway package with tests that: pass; fail a check; have zero checks; segfault; abort via ASan
(in san mode); `_exit(0)` early; `exit(0)` early; loop forever (timeout); depend on run order (passes with one
seed, fails with another). Assert the JSONL for each is exactly right, the summary agrees, exit codes are right,
and that `<name>_results` for an unchanged test is a cache hit on the second build (0 actions executed).

## Acceptance (orchestrator re-runs)
```sh
selftest/ctest.sh          # exit 0, twice in a row
selftest/toolchain.sh      # still exit 0
```
Report: the public API, the JSONL produced for each self-test case, the cache-hit evidence, deviations.
