# T017: the mutant generator never drops a function silently (backlog B19)

Repo: `Mivr/c-rigor-gate`. Branch `task/T017`. Read `AGENTS.md`, `docs/mutate.md`, `plan/backlog.md` (B19),
`mutate/gen.py`, `mutate/tool.py`, `rules/mutate.bzl`, `gate/rigor_lib/mutants_*.py`. **In parallel:** T011,
T013 (`grade*.py`, `product_layout.py`, `products/**`), T014, T015 and T016. Touch none of their files.

## Why
`gen.py` takes `node["inner"][-1]` as a function body. When clang lists an attribute node after the body
(`__attribute__((noinline)) int f(void) {...}`), that function is neither mutated nor listed as skipped, so no
`no-mutants` or `unmutated-function` finding fires. Any case where the generator can lose a function is a
mutation-testing escape.

## Allowed paths
`mutate/**`, `rules/mutate.bzl` (only if needed), `gate/rigor_lib/mutants_report.py`,
`gate/rigor_lib/mutants_verdict.py`, `gate/tests/test_mutants*.py`, `gate/tests/fixtures/mutate/**`,
`selftest/mutate.sh`, `selftest/scratch_mut/**` (or wherever mutate's fixtures live), `docs/mutate.md`,
`plan/backlog.md` (mark B19).

## Requirements
1. Find the body as the unique `CompoundStmt` child of the `FunctionDecl`, wherever it sits among the children.
2. **Accounting invariant (the real fix):** every function *definition* in a product source (a `FunctionDecl`
   with a body, located in the file being mutated, after the same `#line`-distrusting location rules mutate
   already uses) ends up in exactly one of `functions` (with mutants or an explicit "no mutable token" reason)
   or `skipped` (with a reason). The generator checks this itself and fails loudly (exit 2) if a definition is
   unaccounted for. `mutants_verdict` cross-checks the count against an independent count from the same AST,
   so a future generator bug can't pass silently.
3. Audit every other place in `gen.py` that indexes AST children positionally or assumes a shape, and fix or
   guard each one. Cover attributes before and after (`noinline`, `cold`, `used`, `unused`, `always_inline`, `section` and
   so on, whichever the product checks allow), K&R-less prototypes then definitions, `static inline` in `.c`, functions
   with `asm` labels if the product checks allow them (they shouldn't; then show that they are refused upstream),
   GNU statement expressions, nested blocks, `_Generic`, compound literals, and designated initializers.

## Tests and self-test
Unit tests with AST fixtures (record real clang JSON from the hermetic toolchain into `gate/tests/fixtures/`), for
each shape above. In `selftest/mutate.sh`: a module whose only function has a trailing attribute must now be
mutated and must survive or be killed as its tests dictate. A deliberately broken generator (an env switch in
the self-test only, or a monkeypatched fixture) must make the accounting check fail closed.

## Acceptance
```sh
selftest/mutate.sh
selftest/gate.sh
```
Report: the shapes covered, before and after counts on annas-c `main` (`gen.py --ast` over its sources, run from a
clone in `/var/tmp/cache/T017/`), and any functions annas-c had silently lost before.
