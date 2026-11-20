# `rigor_require`: guards (T128, T131, P003 §6, parts 1 and 2)

In C a defensive check is often the only thing between an invariant broken elsewhere and memory corruption. When the
invariant holds, no test can kill a mutant of the check, and the zero-survivors rule then says "delete it". A **guard**
is the gate-owned form of such a check: it can do nothing but stop the process, so it cannot hide logic, and a test can
assert that it fires.

T128 landed the two primitives, `rigor_require` and `CHECK_TRAPS` (docs/ctest.md). T131 (the static part) binds the trap
allowance to the gate's own file, reserves the name, records where the guards are and judges the declared budget (below).
`dead-guard`, the mutation engine's special treatment of declared guards and the check that a guard was executed come
later (P003 §6).

## The rule

```c
#include "rt/require.h"            /* BUCK: deps = ["gate//rt:require"] */

int table_get(unsigned index) {
    rigor_require(index < TABLE_CAP);
    return g_values[index];
}
```

`rigor_require(cond)` evaluates `cond` exactly once. When it is false the process stops with `__builtin_trap()` (SIGILL
on x86-64), **in every build mode**. It has no message, no handler, no way to disable it and no variant that returns.
It is a `static inline` function (`always_inline`) in a header-only gate library, so the cost is one compare and one
never-taken branch, and the condition is ordinary product code.

A product `c_library`, `c_binary` or `c_test` may list `gate//rt:require` in `deps` (a `c_library` also in
`exported_deps`, when a public header includes `rt/require.h`). Nothing else of the gate cell besides `ctest` (added by
the `c_test` macro) and the allowlisted third-party libraries may be named; `c_fuzz`, `c_catalog` and the other macros may
not name it yet.

## What each gate does with it

| Gate | Effect |
|---|---|
| `buckfiles` | accepts exactly the label `gate//rt:require`, for `c_library`, `c_binary` and `c_test`; every other `gate//` label is `bad-argument` as before |
| `layering`, `symbols`, `semantic-suppressions` | its facts (if the grading driver builds them) are not a module and need no policy entry; a dependency on it needs no facts (`missing-dep-facts` does not fire for it) |
| `semantic-suppressions` | the `__builtin_trap` the scanner finds in `rt/require.h`, in a unit of a target that depends on the library, **and whose file the compiler read from the gate's own tree** (the identifier fact's `gate` flag), is the gate's, not the product's: no `allow_builtins` entry is needed. A `__builtin_trap` in any other file (a product's own `rt/require.h` included), or in a target without the dependency, is judged as before (`forbidden-builtin` unless `allow_builtins` lists it). The name `rigor_require` is **reserved** in product code: a `#define` or `#undef` of it, a function or object of that name (declared or defined) and its address are `reserved-identifier` (error; name, file, line); calling it is the only use |
| `structure` | `//rt:require` / `gate//rt:require` need no structure facts. The function in the header belongs to another cell (rt/require.h is under no package of the product) |
| `mutants` | the call is a plain function call with the condition as its argument: the condition is mutated like any code (`index < CAP` gives `<=` and `>=`), and the call itself can be deleted (`statement-deletion`). The header's function is not product code (`unmutated-function` skips headers outside the product) and there is no macro, so `macro-hidden-code` cannot fire |

Code: `gate/rigor_lib/facts_rt.py` (the label, the header path, the predicates), used by `buckfiles.py`,
`facts_third_party.split`, `facts_symbols.py`, `facts_semantic.py` and `structure.py`; the scanner (`cscan.py`) reports
the `gate` flag, the reserved-name uses and the guard sites; `guards_gate.py` is `rigor guards`. Selftest:
`selftest/require.sh` (release and san, everything twice); unit tests: `gate/tests/test_require.py`,
`gate/tests/test_guards.py`.

## Where the guards are: facts and `rigor guards` (T131)

**Facts.** Per unit, `guards`: every call of `rigor_require` in product text, as `{file, line, function}` (the function whose
body is open at the call; `<file scope>` / `<unknown>` for a call outside a body or in a shape the scanner cannot read).
A call is the name followed by `(` after the end of a statement, a block, a condition or a label (or `else`/`do`);
every other occurrence of the name in product text is the reserved-name finding above. The gate's own header is not
scanned for either. Every identifier fact also says whether its file is the gate's (`gate`, a boolean): the compiler
read it from the output tree of a cell other than the product's, or from the gate's `rt:require` header tree (so the
gate's own selftests, where the gate is the root cell, work too). Both keys are optional for the reader; facts made before
T131 are still read, and a `__builtin_trap` in them is judged as a product's (no flag, no allowance).

**`rigor guards --facts DIR --structure DIR --policy P.toml [--out F]`** (`gate/rigor_lib/guards_gate.py`, exit 0 / 1 / 2 like
the other judges). The policy key `[module."//pkg:name"] guards = N` declares how many of the module's guards no
public call can make false (P003 §6); absent means 0 (a non-negative integer, else exit 2; every policy reader accepts it).
A module's guards are the distinct call sites in its own source files (the `srcs` of its structure facts; a guard in a
header does not count, as code in a header is not mutated, `unmutated-function`). Findings:

| Rule | Meaning |
|---|---|
| `guard-budget-over-sites` (error) | `N` is larger than the number of guard call sites of the module (also for a policy module with no facts: 0 sites) |
| `guard-budget-over-cap` (error) | `N` is larger than the density cap: `lines // DENSITY_LINES` (`guards_gate.DENSITY_LINES = 40`), one declared guard per 40 lines of the module's own source files (line counts from the structure facts) |
| `structure-missing` (error) | the module has guard sites or a declaration and no structure facts: the cap cannot be decided |
| `guards` (info) | per module: `sites`, `declared`, `cap` |

Judged modules: every module of the policy, and every `c_library` / `c_binary` that has structure facts or guard sites.
Tests are not modules. Nothing is wired into `rigor grade` yet.

**Still missing.** The mutation gate does not yet treat declared guards specially (a mutant of a declared guard is
judged like any other: it survives unless a test reaches the guard with the bad value). Nothing yet checks that a guard
was executed (that needs the coverage build): a declared guard that no test reaches is not found, and `dead-guard` does
not exist. The budget is a declaration the gate bounds (by sites and by density), not one it proves.

## What a guard is, and what it is not

- A guard is **reached** by a test that calls the public API with the bad value: that test is a `CHECK_TRAPS` at the
  boundary, and it kills the mutants of the condition (`selftest/require.sh` shows `<` -> `<=` killed by it, and the same
  module tested without `CHECK_TRAPS` leaving the boundary and the deleted guard as survivors).
- A guard is **not** error handling. A caller that can pass a bad value in normal operation needs a returned error that
  the tests cover; a guard is for an invariant that the caller's own code is supposed to uphold.
- A guard is not logging, not recovery, not a place for a side effect. `cond` must have none that matters: a guard
  that is compiled out would change the program, and none can be (there is no switch), but a reader must still be able to
  delete the line mentally and see the same program on every good input.
- A trap **outside** `CHECK_TRAPS` is a failure of the test, fuzz run or simulation that hit it (the test died by a
  signal). Guards therefore turn every other technique into an oracle.

## Limits

- **A trap is fail-stop.** The process dies at once, without unwinding, flushing, closing or releasing anything. A product
  that uses guards must be safe to restart: durable state is written so that a death between any two instructions leaves
  it consistent, and a supervisor restarts the process. A guard in a path that holds an external resource (a relay, a
  lock file, a device) must leave that resource in a state the next start can recover from.
- The gate cannot see that `cond` is *meant* as a guard condition; it is judged like any code. Only the trap is exempt.
- The exemption of the trap is by header path (`rt/require.h` as the scanner reports it), by the dependency **and** by
  the file being the gate's (T131): a product's own header of that name gets no allowance, whatever the unit depends on.
  The name `rigor_require` is reserved, so a product cannot redefine it to nothing; a macro under any other name that
  wraps a guard (`#define CHECK(c) rigor_require(c)`) is still ordinary product code, and the call inside it is a guard
  call site at the line of the expansion.
- Sanitizers: in `san` the runtime handles SIGILL (`handle_sigill=1`), so a trap outside `CHECK_TRAPS` shows as an exit
  with the sanitizer's `ILL` report; inside `CHECK_TRAPS` the child gets the default SIGILL action back and dies by the
  signal in both modes.
