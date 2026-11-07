# T089: static data facts, `allow_mutable_data`, per-binary RAM budget ratchet (P002 G26)

Repo: `Mivr/c-rigor-gate`. Branch `task/T089`. Read `AGENTS.md`, `docs/product-checks.md`, `docs/grade.md`,
`rules/facts.bzl`, the facts extractor it runs, `gate/rigor_lib/facts_data.py` (`mutable`, T033), `facts_symbols.py`,
`facts_policy.py`, `ratchet.py` and `docs/ratchet*.md` if present.

## Why
The next product (`Mivr/business-apps`) is static memory only: every module takes caller storage and the only mutable
static data allowed is the one `static <app>_mem_t` in an app's composition root (`main` unit). Today the facts only
record **external** objects in writable sections (T033); a `static` buffer inside a library module is invisible.

## Build
1. **Facts:** for every unit, every defined data symbol, external **and local** (`static` at file or function scope),
   with its size and its section class: `ro` (`.rodata`, `.data.rel.ro`, `r`/`R`), `data` (`d`/`D`), `bss` (`b`/`B`),
   `tls` (`.tdata`/`.tbss`), from the pinned `llvm-nm -S` (and the sysv section listing the gate already uses, if you
   need it to tell `.data.rel.ro` from `.data`). Keep the existing `mutable` field's meaning; add a new field.
2. **Policy:** `allow_mutable_data = true` per module in `policy.toml` (default false). A module that is not allowed and
   defines any `data`/`bss`/`tls` symbol, local or external, gets `mutable-data` (error) naming unit, symbol, size and
   section. Compiler-generated symbols that are not program state (say exactly which, if any, and why) are excluded by
   a gate-owned list, not by a product setting. Test targets (`c_test`, `c_fuzz`) are exempt; a testkit library is not
   (it is linked into tests only, so say what you chose and why).
3. **RAM budget:** for every `c_binary` (and only binaries), the sum of `data + bss + tls` of every unit it links
   (product and trusted third-party, reported separately) as facts. A product may have a gate-owned
   `products/<p>/ram-budget.toml` (`[binary."//x:y"] max_bytes = N`); the gate fails `ram-over-budget` when a binary
   exceeds it, and the existing `rigor ratchet` machinery (direction `down`, `ratchet` approval to raise) governs edits to
   that file. A binary with no budget entry in a product that has the file: `ram-unbudgeted` (error). No file: no check.
4. Gate wiring: the findings belong to the `symbols` gate (same facts) unless you show a reason for a new gate; docs in
   `docs/product-checks.md`; canaries (new dirs only): `mutable-data-static-local` (a `static int counter;` inside a
   function of a library module: red), `mutable-data-allowed` is not needed if `control` covers it (say), and
   `ram-over-budget` (a binary one byte over: red).
5. **Measure** on annas-c `main` (clone into your cache dir): list every `mutable-data` it would report (do not edit
   annas-c's policy; report only) and every binary's RAM total. annas-c may have legitimate statics; the list is input
   for the orchestrator.

## Allowed paths
`rules/facts.bzl` and the facts extractor it runs, `gate/rigor_lib/facts_*.py`, `gate/rigor_lib/ram_budget*.py` (new, if
needed), `gate/tests/test_*facts*.py`, `gate/tests/test_*ram*.py`, `gate/tests/test_*mutable*.py`,
`gate/tests/fixtures/**` (new fixtures), `canaries/mutable-data-*/**`, `canaries/ram-over-budget/**`,
`docs/product-checks.md`. No product's `products/*` file.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/gate.sh
selftest/product_checks.sh
selftest/canaries.sh --only control --only mutable-data-static-local --only ram-over-budget
selftest/grade.sh
```
Report the change, the facts format, the findings, the annas-c list and RAM totals, and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T089/tmp`; never write to `/tmp`. Build only with `gate/tools/buck2`, never host compilers.
No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill processes you did not start; never
`buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
