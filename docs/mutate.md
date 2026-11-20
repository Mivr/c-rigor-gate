# Mutation testing for C (T006)

Coverage says a line ran, not that a test would notice if the line were wrong. A mutant is the module with
one small, deliberate defect; if every test still passes, the tests do not constrain that behaviour. The rule
for L3 modules is **zero surviving mutants**; the only way past one is a signed `equivalent-mutant` approval.

Everything runs on RE in the `release` mode (a grading builds the `c_mutants` targets in chunks of 12, three at a time, T115/T121; the target name derives from the module label, so action keys do not depend on the module's position; `docs/grade.md`): `buck2 build //pkg:<name>` of a `c_mutants` target yields
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
| 3 `mutant_compile` | `dynamic_output` over the lists: one action per **batch** of at most 16 mutants (T064) writes the mutated copy of the source and compiles it with the same command, once per mutant; result = sha256 of the object, or `unviable` | RE, cached |
| 3b `mutant_compile_o0` | the same, in batches, for every mutant whose `-O2` object equals the baseline's or an earlier mutant's (the candidates for `equivalent` and `duplicate`), and for each source's unmodified baseline: the same command with `-O0` appended (T051, B15) | RE, cached |
| 4 `mutant_run` | `dynamic_output` over the compile results: for every mutant that is live (see below) and every test, one action per batch and test relinks, for each mutant of the batch in its own process, the test with the mutated object (the `-O0` one for a mutant the optimiser folded) and runs it with ctest (`--seed 1`) | RE, cached |
| 4c `mutant_perf` | only with `perf = [...]` (T090, "Perf kills" below): for every mutant that passed all its tests, one action per perf target relinks the perf binary with the mutated object and runs it; one more action per target measures the unmutated module the same way | RE, cached |
| 5 `mutant_report` | one `report.json` with the raw facts of all of the above | RE |

### Batched actions (T064, R006 #9)
One Buck2 action per mutant meant about 110,000 actions for annas-c: the daemon was OOM-killed at 8 GiB with 109k pending.
Now `c_mutants` has an attribute `batch` (default 16):
| What | One action per |
|---|---|
| `mutant_compile` (`-O2`) and `mutant_compile_o0` | batch of at most `batch` mutants (of one or more sources); `tool.py compile-batch` compiles each mutant on its own, in its own scratch directory, and writes its object and its record. A mutant the compiler rejects is `unviable`, the others still compile. A compiler crash or a stale spec fails the batch (as it failed the single action) |
| `mutant_run` | batch and test (resource limits: every mutant binary runs under the ctest harness limits, 64 MiB per file, 20 s CPU per test, 256 descriptors, no core, a 256 MiB scratch quota per test, see "Runaway tests" below); `tool.py linkrun-batch` links and runs each mutant in a fresh process and scratch directory, one after another, with the timeouts of before (10 s per test inside ctest) and an adaptive limit per binary instead of a fixed 180 s (T122, "Adaptive run limit" below). A crash or timeout is that mutant's record only; a failed link fails the batch. **Stop at the first kill (T121):** the action is per batch and *group* of tests (the module's own package's tests first, then the others, in groups of 16, every order fixed by the labels). A mutant's runs stop at the first one that fails a check; the later runs of that mutant, in the group and in every later group (each group action reads the previous group's record of the mutant), are not made and are recorded as `{"killed_by": <test>}`. A surviving mutant, or one that only crashes, runs every test. The report's `tests` is this order; `runs` holds every test, the skipped ones as `killed_by` records. Measured on business-apps (lk/audit): 78,126 of about 86,800 test runs ran after the mutant was already dead |

The records are the same files as before (`obj/.../<id>.json`, `run/.../<id>.json`), one per mutant (and test), so
`collect` and `rigor mutants` are unchanged; a missing record fails the build (exit 2, never a pass). A batch that fails
as a whole fails the module's build, which the grading driver reports as `mutants-build-failed`.
Batches are formed by `_batches` in `rules/mutate.bzl`, deterministically: mutants sorted by (source, function, id), packed
in that order, a batch may span sources, and a function that fits in a batch is never split. (Sorting by id alone, as the
T064 contract first said, scatters the mutants of one function over every batch, so an edit to one function would
invalidate nearly all of them.) Which mutant is the "duplicate" of which is still decided in the order of the mutant list.
An action's key is the specs and source (compile) or the objects (run) of its batch: an edit to one function re-compiles the
batches of that source (the source is an input, as before) and re-runs only the batches whose objects changed.
Not changed by batching: the `-O2` identity check, the `-O0` cross-check, `unviable`, and every verdict. `selftest/mutate.sh`
builds four modules a second and third time with `batch = 1` (one mutant per action, the old shape) and `batch = 3` and requires
the report to be byte-identical to the default build; `gate/tests/test_mutate_batch.py` checks the two tool commands against the one-mutant
ones. The `detail` of an `unviable` record no longer names the scratch directory (it was a `buck-out` path before; no verdict reads it).

### Equivalence is checked at -O0 too (T051, B15; R001 R2)
At `-O2` the optimiser can fold a behaviour-changing mutation into the baseline object. The classic case is undefined
behaviour: in `return (a + 1 < a) ? 7 : 3;` the condition is false for every defined `int`, so `-O2` deletes the branch and
`7 -> 8` compiles to the baseline's bytes. Before T051 that mutant was `equivalent` and never ran, whatever the tests did.

Only the candidates are compiled again (a mutant whose `-O2` object already differs costs nothing extra), the baseline once
per source, with the module's exact compile command and `-O0` appended (the last `-O` wins). Then:
| Candidate | At `-O0` | Verdict |
|---|---|---|
| `-O2` object == baseline's | object == baseline's `-O0` object | `equivalent` (not run) |
| | different | live: its `-O0` object is relinked into each test and run; killed or `survived` like any mutant |
| `-O2` object == an earlier mutant's | object == that mutant's `-O0` object (or another live one's) | `duplicate` of it |
| | different | live, as above |
| no usable `-O0` result in the report (missing or failed) | | `unrun` with a `missing-o0` finding (never equivalent: the claim could not be checked) |

`rules/mutate.bzl` `_stage3` (which mutants to run) and `mutants_verdict.derive` (the verdict) apply the same rule; the report
carries `baseline_o0` per source and `compile.o0 = {status, hash}` per candidate. The verdict metadata of a module has
`tce = {equivalent_o2, equivalent_o0}`: how many mutants had the baseline's `-O2` object, and how many of those still have
its `-O0` object (the `equivalent` verdicts); the difference ran as live mutants.

Consequence for products: a mutation that is harmless but not folded away at `-O0` (`x * 1 -> x / 1`, a dead store
`int v = 0;` -> `= 1`) is now live, and a test cannot kill it; it needs an `equivalent-mutant` approval or a source change.
Only mutants identical at both levels (a constant the front end folds, `1 * 1 -> 1 / 1`) stay `equivalent`. A folded
mutant is run at `-O0` against tests that passed at `-O2`; for undefined behaviour the two builds legitimately differ, so a
test written against the optimised result kills such a mutant, and a test that never reaches the branch lets it survive.
Canary `o2-folded-mutant`; selftest `mutate.sh` module `fold`.

### Runaway tests (T097)
A mutant can turn a bounded loop into an endless one (`left -= w` -> `left += w` in a write retry). In a test that uses a real file under
`$TMPDIR` that filled the shared RE farm's disk (`No space left on device ... /data/cas/tmp`). The harness every `c_test` and every
`mutant_run` executes (`ctest_run`, [ctest.md](ctest.md#resource-limits-t097)) therefore sets `RLIMIT_FSIZE` 64 MiB, `RLIMIT_CPU` 20 s per test,
`RLIMIT_NOFILE` 256 and `RLIMIT_CORE` 0, ignores `SIGXFSZ`, gives each test a private `$TMPDIR` with a 256 MiB / 4096 entry quota and removes it
afterwards. The mutant's test then fails on `EFBIG` (a failed check: `killed-assert`) or is killed by the quota or `SIGXCPU`
(`killed-crash`); it never becomes `unrun` or an action error, and the action finishes in seconds instead of at the 180 s kill.
`selftest/mutate.sh` module `runaway` proves it with the incident's mutant.

### Deterministic results (T034, B34)
What `mutant_run` stores is a function of the verdict, not of the execution: a mutant that reads uninitialised memory
or past an array must give the same stored text every time. `tool.py linkrun` therefore normalises before it writes:

| Stored | Becomes |
|---|---|
| a failed-check reason `N of M checks failed; first: f.c:L: CHECK_X(a, b): got != want` | the constant `0 of 0 checks failed; first: (not stored)` (the verdict code only asks for the prefix; counts, observed values, and which check failed first are dropped, T067: for a mutant that reads uninitialised memory the first failing check depends on the garbage, and its place and text reached the report) |
| any other reason (`killed by signal 11`, `timeout after 10 s`, ...) | the same words with every number (decimal or `0x...`) turned into `#` |
| `asserts` of a test line | 0 or 1 (the verdicts only ask for at least one) |
| `rc` of the test binary | 0 or 1 as is, -9 for the timeout kill, -1 for any other way of dying |
| a results line that is not a JSON object | the line `!`, which still does not parse |

Normalising never turns a crash into a check failure or back, and keeps `status` and test ids, so no verdict changes
(`gate/tests/test_mutate_tool.py` runs `outcome_of_run` before and after). `selftest/mutate.sh` builds the `uninit`
module twice with different nonces in the test source (every mutant is run again) and requires byte-identical reports; T064's batch-size comparison is byte for byte for `uninit` as well.

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
| `return-value` | `return e;` -> `return ((void)(e), (T)0);` with T the expression's type (`(T)1` when it was `0`); not for complex or void; `e` is still evaluated, so no variable or parameter becomes unused. **Struct or union return (T050):** `return ((void)(e), (T){0});` with T the declared return type (qualifiers dropped), unless `e` already is `(T){0}` |
| `statement-deletion` | an expression statement that is a call -> `(void)0;` |
| `function-body` | body of a scalar function -> `{ (void)p; ... return 0; }`, void -> `{ (void)p; ... }`, struct or union -> `{ (void)p; ... return (T){0}; }` (pseudo-tested function check) |
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

### Ids (B18, T058)
`id` = first 16 hex digits of sha256 over `file`, `function`, `operator`, `original` (the mutated token's text),
`replacement`, the sha256 of the **body of the enclosing function** and the ordinal (`NUL`-separated). The body is
normalised for white space and comments only: comments become one space, runs of white space one space, line splices
vanish, string and character literals stay exact. The ordinal is a tie-break only, among candidates of that same body
with identical `operator`, `original` and `replacement`. No line or offset is in it, so an approval survives edits
elsewhere in the file and a moved function; the id does not depend on the checkout's path (`file` is the path the
module's target gives, relative to the repository), the machine or the run.
**Any other change to the function body changes every id in that function.** An `equivalent-mutant` approval written
for an old id then names no mutant: it does not cover the survivor that now has the same ordinal (which is an ordinary
`survived-mutant`), and it is absent from `approvals_used`. No fuzzy matching: a refactor means a new approval.
(`replacement` is part of the hash, because `<`->`<=` and `<`->`>=` at one place would otherwise collide.)
**Cold caches, once:** every id changes with this change, so mutant verdict caches keyed on ids go cold once, and every
existing `equivalent-mutant` approval of a product must be re-issued. `selftest/mutate.sh` pins the drift case.
Old formula: sha256 of `file`, `function`, `operator`, `original`, `replacement`, ordinal.

### Struct and union returns (T050; R003 G4, G5; B30)
A function whose return type is a struct or union gets the `function-body` mutant `{ (void)p; ... return (T){0}; }` and
every `return e;` the `return-value` mutant `((void)(e), (T){0})`, T being the declared return type without
`static`/`inline`/`const`/`volatile`; so a struct-returning function that is only called, never checked, now has
survivors (canary `struct-return-untested`). "Is a struct" is resolved from the AST, never from the spelling:
`TypedefDecl` nodes are read (`typedef_kinds`), anonymous (`typedef struct {..} T`) and tagged typedefs, and any chain of
typedefs (`typedef span_t span2_t`) lead to a record; a typedef of a complex type does not. Because a typedef'd struct is
no longer classed as scalar, no `return 0` / `(T)0` mutant that cannot compile is made for it (G5: the false
`no-assert-kill-function` and the unviable ratio are gone; selftest module `rec`). `(T){0}` is the universal zero
initializer, which the pinned clang accepts for any struct or union.

`no-mutable-token`: a function with a body but no mutant. With this change every function whose body starts with `{`
and whose return type is void, a scalar or a record has the `function-body` mutant, so what is left is a complex or
function-pointer return. `mutants_verdict.accounting_findings(report, level)` makes it an **error at L3 and above**
and info below; with no `level` it is info (the caller must pass the module's level).

## Lane workflow: `tools/mutants` (T123)

A lane that must kill the survivors of its module does **not** write a `c_mutants` target in a scratch clone (other
action keys: the whole-repo grade then measured the same mutants again from scratch). From the lane's worktree, after
committing:

    gate/tools/mutants //path/to/module [//other:module ...] --product gate/products/<p>/product.toml [--level L3] [--head SHA] [--uncached]

(`rigor lane-mutants`, `gate/rigor_lib/lane_mutants.py`.) It builds the grade's tree from the commit (`HEAD` by default; a
checkout with uncommitted changes to tracked files is refused, the grade grades commits) in a work directory outside
the checkout (`$TMPDIR/lane-mutants/<checkout>`, or `--work`), so the product tree is never touched. The module list
comes from the grade's own `grade_mutants.build_plan` (policy levels, the tests of the module's own package that depend on it, link deps,
perf targets), and the chosen modules get the grade's `gate-mutants/BUCK` entries (`write_package`: same target name,
attributes, tests and order, same rules), built with the pinned Buck2 on RE and judged by `grade_mutants.judge`
(`rigor mutants`' code). A module that is not mutated (level L1, no test in its own package, not in the policy) is exit 2, naming the choices.

Output: one line per mutant (`verdict  module  file:line  id  function: original -> replacement`; verdicts killed-assert,
killed-crash, killed-perf, survived, unviable, unrun, equivalent, duplicate), a count line per module, the findings that
are errors at the module's level, `mutant actions: N executed, M from the cache`, and the verdict the grade would give.
Exit 0 = no error finding, 1 = some, 2 = internal error. `--level` changes only the level the verdict is judged at (the
actions do not depend on it).

**What is shared:** the `mutant_list`, baseline, `mutant_compile`, `mutant_compile_o0` and `mutant_run` actions have the
same keys as the grade's, so the grade of the same sources executes none of them for that module
(`selftest/mutants_lane.sh`: the grade runs zero `mutant_run` actions for the measured module, its report is byte-identical
to the lane's). A change to the module, its tests, its deps or the gate commit makes new actions in both, as always.
**Not shared:** modules with perf targets are measured without the perf bundle the grade may have (those actions differ);
the whole-repo verdict (other modules, `level-missing` findings and the like) is still the grade's.

## Perf kills: `killed-perf` (T090, G30)
Some mutants are not equivalent although no test can see them: in a hash map, `hash(key)` replaced by `return 0`
leaves the map correct and makes every operation O(n). The module's complexity is a promise (`docs/perf.md`,
"Judging"); a mutant that breaks it is killed by that promise.

- **The attribute.** `c_mutants(name, module, tests, deps, perf = [":x_perf", ...])` (`rules/c.bzl`): `perf` lists the
  `c_perf` targets that exercise the module. `rigor grade` writes it into `gate-mutants/BUCK` for a module
  whose policy declares perf targets, and links the libraries of the perf binaries into the module's mutant links. The
  `[perf]` sub-target of the `c_mutants` target is `perf.json` (evidence, below).
- **Which mutants.** A functional killer costs nothing extra. The perf stage is a `dynamic_output` over the test runs: a
  mutant for which every test run passed (`rc` 0, no timeout) gets one `mutant_perf` action per perf target: the
  driver objects of the `c_perf` binary, the mutated module object (the `-O0` object for a mutant the optimiser folded;
  the baseline objects for the other sources), the link flags of the tests plus the `-Wl,--wrap=` list, the harness
  `gate//ctest:perf` (never `ctest`, which has its own `main`), run with the sizes and seed of the target. The actions
  are independent and cached on the mutant's object, like `mutant_run`.
- **Cost per survivor.** One link and one harness run per perf target: about 0.5 s of work on top of the roughly 1.5 s fixed
  cost of an RE action (measured: 24 `mutant_perf` actions of the `flat` fixture, 2.0 s average and 3.5 s at most,
  the whole stage adds one layer of about 3 s plus the 1 s `mutant_perf_report`; a mutant that makes the driver quadratic
  costs its quadratic run, the harness caps each size at 100 s). A module with no survivors costs the baseline run only.
  A module without `perf` is unchanged: not a single action more.
- **Evidence** (`perf.json`, read by `mutants_perf.py`): `{"schema": 1, "label", "targets": {"<perf label>": {"baseline":
  [records], "mutants": {"<mutant id>": [records]}}}}`; records are those of `perf.jsonl`, or one marker line
  (`{"marker": "link-failed"}`, `harness-failed`) when the link or the harness did not produce records.
- **The verdict** (`rigor mutants --perf-results DIR`, the policy table `[module."label".perf."<perf label>"] class = "O(n)"`
  that `rigor grade` writes from the product policy). A `survived` mutant becomes `killed-perf` when for some target its
  records are all `ok` and a counter leaves the class (`perf_judge.exceeded`, the same thresholds as the `perf` gate),
  or its run timed out. A mutant that crashes, fails to link, or whose run is otherwise not ok stays `survived`: that is
  behaviour the tests missed, not a complexity change. The baseline is measured through the same link; if it is not
  ok or is itself outside the class, nothing is judged against it (`perf-baseline-bad`), and an unreadable counter gives
  `perf-counter-unavailable`. Both only when there is a survivor to judge; error at L3 and above, info at L2.
  `perf-evidence-missing` (always an error) means a survivor has no record: the rule and the verdicts disagree.
- **Accounting.** `killed-perf` counts as killed: it is not a survivor, needs no approval, and a function whose mutants are
  killed by checks or by perf is not `no-assert-kill-function`. `crash-kill-ratio` counts only `killed-assert` and
  `killed-crash`, so it is unaffected. The module summary gets `verdicts.killed-perf` and a `perf` object
  (`targets`, `candidates`, `killed`: id, place, target, class, counter, both counts, ratio, limit); it is absent for
  a module without perf.

## Verdicts (derived by `rigor mutants`, never by the build)
| Verdict | Meaning |
|---|---|
| `unviable` | the mutated source did not compile; reported, not counted against the tests |
| `equivalent` | object byte-identical to the unmutated object at `-O2` and at `-O0` (trivial compiler equivalence, TCE) |
| `duplicate` | object identical to an earlier mutant's in the same file at `-O2` and at `-O0`; that mutant's verdict stands |
| `killed-assert` | some test failed with a check failure (`N of M checks failed; first: ...`) |
| `killed-crash` | no check failure, but a test crashed, was killed, timed out (ctest 10 s per test, the adaptive per-binary limit of at most 180 s), tripped a sanitizer exit, or the binary died |
| `killed-perf` | every test passed, but a perf target of the module (`perf = [...]`) left its declared complexity class with this mutant (T090, below). Counted as killed, reported separately |
| `survived` | every test passed |
| `unrun` | a live mutant has no usable run (a `missing-run`, `bad-results` or `bad-skip` finding says why) |

## Deferred modules at tier `merge` (T137)
`rigor grade --tier merge` does not build or run the mutants of a module whose mutation can only report: level L2 without a
`profile`, or a module with `profile` for which `profiles.required(profiles, level)` does not make `mutation_zero_survivors`
a `gate` (docs/grade.md, "Grade tiers"). `rigor mutants` itself is unchanged: it judges the reports it is given, with the
policy it is given, and the grade simply leaves a deferred module out of both. The gate lists the module as info
`mutation-deferred` (module, level, reason). What a deferred module cannot raise at merge, and only the nightly grade
(`--tier nightly`, the default) raises: `no-mutants` (an error at every level), `all-unviable`, `mutants-build-failed`, and for a profiled module at
L3 or above whose profile only reports mutation the survivor, `unviable-ratio` and `unmutated-function` errors. The mutants that exist and how they are judged do not
depend on the tier.

## `rigor mutants --results DIR --policy P.toml [--perf-results DIR] [--out F] [--approvals DIR --repo R --head H]`
`DIR` holds one `report.json` copy (`*.json`) per `c_mutants` target; the policy is
`[module."//pkg:name"]` with `level = "L2" | "L3" | "L4" | "L5"` for each (L3, L4 and L5 are equally strict;
L1 is "not mutated" and never appears here; `rigor grade` writes this policy, see docs/grade.md). Findings (all errors unless noted):

| Rule | When |
|---|---|
| `survived-mutant` | L3 module, survivor not covered by an `equivalent-mutant` approval whose scope is the mutant id. L2: info `survivor` |
| `no-mutants` | a source with functions but no mutants (the generator went blind), or a module none of whose sources produced a mutant at all, even without functions (a gate that mutates nothing must not pass; a pure-data module is L1 by policy). `gen.py` itself exits non-zero, failing the build, when no location of the AST names the source file |
| `unviable-ratio` | more than 25 % of the module's generated mutants are `unviable` (code shaped to make mutants fail to compile, B11). L3+: error; L2: info. Not reported when all are unviable (`all-unviable`) |
| `macro-hidden-code` | a function body uses code a macro of the product wrote (see Macros). L3: error; L2: info. Not approvable |
| `unmutated-function` | L3 (info in L2): a function with a body that no mutant can reach, because a macro makes it or it is defined in a header of the product (not one of the toolchain's `--system-root`s). Move the code into a source file; not approvable. `file` is the product-relative path (`annas/src/internal.h`), never the `buck-out/.../buck-headers/` copy the compiler read (T079). Only headers **of the product** are reported (T081): a header of another cell (`buck-out/v2/{gen,art}/<cell>/...` with a cell other than `root`: `gate//third_party/**`, the toolchain's), a Buck2 header tree whose product-relative path is under no package of the policy's modules (`psa/crypto_struct.h`), a path under `third_party/` or `external/`, and an absolute path under `/usr/` are skipped silently (an absolute path into `buck-out/` is classified like the relative one). Every other path, absolute ones included, is still reported (fail closed). |
| `all-unviable` | every mutant of a module failed to compile |
| `crash-only-function`, `no-assert-kill-function` | L3: a function with mutants none of which was killed by a failed check (only crashes, or only equivalent/unviable ones) |
| `crash-kill-ratio` | T078 / B31 (R003 G6): a function with at least `MIN_KILLS` (4) killed mutants, at least one of them killed by a failed check, whose `killed-crash` share is **over** `CRASH_RATIO_NUM/CRASH_RATIO_DEN` (1/2, integer arithmetic): the tests mostly check "does not crash". Error at L3 and above, info at L2. A function with no check kill at all is `crash-only-function`, not reported twice. Fields: `module`, `function`, `file`, `asserts`, `crashes`, `ratio`, `threshold`, `min_kills`. Constants live in `gate/rigor_lib/mutants_gate.py`. Calibration on the annas-c audit grade (13 modules, 562 functions with a kill, 7668 kills, 205 crashes): 503 functions are under 0.1, the highest honest ratio with 4+ kills is 0.42, and 8 functions are over 1/2. Fix by asserting the result, not only calling the function |
| `baseline-red` | the unmutated tests are not all passing with at least one assertion each |
| `harness-mismatch` | the unmutated recompile is not byte-identical to Buck2's own object |
| `missing-o0` | a mutant equal at `-O2` to the baseline or an earlier mutant has no usable `-O0` compile in the report (the verdict is `unrun`) |
| `bad-skip` | a run of a live mutant is marked skipped (`killed_by`), but the named test is not an earlier test whose run of that mutant fails a check (T121): a skipped run is never a pass and never trusted |
| `missing-run`, `bad-results` | a live mutant has no run, or results that are unparsable, skip a test, disagree with the exit status, or name other tests than the baseline |
| `module-not-in-policy`, `policy-module-without-report` | report and policy disagree |
| `forged-approval` | as in docs/gate.md |

Exit 2: unreadable or malformed report or policy, a stray file in `DIR`, two reports for one label, no
reports. Metadata per module: total, counts per verdict and per operator, survivors with `file:line`, `tce` (see above).
Approvals never cover anything but a survivor.

## Limits and notes
- Release mode only. The `san` mode would add sanitizer kills but doubles the compile and link work; not done.
- Macro-heavy code is mutated less: an expression that touches a macro is not mutated as a whole, and the code a product
  macro writes is a finding (`macro-hidden-code`), not a silent skip. `rigor mutants` reads `hidden` in the report; a report without it is exit 2.
- Pointer arithmetic is not mutated. Complex-valued and function-pointer-valued returns get no `function-body` mutant. File-scope initializers (constant tables)
  are not mutated; only function bodies are.
- The 10 s per-test limit (ctest, unchanged) and the per-binary limit (adaptive, at most 180 s, see "Adaptive run limit") are wall-clock.
- Mull cross-check: not done. A Mull release for LLVM 19 would have to be fetched by a sha256 that is not
  known in advance, and the sandbox has no network apart from Buck2's pinned archives.
- Report integrity rests on the build: `rigor mutants` re-derives every verdict from the raw facts, but a
  forged `report.json` is as trustworthy as the build that made it (the driver builds it freshly on RE).
- A test can still kill mutants for the wrong reason, for example by hashing the machine code of the function under
  test: every mutant then fails a check. Nothing in the gate detects that (the `symbols` policy is the only barrier);
  hidden tests and the red team (B7, B8) are the answer.
- In `c_mutants` a test is named `<package>__<name>` in the report (every character outside `[a-z0-9_]` becomes
  `_`), because two packages may each have a test called `arena_test` and both can depend on the same module.

## Adaptive run limit (T122)

A mutant can make a test loop forever, and every test binary that depends on the module then ran until the fixed 180 s
kill (about 175 binaries x 180 s = 8.7 h for one mutant on business-apps lk/inventory). The kill limit is now per test
binary and derived from that binary's own unmutated run:

    limit = clamp(20 x baseline_wall, 5 s, 180 s)        a baseline that itself timed out: 180 s

- The `mutant_run` action (batch and group of tests) runs each test binary unmutated once (`tool.py linkrun-batch
  --baseline`, the objects of the baseline link), the first time a mutant of the action needs that binary (a group whose
  mutants are all skipped by a kill runs nothing extra), on the machine and at the load of the mutant runs. Its wall
  time is never stored, so every record stays a function of the verdict and cache hits are unchanged. The one extra run
  per binary and action is small next to the mutant runs of a batch.
- K = 20 and MIN = 5 s: the fixture's baseline binaries run in a few milliseconds, so MIN decides, and 5 s is 500 times
  that, far beyond load jitter, yet a hanging binary costs 5 s instead of 180 s. K = 20 leaves a mutant that is
  legitimately slower (more iterations, a slower path) a margin of twenty times before it is called a hang. The ctest
  per-test limit (10 s, in the harness, not set by the tool) is unchanged; with several hanging tests it already
  bounded a binary by 10 s x tests, now also by the limit.
- A timeout is the same record as before (`timed_out`, rc -9, reason words unchanged), so verdict classes do not change.
  The only run whose record changes is one that took between the new limit and 180 s: it was a pass (or a check
  failure) and is now a timeout. For a deterministic test a run over 20 times its unmutated time is a behaviour change
  of the mutant (a livelock or a runaway loop), which is what `killed-crash` already says for a timeout; it cannot make a
  failed-check kill out of anything, and a survivor can only become `killed-crash` (never `killed-assert`), and only when
  a run was slower than 20x its baseline. A mutant that fails a check still is `killed-assert`, whatever else timed out.
- Not done (optional step): giving later runs of a mutant the limit MIN after one of its runs timed out. Verdicts are
  not the same: a later test that needs 6 s but fails a check would be cut at 5 s and `killed-assert` would become
  `killed-crash`, so a hang in one binary is not allowed to shorten the others.
