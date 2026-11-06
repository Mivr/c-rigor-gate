# T059: refresh the gate-owned annas-c product config (layout, policy, expected tests)

Repo: `Mivr/c-rigor-gate`. Branch `task/T059`. Read `AGENTS.md` ("Working efficiently"), `docs/grade.md`,
`docs/product-checks.md`, and `products/annas-c/*`.
Source: the orchestrator's audit grade of annas-c main `81012ea` with gate `02050f8` (2026-11-06). Its per-gate
results are in `/var/tmp/cache/grade-annas-02050f8/work/results/*.json`, which you may **read** (read-only; do not
read anything else in that directory). Findings:
- `buckfiles`: 28 `ungraded-path`, because `wire/**` and `bin/**` are not in `products/annas-c/product.toml`
  `layout.include`.
- `symbols`: 302 `undeclared-symbol`, 48 `unexpected-export`, 14 `denied-symbol` (`fopen` in posix_fs test kits),
  and 10 `module-not-in-policy`. The new test targets from A036-A039, and module changes since T033 generated the
  lists, are not in `products/annas-c/policy.toml`.
- `tests-*`: 149 `unexpected-test` (info). `products/annas-c/expected-tests.json` lacks the new test ids.
- `contract`: `submodule` (`gate`). This is only because the audit grade used the root commit as base; see 4.

**In flight in parallel:** the T055 fix-up (`products/selftest/**`, `canaries/**`), T057 (`trajectory*`). T039
starts later and will add `impl` keys to the same `policy.toml`, so keep your changes to the keys named here.
Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`products/annas-c/product.toml`, `products/annas-c/policy.toml`, `products/annas-c/expected-tests.json`,
`products/annas-c/tasks/**`, `docs/grade.md` (the annas-c audit-grade recipe only).

## Requirements
1. Layout: add `wire/**` and `bin/**`. If `bin/` holds only thin mains, they are still graded code.
2. Policy:
   - Add a table for every built module and test target. Its `exports` list is what it really exports
     (generated from the facts, as T033 did).
   - Add each `allow` list a module needs. **Product modules (non-test): do not widen any allow list or
     deny exemption on your own.** List every product-module symbol you would need to add, with the
     calling function, in the report, and leave those findings failing. The orchestrator rules on them.
   - Test targets may get the libc symbols their kits use (for example `fopen` in posix_fs test kits). List each
     one in the report.
   - Keep every existing `level` unchanged. New test targets get no level.
3. Expected tests: add the 149 ids with `gate/tools/expected.py add` (add-only), from results of your own grade
   run. Remove nothing.
4. The whole-repo audit recipe: document in `docs/grade.md` which base an audit grade of annas-c must use, so the
   gate submodule's addition is not in the diff. Use the commit that added `gate`, or explain an alternative.
   Do not change `contract.py`.
5. Prove it: run your own audit grade of annas-c `81012ea`. Clone `/var/tmp/src/annas-c` into
   `/var/tmp/cache/T059/annas` and grade with `--work /var/tmp/cache/T059/work`, via `tools/job`. Report the
   per-gate status and the findings that remain, by rule. Expected: `buckfiles`, `contract` and `tests-release`
   PASS. `symbols` either PASS or fails only on the product-module symbols you listed. Product-side
   failures (`structure` line-length in `annas.h`, san timeouts in `tls_stream`) remain; they belong to another
   task. Note whether `mutants` ran.

## Acceptance
```sh
selftest/gate.sh
TMPDIR=/var/tmp/cache/T059/tmp tools/job run grade -- gate/rigor grade ...   # as in requirement 5
```
Report the diff stats per file, the symbol lists from requirement 2, the grade summary, and every deviation.
