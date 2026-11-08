# ctest (T003)

Tiny C17 test framework (`ctest/ctest.h`, `ctest/ctest.c`) whose results a test cannot fake.
`c_test` links it automatically (`#include "ctest/ctest.h"`) and defines `<name>_results`.

```c
static void t_add(ctest_t *t) { CHECK_EQ_I64(t, add(2, 3), 5); }
CTEST_SUITE("hello", { "add", t_add })     /* defines main() */
```

Checks: `CHECK`, `CHECK_EQ_I64`, `CHECK_EQ_U64`, `CHECK_EQ_STR` (NUL-terminated, NULL allowed),
`CHECK_EQ_MEM(t, a, alen, b, blen)`. Each executed check is one assertion; a failed check is recorded
(file:line, values) and the test continues. No skip, no expected-failure.

Binary: `<bin> [--seed N] [--out FILE] [--san-log PREFIX --san-report FILE]` (default seed 1, default output stdout;
the two `--san-*` options go together, see "Sanitizer reports"). Exit 0 all passed,
1 some test failed, 2 usage/framework error (bad option, bad or duplicate test name, no tests, I/O error).
Test and suite names must match `[a-z0-9_]+` (<= 64 chars) and be unique.

## Why a test cannot look green by cheating
Every test runs in a forked child (own process group, stdout redirected to stderr). The test function
returns into framework code that writes one fixed-size report (magic, per-run random nonce, assert count,
failed count, first failure) into an anonymous shared page, then `exit(0)`s. The parent says `pass` only if: the report is
written last (magic set), carries the nonce, `failed == 0`, `asserts >= 1`, and the child exited 0.
Everything else is `fail` with a reason: `exit()`/`_exit()` before returning ("exited without reporting"),
non-zero exit before or after reporting (this is how ASan/LSan/UBSan failures surface), death by signal,
zero checks ("no checks executed"), invalid report, and a fixed **10 s timeout** ("timeout after 10 s";
the process group is SIGKILLed). Order is shuffled by `--seed` (splitmix64 Fisher-Yates).

No file descriptor owned by the parent reaches a test: there is no pipe (the report is shared memory) and
the results file is **not opened until every child has finished**; the lines are kept in a fixed 1 MiB
buffer (overflow is a framework error, exit 2) and written once with `O_CLOEXEC`. A test that
`write`/`pwrite`s into every fd 0..255 cannot alter the results (selftest case `fds`).

## Output (JSON Lines, one object per test in run order, then the summary)
```
{"id":"<suite>/<name>","status":"pass"|"fail","asserts":N,"reason":""}
{"summary":{"total":N,"passed":M}}
```
`reason` is empty exactly when `status` is `pass`. Strings are JSON-escaped; bytes < 0x20 and >= 0x7f
become `\u00XX`. This is the format `gate/rigor tests` parses.

## Sanitizer reports
With `--san-log PREFIX` the parent expects sanitizer logs in `PREFIX.<pid>` (the sanitizers' `log_path`). After each
child ends it reads that child's file, deletes it, normalizes it (`==<pid>==` becomes `==`, every `0x<hex>` becomes
`0x_`, shadow-byte rows and `(BuildId: ...)` are dropped) and then:
- appends `; <kind> at <file>:<line> <function>` to the test's `reason`, where `<function>` is the first symbolized
  frame in the product's own code (a relative path that is not ctest itself; runtime and libc frames are skipped).
  `<kind>` is `AddressSanitizer: <error>`, `UBSan: <runtime error text>`, `LeakSanitizer: detected memory leaks`;
  if no product frame exists it is `<kind>; no frame in product code`. The reason stays under 512 bytes (cut);
- appends the whole normalized log under `== <suite>/<name> ==` to the file given by `--san-report`
  (always written, empty when nothing failed with a report; cut at 1 MiB with a marker).

Examples (`san` mode):
```
exited with status 1 before reporting; AddressSanitizer: heap-buffer-overflow at pkg/t.c:16 t_heap_overflow
exited with status 1 after reporting; LeakSanitizer: detected memory leaks at pkg/t.c:29 t_leak
exited with status 1 before reporting; UBSan: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int' at pkg/t.c:34 t_ub_overflow
```
A log can only add text to a failing test or **turn a pass into a fail** ("sanitizer report in a test that looked
passing"); nothing in it can make a test pass. A missing or forged log changes at most the `reason` of a test that
already fails. In `san`, SIGSEGV/SIGABRT/SIGILL/SIGBUS/SIGFPE are handled by ASan (`handle_*=1`), which prints the
stack and exits with status 1, so such a death reads `exited with status 1 ...; AddressSanitizer: SEGV at ...`
rather than `killed by signal N`. In `release` there is no sanitizer, so a signal death stays `killed by signal N`.

## `<name>_results` (rules/ctest.bzl)
A build action on RE: `<bin> --seed 1 --out results.jsonl`. It succeeds when the binary ran (exit 0 or 1)
and wrote a non-empty file, so failures are in the file; it fails on exit 2, a signal, or no file.
Built in `release` and `san` (incompatible in `cov`/`fuzz`). A verdict is cached until an input changes.
The action also declares the pinned `llvm-symbolizer` as an input and sets (identical in every mode, ignored when
there is no sanitizer): `ASAN_SYMBOLIZER_PATH` and `LLVM_SYMBOLIZER_PATH` to it, and, with `$common` =
`symbolize=1:fast_unwind_on_malloc=0:strip_path_prefix=<exec root>/:log_path=<out dir>/sanlog`,
`ASAN_OPTIONS=$common:halt_on_error=1:abort_on_error=0:detect_leaks=1:handle_abort=1:handle_sigill=1:handle_sigbus=1:handle_sigfpe=1`,
`UBSAN_OPTIONS=$common:halt_on_error=1:abort_on_error=0:print_stacktrace=1`, `LSAN_OPTIONS=$common`.
The compile flags (`-fno-sanitize-recover=all`) and these options keep every sanitizer failure fatal; none is weakened.
The second output is `san_report.txt`, available as the sub-target `<name>_results[san_report]` (and materialized
beside `results.jsonl`). It holds no PIDs, addresses or worker paths, so two cold runs are byte-identical.

## `c_fuzz` runs (rules/ctest.bzl, `fuzz_run`)
The same symbolizer and fatal options (one shared helper, `sanitizer_env_lines`) apply to the fuzz action, minus
`log_path` (the report stays on stderr and is filtered). Outputs `report.txt` (`<name>[report]`) and `crash`
(`<name>[crash]`) are declared; see `docs/toolchain.md`, "Fuzz runs".

## Resource limits (T097)
A mutant of a write retry once made a real-directory test write the same bytes forever and filled the RE worker's CAS
temp disk, which broke every lane's builds for hours. Tests may write small real files under `$TMPDIR`, so the
harness bounds what any one test can consume. The limits are set in `ctest_run` (`ctest/ctest.c`) before any test runs, the
same in release, san, cov and every mutant run (a mutant run is the same binary), and `ctest/perf.c` sets the same:

| Limit | Value | Effect |
|---|---|---|
| `RLIMIT_FSIZE` | 64 MiB per file | a write past it fails with `EFBIG` (`SIGXFSZ` is ignored), so the test's own check fails |
| `RLIMIT_CPU` | 20 s per test process (the runner itself: 600 s) | an infinite loop dies by `SIGXCPU` (`killed by signal 24`); twice the 10 s wall timeout, so two busy threads still pass |
| `RLIMIT_NOFILE` | 256 | a leaking loop of opens fails with `EMFILE` |
| `RLIMIT_CORE` | 0 | no core file |
| scratch quota | 256 MiB (apparent size) and 4096 entries per test | many files, each under 64 MiB, cannot add up |

The scratch quota: the runner makes a private directory `$TMPDIR/ctest.XXXXXX` (`/tmp` if `$TMPDIR` is unset) for each test and
sets `$TMPDIR` to it in the test process; while it waits it measures the directory every 20 ms (`nftw`), kills the test's process
group when it is over the quota (result `fail`, reason `scratch quota exceeded (limit 256 MiB, 4096 entries under $TMPDIR)`), and always
removes the directory afterwards, so a test also starts with an empty `$TMPDIR` and leaves nothing behind. A test that writes
elsewhere (a hard-coded path) is bounded by `RLIMIT_FSIZE` alone. The overshoot is what the disk writes in 20 ms.
A test killed by a limit is a failed test, so a mutant that hits one is `killed-assert` (the check failed) or `killed-crash` (signal or quota), never `unrun`
or an action error. Selftest: `selftest/ctest.sh` package `limits` (write-forever, many files, many entries, descriptors, the limits
themselves) in release and san; `selftest/mutate.sh` module `runaway` (the `left -= w` -> `left += w` mutant).

## Known limits
- A hostile test can still run arbitrary code in its child; the nonce only stops accidental or naive
  forgery of the report, not an attacker who reads the process image. The suppression scan and review
  cover that.
- Tests are isolated by `fork`, so order dependence can only go through the file system or environment;
  `--seed` still catches that.
- The 10 s limit is wall-clock and fixed in `ctest.c`.
