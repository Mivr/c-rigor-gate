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

A dep may be a **header-only test kit** (a `c_library` with `srcs = []`, as in annas-c): it has no archive, so it adds
nothing to the link line (the tests were compiled against its headers by Buck2). A dep that has neither an archive nor
headers of its own is an analysis error (`provides neither a library nor headers`), never silently dropped. Canary
`header-only-kit`, selftest module `uninit`.

## Pipeline
| Step | What | Where |
|---|---|---|
| 1 `mutant_list` | per source: the pinned clang with the module's **exact compile command** (the argsfile Buck2 itself uses) runs `-Xclang -ast-dump=json -fsyntax-only`; `mutate/gen.py` reads the JSON and writes the sorted mutant list | RE, cached |
| 2 baseline | each source is recompiled *unmodified* through the mutant path, each test is relinked from those objects and run; the harness objects are compared with Buck2's own objects | RE, cached |
| 3 `mutant_compile` | `dynamic_output` over the lists: one action per mutant writes the mutated copy of the source and compiles it with the same command; result = sha256 of the object, or `unviable` | RE, cached |
| 4 `mutant_run` | `dynamic_output` over the compile results: for every mutant whose object is new (not the baseline's, not an earlier mutant's) and every test, one action relinks the test with the mutated object and runs it with ctest (`--seed 1`) | RE, cached |
| 5 `mutant_report` | one `report.json` with the raw facts of all of the above | RE |

### Deterministic results (T034, B34)
What `mutant_run` stores is a function of the verdict, not of the execution: a mutant that reads uninitialised memory
or past an array must give the same stored text every time. `tool.py linkrun` therefore normalises before it writes:

| Stored | Becomes |
|---|---|
| a failed-check reason `N of M checks failed; first: f.c:L: CHECK_X(a, b): got != want` | `0 of 0 checks failed; first: f.c:L: CHECK_X(a, b)` (place and text of the check kept; counts and observed values, numbers, strings, addresses dropped; the prefix still matches the verdict code) |
| any other reason (`killed by signal 11`, `timeout after 10 s`, ...) | the same words with every number (decimal or `0x...`) turned into `#` |
| `asserts` of a test line | 0 or 1 (the verdicts only ask for at least one) |
| `rc` of the test binary | 0 or 1 as is, -9 for the timeout kill, -1 for any other way of dying |
| a results line that is not a JSON object | the line `!`, which still does not parse |

Normalising never turns a crash into a check failure or back, and keeps `status` and test ids, so no verdict changes
(`gate/tests/test_mutate_tool.py` runs `outcome_of_run` before and after). `selftest/mutate.sh` builds the `uninit`
module twice with different nonces in the test source (every mutant is run again) and requires byte-identical reports.

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
### Macros (R002 F1, F3; B24, B25)
A node whose begin or end is a macro expansion has no plain span, so it is not mutated; before T028 that was silent,
and a backdoor in a function-like macro defined in the module's own `.c` passed L3 with zero survivors (the function
still had other mutants). The choice made is to **report, not to mutate inside the expansion**: a token that a macro
spells has no source line of its own to replace (the same bytes serve every use), so a mutant could not be a precise
byte replacement and could not be tied to one place; and a finding cannot be dodged by choosing a different macro shape.

`gen.py` classifies, for every node inside a mutated function, each location that is an expansion by where its token
is *spelled* (`Walker.note_macros`):
| Spelled in | Meaning | Result |
|---|---|---|
| a `--system-root` directory (`stdbool.h`, `stdint.h`, `assert.h`, ...) | `NULL`, `bool`, `INT32_MAX`, `offsetof`, ... | nothing |
| `<built-in>` | `__LINE__`, `__INT_MAX__` | nothing |
| the main file, after the use's start | a macro **argument**: text the author wrote at the call | nothing (it is plain text) |
| the main file before the use, a product header, `<command line>` | a body of a macro of the product | `hidden` entry |
| `<scratch space>` (`##`, `#`) | names no macro | `hidden` entry, unless another token of the same macro proves it the toolchain's |

Each entry is `{function, macro, line, defined_in}` (the macro name is read at the use, the line is that of the use).
`rigor mutants` turns every entry into **`macro-hidden-code`**: error at L3 and above, info at L2, not approvable
(move the code out of the macro: an inline function in a source file, or `enum`/`static const` for a constant).
Not looked at, because they decide nothing alone: literals, casts, parentheses, names, declarations, attributes,
compound literals, and any **constant expression** (literals, `sizeof`, enumerators and operators between them): a
macro `#define N (4 * 1024)` is not a finding. A macro that writes an operator is found by another route: the
generator looks for the operator token between its two operands (`operand_span`: an operand may be a macro use, or an
argument, and still be located); if a macro wrote the operator (`a PLUS b`, `SUM(a, b)`), the token is not there and
that is the same finding. The operator next to a macro constant (`x < LIMIT`) is plain text and **is mutated**
(`x <= LIMIT`); before T028 it was skipped with the rest of the expression.
Function-like macros that wrap *plain* code in their arguments (`assert(a < b)`) keep their arguments' operators
mutated for the same reason; other node kinds inside such an argument (a call, a `?:` condition) are still not.
Limit: a pure `##` product-header macro whose every token is pasted, in a node that is not a literal, is a finding only
if its name is not proven the toolchain's by another of its tokens in the same source (`UINT64_C(5)` alone is a finding;
`UINT64_MAX - d` is not).

**F3.** "Made by a macro" is decided from where the function's *name* and its *body* are, never from `range.begin`
(for `bool f(int)` that is the macro `bool`, and the function is an ordinary one). T017 had already moved the decision
to the body; T028 adds the name (a name written by a macro, `DEF(n)` or `#define NAMED f`, is `skipped` with reason
`macro` and an L3 `unmutated-function`).

### Accounting (B19)
Every function **definition** (a non-implicit `FunctionDecl` with a `CompoundStmt` among its children, wherever
among them: clang lists attributes such as `noinline` or `cold` after the body) outside the toolchain's own
headers is in exactly one of `functions` and `skipped` of the source's entry:
- `functions`: mutated, or, when no mutation applies (for example `for (;;) {}`), listed with
  `"reason": "no-mutable-token"` (an `info` finding of the same name; nothing to test there).
- `skipped`: the body is made by a macro or lives in a product header (`unmutated-function`, as before). A node
  whose range only *starts* in a macro (`NOINLINE int f(void) { ... }`) is not that: its body is plain text and it is
  mutated.

The invariant is checked twice, by code that shares nothing:
1. `gen.py` counts the definitions with `audit_definitions`, a second walk over the raw AST that uses none of the
   walker's state, and compares by name with what the walker listed. A difference (or a function with two
   bodies) is exit **2**, nothing written, so the Buck2 action fails.
2. The report carries that count as `definitions`. `rigor mutants` fails any source where
   `len(functions) + len(skipped) != definitions`, where a name appears twice, where a function has neither a mutant
   nor a reason, where a mutant names an unlisted function, or where a reason is given for a mutated one
   (`unaccounted-function`, every level). A report without `definitions` is exit 2.

Asm labels (`int f(void) __asm__("x")`) and the `used`/`section` attributes are refused upstream (`inline-asm`,
`forbidden-attribute`); the generator accounts for them regardless (fixtures in `gate/tests/fixtures/mutate/`).

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
| `enum-constant` | an enumerator used as a value (return, assignment, argument, comparison operand) -> the next enumerator of the same enum in declaration order, wrapping; none when the enum has one value |
| `string-literal` | a non-empty `"..."` -> `""`; and its first byte incremented (second mutant; none when the byte is an escape start, non-ASCII, or the next byte would be `"` or `\\`) |
| `char-literal` | `'c'` -> `('c' + 1)`, any spelling (`'\\n'`, `L'x'`) |

### Toolchain macros in conditions and returns (T035; R003 G2, B28)
A condition (`if`, `while`, `do`, `for`) or a `return` value that contains macros of the **toolchain** only
(`NULL`, `true`/`false`, `INT_MAX`, `assert`, ...: spelled in a `--system-root`, in `<built-in>`, or a plain macro
argument) has a main-file location even though its range ends in an expansion: the text from the first token to
the last as the main file shows it (a macro's name at its use, a function-like macro's call up to its closing
parenthesis; `visible_span`). That location is the **G2 location rule**. It gives the `condition` mutant
(`if (a == NULL || b == NULL)` -> `if (!(a == NULL || b == NULL))`), and `return true;`/`return INT_MAX;` its
`return-value` mutant (`false`, `NULL` and any constant 0 flip to 1). The text must have balanced parentheses, so a
macro that swallows half an expression (`SYS_ID(x) > 3`) is not cut. Mutants rewrite main-file bytes around the macro
token, never inside it. A single product macro anywhere below the expression (`IS_NULL(p)`) keeps the expression
unmutated and under `macro-hidden-code`, as in T028 (unchanged). An `if` whose branch ends in a toolchain macro
(`if (p == NULL) return NULL;`) is no longer skipped as a whole for its condition. The relational and logical
operators next to such macros were already mutated by T028.

### Literal operators (T035; R003 G3, B29)
Kill semantics: `enum-constant` is killed by a test that pins *which* enumerator comes out (not just `!= OK`);
`string-literal` by one that compares the text (not just `!= NULL`); `char-literal` by one that checks the character.
Never mutated: case labels, enumerator values, bit-field widths, `_Static_assert`, `sizeof`/array sizes (a string
that initialises an unsized array, `char buf[] = "..."`, sizes it), attribute arguments, assembler text, and
literals a macro spells (a product macro's text is a finding; a toolchain's is not ours). A mutant that does not
compile (a shadowed enumerator, a format check on `""`) is `unviable`, as for any operator, never a survivor; one whose
object is identical (two enumerators of equal value) is `equivalent`.

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
`[module."//pkg:name"]` with `level = "L2" | "L3" | "L4" | "L5"` for each (L3, L4 and L5 are equally strict;
L1 is "not mutated" and never appears here; `rigor grade` writes this policy, see docs/grade.md). Findings (all errors unless noted):

| Rule | When |
|---|---|
| `survived-mutant` | L3 module, survivor not covered by an `equivalent-mutant` approval whose scope is the mutant id. L2: info `survivor` |
| `no-mutants` | a source with functions but no mutants (the generator went blind), or a module none of whose sources produced a mutant at all, even without functions (a gate that mutates nothing must not pass; a pure-data module is L1 by policy). `gen.py` itself exits non-zero, failing the build, when no location of the AST names the source file |
| `unviable-ratio` | more than 25 % of the module's generated mutants are `unviable` (code shaped to make mutants fail to compile, B11). L3+: error; L2: info. Not reported when all are unviable (`all-unviable`) |
| `macro-hidden-code` | a function body uses code a macro of the product wrote (see Macros). L3: error; L2: info. Not approvable |
| `unmutated-function` | L3 (info in L2): a function with a body that no mutant can reach, because a macro makes it or it is defined in a header of the product (not one of the toolchain's `--system-root`s). Move the code into a source file; not approvable |
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
- Macro-heavy code is mutated less: an expression that touches a macro is not mutated as a whole, and the code a product
  macro writes is a finding (`macro-hidden-code`), not a silent skip. `rigor mutants` reads `hidden` in the report; a report without it is exit 2.
- Pointer-arithmetic and struct-valued returns are not mutated. File-scope initializers (constant tables)
  are not mutated; only function bodies are.
- The 10 s per-test and 180 s per-binary limits are wall-clock, as in ctest.
- Mull cross-check: not done. A Mull release for LLVM 19 would have to be fetched by a sha256 that is not
  known in advance, and the sandbox has no network apart from Buck2's pinned archives.
- Report integrity rests on the build: `rigor mutants` re-derives every verdict from the raw facts, but a
  forged `report.json` is as trustworthy as the build that made it (the driver builds it freshly on RE).
- A test can still kill mutants for the wrong reason, for example by hashing the machine code of the function under
  test: every mutant then fails a check. Nothing in the gate detects that (the `symbols` policy is the only barrier);
  hidden tests and the red team (B7, B8) are the answer.
- In `c_mutants` a test is named `<package>__<name>` in the report (every character outside `[a-z0-9_]` becomes
  `_`), because two packages may each have a test called `arena_test` and both can depend on the same module.
