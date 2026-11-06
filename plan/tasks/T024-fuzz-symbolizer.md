# T024: symbolized, readable fuzz crash reports (rest of backlog B9)

Repo: `Mivr/c-rigor-gate`. Branch `task/T024`. Read `AGENTS.md`, `docs/toolchain.md`, `docs/ctest.md`,
`rules/c.bzl` (`c_fuzz`), `rules/ctest.bzl` (how T016 wired the symbolizer for `san`), `toolchains/**`.
**T013, T021, T022 and T023 run in parallel**: don't touch `gate/rigor_lib/**`, `tools/lanes/**`, or `rules/facts.bzl`;
in `rules/c.bzl` change only `c_fuzz`.

## Why
T016 symbolized `san` test reports, but `c_fuzz` runs still print bare addresses, and a crash input goes to
`-artifact_prefix=/tmp/` on the RE worker, where nobody can read it. An agent can't reproduce a fuzz crash.

## Allowed paths
`rules/c.bzl` (`c_fuzz` only), `rules/ctest.bzl` (only to share the env helper), `toolchains/**`,
`selftest/toolchain.sh` or a new `selftest/fuzz.sh`, `selftest/fuzz_product/**` (new), `docs/toolchain.md`,
`docs/ctest.md`, `plan/backlog.md` (mark B9 done).

## Requirements
1. Fuzz runs get the hermetic `llvm-symbolizer` (`ASAN_SYMBOLIZER_PATH`, `LLVM_SYMBOLIZER_PATH`, `symbolize=1`) as
   a declared input, the same way as T016. Keep every option that makes failures fatal; never weaken them.
2. A crash writes its input into a declared output of the fuzz action (not `/tmp`), so `buck2 build
   //x:fuzz[crash]` (or the documented equivalent) gives the reproducer, and the report (symbolized, paths
   relative to the repo root, no absolute worker paths) is readable next to it.
3. Deterministic: same seed, same runs, same verdict and report bytes across two cold runs; a warm run executes 0
   actions. A passing fuzz run's outputs don't vary between runs.
4. A crashing fuzz target still fails its test. Nothing in the report or the crash file can turn a fail into a pass.

## Self-test
A fuzz target with a heap overflow reachable from a 4-byte magic prefix, and one with a signed-overflow UBSan
report: each must fail, name the right `file:line function`, and give the crash input as a readable output that
reproduces the failure when fed back. A clean fuzz target passes. Report cold and warm action counts.

## Acceptance
```sh
selftest/fuzz.sh        # or the selftest you extend
selftest/toolchain.sh
selftest/ctest.sh
selftest/gate.sh
```
