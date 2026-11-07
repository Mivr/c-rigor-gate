# T091: refresh `products/annas-c` to annas-c `main` (test ids, exports, allow lists)

Repo: `Mivr/c-rigor-gate`. Branch `task/T091`. Read `AGENTS.md`, `docs/grade.md` (whole-repo grading, line 360 on;
`tools/expected.py`), `docs/product-checks.md` and `products/annas-c/`. The product is `Mivr/annas-c`, local clone
`/var/tmp/src/annas-c` (**read-only for you**: clone it into `/var/tmp/cache/T091/annas-c-clone` and grade the clone;
never edit, commit or push in `/var/tmp/src/annas-c`). Its `main` is at `6e31d86` or later.

## Why
Since `products/annas-c` was last refreshed, annas-c merged: A061 (new key contract, 16..256 bytes, new tests), A062
(export changes), A064 (json tests), A066, A068 (app/posix_fs tests; test `one_byte_key` deleted), A056 + A069
(tls_stream implementation, new `tls_stream/tests/wall_bound_test.c`, 18 ids). A whole-repo grade of `main` must be
clean apart from findings that are real product defects.

## Build
1. Run a whole-repo grade of the clone at `main` (`docs/grade.md`, "Whole-repo grade"), and keep the verdict.
2. For every finding, classify it as (a) **stale config** (a new test id not in `expected-tests.json`; a new public symbol
   not in a module's `exports`; an allow list naming a symbol no longer used: `unused-allow`) or (b) **product defect**.
   Fix (a) only:
   - new ids with `gate/tools/expected.py add` (add-only). A removed id (for example `one_byte_key`) is a
     `test-removed` finding: do **not** edit it out; list it in your report with the commit that removed it and I sign
     the `test-removal` approval.
   - exports and allow lists in `products/annas-c/policy.toml`: add new exports the header declares; drop allow entries
     the facts show unused. Never widen a deny list exception or add a module-level allow without listing it in the
     report with the reason.
3. Re-grade until only (b) findings and the `test-removed` items remain. List every (b) finding (gate, rule, module,
   excerpt); do not fix product code.

## Allowed paths
`products/annas-c/policy.toml`, `products/annas-c/expected-tests.json`, `products/annas-c/expected-tests.previous.json`
(only if `docs/grade.md` says the refresh needs it), `products/annas-c/product.toml` (layout only, if a module dir changed).

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary (gates, statuses, finding counts) in your report.

## Rules
Use `TMPDIR=/var/tmp/cache/T091/tmp`; never write to `/tmp` (the harness scratchpad under `/tmp` included). Build only
with `gate/tools/buck2`, never host compilers. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Do not run
anything that needs a real Anna's Archive key; fake keys only. Never kill processes you did not start; never
`buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
