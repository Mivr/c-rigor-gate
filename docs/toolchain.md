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

## Verified reuse for `--uncached` grades (T030)

`--no-remote-cache` makes every action run, including `fetched_tree llvm` (single-threaded `tar -xJf` of the 1.6 GB
archive, about two minutes, once per Buck2 daemon). The action cache is client-writable (backlog B4), so the tree
cannot just be trusted from it. Design:

- `toolchains/llvm.manifest` and `toolchains/sysroot.manifest` list every member of the extracted trees (directory,
  file with exec bit, size and sha256, symlink with target). They are gate files (`toolchains/**`), covered by the
  gate-clean check, and a change to one is a review item of its own.
- The `toolchain` gate of `rigor grade` (`gate/rigor_lib/grade_toolchain.py`, T073; `docs/grade.md`) runs right after
  `assemble`, before any gate that compiles, and does this in the head tree's daemon (`toolchain_verify.prepare`):
  (1) `build toolchains//:{llvm,sysroot}_ref`, cache allowed, nothing materialised, so the tree comes from the action
  cache (the unpack runs only when the cache truly lacks it); (2) `build --no-remote-cache
  toolchains//:{llvm,sysroot}_verified`: the `verified_tree` rule (`toolchains/fetch.bzl`) runs
  `toolchains/verify_tree.py` on a worker, uncached, over the very tree of step 1 and compares every name, type,
  exec bit, size, link target and sha256 with the manifest. Buck2 keeps that tree in the daemon, so the compile and
  link actions of the builds that follow consume the digest that was verified. Warm cost: about 8 s.
- Any difference (flipped byte, mode, extra or missing file or directory, retargeted link, special file) fails the
  verify action, and the grade reports it as the `toolchain` gate's FAIL `toolchain-mismatch` (manifest, first
  differing path, step, buck2 and verifier exit codes), never as the product's `build-failed`: every gate that
  compiles is NOT_RUN, the verdict is FAIL, exit 1. It never falls back to a re-fetch. The verify action being
  answered from a cache is also refused (`log what-ran`). A cached grade verifies nothing (`toolchain` PASS with
  info `toolchain-not-verified`).
- Later daemons: gates that kill their daemon (`build`, `structure`, `mode-divergence`, `mutants`, the witness tree)
  make the next uncached `buck2 build` start a fresh one, which `grade_build.run_buck` re-primes with the same two
  steps first. So the verify action runs once per daemon, as before T073; in the daemon the gate primed nothing
  re-executes. A re-check that fails after `toolchain` passed is an internal error (exit 2).
- Not covered: cached builds (`--uncached` absent) still trust the cache, as before; the worker's `python3` runs the
  verifier; the fetched archive itself is sha256-pinned by `download_file`.
- Regenerating the manifests: `toolchains/gen_manifests.sh` (a real, uncached unpack; deterministic, so a second
  run leaves `git diff` empty). Bootstrapping a new pin needs empty `*.manifest` placeholder files first (the BUCK
  file names them as sources).
- Tests: `gate/tests/test_toolchain_verify.py`, `gate/tests/test_grade_toolchain.py`; the last step of
  `selftest/grade.sh` grades with a scratch gate copy whose `llvm.manifest` has one sha256 flipped (`toolchain` FAIL).

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

## WebAssembly (wasm32)

Why (P008, owner decision D18): the staff bot's operations are C17 static-memory modules that run inside a Cloudflare
Worker as WebAssembly. The C decides; the Worker does every I/O. A product builds the `.wasm` from the very
`c_library` modules it tests natively.

**Toolchain.** No new download: the pinned LLVM 19.1.7 tree already holds `clang-19` (with its WebAssembly backend),
the multi-call `bin/lld` and clang's builtin headers. `toolchains/BUCK` adds:

- `toolchains//:wasm32_release`, a target platform with cpu `toolchains//:wasm32`, os `prelude//os/constraints:none`
  and mode `release`. The cpu is a gate-owned constraint (setting `toolchains//:wasm_cpu`, which no other platform
  sets): the pinned bundled prelude has no `prelude//cpu/constraints:wasm32` (its `prelude//cpu:wasm32` is a
  `config_setting`, not a constraint value), and a select key the gate owns cannot drift with the prelude. The first
  version named the missing prelude label, which broke the analysis of every target, native ones included, because
  `toolchains//:cxx` selects on it. `gate/tests/test_toolchain_labels.py` now guards this without Buck2: every
  `prelude//cpu|os/constraints:*` label in `toolchains/` and `rules/` must be one the pinned prelude has, and every
  `toolchains//:` label (and every `":name"` select key or platform attribute in `toolchains/BUCK`) must be a target
  that `toolchains/BUCK` defines;
- `toolchains//:wasm_cc` (`wasm_cc` in `toolchains/tools.bzl`): `clang-19 --target=wasm32-unknown-unknown -nostdinc
  -ffreestanding -nostdlib`, then exactly two include directories, `-isystem <clang's builtin headers>` and `-isystem
  toolchains/wasm/include`. No sysroot;
- `toolchains//:wasm_ld`: `lld -flavor wasm` (that is, wasm-ld), and the `cxx_wasm` C toolchain built from both (the
  archiver is the same pinned `llvm-ar` as on Linux). `toolchains//:cxx` selects it on `toolchains//:wasm32`, before the
  android and Linux choices, which are unchanged.

The mode is `release`, so a wasm32 object gets exactly the native release compile flags: `-O2`, the hardened release
flags (`-ftrivial-auto-var-init=zero -fstrict-flex-arrays=3`) and the whole sealed warning set above, with `-Werror`.
There are no sanitizer, coverage or fuzz flags and no wasm32 variant of those modes.

**Freestanding headers, and why there is no libc.** A module that runs in a Worker has no file system, clock,
environment, process or allocator of its own: the Worker passes everything in through linear memory and the exported
functions. That is already the C rule of the products (pure core, injected ports, static memory), so a libc would only
add code that must never be called. The include path is therefore clang's builtin headers (`stdint.h`, `stddef.h`,
`stdbool.h`, `limits.h`, `float.h`, `stdarg.h`, `stdalign.h`, `stdnoreturn.h`, `iso646.h`, ...: types and macros,
no functions) plus the gate's `toolchains/wasm/include/string.h`, which declares only `memcpy`, `memmove`, `memset`,
`memcmp`, `strlen`, `strcmp`, `strncmp` and `strchr`. Any other libc or POSIX header (`stdio.h`, `stdlib.h`,
`errno.h`, `unistd.h`, `inttypes.h`, ...) does not exist for wasm32 and fails the compile with clang's
`fatal error: 'stdio.h' file not found`; they are deliberately not stubbed. The eight functions are implemented by
`toolchains/wasm/rt/fsl.c` (plain byte loops, no allocation, no state), which `c_wasm` compiles with the same flags
and links into every module. clang may also call `memcpy`, `memmove` and `memset` itself (struct copies,
zero-initialisation); those calls land there too. Not supported here: WASI, threads, SIMD, exceptions.

**`c_wasm(name, deps, exports, stack_bytes = 65536, memory_pages = 32)`** (`rules/c.bzl`, `rules/wasm.bzl`). `deps` are
`c_library` targets. The macro configures them to `toolchains//:wasm32_release` itself (a configuration transition on
the `deps` attribute), so the module is built by its label alone, under the default platform:

    tools/buck2 build //examples/wasm:tally_wasm --show-output

The same command with `--target-platforms toolchains//:wasm32_release` builds the identical module (the selftest
compares the bytes). Never build a whole package (`//pkg/...`) for that platform: its `c_test` and the facts targets
would be configured for wasm32 too. The transitive sources of `deps` are compiled and archived by the prelude with
`cxx_wasm`; `c_wasm` then links the archives of the whole link closure and `fsl.c` with

    lld -flavor wasm --no-entry --export=<each of exports> -z stack-size=<stack_bytes>
        --initial-memory=<memory_pages * 65536> --max-memory=<the same> --strip-debug

and the output is `<name>.wasm`. Memory is fixed (initial = maximum) and the module exports its `memory` plus exactly
the listed functions. An undefined symbol (a call to anything that is neither in the deps nor in `fsl.c`) is a link
error, as is an export that no dep defines. A dep that links a system library (`system_libs`) fails the analysis.
The macro checks `exports` (non-empty C identifiers, no duplicates), `stack_bytes` (a positive multiple of 16, less than
the memory) and `memory_pages` (1 to 65536). `c_wasm` is built in the release mode only (it is incompatible with san,
cov, fuzz, msan, tsan and android).

**Not graded.** A `c_wasm` target is an artifact, like a `c_binary`'s executable: it has no facts, adds no module kind
to grade, and nothing about it enters a verdict. The module's native `c_test` (and `c_mutants`) stay the evidence;
the wasm32 build only proves that the same sources compile freestanding, link without libc, and export what the
Worker calls.

**Checking a module's exports.** `gate/rigor_lib/wasm_exports.py` (stdlib only) reads the export section (id 7) of a
`.wasm` file and prints the exported function names, one per line; `--expect NAME` (repeated) exits 1 unless they are
exactly those names; a malformed file exits 2:

    python3 -I -B gate/rigor_lib/wasm_exports.py <file>.wasm --expect tally_char

**Example.** `examples/wasm`: the freestanding module `tally` (`tally_char`, counts a byte in a string with `strchr`),
its native `c_test` `tally_test`, and `c_wasm(name = "tally_wasm", deps = [":tally"], exports = ["tally_char"])`.
`selftest/toolchain.sh` runs the native test, builds `tally_wasm.wasm` in both forms, checks its exports and the
documented compile and link flags (aquery), and demands that `stdio.h`, `stdlib.h`, `errno.h` and `unistd.h` are not
found, that an undefined symbol and a missing export fail the link, and that a dep with `system_libs` is refused.
Unit tests of the reader: `gate/tests/test_wasm_exports.py`.

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
