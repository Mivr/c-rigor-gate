# T050: struct-returning functions get mutants (B30; R003 G4, G5)

Repo: `Mivr/c-rigor-gate`. Branch `task/T050`. Read `AGENTS.md` ("Working efficiently") and `docs/mutate.md` first.
R003 (`plan/audits/R003-test-adequacy.md`, G4 and G5, rows S0', S0'', S1s, S1s-w): a function returning a struct with
no operators gets no mutants (info `no-mutable-token`), so it can be untested or wrong and pass L3; a function
returning a `typedef struct {...} T` yields uncompilable mutants, reported as a false `no-assert-kill-function`.
**In flight in parallel:** T038 (`grade_build.py`, `grade_mutants.py`, `mutants_gate.py`), T049 (`trajectory*`), T047
(`plan/backlog.d/`, `plan/backlog.md`), batch3. Touch none of their files. Do not edit `plan/backlog.md`.

## Allowed paths
`mutate/gen.py`, `gate/tests/test_mutate_gen*.py`, `gate/tests/fixtures/mutate/**`, `selftest/mutate.sh` (new steps
only), new `canaries/struct-return-untested/`, `docs/mutate.md`, and `gate/rigor_lib/mutants_verdict.py` only if
`no-mutable-token` severity lives there (then only that).

## Requirements
1. A function whose return type is a struct (directly, or through any chain of typedefs, resolved from the AST) gets a
   body mutant `return (T){0};` (T spelled as the declared return type), and each `return expr;` a return-value
   mutant `(T){0}` unless `expr` is already that literal.
2. `return_class` resolves typedefs so a typedef'd struct return is classed as a struct, and no mutant it generates
   fails to compile for that reason (G5 false positive gone).
3. `no-mutable-token` becomes an error at L3 (info below L3), unless the function has no body to mutate at all (say
   precisely what counts; a `static inline` trivial getter returning a member still gets the struct/return mutants).
4. Canary `struct-return-untested`: S1s from R003 (a struct-returning function only called, never checked) must fail
   `mutants:survived-mutant`. Green fixture step in `selftest/mutate.sh`: a well-tested struct return (all mutants
   killed) and the typedef variants S0' / S0'' compile all their mutants.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutate*.py'
selftest/mutate.sh
selftest/canaries.sh --only struct-return-untested --only control --only bool-function
selftest/gate.sh
```
Report how many new mutants this adds on annas-c (run old and new gen.py over a clone, as T035 did).
