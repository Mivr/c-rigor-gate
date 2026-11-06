# T016: symbolized sanitizer and crash reports in test results (backlog B9)

Repo: `Mivr/c-rigor-gate`. Branch `task/T016`. Read `AGENTS.md`, `docs/toolchain.md`, `docs/ctest.md`,
`rules/ctest.bzl`, `toolchains/**`, `ctest/ctest.c`. **T011, T014 and T015 run in parallel**: don't touch
`gate/rigor_lib/**` (except `results_parse.py`, and only if the results format gains a field), `rules/c.bzl`
or `structure*`.

## Why
ASan, UBSan and LSan reports in `san` (and the fuzz mode) come out unsymbolized, as bare addresses. Agents waste
turns guessing where a fault is. The hermetic LLVM tarball already contains `llvm-symbolizer`.

## Allowed paths
`rules/ctest.bzl`, `rules/cov.bzl` (if fuzz or cov runs share the runner), `toolchains/**`, `ctest/**`,
`gate/rigor_lib/results_parse.py` (only if needed), `gate/tests/test_results*.py`, `selftest/ctest.sh`,
`selftest/toolchain.sh`, `docs/ctest.md`, `docs/toolchain.md`, `plan/backlog.md` (mark B9).

## Requirements
1. Test actions in `san` (and fuzz runs) get `ASAN_SYMBOLIZER_PATH` and `LLVM_SYMBOLIZER_PATH` pointing at the
   hermetic `llvm-symbolizer` from the pinned tarball, declared as an action input so it is cached and
   remote-executable. Also `ASAN_OPTIONS`/`UBSAN_OPTIONS` with `symbolize=1` and stable settings, documented. Keep
   every existing option that makes failures fatal (`halt_on_error`, `abort_on_error` and so on), and never
   weaken them.
2. When a test dies of a sanitizer report or a signal, its `reason` in the results JSONL includes the first
   symbolized frame of the product's own code (`file:line function`), truncated to a fixed length. The full report
   goes to a sibling artifact `<name>_san_report` (or the existing log artifact) so the agent can read it, and
   the paths are relative to the repo root, never absolute RE worker paths. Output must stay deterministic
   between runs, so the action cache key doesn't change: no PIDs, no addresses in `reason`.
3. Results integrity is unchanged: the report can't be forged into a pass. Re-read how ctest guards its shared
   page, and keep it.

## Self-test
In `selftest/ctest.sh`: a heap overflow, a use-after-free, a signed-overflow UBSan report, a leak, and a SIGSEGV.
Each must produce a `reason` naming the right `file:line function`, be byte-identical across two cold runs, and
execute 0 actions on a warm run.

## Acceptance
```sh
selftest/ctest.sh
selftest/toolchain.sh
selftest/gate.sh
```
