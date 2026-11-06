# T014: default-deny compiler builtins; ban alloca (R001 R1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T014`. Read `AGENTS.md`, `plan/audits/R001-gate-audit.md` (R1),
`docs/product-checks.md`, `gate/rigor_lib/cscan.py`, `gate/rigor_lib/semantic_table.py`,
`gate/rigor_lib/facts_semantic.py`, `rules/c.bzl`. **T008 and T011 run in parallel**: don't touch
`grade*.py`, `mutants_*.py`, `order.txt`, `products/**`, `cli.py` or `structure*`.

## Why
The symbol deny list, the semantic watch list and the 512-byte frame limit are keyed on libc symbol names.
`__builtin_setjmp`/`__builtin_longjmp` lower to intrinsics with no `setjmp`/`longjmp` symbol, and
`__builtin_alloca` emits no symbol and is not counted by `-Wframe-larger-than`. An implementer can use them and
pass. Enumerating dangerous builtins is fail-open, so builtins must be **default-deny**.

## Allowed paths
`gate/rigor_lib/cscan.py`, `gate/rigor_lib/semantic_table.py`, `gate/rigor_lib/facts_semantic.py`,
`gate/rigor_lib/facts_policy.py`, `rules/c.bzl` (only to add a compiler-side guard, never to remove a flag),
`gate/tests/test_cscan*.py`, `gate/tests/test_facts*.py`, `selftest/product_checks.sh`,
`selftest/product_checks_fixtures/**` (or the existing fixture dir), `docs/product-checks.md`.

## Requirements
1. Any identifier that begins with `__builtin_` or `__sync_`, or is one of `__atomic_*`, `__c11_atomic_*`,
   `alloca`, `__alloca` or `_alloca`, found in the **preprocessed** source of a product module is a finding,
   unless it is in a small gate-owned allowlist of pure builtins that the gate's own headers or the toolchain's
   headers need: for example `__builtin_expect`, `__builtin_offsetof`, `__builtin_va_*` (only where `<stdarg.h>` is
   allowed), and the overflow checkers `__builtin_add_overflow`, `__builtin_sub_overflow` and
   `__builtin_mul_overflow`. Justify each entry in `docs/product-checks.md`. Measure what annas-c `main` (at
   `/var/tmp/src/annas-c`, read-only) and the third-party-using modules actually expand to, so the allowlist is
   minimal and annas-c still passes. Report every identifier you had to allow.
2. Tokens reached through macro expansion count, because the scan is post-preprocessing. Names that the system
   headers introduce, but that the product never *uses* in its own code, must not cause false positives: decide
   by the location of the use, the same way the scan already handles `#line` distrust (re-read its rules and
   keep them).
3. `alloca` and `__builtin_alloca` (and `__builtin_alloca_with_align*`) are banned at every level, with no
   policy override. `__builtin_setjmp`/`__builtin_longjmp` follow the deny entries of `setjmp`/`longjmp`, and
   `__builtin_frame_address`/`__builtin_return_address` are denied.
4. Belt and braces, if cheap: a compiler-side guard in the sealed flags that turns any use of the banned builtins
   into an error (for example a forced-include header with `#pragma clang poison` for the identifiers that
   can be poisoned). Prove that poisoning doesn't break the system headers in release, san, cov and fuzz.

## Tests and self-test
Unit tests with red and green cases for each rule. In `selftest/product_checks.sh`: red fixtures using
`__builtin_alloca`, `__builtin_longjmp`, a builtin hidden behind a macro, a builtin spelled through token pasting
(`__builtin_ ## alloca`), `__builtin_frame_address`, and `__sync_fetch_and_add`. Green: annas-c-like code using
`__builtin_mul_overflow` and `offsetof`.

## Acceptance
```sh
selftest/product_checks.sh
selftest/gate.sh
```
Plus: `gate/tools/rigor facts`, or a grade of annas-c `main` with this gate, still passes semantic-suppressions.
Report the exact command and its output.
