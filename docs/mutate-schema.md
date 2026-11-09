# Schema mutation engine, prototype (T124, P003 W1)

Step 4 of `docs/mutate.md` relinks every test with every mutated object and runs it in a fresh process. This prototype
builds the run stage P003 section 5 proposes **beside** the v1 engine and measures both
(`plan/metrics/schema-engine-proto-2026-11.md`). It is not wired into `rigor grade` or `rigor mutants`, changes no
verdict, and decides only whether P003 W2 is built.

```
load("@gate//rules:mutate_schema.bzl", "c_mutants_schema")
c_mutants_schema(name = "core_mutants_schema", module = ":core", tests = [":core_test"], deps = [])
```
`buck2 build //pkg:core_mutants_schema` yields `report.json` (`"engine": "schema"`). `kill_chunk = N` splits a test's kill
action into actions of at most N mutants (default 0: one action per test, as in the design).
`python3 -I -B mutate/schema/schema_compare.py compare --v1 V1_REPORT --schema SCHEMA_REPORT [--strict]` compares the two.
Self-test: `selftest/mutate_schema.sh`. Files are in `mutate/schema/` (a package of its own, because `mutate/BUCK` is not
part of the contract): `schema.py`, `schema_rt.c`/`.h`, `schema_run.py`, `schema_compare.py`.

## Pipeline

| Step | What |
|---|---|
| 1 to 3b | **Shared with v1** (the same helpers of `rules/mutate.bzl`, exported by appending `mutate_helpers`): `mutant_list` (`gen.py`), the baseline compile, the standalone `-O2` compile of every mutant, the `-O0` compile of the candidates for equivalent/duplicate. They decide which mutants v1 would run (viable, not `equivalent`, not `duplicate`; `_live` repeats `_stage3`'s decision). |
| 4a `schema_gen` | Per source with such mutants, one action (`schema.py generate`): the AST of the module's exact command, the plan, **one** compile of the schema source with the module's exact compile command, bisection if it does not compile. Output: schema object, schema source (for inspection), table. |
| 4b `schema_link` | Per test, one link: the test's objects, the schema objects (the baseline object for a source without live mutants), `-Wl,--wrap=main`, the libraries, `schema_rt`. |
| 4c `schema_reach` | Per test, one run with no mutant active. It writes the results (normalised exactly like a v1 `linkrun` record) and the reach set. The report checks the record against v1's baseline run (`baseline_reproduced`). |
| 4d `schema_kill` | Per test, one action over the mutants **that test reached**: fork, activate, run the real `main`, wait. A mutant no test reaches is `unreached` and is not run. |
| 5 `schema_report` | `schema_compare.py collect`: one report. |

No cross-test "stop at the first kill" in this prototype: every reached (mutant, test) pair runs. The report counts what
v1's rule would have saved (`kill_runs_after_first_kill`).

## The schema source

For each mutant that is **schema-eligible** the generator writes a switch into the source, keeping every line number
(`#include "schema_rt.h"` and `#line 1` come first). `rigor_hit(N)` (`schema_rt.h`, inline) sets byte N of the reach bitmap
and returns whether mutant N is the active one.

| Mutant | Written as |
|---|---|
| relational, arithmetic, logical, compound assignment, `++`/`--`, literals, enumerator, `return` value | `(rigor_hit(N) ? (mutated) : (original))` over the whole AST expression the operator belongs to |
| `condition` | `((cond) ? !rigor_hit(N) : rigor_hit(N))`: the pointer or integer type of `cond` cannot make the conditional ill-typed, and the condition is evaluated either way |
| `statement-deletion` | `if (!rigor_hit(N)) { call(); }` |
| `function-body` | `if (rigor_hit(N)) { <v1's replacement body> }` as the first statement of the body (a void body gets its `return;`: v1 replaces the whole body, here it must stop the original) |
| `not-removal` | `!x` -> `x` when the value stays an `int` (the operand promotes to `int`); in a context that only tests for zero (`if`, `while`, `&&`, `||`, `!`, `?:`) `!!(x)`; otherwise not eligible (`type-change`) |

Nested ranges: the inner wrapper goes inside the outer one's `original` arm (so an inner site is reached only when the
outer one is inactive, which is exactly when it runs in v1). Equal ranges chain (`hit1 ? m1 : (hit2 ? m2 : orig)`).
The mutated arm is the original text with v1's replacement applied, so it contains no wrappers.

### Eligibility (from the AST parent, never from text)

Not eligible, one reason code each (counted in the report; in a full engine these go through the v1 path):

| Reason | When |
|---|---|
| `constant-context` | an ancestor up to the function is a `ConstantExpr` (case label), `StaticAssertDecl`, enumerator, bit-field, designator, `sizeof`/`alignof`, or a `static`/`extern`/thread-local `VarDecl` (a static local's initialiser) |
| `array-string-init` | a string literal that is a direct child of a `VarDecl` or `InitListExpr` (an array initialiser; a pointer's literal sits below an array-to-pointer conversion) |
| `type-change` | the replacement would give the conditional another type: an integer literal whose successor has another C17 type (`2147483647` -> `2147483648`), a `u`/`U`/`u8` character literal, a `!x` whose operand is not `int`-promoted outside a zero test |
| `partial-overlap` | the wrapped ranges of two mutants overlap without nesting |
| `directive-in-range` | the wrapped text contains a preprocessor line (it would be written twice) |
| `no-anchor` | no AST node matches the mutant: fail closed, never silently dropped (zero in every module measured) |
| `schema-unviable` | the schema did not compile; found by bisection (below) |

File-scope initialisers are never mutants (`gen.py` mutates function bodies only).

### Bisection

If the schema of a source does not compile, `bisect_unviable` finds the offenders: with the mutants known to compile
(`base`), the shortest prefix of the rest that fails ends at an offender (binary search); that mutant is left out, the
search continues. k offenders cost about k log2 n compiles. The result is verified by compiling the final set. Indices
are assigned before the compile, so a left-out mutant leaves a gap in the numbering. Typical offenders: text that
cannot be written twice (a `struct` defined inside the expression), and warnings the sealed flags turn into errors.

## The runtime (`schema_rt.c`)

Linked with `-Wl,--wrap=main`, `__wrap_main` strips its own options (`--rigor-mode`, `--rigor-reach`, `--rigor-list`,
`--rigor-dir`) and calls the test's own `main` (`ctest/` is not touched):

* no option: the real `main`, nothing active;
* `reach`: the real `main` once with no mutant active; the reach bitmap is an anonymous **shared** mapping (ctest runs
  every test in a forked child), written to a file, one index per line;
* `kill`: a list file of `INDEX NAME` lines. A baseline run first fixes the limit `clamp(20 x wall, 5 s, 180 s)` (T122; a
  baseline that timed out: 180 s). Then, per line, `fork()`, activate the index in the child, `exit(real main)` with
  `--out DIR/NAME.res`; the parent waits (polling with a growing nap, no signals) and kills the child's process group
  at the limit, then writes `DIR/NAME.st` (`rc`, `timed_out`). The ctest resource limits (`RLIMIT_FSIZE`, `RLIMIT_CPU`,
  descriptors, scratch quota) are set by the real `main` in each child, as in v1.

No allocation: static buffers (the list is read into a 4 MiB static buffer **before** the first `fork`, because a child
that exits closes its copy of an input stream and moves the shared file offset) and one `mmap` in reach mode. At most
131071 mutants per module (`RIGOR_SCHEMA_MAX`); a module with more fails its schema action loudly.

`schema_run.py` turns each result into the record `tool.py linkrun` stores (`tool.normalise_rc`, `normalise_results`
are used from `tool.py` itself): `{"rc", "timed_out", "results"}`, so a kill is classified by one definition on both
sides (`schema_compare.classify`, the rule of `mutants_verdict.outcome_of_run` without the baseline-id cross-check).

## What the report says, and the comparison

Per mutant: `status` (`eligible`, `ineligible` + reason, `schema-unviable`, `v1-not-run`), its runs per test
(`{"unreached": true}` where the test does not reach it) and a `class`: `killed-assert`, `killed-crash`, `survived`,
`unreached` (no test executes the site), `bad-results`. `unreached` compares equal to v1's `survived`: with no
execution of the site every test passes. A *kill* by v1 of a mutant the schema calls unreached is a disagreement (the
reach set would be an under-approximation).

`schema_compare.py compare` lists every disagreement with file, line, operator and both records. A disagreement is
**explained** only when it follows from the construction: v1 ran the `-O0` object of a mutant the optimiser had folded at
`-O2` (docs/mutate.md "Equivalence is checked at -O0 too"), which the schema, compiled at `-O2` with the sites switchable,
cannot reproduce. Everything else is unexplained and fails `--strict`.

## Limits of the prototype

* **Undefined behaviour.** The two engines have the same semantics for defined behaviour only. A mutant that makes the
  program read an uninitialised variable can be killed in one build and survive in the other (the stack holds something
  else). The selftest fixture `multi_a.c` is initialised for that reason; the v1 fixture's `int log;` gives such a
  disagreement. This is the divergence P003 section 5.3 audits with a sample re-run through the v1 path.
* **Speed of the switch.** Every site is an inline load, store and compare; the optimiser can no longer fold a site. Tests
  that spend their time in the mutated module run slower than in v1 (the factor is in the metrics file).
* **One kill action per test** serialises the mutants of a test; with `kill_chunk` the actions can be split.
* **Not the verdict.** No `survived` is declared here: a survivor would be re-run through v1 (P003 4e), which this prototype
  does not do. Mutants that are not schema-eligible are only counted.
* **Reach is dynamic.** A site reached only under a condition the tests do not provide is `unreached`; v1 says `survived`.
  The comparison treats them as equal; a v1 kill of such a mutant is reported.
* `-Wl,--wrap=main` assumes the test's `main` is a plain definition in a linked object (ctest's `CTEST_SUITE`).
