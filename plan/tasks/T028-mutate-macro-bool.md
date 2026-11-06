# T028: mutation sees macro-hidden code (R002 F1) and `bool` functions (R002 F3); canaries for R002's wins

Repo: `Mivr/c-rigor-gate`. Branch `task/T028`. Read `AGENTS.md`, `docs/mutate.md`, `mutate/gen.py`,
`gate/rigor_lib/mutants_gate.py`, `gate/rigor_lib/mutants_report.py`, `docs/canaries.md`, and the R002 red-team
report (copy at `/var/tmp/cache/T028/R002-redteam.md`, sections F1, F2, F3). **T013, T021, T023 and T025 run in
parallel**: don't touch `gate/rigor_lib/grade*.py`, `verdict*.py`, `facts*.py`, `product_layout.py`,
`selftest/grade.sh`, `canaries/runner.py`, or any existing `canaries/<id>/`.

## Why
R002 got `rigor grade` to PASS an L3 module with a backdoor:
- **F1**: the backdoor in a function-like macro defined in the module's own `.c`. `gen.py` skips every node whose range
  touches a macro expansion, and one ordinary statement's `function-body` mutant satisfies the per-function checks.
- **F3** (fails closed, but blocks honest code): `bool f(...)` with no storage class is skipped as "macro" because the
  FunctionDecl `range.begin` is the `bool` macro location; annas-c has 58 such functions, and its L3 modules can't
  pass `mutants` honestly (T013 saw 25 `unmutated-function` errors).
- **F2** (attribute hides a function) was B19, fixed by T017; it needs an end-to-end canary.

## Allowed paths
`mutate/**`, `rules/mutate.bzl` (only if needed), `gate/rigor_lib/mutants_gate.py`, `gate/rigor_lib/mutants_report.py`,
`gate/rigor_lib/mutants_verdict.py`, `gate/tests/test_mutants*.py`, `gate/tests/fixtures/mutate/**`, `selftest/mutate.sh`,
`selftest/scratch_mut/**` (or wherever mutate's fixtures live), new `canaries/<new-id>/` dirs, `docs/mutate.md`,
`plan/backlog.md` (add B24 for F1, B25 for F3, and mark them).

## Requirements
1. **F3**: decide "made by a macro" from the function name's location and the body's span, not `range.begin`. A
   `bool`-returning (or any macro-typed return) function is mutated like any other. Red twin: a function whose
   name or whole body comes from a macro is still `skipped` (reason `macro`) and still an L3 `unmutated-function`.
2. **F1**: code skipped because it expands a macro **defined in a product file** (not under the system root and not
   gate-owned) is a finding `macro-hidden-code` with file, line and macro name: error at L3, info at L2. Macros from
   system headers (`NULL`, `bool`, `true`, `INT32_MAX`, `offsetof`, ...) are not findings. If you instead mutate inside
   the expansion, say how a mutant maps back to a source line and why it can't be dodged. Document the choice.
3. **Canaries**, each graded through `rigor grade` like the others and failing in exactly the gate and rule named:
   `macro-backdoor` (F1: `mutants:macro-hidden-code`), `attr-noinline-backdoor` (F2: `mutants:survived-mutant`),
   and `bool-function` as a green control that must not report `unmutated-function` for a tested `bool` function (if the
   pack can't express a green canary, put it in `selftest/mutate.sh` and say so).
4. **annas-c effect** (information only): run the generator over a scratch clone of `/var/tmp/src/annas-c` main in your
   cache and report, per module, the functions newly mutated and any `macro-hidden-code` it would report.

## Acceptance
```sh
selftest/mutate.sh
selftest/gate.sh
selftest/canaries.sh --only macro-backdoor --only attr-noinline-backdoor --only bool-function
```
