# Recursion and size limits from the clang AST (T011, backlog B1 and B2)

"No recursion, functions <= 50 lines, files <= 500 lines" used to be prompt-only rules. They are findings now.
`c_structure` (rules/structure.bzl) makes the facts on RE; `rigor structure` decides. Self-test:
`selftest/structure.sh`. **Landed, not wired**: `rigor grade` does not run it yet, and `rules/c.bzl` does not define
the `c_structure` targets (the grading driver writes them in a gate-owned package, as it does for `c_mutants`).

## 1. `c_structure` (rules/structure.bzl, gate/rigor_lib/structure_scan.py)
```
c_structure(name = "core_structure", module = ":core", srcs = ["a.c", ...], headers = ["a.h", ...],
            deps = [...], kind = "c_library")          # c_library, c_binary, c_test or c_fuzz
```
`srcs` must be the module's own list: it is compared with the objects the module compiles, and a difference fails
the build. A header-only module (no sources) has nothing to compile and gets no target. Release platform only.

* **Per source, one action** (`c_structure_unit`): the pinned clang runs with the module's *exact compile command*
  (the argsfile Buck2 itself uses, same flags, same toolchain, as `c_mutants` does) plus
  `-Xclang -ast-dump=json -fsyntax-only -H`. Only that source and the module's headers are inputs, as in the real
  compile. The scanner (stdlib Python) reduces the JSON AST to a unit file.
* **One join action** (`c_structure`): the unit files and the declared sources, checked against each other, in
  `structure.json`. A source without a unit, or the reverse, fails the build.
* Both are plain cacheable actions: an unchanged tree executes **0** actions; an edit to one source re-runs that
  source's unit and the join only.
* **Wrapper units (T048).** A source the dump never names is normally a blind scan and fails. The one exception: its
  text, with comments and whitespace removed, is only `#include "..."` lines (annas-c `tests/kit.c`), and the dump
  has a location in each included non-system file. The included functions are reported under their own paths and the
  main file is listed in `files`. Any other token (a `#define`, a `#pragma`, a declaration alone, an `#include <...>`
  of a system header, an include that produced no location, an empty file) stays a `ScanError`.
* Not product code, so not reported: files under the toolchain's `--system-root`s, and the gate's own third-party
  libraries (path contains `/art/<gate cell>/third_party/`; a directory of that name in a product is not exempt).

### Facts format (`structure.json`, schema 1; `rigor structure` accepts exactly this and nothing else, else exit 2)
```
{"schema":1,"label":"//pkg:name","kind":"c_library","deps":["//pkg:dep",...],"srcs":["pkg/a.c",...],
 "units":[{"src":"pkg/a.c",
   "files":[{"path","lines","bytes","longest_line"}],          // every file the compiler read, src included
   "functions":[{"name","key","static","file","line","end_line","body_lines","split","macro",
                 "params","nesting","cyclomatic","statements",
                 "calls":[{"to","fp_args","line"}],             // direct calls, macros expanded
                 "indirect":[{"file","line"}],                  // calls through a value
                 "refs":[{"to","file","line"}]}],               // the function's address is taken here
   "refs":[{"to","file","line"}]}]}                             // the same, outside every function (tables)
```
* `key` names a function: the link name for external linkage (`mangledName`: an `__asm__("x")` label is honoured,
  an `alias` attribute resolves to its aliasee); `static:FILE:NAME` for a static function.
* `body_lines` runs from the line of `{` to the line of `}`, both included; `null` with `split: true` when the
  body is not within one file. `macro: true` when the body is written in a macro (the larger of the macro's text and
  the expansion site is measured).
* `nesting`: depth of control statements (`if for while do switch`; `else if` is flat) and of bare blocks and
  statement expressions; the body is depth 0. `cyclomatic`: 1 + `if for while do case ?: && || goto`.
  `statements`: statements in the body, nested ones included (an unbraced `if (x) f();` counts both).
* `calls[].fp_args`: the call passes a function, or a value of function-pointer type, along.
* Every line number is computed from the byte `offset` of the dump and the bytes of the real file, and checked
  against the dump's own `line`; a disagreement, an offset outside the file, a dump that never names the source
  (blind) or a function definition the walk did not account for fails the build.

## 2. `rigor structure --facts DIR --policy products/<p>/policy.toml [--out F]`
`DIR` holds one `*.json` per module (a stray file, a symlink, an empty directory, two files for one label or a
malformed file is exit 2). The policy names the modules and their level (`[module."//core:core"] level = "L3"`).
Other keys (`allow`, ...) are not ours and are ignored. A module without `level` is **L3**, and a note is printed
(and kept in the metadata). Tests and fuzz targets (kind `c_test`, `c_fuzz`) must be present but are not graded.
Exit 0 / 1 / 2 like every other gate; the result file is replaced by a FAIL on an internal error.

### Rules (`rigor_lib/structure.py`; limits `rigor_lib/structure_limits.py`, gate-owned)
| Level | function body | file | params | nesting | cyclomatic | statements\* | longest line\* |
|---|---|---|---|---|---|---|---|
| L3 | 50 | 500 | 6 | 4 | 15 | 50 | 160 |
| L2 | 80 | 800 | 8 | 5 | 25 | 80 | 240 |
| L1 | none | none | none | none | none | none | none |

\* Not in the task's table. They close two ways round the line limits: a body or a file packed into few long lines.
`statements` equals the line limit, so formatted code meets the line limit first. A function over a limit is judged
once, at the strictest level of the modules whose units contain it (a function in a shared header).

| Rule | When |
|---|---|
| `recursion` | a cycle in the direct call graph of the whole product (all modules, all translation units): self-recursion, mutual recursion across files and across modules. Names the cycle. **Every level**, L1 included. A callee the product does not define (libc, a dependency's export) is a leaf. Two programs (`c_binary`) may define the same names; each program has its own nodes, a library function is shared. |
| `indirect-cycle-possible` | L3 (info at L2): module M takes the address of one of its own functions F, some function G of the product makes a call through a value *or passes a function pointer to code the product does not define* (`qsort(.., cmp)`: that code may call back), and F reaches G by direct calls (F = G included). Stricter than the minimum reading: G may be in any module. |
| `function-length`, `parameter-count`, `nesting-depth`, `cyclomatic-complexity`, `statement-count` | over the limit of the level; the finding names the function, `value` and `limit` |
| `file-length`, `line-length` | every file the compiler read (headers too) over the limit |
| `split-function-body` | L2/L3: the body is not within one file (an `#include` inside the body) |
| `macro-defined-function` | L3 error (L2 info): the body is written in a macro. Same as `unmutated-function` in `rigor mutants` |
| `included-non-header` | L2/L3: a unit read a file that is not a `.h` |
| `duplicate-definition` | one external function defined twice in one program or in the libraries |
| `module-not-in-policy`, `policy-module-without-facts`, `missing-dep-facts` | facts and policy disagree, or a dependency has no facts. A missing file is a finding, never a pass. (Dependencies under `gate//`, `//third_party/` and `//ctest:` are gate-owned and exempt.) |

Metadata: modules with level and function count, the number of call edges, **every indirect call site** per
function (`file:line pointer` or `file:line callback:<callee>`), and the address-taken functions.

## 3. Hiding recursion or size: every case is red or impossible
| Trick | Why it does not work | Where tested |
|---|---|---|
| **Macro** around the call (`#define STEP(n) f((n)-1)`) | the AST is after expansion; the call is in it | red `macrorec`; scanner test `macro` |
| **Macro that defines the function** | the body is measured by the macro's text and by the expansion site (the larger), flagged `macro`, and L3 refuses it | red `macrofn`; scanner test `macro` |
| **`#line`** to reset line numbers or rename the file | the dump has the actual buffer name and byte offset next to the presumed ones; only those are used, and lines are recomputed from the file's bytes | red `linehide` (51 lines after `#line 1 "tiny.c"`); scanner test `line` |
| **`#include "x.c"`** | impossible: the real build gives a compile only its own source and the declared headers (`headers` must end `.h`), so it fails with `file not found`; the structure action has the same inputs. `included-non-header` is the second wall | `selftest` step "IMPOSSIBLE" (module `included`); gate test |
| **`#include` inside a function body** (a `.h` full of statements) | the body is `split`; and its statements are counted anyway | red `splitbody` |
| **`__attribute__((cleanup(f)))`** (a call with no call expression) | the dump has the `CleanupAttr`; the cleanup function is an edge from the enclosing function | red `cleanuprec`; scanner test `hidden` |
| **`__asm__("name")` label** or **`alias`** attribute renaming a function | the link name is used as the key, so the renamed call lands on the definition. (Both are also refused by `rigor facts`: `inline-asm`, `forbidden-attribute`) | red `asmrec`, `aliasrec` |
| **`constructor`/`destructor`, `weak`, `ifunc`** | no recursion in themselves; refused by `rigor facts` (`forbidden-attribute`) | docs/product-checks.md |
| **Statement expressions** `({ ... })` for calls or nesting | refused by the sealed flags: `-Wpedantic -Werror` makes `-Wgnu-statement-expression` an error, and `#pragma` is refused by `rigor facts`. The scanner counts them anyway (a statement expression is a nested block; its calls are edges) | selftest "IMPOSSIBLE" (`stmtexprrec`, `stmtnest`); scanner test `metrics` |
| **`goto`** to flatten nesting or loop | a `goto` is a decision (cyclomatic +1), so a chain of them cannot hide complexity; it cannot create recursion (no call) or lengthen the body | red `gotos` (17 > 15) |
| **Computed goto** `goto *p` | refused by `-Wpedantic` (GNU extension); counted as a decision anyway | scanner `DECISIONS` |
| **Function pointers** | every call through a value is an `indirect` site; every non-callee mention of a function is an address-taken ref; the cycle rule above | red `fpcycle`; gate tests |
| **Callback through libc** (`qsort`, `bsearch`, ...) | a direct call whose arguments include a function or function-pointer value, to code the product does not define, is a call site (`callback:<callee>`) | red `callbackcycle` |
| **Recursion split across files/modules** | one graph for the whole product | red `mutual`, `xa`+`xb` |
| **Same name, different `static`** to confuse the graph | static functions are keyed by their file | gate test |
| **Pack a body or file into few long lines** | `statement-count` and `line-length` | red `packed`, `longline` |
| **Delete the facts** | a module or dependency without facts is a finding; a partial file is exit 2 | selftest "fail closed" |

## 4. Known limits (honest list)
* A function pointer kept in a struct and passed to code outside the product is not seen as a callback (only values
  whose own type is a function pointer, and function names, are). The product's own indirect calls are all listed.
* `indirect-cycle-possible` is conservative: it cannot tell which functions a pointer may hold. It has no sanction;
  a module that needs a dispatch table must keep the table's functions from reaching their dispatcher.
* `sizeof(f(x))` and the unselected branches of `_Generic` contribute edges although they are never run: a
  false positive, never a miss.
* Recursion through `setjmp`/`longjmp`, signals or threads is not a call-graph cycle; those symbols are on the
  `rigor facts` deny list.
* A function defined in a vendored library under `third_party/` is trusted, so a call from it back into the
  product (a registered callback) is covered only through the `callback:` site on the registering call.
* Facts are release-mode only (like `rigor facts`); code under `#ifdef __SANITIZE_ADDRESS__` is not seen.
* The scanner trusts clang's JSON dump. A forged `structure.json` is as trustworthy as the build that made it (the
  driver builds it freshly on RE, as for every other fact).
