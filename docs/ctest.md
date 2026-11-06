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

Binary: `<bin> [--seed N] [--out FILE]` (default seed 1, default output stdout). Exit 0 all passed,
1 some test failed, 2 usage/framework error (bad option, bad or duplicate test name, no tests, I/O error).
Test and suite names must match `[a-z0-9_]+` (<= 64 chars) and be unique.

## Why a test cannot look green by cheating
Every test runs in a forked child (own process group, stdout redirected to stderr). The test function
returns into framework code that sends one fixed-size report (magic, per-run random nonce, assert count,
failed count, first failure) over a pipe, then `exit(0)`s. The parent says `pass` only if: the report is
complete, exactly one, carries the nonce, `failed == 0`, `asserts >= 1`, and the child exited 0.
Everything else is `fail` with a reason: `exit()`/`_exit()` before returning ("exited without reporting"),
non-zero exit before or after reporting (this is how ASan/LSan/UBSan failures surface), death by signal,
zero checks ("no checks executed"), invalid report, and a fixed **10 s timeout** ("timeout after 10 s";
the process group is SIGKILLed). Order is shuffled by `--seed` (splitmix64 Fisher-Yates).

## Output (JSON Lines, one object per test in run order, then the summary)
```
{"id":"<suite>/<name>","status":"pass"|"fail","asserts":N,"reason":""}
{"summary":{"total":N,"passed":M}}
```
`reason` is empty exactly when `status` is `pass`. Strings are JSON-escaped; bytes < 0x20 and >= 0x7f
become `\u00XX`. This is the format `gate/rigor tests` parses.

## `<name>_results` (rules/ctest.bzl)
A build action on RE: `<bin> --seed 1 --out results.jsonl`. It succeeds when the binary ran (exit 0 or 1)
and wrote a non-empty file, so failures are in the file; it fails on exit 2, a signal, or no file.
Built in `release` and `san` (incompatible in `cov`/`fuzz`). A verdict is cached until an input changes.

## Known limits
- A hostile test can still run arbitrary code in its child; the nonce only stops accidental or naive
  forgery of the report, not an attacker who reads the process image. The suppression scan and review
  cover that.
- Tests are isolated by `fork`, so order dependence can only go through the file system or environment;
  `--seed` still catches that.
- The 10 s limit is wall-clock and fixed in `ctest.c`.
