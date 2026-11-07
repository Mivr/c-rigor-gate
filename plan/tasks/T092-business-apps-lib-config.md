# T092: `products/business-apps` config for the lockers library modules (policy, expected ids, architecture)

Repo: `Mivr/c-rigor-gate`. Branch `task/T092`. Read `AGENTS.md`, `docs/products.md`, `docs/grade.md` (whole-repo
grade), `docs/product-checks.md`, `docs/layering.md` (T087) and `products/business-apps/` (T088: `lib/base/core` only)
plus `products/annas-c/policy.toml` (the model for module entries). The product is `Mivr/business-apps`, local clone
`/var/tmp/src/business-apps` (**read-only for you**: clone it into `/var/tmp/cache/T092/biz-clone` and grade the clone).

## Why
business-apps `main` now has these modules besides `lib/base/core`: `lib/base/bits`, `lib/ds/sidx`, `lib/ds/fmap`,
`lib/ds/ring`, `lib/ds/pool`, `lib/fmt/lines`, `lib/rt/dtab` (and possibly more by the time you start: take every module
on `main` when you clone, and list them). The product config grades only `core`. A whole-repo grade of `main` must pass.

## Build
1. **policy.toml:** one module entry per module, like annas-c grades `//core:*`: level L3, `impl = "<dir>/src/**"`,
   the exports exactly as each public header declares (from the facts), and minimal allow lists (only symbols the facts
   show used; for example `memset`/`memcpy`/`memmove` where used). The G25 allocation deny list stays in force: no
   module may allow an allocator. List every allow entry per module in your report.
2. **expected-tests.json:** every test id of those modules, added with `gate/tools/expected.py add` from a real build of
   the clone (release and san results), add-only.
3. **architecture.toml** (new, T087 format): layers bottom to top `lib-base` (`//lib/base/**`), `lib-ds`
   (`//lib/ds/**`), `lib-rt` (`//lib/rt/**`), `lib-fmt` (`//lib/fmt/**`), `lib-io`, `lib-ui`, `lib-sim`, then the app
   layers from `docs/design.md` of business-apps section 2 (read it from your clone; keep app layers with no modules yet
   only if the format allows empty layers, else omit them and say so). Library modules may depend only on lower or
   same-tier library modules; `lib` never depends on `apps`. Edge kinds as `docs/layering.md` defines; use the fewest
   `[[edge]]` declarations that make the current graph PASS, and name each.
4. **product.toml:** `[layout] include` covers exactly the module dirs on `main` (no `stale-include`, no `ungraded-path`).
5. Run the whole-repo grade on the clone until it is PASS, or until only findings remain that are real product defects
   (list them: gate, rule, module, excerpt; do not edit product code). Mutant survivors already approved by the
   orchestrator are in business-apps commit messages ("survivor approved"); if the grade needs an approvals file for
   them, list the exact mutant ids and I will sign them: do not sign anything.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary (gates, statuses, finding counts) in the report.

## Rules
Use `TMPDIR=/var/tmp/cache/T092/tmp`; never write to `/tmp` (the harness scratchpad under `/tmp` included). Build only
with `gate/tools/buck2`, never host compilers. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill
processes you did not start; never `buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and
8 GiB are shared.
