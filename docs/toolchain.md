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
| release | `tools/buck2 test //...` | `-O2 -ftrivial-auto-var-init=zero -fstack-protector-strong -fstrict-flex-arrays=3` (T139, below) |
| san | `tools/buck2 test --target-platforms toolchains//:linux_san //...` | `-O1 -g -fsanitize=address,undefined,leak -fno-sanitize-recover=all -fno-omit-frame-pointer` |
| cov | `tools/buck2 test --target-platforms toolchains//:linux_cov //...` | `-fprofile-instr-generate -fcoverage-mapping -fcoverage-mcdc` |
| fuzz | `tools/buck2 test --target-platforms toolchains//:linux_fuzz //...` | `-fsanitize=fuzzer,address,undefined` (+ `-O1 -g -fno-sanitize-recover=all -fno-omit-frame-pointer`) |
| msan (T125) | `tools/buck2 build --target-platforms toolchains//:linux_msan //x:t_results` | `-O1 -g -fsanitize=memory -fsanitize-memory-track-origins=2 -fno-sanitize-recover=all -fno-omit-frame-pointer`; link `-fsanitize=memory -fsanitize-memory-track-origins=2` |
| tsan (T125) | `tools/buck2 build --target-platforms toolchains//:linux_tsan //x:t_results` | `-O1 -g -fsanitize=thread -fno-sanitize-recover=all -fno-omit-frame-pointer`; link `-fsanitize=thread` |

Coverage report (line, branch, MC/DC), also on RE, via the fetched `llvm-profdata` / `llvm-cov`:

```sh
tools/buck2 build --target-platforms toolchains//:linux_cov //examples/hello:hello_test_coverage --show-output
```

`c_binary` and `c_test` are incompatible with `fuzz` (libFuzzer supplies `main`); `c_fuzz` is only built in `fuzz`.
`c_fuzz` is a test that runs `-seed=1 -runs=200000` as a cacheable RE action (see "Fuzz runs" below); it fails when
the fuzzer finds a crash.

## The hardened release profile (T139, P003 §6, D5)

The shipped binary is the `release` build, and the sanitizers run in other modes only. T139 measured five flags of the
pinned LLVM 19.1.7 and sysroot (glibc 2.31) on the `c_perf` targets and adopted the ones the owner's rule allows: **adopt
a flag only if every declared `c_perf` target moves by under 3% in instructions** (D5; the threshold is not tuned).

**Adopted (release mode only; `_HARDENED_RELEASE` in `rules/c.bzl`):** `-ftrivial-auto-var-init=zero`,
`-fstack-protector-strong`, `-fstrict-flex-arrays=3`. **Not adopted:** `-fsanitize=bounds -fsanitize-trap=bounds`
(+21.2% on `bsearch`, +34.6% on `nlogn`) and `-D_FORTIFY_SOURCE=3` (+5.4% on `mmove`, and it hides libc calls from
`libc_bytes`, see below). The other modes are untouched. Gate-owned third-party code (`rules/third_party.bzl`) keeps its own
flags: no flag had to match across objects to link.

**What each flag does here (checked with the pinned compiler, release binary, `selftest/toolchain.sh`):**

| flag | effect, verified |
|---|---|
| `-ftrivial-auto-var-init=zero` | an automatic array nobody wrote reads as zero (0xA5 left on the stack by an earlier call otherwise) |
| `-fstack-protector-strong` | a write past a stack array that reaches the canary ends in `SIGABRT` ("stack smashing detected") instead of a corrupted return address (`SIGSEGV`) |
| `-fstrict-flex-arrays=3` | only a trailing `[]` is a flexible array. **Inert on its own**: it matters to `-fsanitize=bounds` and to object-size checks, neither of which is on; it is in the profile because it costs nothing and keeps a later bounds flag honest |
| `-fsanitize=bounds` + `-fsanitize-trap=bounds` (rejected) | works: the out-of-range write into a struct's array member ends in `SIGILL` |
| `-D_FORTIFY_SOURCE=3` (rejected) | works: a `memcpy` of 12 bytes into an 8-byte object aborts (`SIGABRT`). glibc 2.31 knows levels 1 and 2, so level 3 acts as level 2; the check is against the whole object, not the member (an overflow of one struct member into the next is not caught) |

**Measurement** (2026-11-13, `selftest/perf.sh` fixtures built with each flag set on the farm; every record is from
`Intel(R) Xeon(R) CPU E5-2690 v4 @ 2.60GHz`, so counts are compared on one CPU model as `docs/perf.md` requires). Each cell
is the larger change of the two sizes, against the build with no flag. `*`: `libc_bytes` also changed. The first six rows are
the declared targets (the fixtures that exist for the gate's `c_perf` selftests); the last three are stress fixtures added by
T139 for the shapes the flags touch, reported, not part of the decision.

| fixture | instructions, no flag (small n, large n) | auto-init | bounds | stack-prot. | fortify | flex-arrays | all five | adopted three |
|---|---|---|---|---|---|---|---|---|
| lin | 115051, 460051 | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| quad | 21452986, 342312026 | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| mmove | 3596112, 4927378 | -0.33% | +0.00% | -0.33% | **+5.38%*** | +0.00% | **+5.14%*** | +0.00% |
| flat | 1473, 1573 | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| bsearch | 7816, 9053 | +0.00% | **+21.24%** | +0.00% | +0.00% | +0.00% | **+21.24%** | +0.00% |
| nlogn | 401506, 1915509 | +0.00% | **+34.56%** | +0.00% | +0.00%* | +0.00% | **+34.56%*** | +0.00% |
| stab (index into `struct { u32 cell[256]; }`) | 260149, 1040149 | +0.00% | +23.07% | +0.00% | +0.00% | +0.00% | +23.07% | +0.00% |
| abuf (384-byte automatic buffer, filled in part) | 106022, 423809 | +16.53%* | +65.82%* | +1.48% | +0.00% | +0.00% | +84.41%* | +20.08%* |
| mcpy (`memcpy` of a run-time length into a member) | 82463, 329963 | +0.00% | +24.24% | +0.00% | +21.21%* | +0.00% | +45.45%* | +0.00% |

Worst move on the declared targets: auto-init 0.33%, stack protector 0.33%, flex-arrays 0%, fortify 5.38%, bounds
34.56%, all five 34.56%, the adopted three 0%. **Decision by the rule:** the whole set fails (bounds, fortify); the largest
subset under 3% on every declared target is auto-init + stack protector + flex-arrays, which is what is adopted. The
stress fixtures say what the declared targets cannot: `abuf` pays +20% for zeroing a 384-byte frame (the price of
`-ftrivial-auto-var-init=zero` on a hot function with a big buffer), `stab` +23% for bounds checks on an array index the
compiler cannot bound. A product whose own `c_perf` targets are of that shape sees those numbers; its targets are the
ones the rule is applied to when it declares them.

Two measurement notes. (1) `-D_FORTIFY_SOURCE=3` turns `memcpy`, `memmove` and `memset` of a checked object into
`__memcpy_chk` and friends, which `PERF_WRAPS` (`-Wl,--wrap=`) does not name, so `libc_bytes` reads 0 for them (`mmove`:
800020000 to 0). Adopting fortify later needs the `__*_chk` names added to `rules/perf.bzl` first. (2) The stack protector
and auto-init each lower the `mmove` count by 0.3% (about 12 thousand instructions, a compiler code-layout effect), and the three together leave it unchanged.

**What the adopted set covers:** a stack overrun that reaches the canary aborts; an automatic variable is never
indeterminate (a read of one yields zero, and the sanitizer modes still find the read, in their own build). **What it does
not cover:** an array index past the end of a fixed array inside a struct is NOT trapped (the neighbour is read or written;
`selftest/toolchain.sh` pins that this is today's behaviour); an overflowing `memcpy` into a sized object is not stopped
(a stack canary may catch it by layout luck, not by design); a pointer plus a separate length is not bounds-checked, with
or without `-fsanitize=bounds`; heap objects do not exist in product code; uninitialised static data is already zero.
`-fbounds-safety`, which would check every pointer-plus-length pair, is not complete in upstream Clang and is not in the
pinned 19.1.7; revisit it at the next toolchain bump (G20).

## The msan and tsan modes (T125; graded by `tests-msan` and `tests-tsan` since T138)

Two target platforms, `toolchains//:linux_msan` (MemorySanitizer with origin tracking) and `toolchains//:linux_tsan`
(ThreadSanitizer). The flags are sealed in `rules/c.bzl` and the same in `rules/third_party.bzl` for gate-owned
third-party code, so a test that links mbedTLS is instrumented throughout. The runtimes (`libclang_rt.{msan,tsan}.a`
and `.syms`) are members of the pinned LLVM 19.1.7 archive and of `llvm.manifest`. Only `<name>_results` is produced
in them, with the sealed environment of `san` plus `MSAN_OPTIONS` / `TSAN_OPTIONS` (`rules/ctest.bzl`:
`halt_on_error=1`, exit codes 77 / 66, the hermetic `external_symbolizer_path`, `log_path`; for TSan also
`stack_trace_format`, so frames read `#N 0x.. in <func> <file>:<line>` like the other sanitizers). `ctest` forks one
process per test; nothing more than `log_path` was needed for that. On a failing exit the action prints the sanitizer
log to stderr, so a runtime that died at start-up names its reason.

- **Which tests.** The gates `tests-msan` and `tests-tsan` of `rigor grade` (`docs/grade.md`) judge exactly these sets: `tests-tsan` the tests declared `threads = True`
  (and the `symbols` gate checks the declaration against thread creation in the test and its link closure: `threads-undeclared`, `threads-vacuous`), `tests-msan` every test but
  those with no msan target (info `msan-not-applicable`, naming the library). `c_test(threads = True)` has a tsan results target; `threads = False` (the default) has none. Every
  `c_test` has an msan results target, except one whose link closure has a sysroot library beyond libc and pthread
  (MSan needs every linked object instrumented; today only X11): such a `c_library` is incompatible with the msan mode,
  and so is everything that depends on it.
- **No frame limit in msan.** In the msan mode only, `-Wframe-larger-than=512` is not passed (every other sealed
  warning is). The limit bounds the stack of shipped code; origin tracking inflates the frames of instrumented code,
  which is not shipped (`ctest_run` alone reaches 632 bytes). TSan did not need this: tsan keeps the limit.
- **What they cannot see.** MSan: only uninitialised reads in code compiled with it (not libc, X11 or the kernel) and
  only on executed paths. TSan: only races between threads that actually ran in the test, and not through uninstrumented
  code. Neither runs a product that talks to a device. A clean verdict is evidence, not proof.
- **The farm prerequisite.** Both runtimes map fixed shadow ranges. When the kernel's ASLR entropy is high they re-exec
  themselves with `personality(ADDR_NO_RANDOMIZE)`. The RE workers run under Docker's default seccomp profile plus one
  rule that allows `personality(0x0040000)`. Without it the call fails, the runtime dies at start-up
  (`CHECK failed: ... personality(...) != -1`, `memory layout is incompatible`) and the results action fails with
  `test binary could not run`: measured on the farm before the rule, about one run in five for msan and almost always
  for tsan (6 of 6). A shared-library layout cannot be fixed with link flags (`-no-pie` was tried: 59 of 300 starts
  still failed). With the rule: 0 of 30 uncached runs of the passing fixture failed to start, for each mode.
  `selftest/sanmodes.sh` prints one line naming this when a results run ends that way; it is still a failure.
  `rigor grade` (T138) turns it into the one error `sanitizer-startup` of `tests-msan` / `tests-tsan`, which names this
  prerequisite and lists no missing test; the build is not retried, so a farm without the rule fails every grade clearly.
- **Stable reports.** TSan prints `(pid=N)` and `(tid=N)`; the normalizer of `ctest/sanlog.c` rewrites them to `pid=N` / `tid=N`
  (with the pids, hex numbers and BuildIds it already scrubbed), so a report is byte-identical across runs.
- Self-test: `selftest/sanmodes.sh`.

## Sealed flags

`rules/c.bzl` appends `-std=c17 -Wall -Wextra -Wpedantic -Werror -Wconversion -Wsign-conversion -Wshadow
-Wcast-qual -Wvla -Wframe-larger-than=512 -Wformat=2 -Wnull-dereference -Wimplicit-fallthrough` after the mode
flags. The macros `c_library`, `c_binary`, `c_test`, `c_fuzz` have no flag parameters. (`-Wframe-larger-than=512` is left out in the msan mode only, see above.)

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

`c_fuzz(name = "fz")` defines `fz__bin` (the libFuzzer binary) and `fz` (rule `fuzz_run`, rules/fuzz.bzl). `fz` is a
build action on RE with the same hermetic symbolizer and the same fatal sanitizer options as `<name>_results`
(`sanitizer_env_lines`, no `log_path`; reports stay on stderr), running `fz__bin -seed=1 -runs=N
-artifact_prefix=<scratch>/` (N: the `runs` of the target, default 200000; first it replays the corpus, see `docs/fuzz.md`). It always produces its outputs; `buck2 test` of `fz` only reads the verdict.

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
