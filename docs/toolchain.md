# Hermetic C toolchain (T001)

Everything compiles, links and tests on the RE farm (`grpc://forge.internal:9092`, concurrency 64) with a
toolchain and sysroot that Buck2 downloads by sha256. Nothing on the host or in the worker image is used for
compiling or linking: no host clang, no `/usr/include`, no `/usr/lib`.

## Pins

| What | URL | sha256 |
|---|---|---|
| Buck2 client | `/usr/local/bin/buck2` (`tools/buck2.version`; `tools/buck2` refuses any other binary) | `400f5fde930a62ff6f64513fb5a7e88fa1847afa85758cadd9484dc93446fa94` |
| Prelude | bundled in that binary (`[external_cells] prelude = bundled`) | n/a |
| LLVM 19.1.7 | `https://github.com/llvm/llvm-project/releases/download/llvmorg-19.1.7/LLVM-19.1.7-Linux-X64.tar.xz` | `4a5ec53951a584ed36f80240f6fbf8fdd46b4cf6c7ee87cc2d5018dc37caf679` |
| glibc sysroot (Chromium Debian bullseye amd64) | `https://commondatastorage.googleapis.com/chrome-linux-sysroot/f851add76bdae472fb6c94b4f920bc4a132d85ac607951391297f636af7e934e` | `f851add76bdae472fb6c94b4f920bc4a132d85ac607951391297f636af7e934e` |

`toolchains/fetch.bzl` (`fetched_tree`) downloads each archive (hash-checked) and runs `tar` on RE to unpack only
the listed members, so the 7 GB LLVM release becomes a ~0.9 GB tree and each action sees only the sub-paths it
names (`toolchains/tools.bzl`, `.project(...)`). A pattern that matches nothing fails the build.

## Modes

A mode is a target platform. The default (`[parser] target_platform_detector_spec`) is `release`.

| Mode | Command | Flags |
|---|---|---|
| release | `tools/buck2 test //...` | `-O2` |
| san | `tools/buck2 test --target-platforms toolchains//:linux_san //...` | `-O1 -g -fsanitize=address,undefined,leak -fno-sanitize-recover=all -fno-omit-frame-pointer` |
| cov | `tools/buck2 test --target-platforms toolchains//:linux_cov //...` | `-fprofile-instr-generate -fcoverage-mapping -fcoverage-mcdc` |
| fuzz | `tools/buck2 test --target-platforms toolchains//:linux_fuzz //...` | `-fsanitize=fuzzer,address,undefined` (+ `-O1 -g -fno-sanitize-recover=all -fno-omit-frame-pointer`) |

Coverage report (line, branch, MC/DC), also on RE, via the fetched `llvm-profdata` / `llvm-cov`:

```sh
tools/buck2 build --target-platforms toolchains//:linux_cov //examples/hello:hello_test_coverage --show-output
```

`c_binary` and `c_test` are incompatible with `fuzz` (libFuzzer supplies `main`); `c_fuzz` is only built in `fuzz`.
`c_fuzz` is a test that runs `-seed=1 -runs=200000` as a cacheable RE action (see "Fuzz runs" below); it fails when
the fuzzer finds a crash.

## Sealed flags

`rules/c.bzl` appends `-std=c17 -Wall -Wextra -Wpedantic -Werror -Wconversion -Wsign-conversion -Wshadow
-Wcast-qual -Wvla -Wframe-larger-than=512 -Wformat=2 -Wnull-dereference -Wimplicit-fallthrough` after the mode
flags. The macros `c_library`, `c_binary`, `c_test`, `c_fuzz` have no flag parameters.

## Known limits (deviations)

- clang has no `-Wstack-usage`; `-Wframe-larger-than=512` is used instead.
- Tools (clang, lld, llvm-*) and test binaries dynamically load the worker image's glibc/libstdc++/libz/libxml2/ICU
  at run time. Headers, link libraries, crt files and sanitizer runtimes come only from the pinned archives.
- `python_bootstrap` and `genrule` toolchains use the worker's `python3` and `/bin/sh` (script interpreters only).
- Sanitizer reports in `<name>_results` and in `c_fuzz` runs are symbolized with the pinned `llvm-symbolizer` (see below).

## Sanitizer symbolization

`llvm-symbolizer` comes from the pinned LLVM tarball (`toolchains//:llvm-symbolizer`) and is a declared input of the
`<name>_results` action, so it is cached and runs on RE; no host symbolizer is ever looked up. `rules/ctest.bzl`
exports `ASAN_SYMBOLIZER_PATH` and `LLVM_SYMBOLIZER_PATH` (absolute paths to it) and these options (details in
`docs/ctest.md`): `symbolize=1`, `fast_unwind_on_malloc=0`, `strip_path_prefix=<exec root>/`, `log_path`, and the
fatal settings `halt_on_error=1`, `abort_on_error=0`, `detect_leaks=1` (the compile flags keep
`-fno-sanitize-recover=all`).

## Fuzz runs

`c_fuzz(name = "fz")` defines `fz__bin` (the libFuzzer binary) and `fz` (rule `fuzz_run`, rules/ctest.bzl). `fz` is a
build action on RE with the same hermetic symbolizer and the same fatal sanitizer options as `<name>_results`
(`sanitizer_env_lines`, no `log_path`; reports stay on stderr), running `fz__bin -seed=1 -runs=200000
-artifact_prefix=<scratch>/`. It always produces its outputs; `buck2 test` of `fz` only reads the verdict.

| Output | Command | Content |
|---|---|---|
| `fz[report]` (default output) | `tools/buck2 build --target-platforms toolchains//:linux_fuzz //x:fz[report] --show-output` | the symbolized sanitizer/libFuzzer report: `file:line function` frames, repo-relative paths, no PIDs, addresses (`0xADDR`) or worker paths, runtime-internal frames dropped |
| `fz[crash]` | `... //x:fz[crash] --show-output` | the crash input (libFuzzer's `crash-*`/`timeout-*`/`oom-*`/`leak-*` file) as a file; empty when the run passed. Replay: `fz__bin <file>` |
| `verdict` | | `pass`, or `fail rc=<exit status>` |

The verdict is written by the action script after the target exits, from its exit status; it is `pass` only for exit 0
and libFuzzer's own `Done 200000 runs` line. Nothing in the report or the crash file is read back by the test, so
none can turn a fail into a pass. Outputs are byte-identical across cold runs (the report keeps only deterministic
lines); a warm run executes 0 actions. Self-test: `selftest/fuzz.sh`.

Self-test: `selftest/toolchain.sh`. Its remote-execution step asserts on the fresh-nonce actions only: every compile, archive, link and test run of the stamped scratch targets must be `re(...)`, and no action anywhere may be `local`. Unchanged dependencies (the fetched LLVM and sysroot, ctest) may be `cache` or `re`, because whether they appear as cache hits depends on farm and daemon history, not on the product.
