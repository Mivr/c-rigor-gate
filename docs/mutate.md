# Mutation testing for C (T006)

Coverage says a line ran, not that a test would notice if the line were wrong. A mutant is the module with
one small, deliberate defect; if every test still passes, the tests do not constrain that behaviour. The rule
for L3 modules is **zero surviving mutants**; the only way past one is a signed `equivalent-mutant` approval.

Everything runs on RE in the `release` mode: `buck2 build //pkg:<name>` of a `c_mutants` target yields
`report.json`, `rigor mutants` decides. Self-test: `selftest/mutate.sh`.

```
c_mutants(name = "core_mutants", module = ":core", tests = [":core_test"], deps = [])
```
`module` is a `c_library`; `tests` are `c_test`s linked against it; `deps` are the other libraries those
tests link besides the module and ctest (a missing one is a link error, which fails the build, never a
verdict). `c_library` also defines `<name>_mutsrc` (its source files) which `c_mutants` reads.
The product build-file guard (`rigor buckfiles`, T004) only admits the four product macros, so
`c_mutants` targets are written by the grading driver in a gate-owned package, not by the product.

## Pipeline
| Step | What | Where |
|---|---|---|
| 1 `mutant_list` | per source: the pinned clang with the module's **exact compile command** (the argsfile Buck2 itself uses) runs `-Xclang -ast-dump=json -fsyntax-only`; `mutate/gen.py` reads the JSON and writes the sorted mutant list | RE, cached |
| 2 baseline | each source is recompiled *unmodified* through the mutant path, each test is relinked from those objects and run; the harness objects are compared with Buck2's own objects | RE, cached |
| 3 `mutant_compile` | `dynamic_output` over the lists: one action per mutant writes the mutated copy of the source and compiles it with the same command; result = sha256 of the object, or `unviable` | RE, cached |
| 4 `mutant_run` | `dynamic_output` over the compile results: for every mutant whose object is new (not the baseline's, not an earlier mutant's) and every test, one action relinks the test with the mutated object and runs it with ctest (`--seed 1`) | RE, cached |
| 5 `mutant_report` | one `report.json` with the raw facts of all of the above | RE |

An action is keyed on its inputs: the mutant spec and source for step 3, the objects for step 4. An
unchanged tree executes **zero** actions; a changed test re-links and re-runs the live mutants of that
module only (other modules and the compile steps are cached). A source edit that moves offsets changes the
specs of the mutants after it, so those compile again (their objects are usually identical, so step 4 is
cached again).

## Mutants
`gen.py` uses an AST range only if its begin and end are plain locations in the main file; a node touching a
macro expansion (`spellingLoc`/`expansionLoc`) is skipped, and so is a binary operator whose token is not
found, between blanks and comments only, exactly where the AST says it is. The effect: code in macros is
never mis-mutated, and a mutant is always a precise byte replacement (`begin_offset`, `end_offset`,
`original`, `replacement`). The mutant carries `operator`, `function`, `line` and a stable `id`.
No mutation is made under `case` labels, enumerator values, bit-field widths, `_Static_assert` or `sizeof`.

| Operator | Replacement |
|---|---|
| `relational` | `<`: `<=` `>=`; `<=`: `<` `>`; `>`: `>=` `<=`; `>=`: `>` `<`; `==`: `!=`; `!=`: `==` |
| `arithmetic` | `+`<->`-`, `*`->`/`, `/`->`*`, `%`->`*`, `<<`<->`>>`, `&`<->`\|`, `^`->`&` (never when an operand is a pointer or array) |
| `logical` | `&&`<->`\|\|` |
| `not-removal` | delete the `!` |
| `compound-assignment` | `+=`<->`-=`, `*=`->`/=`, `/=`->`*=`, `%=`->`*=`, `<<=`<->`>>=`, `&=`<->`\|=`, `^=`->`&=` |
| `increment` | `++`<->`--` |
| `integer-literal` | `0`->`1`, `1`->`0`, `n`->`n+1`; notation (hex) and suffix kept |
| `condition` | the condition of `if`, `while`, `do`, `for` becomes `!(c)` |
| `return-value` | `return e;` -> `return ((void)(e), (T)0);` with T the expression's type (`(T)1` when it was `0`); not for struct, union, complex or void; `e` is still evaluated, so no variable or parameter becomes unused |
| `statement-deletion` | an expression statement that is a call -> `(void)0;` |
| `function-body` | body of a scalar function -> `{ (void)p; ... return 0; }`, void -> `{ (void)p; ... }` (pseudo-tested function check) |

If two operators propose the same text change, one mutant is kept. Compile failure (including a warning
that is an error under the sealed flags) = `unviable`.

### Ids
`id` = first 16 hex digits of sha256 over `file`, `function`, `operator`, `original`, `replacement` and the
ordinal of the mutant among those equal in the function (`NUL`-separated). No line or offset is in it, so an
approval survives edits elsewhere in the file. (Deviation from the task text: `replacement` is part of the
hash, because `<`->`<=` and `<`->`>=` at one place would otherwise collide.)

## Verdicts (derived by `rigor mutants`, never by the build)
| Verdict | Meaning |
|---|---|
| `unviable` | the mutated source did not compile; reported, not counted against the tests |
| `equivalent` | object byte-identical to the unmutated object (trivial compiler equivalence, TCE) |
| `duplicate` | object identical to an earlier mutant's in the same file; that mutant's verdict stands |
| `killed-assert` | some test failed with a check failure (`N of M checks failed; first: ...`) |
| `killed-crash` | no check failure, but a test crashed, was killed, timed out (ctest 10 s per test, 180 s per binary), tripped a sanitizer exit, or the binary died |
| `survived` | every test passed |
| `unrun` | a live mutant has no usable run (a `missing-run` or `bad-results` finding says why) |

## `rigor mutants --results DIR --policy P.toml [--out F] [--approvals DIR --repo R --head H]`
`DIR` holds one `report.json` copy (`*.json`) per `c_mutants` target; the policy is
`[module."//pkg:name"]` with `level = "L3" | "L2"` for each. Findings (all errors unless noted):

| Rule | When |
|---|---|
| `survived-mutant` | L3 module, survivor not covered by an `equivalent-mutant` approval whose scope is the mutant id. L2: info `survivor` |
| `no-mutants` | a source with functions but no mutants (the generator went blind) |
| `all-unviable` | every mutant of a module failed to compile |
| `crash-only-function`, `no-assert-kill-function` | L3: a function with mutants none of which was killed by a failed check (only crashes, or only equivalent/unviable ones) |
| `baseline-red` | the unmutated tests are not all passing with at least one assertion each |
| `harness-mismatch` | the unmutated recompile is not byte-identical to Buck2's own object |
| `missing-run`, `bad-results` | a live mutant has no run, or results that are unparsable, skip a test, disagree with the exit status, or name other tests than the baseline |
| `module-not-in-policy`, `policy-module-without-report` | report and policy disagree |
| `forged-approval` | as in docs/gate.md |

Exit 2: unreadable or malformed report or policy, a stray file in `DIR`, two reports for one label, no
reports. Metadata per module: total, counts per verdict and per operator, survivors with `file:line`.
Approvals never cover anything but a survivor.

## Limits and notes
- Release mode only. The `san` mode would add sanitizer kills but doubles the compile and link work; not done.
- Macro-heavy code is mutated less, by design (an expression that touches a macro is skipped).
- Pointer-arithmetic and struct-valued returns are not mutated.
- The 10 s per-test and 180 s per-binary limits are wall-clock, as in ctest.
- Mull cross-check: not done. A Mull release for LLVM 19 would have to be fetched by a sha256 that is not
  known in advance, and the sandbox has no network apart from Buck2's pinned archives.
- Report integrity rests on the build: `rigor mutants` re-derives every verdict from the raw facts, but a
  forged `report.json` is as trustworthy as the build that made it (the driver builds it freshly on RE).
