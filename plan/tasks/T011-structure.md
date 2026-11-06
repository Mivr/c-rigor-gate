# T011: `rigor structure`: recursion and size/complexity limits from the clang AST (backlog B1, B2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T011`. Read `AGENTS.md`, `plan/phase1.md`, `plan/backlog.md` (B1, B2),
`docs/gate.md`, `docs/product-checks.md`, `docs/mutate.md` (how mutate already gets the clang JSON AST).
**T008 runs in parallel.** Don't touch `gate/rigor_lib/grade*.py`, `gate/rigor_lib/mutants_*.py`,
`gate/order.txt` or `products/**`. Wiring into `rigor grade` is a later task. In `gate/rigor_lib/cli.py` add one
entry to `COMMANDS` and nothing else (the orchestrator resolves that line at merge).

## Why
Today "no recursion, functions <= 50 lines, files <= 500 lines" are prompt-only rules (only the 512-byte frame
limit exists mechanically). An agent can break them and still pass. They must be gate findings.

## Allowed paths
`gate/rigor_lib/structure*.py`, `gate/rigor_lib/cli.py` (one `COMMANDS` entry), `rules/structure.bzl` (a rule
that produces the AST facts on RE with the hermetic toolchain, the same compiler and flags as the release build),
`gate/tests/test_structure*.py`, `selftest/structure.sh`, `selftest/structure_product/**`, `docs/structure.md`,
`plan/backlog.md` (mark B1 and B2 as landed-not-wired).

## Requirements
1. **Facts on RE**: for each product `c_library`/`c_binary` (not tests), a Buck2 action dumps the clang JSON AST
   (or a smaller `-ast-dump-filter`ed form) of every source, with the exact release flags, and reduces it to a
   compact `structure.json`: per function its file, the line extent of its body, the parameter count, the maximum
   nesting depth of compound statements and control flow, the cyclomatic count, and the direct calls (callee
   USR or name, including calls through macros, expanded). Per file: physical line count. Cached like every
   other action. No trust in `#line` markers: take extents from the source manager locations of the real file.
2. **Recursion (B1)**: build the call graph across all translation units of the product (callee names resolved
   to definitions in the product; calls into the dependency exports or libc are leaves). Any cycle, including
   self-recursion and mutual recursion across files, is a finding `recursion` naming the cycle. **Indirect
   calls** (through a function pointer) are leaves for the cycle check, but each indirect call site is listed in
   the facts, and an L3+ module that both takes the address of one of its own functions and makes an indirect
   call is a finding `indirect-cycle-possible` unless the address-taken function cannot reach that call site in
   the direct call graph.
3. **Limits (B2)**: one table per level in `gate/rigor_lib/structure_limits.py` (gate-owned, never product
   config):
   - L3: function body <= 50 lines, file <= 500 lines, params <= 6, nesting <= 4, cyclomatic <= 15.
   - L2: function body <= 80 lines, file <= 800 lines, params <= 8, nesting <= 5, cyclomatic <= 25.
   - L1: no limits, only recursion.
   Exceeding a limit is a finding naming the function, the measured value and the limit.
4. `rigor structure --facts <dir> --policy <products/p/policy.toml>` reads the facts plus the module levels (the
   `level` field from T008; if it is absent, treat the module as L3 and print a note) and exits 0, 1 or 2 like
   every other gate: fail closed, and a missing facts file is a finding, not a pass.

## Tests and self-test
Python unit tests for the graph and limits logic, with red and green for every rule. `selftest/structure.sh`
builds a throwaway product on RE with: self-recursion; a two-file mutual recursion; recursion hidden behind a
macro; a function of exactly 50 body lines (passes) and 51 (fails); a 501-line file; 7 params; nesting of 5;
a function-pointer callback cycle (`indirect-cycle-possible`); and a clean module that passes. Each red case is
tested alone (it is the only finding), and the warm re-run executes 0 actions.

## Acceptance
```sh
selftest/structure.sh
selftest/gate.sh            # all gate unit tests still pass
```
Report: the facts format, the rules, the self-test output, cold and warm action counts, and the measured
structure findings for annas-c `main` (run `rigor structure` on it as information only, without changing annas-c).
