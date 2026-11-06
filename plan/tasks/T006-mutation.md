# T006: mutation testing for C (`c_mutants`), one cached Buck2 action per mutant

Repo: `Mivr/c-rigor-gate`. Branch `task/T006`. Read `AGENTS.md`, `plan/phase1.md`, `docs/toolchain.md`,
`docs/ctest.md`, `docs/gate.md`, `docs/product-checks.md`, `docs/grade.md` first.

## Why
Coverage says a line ran; it does not say a test would notice if the line were wrong. An agent can reach 100 %
coverage with assertion-light tests. Mutation testing measures whether the tests actually constrain behaviour.
The rule is **zero surviving mutants** on L3 modules. There are no exclusions except signed approvals.

## Allowed paths
`mutate/**`, `rules/**`, `gate/**` (new `mutants` gate; existing gates untouched), `selftest/mutate.sh`,
`docs/mutate.md`.

## Design (decided; deviations need a reason in the report)
### Mutant generation: AST-located, source-level
- For each source of a module, run the fetched clang with the real compile flags and
  `-Xclang -ast-dump=json -fsyntax-only` **on RE** (cached). A gate-owned Python script (`mutate/gen.py`, stdlib
  only) reads the JSON AST and emits a deterministic, sorted mutant list:
  `{id, file, begin_offset, end_offset, original, replacement, operator, function, line}`.
  Use AST source ranges only for nodes whose range lies in the main file and not inside a macro expansion
  (skip `isMacroExpansion`/spelling-vs-expansion mismatches), so every mutant is a precise text replacement.
- Operators (each a row in one table):
  - relational: `<` `<=` `>` `>=` `==` `!=` to each other (sensible pairs: `<`->`<=`, `<`->`>=`, `==`->`!=`, ...);
  - arithmetic: `+`<->`-`, `*`->`/`, `/`->`*`, `%`->`*`, `<<`<->`>>`, `&`<->`|`, `^`->`&`;
  - logical: `&&`<->`||`, remove `!`;
  - compound assignment: `+=`<->`-=`, etc.;
  - increment: `++`<->`--`;
  - integer literal: `0`->`1`, `1`->`0`, `n`->`n+1` (only when the literal is not an array size or a
    `case` label or `_Static_assert` operand);
  - condition: `if (c)` -> `if (!(c))`, loop conditions likewise;
  - return value: `return e;` -> `return 0;` / `return NULL`-equivalent by type (scalar and pointer
    returns only);
  - statement deletion: an expression statement that is a call whose result is unused -> `;`;
  - whole body (pseudo-tested function check): non-void scalar function body -> `{ return 0; }`, void
    function body -> `{}`.
  Skip pointer-arithmetic `+`/`-` mutations whose result would not type-check (use the AST types).
### Mutant evaluation: per-mutant actions with dynamic fan-out
- `c_mutants(name, module, tests)`: a rule using Buck2 `dynamic_output` over the mutant list. For each mutant:
  write the mutated source, compile that single TU with the module's exact flags (RE), and compare the object
  file hash to the original object's: **identical = equivalent (TCE)**, identical to an earlier mutant =
  duplicate. Otherwise relink each test in `tests` with the mutated object replacing the original and run it
  through ctest (RE) producing a results file. Compile failure = `unviable` (not counted, but reported).
- Verdict per mutant: `killed-assert` (some expected test `fail` with a check-failure reason), `killed-crash`
  (crash, sanitizer, timeout), `survived`, `equivalent`, `duplicate`, `unviable`. Run in `release`; use the
  `san` mode for the `killed-crash` classification only if cheap (document).
- Every per-mutant action is keyed on its inputs, so an unchanged module re-runs **zero** mutant actions.
### The `mutants` gate
`rigor mutants --results DIR --policy P.toml --out ...`: FAIL on any `survived` mutant in a module whose policy
`level` is L3 (L2: report only), unless covered by a signed approval of a new kind `equivalent-mutant`
(scope = mutant id, which must be stable: hash of file path + function + operator + original text + ordinal
within the function, not a line number). Also FAIL if an L3 function has mutants but **no** `killed-assert`
(only crash kills), and if the mutant list for a module is empty while the module has functions (generator
blind). Report per module: total, per-verdict counts, survivors with file:line, operator and replacement.

## Self-test `selftest/mutate.sh`
A throwaway module with: a function fully pinned by strong tests (0 survivors); a weak test that only checks
non-NULL (survivors listed precisely); a pseudo-tested function (whole-body survivor); an equivalent mutant
(`x * 1` style or dead store) classified `equivalent` by TCE; a macro-generated expression that is skipped,
not mis-mutated; a second run with unchanged sources executing **0** actions; a one-line test strengthening
that kills a previous survivor re-running only the affected mutants.
Also cross-check: on the throwaway module, compare our survivors with Mull's if a Mull release for LLVM 19 can be
fetched by sha256 from GitHub releases; if not, say so and skip (do not install anything).

## Acceptance
```sh
selftest/mutate.sh   # twice, exit 0; second run 0 mutant actions executed
selftest/gate.sh && selftest/ctest.sh && selftest/toolchain.sh
```
Report mutant counts per operator for the self-test module, timings cold/warm, and deviations.
