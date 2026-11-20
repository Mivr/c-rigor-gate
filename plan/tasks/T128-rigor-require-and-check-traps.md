# T128: `rigor_require` and `CHECK_TRAPS` (P003 W4 part 1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T128` from main. Read P003 §6 in full, then `ctest/ctest.h`, `ctest/ctest.c`,
`docs/ctest.md`, `docs/product-checks.md` ("Builtins", "Gate `symbols`", "System libraries"), `rules/c.bzl`,
`gate/rigor_lib/semantic_table.py`, `buckfiles.py`, and the canary `cross-cell-dep`.

## Why
In C a defensive check is often the only thing between an invariant broken elsewhere and memory corruption. When the
invariant holds, no test can kill a mutant of the check, and the zero-survivors rule then says "delete it": business-apps
commit `2975620` removed the range check in `durable()` for exactly that reason. P003 §6 gives such checks a
gate-owned form that can do nothing but stop the process, and gives tests a way to assert that a guard fires. This
task lands the two primitives. Counting guards, the guard budget and the mutation engine's treatment of guards come
later; do not start them.

## Do
1. **`gate//rt:require`**: a header-only gate library in a new directory `rt/` (`rt/require.h`, `rt/BUCK`).
   `rigor_require(cond)` evaluates `cond` exactly once; when it is false the process stops with `__builtin_trap()`, in
   every build mode. It has no other effect and no other entry point: no message, no handler, no way to disable it,
   no variant that returns. Keep the expansion minimal so the cost is one compare and one never-taken branch.
2. **Products may use it.** A product `c_library`, `c_binary` or `c_test` may list `gate//rt:require` in `deps` and
   include `rt/require.h`. Make every gate that looks at dependencies, cells, headers, builtins and symbols accept
   exactly that and nothing wider: `buckfiles` (the cross-cell rule), `layering`, `symbols` (the trusted list), and
   the semantic scan (the `__builtin_trap` inside the gate's header is the gate's, not the product's: a product that
   has no `allow_builtins` entry for trap must still pass, and a product that calls `__builtin_trap` itself is judged
   as before). Structure and mutation: the header belongs to another cell, so its code is not product code
   (`unmutated-function`, `macro-hidden-code` and the size rules must not fire for it); the **condition** the product
   wrote stays product code and is still mutated.
3. **`CHECK_TRAPS(t, expression)`** in `ctest`: runs `expression` in a child process and passes only if the child died
   by the trap of `rigor_require` (SIGILL from `__builtin_trap`). It fails, with a reason that names what happened
   instead, when the expression returns, when the child exits by itself, or when it dies any other way (another
   signal, a sanitizer report, a timeout). It counts as one check. It must work in `release` and `san` and under the
   existing per-test limits, and it must not leave a core file. A trap **outside** `CHECK_TRAPS` stays what it is
   today: the test died by a signal and fails.
4. **Selftest** `selftest/require.sh` with a small product under `selftest/require_product/`:
   - a module with `rigor_require(index < CAP)` before an array read, and tests: in range passes; out of range inside
     `CHECK_TRAPS` passes; out of range outside `CHECK_TRAPS` fails as a signal death; `CHECK_TRAPS` on a call that
     returns fails; `CHECK_TRAPS` on a call that dies by SIGSEGV or by an ASan report fails;
   - `rigor buckfiles`, `rigor facts` (semantic and symbols) and `rigor structure` on that product: PASS with the
     dependency and without any `allow_builtins`; a product depending on another `gate//` target the same way: FAIL as
     today;
   - the mutants of the module (`selftest/mutate.sh` shows how to build them): the condition's mutants exist and the
     `CHECK_TRAPS` test kills the boundary one;
   - `release` and `san`, every case twice with identical results; `elapsed <S>s` and `ALL CHECKS PASSED (n)` last.
5. Give the selftest a name: `require` in `tools/affected.py`, `tools/validate.sh`, `docs/validation.md` and the
   affected-map unit test (it builds in the project root: shared Buck2 lane), and map the new paths to it.
6. `docs/require.md` (the rule, what a guard is and is not, the limits: a trap is fail-stop, so a product must be safe
   to restart), `docs/ctest.md` (`CHECK_TRAPS`).

## Not in this task
`mutate/gen.py` and `mutate/tool.py`, guard counting or a guard budget, `gate/rigor_lib/grade*.py`, `gate/order.txt`,
`products/**`, any change to how an existing canary or selftest behaves.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/ctest.sh`; `selftest/product_checks.sh`; `selftest/require.sh`
twice in a row; `python3 -I tools/affected.py --check`; `tools/validate.sh --dry-run task/T128` lists `require`. The
orchestrator runs the full `tools/validate.sh`, canaries included, so existing behaviour must stay byte-identical.

## Allowed paths
`rt/**`, `ctest/**`, `gate/rigor_lib/buckfiles.py`, `gate/rigor_lib/layering*.py`, `gate/rigor_lib/facts_*.py`,
`gate/rigor_lib/semantic_table.py`, `gate/rigor_lib/structure*.py`, `rules/c.bzl` (only if a macro must learn about the
new library), `gate/tests/test_require*.py` and the existing tests of the files you change, `selftest/require.sh`,
`selftest/require_product/**`, `docs/require.md`, `docs/ctest.md`, `docs/product-checks.md`, `docs/validation.md`,
`tools/affected.toml`, `tools/affected.py`, `tools/validate.sh`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T128`. `TMPDIR=/var/tmp/cache/T128/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Commit on `task/T128`; your last message is the report (what works, what does not, every deviation).
