# T131: guards, static part: cell-bound trap allowance, reserved name, guard facts, `rigor guards` (P003 W4 part 2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T131` from main (T128 merged: `gate//rt:require`, `CHECK_TRAPS`). Read P003 §6,
`docs/require.md`, `gate/rigor_lib/facts_rt.py`, `cscan.py`, `facts_semantic.py`, `semantic_table.py`, `facts_data.py`,
`rules/facts.bzl`, `docs/product-checks.md` ("Builtins", "Line markers", "Known limits"), and how `mutate/gen.py` tells a
product header from a header of another cell (T081, `docs/mutate.md` "unmutated-function").

## Why
T128 landed the guard primitive with two limits it reported itself: the `__builtin_trap` allowance is tied to the path
`rt/require.h` plus the dependency, not to the gate cell, so a product header at that path is allowed to trap; and
`rigor_require` is not a reserved name, so a product can redefine it to nothing. P003 §6 also needs the gate to know
where the guards are. This task closes the two limits and lands the facts and a judge. It does not change how mutants
of a guard are treated and it wires nothing into `rigor grade`.

## Do
1. **Bind the allowance to the gate cell.** The scanner must report, for every identifier fact, whether its file is
   the gate's own (the same notion the mutation generator uses for "a header of another cell"), from the path the
   compiler really read, not from the include spelling. `facts_rt.is_gate_trap` then requires the gate's file. Red
   case: a product that carries its own `rt/require.h` containing `__builtin_trap`, with the dependency on
   `gate//rt:require`: `forbidden-builtin` as for any other product trap.
2. **`rigor_require` is reserved.** In product code (any file that is not the gate's): a `#define` or `#undef` of
   `rigor_require`, a declaration or definition of a function or object with that name, and taking its address are the
   error finding `reserved-identifier` (name, file, line) of the semantic gate. Calling it is the only use.
3. **Guard facts.** Per unit, every call site of `rigor_require` in product code: file, line, enclosing function. Keep
   older facts readable (an optional key, as T063 did for function types).
4. **`rigor guards --facts DIR --structure DIR --policy P.toml [--out F]`** in `gate/rigor_lib/guards_gate.py`, fail
   closed like the other judges. Policy: `[module."//pkg:name"] guards = N` declares how many of the module's guards
   no public call can make false (P003 §6); absent means 0. Findings:
   - `guard-budget-over-sites` (error): `N` is larger than the number of guard call sites of the module;
   - `guard-budget-over-cap` (error): `N` is larger than the density cap, one declared guard per 40 lines of the
     module's own source files (lines from the structure facts; the constant in one place, named);
   - info `guards` per module: sites, declared, cap.
   Every policy reader must accept the key `guards`.
5. **Selftest and tests.** Extend `selftest/require.sh` and `selftest/require_product/` with the red cases of items 1
   and 2 and a module for item 4 (within cap passes; over sites and over cap fail), each twice with identical
   results. Unit tests for the scanner changes, the reserved-name rule and the judge.
6. **Docs.** `docs/require.md` (remove the two limits, add the facts and the judge, state what is still missing: the
   mutation gate does not yet treat declared guards specially, and nothing yet checks that a guard was executed),
   `docs/product-checks.md`.

## Not in this task
`mutate/**`, `gate/rigor_lib/mutants*.py`, `gate/rigor_lib/grade*.py`, `gate/order.txt`, `products/**`, the "every guard
was executed" check (it needs the coverage build; a later task).

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/product_checks.sh`; `selftest/require.sh` twice in a row;
`selftest/canaries.sh --jobs 8`; `selftest/mutate.sh`; `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/cscan.py`, `gate/rigor_lib/facts_*.py`, `gate/rigor_lib/semantic_table.py`,
`gate/rigor_lib/guards_gate.py`, `gate/rigor_lib/cli.py` (registering the subcommand only), the policy readers (key
acceptance only), `rules/facts.bzl` (only if the scanner needs one more input), `gate/tests/**`, `selftest/require.sh`,
`selftest/require_product/**`, `docs/require.md`, `docs/product-checks.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T131`. `TMPDIR=/var/tmp/cache/T131/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. If you need a throwaway script, write it with the Write tool or a heredoc so its text is in your transcript;
do not generate it with `sed` from another file. Commit on `task/T131`; your last message is the report (what works,
what does not, every deviation).
