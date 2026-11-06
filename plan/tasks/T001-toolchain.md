# T001: hermetic C toolchain on Buck2 + RE, four modes, macro skeleton

Repo: `Mivr/c-rigor-gate`. Branch `task/T001`. Worktree given in your prompt. Read `AGENTS.md` and
`plan/phase1.md` first.

## Goal
A Buck2 project in this repo that compiles, links and tests C17 **entirely on the remote execution farm**, with
a toolchain and sysroot that Buck2 fetches by sha256, so no host or worker-image compiler, header or library is
ever used. Products will later consume `toolchains/` and `rules/` from this repo as a cell.

## Allowed paths
`.buckconfig`, `.buckroot`, `.gitignore`, `tools/buck2`, `tools/buck2.version`, `toolchains/**`, `rules/**`,
`examples/**`, `selftest/**`, `docs/toolchain.md`. Nothing else.

## Environment facts
- Buck2 binary: `/usr/local/bin/buck2`, sha256 `400f5fde930a62ff6f64513fb5a7e88fa1847afa85758cadd9484dc93446fa94`.
  Write `tools/buck2` as a wrapper that refuses to run if the binary's sha256 differs from `tools/buck2.version`.
  Use the prelude **bundled** in that binary (`[external_cells] prelude = bundled`), so prelude and binary match.
- RE: `grpc://forge.internal:9092` for engine, action cache and CAS, `tls = false`, concurrency limit 64.
  A working reference config (read-only, do not modify) is
  `/data/club-apps/orca-workspaces/club-apps/repo/Club-apps-work/.buckconfig` and its `toolchains/BUCK`
  (look at how the RE execution platform, `exec_properties` and the worker image digest are defined there).
- Host: no sudo, no Docker, only `/var/tmp` writable. Host clang 18 is bare (no sanitizer runtimes,
  no clang-tidy, no llvm-cov). **Do not use it.** Downloads for sha256 computation go to `/var/tmp/cache/T001/`.
- Allowed downloads: an official LLVM release tarball from `github.com/llvm/llvm-project/releases`
  (LLVM 18.x or 19.x, for Mull compatibility later) and a glibc sysroot from a reputable pinned source
  (for example the Chromium Debian bullseye amd64 sysroot from `commondatastorage.googleapis.com`).
  Pin each by sha256 in Buck2 `http_archive`/`http_file`.

## Requirements
1. **Toolchain:** `cxx_toolchain` built from the fetched LLVM + sysroot (`--sysroot`, `-nostdinc` + explicit
   include dirs or equivalent). Keep per-action inputs small: expose only the binaries, resource dir and
   runtime libraries actually needed (not the whole multi-GB release tree). Clang resource dir with the
   compiler-rt sanitizer, profile and fuzzer runtimes must come from the fetched release.
2. **Execution:** every compile, link and test runs remotely (no local fallback for these). Target platform is
   linux-x86_64.
3. **Modes:** `release` (`-O2`), `san` (`-O1 -g -fsanitize=address,undefined,leak -fno-sanitize-recover=all
   -fno-omit-frame-pointer`), `cov` (`-fprofile-instr-generate -fcoverage-mapping -fcoverage-mcdc`),
   `fuzz` (`-fsanitize=fuzzer,address,undefined`). Select with a single documented switch (a constraint plus
   platform, or a modifier), for example `tools/buck2 test //... -m san` or `--target-platforms ...`.
   Document the exact command for each mode in `docs/toolchain.md`.
4. **Sealed flags:** every mode always uses
   `-std=c17 -Wall -Wextra -Wpedantic -Werror -Wconversion -Wsign-conversion -Wshadow -Wcast-qual -Wvla
   -Wstack-usage=512 -Wformat=2 -Wnull-dereference -Wimplicit-fallthrough`, appended **after** anything a
   target could contribute.
5. **Macros** in `rules/c.bzl`: `c_library(name, srcs, headers, deps, visibility)`,
   `c_binary(name, srcs, deps)`, `c_test(name, srcs, deps)`, `c_fuzz(name, srcs, deps)`. They accept **no**
   flag arguments (`compiler_flags`, `preprocessor_flags`, `linker_flags`, `copts` ... must not exist). A
   `c_test` is any binary that exits 0 on success; the real framework comes in T002.
6. **Examples:** `examples/hello` (library + binary + test), `examples/bad/` targets that must fail:
   `warn` (unused variable: must fail to build), `ubsan` (signed overflow: test must fail under `san`),
   `asan` (heap overflow: test must fail under `san`), `leak` (must fail under `san`),
   `fuzzme` (a `c_fuzz` target with a planted crash reachable from a 4-byte input).
7. **Self-test** `selftest/toolchain.sh` (bash + stdlib Python only): runs every acceptance check below and
   exits non-zero on the first failure, printing which check failed. It must assert that the "bad" examples
   **fail for the right reason** (grep the sanitizer report kind), not just that they fail.

## Acceptance commands (the orchestrator re-runs these)
```sh
tools/buck2 build //examples/hello:hello                  # remote
tools/buck2 test //examples/hello/...                     # release
tools/buck2 test //examples/hello/... <san switch>
tools/buck2 test //examples/hello/... <cov switch>  &&  coverage report via the fetched llvm-cov/llvm-profdata
selftest/toolchain.sh                                      # all checks, exit 0
tools/buck2 build //examples/hello:hello && tools/buck2 log what-ran   # second build: 0 actions executed
```
`selftest/toolchain.sh` must also check:
- **hermeticity:** no compile or link command line references `/usr/include`, `/usr/lib`, `/lib`, or the host
  clang; inputs come only from the fetched archives (use `buck2 aquery` / `what-ran` / `-v` output);
- **remote:** `what-ran` shows the compile, link and test actions executed on RE, not locally;
- **sealed flags:** a target cannot turn `-Werror` off (prove that the macros reject a flag argument and that
  `examples/bad/warn` fails);
- **fuzz:** the `fuzzme` target finds its crash with `-seed=1 -runs=200000` (deterministic).

## Report
What you built, the exact output of each acceptance command (trimmed to the relevant lines), the pinned URLs and
sha256s, per-action input size, wall time of a cold and a warm build, and every deviation or unresolved issue.
