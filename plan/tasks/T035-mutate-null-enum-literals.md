# T035: mutation sees conditions with `NULL` (R003 G2, B28) and mutates enum constants and string/char literals (G3, B29)

Repo: `Mivr/c-rigor-gate`. Branch `task/T035`. Read `AGENTS.md`, `docs/mutate.md` (incl. T028's "Macros" section),
`mutate/gen.py`, `gate/rigor_lib/mutants_gate.py`, R003 (`plan/audits/R003-test-adequacy.md`: G2, G3, suites S3n, S6b, S1)
and annas-c R004 (`/var/tmp/cache/T035/R004-test-adequacy.md`: 277 `NULL` conditions, 107 product-limit-macro conditions,
1346 tests checking exact codes). **T034 runs in parallel on `rules/mutate.bzl` and `mutate/**` except `gen.py`; T032 on
`grade_*.py`; T030 on `toolchains/**`.** You own `mutate/gen.py`.

## Allowed paths
`mutate/gen.py`, `gate/tests/test_mutate_gen*.py`, `gate/tests/test_mutants*.py`, `gate/tests/fixtures/mutate/**`,
`selftest/mutate.sh` (new steps only), new `canaries/null-guard/`, `canaries/weak-error-code/`, `canaries/weak-string/`,
`docs/mutate.md`, `plan/backlog.md` (mark B28, B29).

## Requirements
1. **G2**: a condition that contains a system object-like macro (`NULL`, and the same for `true`/`false`, `INT_MAX` ...)
   gets its relational, logical and condition mutants like any other: locate the operator and operands by the main-file
   expansion location of the macro. Product macros stay under T028's `macro-hidden-code` rule; don't change that rule.
2. **G3**: new operators, each with its kill semantics documented:
   - `enum-constant`: an enumerator used as a value (return, assignment, argument, comparison operand) is replaced by the
     next enumerator of the same enum (wrapping); skipped when the enum has one value;
   - `string-literal`: a non-empty string literal used as a value becomes `""`, and a one-char change (first byte
     incremented) as a second mutant; never in `static_assert`, `_Pragma`, attribute or array-size contexts;
   - `char-literal`: incremented by one.
   Mutants that don't compile are unviable as today, never survivors.
3. Canaries, each failing in exactly `mutants:survived-mutant`: `null-guard` (R003 S3n shape), `weak-error-code` (tests
   check `!= OK` only), `weak-string` (tests check `!= NULL` on a name function).
4. **annas-c effect** (information only, generator run over a scratch clone of `/var/tmp/src/annas-c` main, as T028 did):
   per module, new mutants per operator. Keep the total action cost in mind: report the increase in mutants per module.

## Acceptance
```sh
selftest/mutate.sh
selftest/gate.sh
selftest/canaries.sh --only null-guard --only weak-error-code --only weak-string --only control --only bool-function
```
