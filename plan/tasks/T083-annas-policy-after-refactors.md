# T083: annas-c policy after the A048/A051/A054/A055 refactors (exports and allow lists)

Repo: `Mivr/c-rigor-gate`. Branch `task/T083`. Read `AGENTS.md`, `plan/tasks/T082-annas-ids-after-a058.md` (the same
procedure), `docs/product-checks.md` (symbols, `exports`, `allow`) and `docs/grade.md` "Audit grade of annas-c (T059)".

annas-c main `696252d` merged four "remove redundant code" refactors (A048 json, A051 annas, A054 posix_fs, A055 app).
A051 moved `ctx_key` into `annas/src/ctx.c`, so it is now an exported symbol of `//annas:annas`; the others may have
removed or added internal exports or stopped needing an allowed libc symbol.

## Allowed paths
`products/annas-c/policy.toml` only. Changes:
- add every symbol the `symbols` gate reports as `unexpected-export` for a module, **only** if it is an internal
  cross-file function of that module (declared in its `src/internal.h`), never a public-header name; report each;
- remove every `exports` entry the gate reports as `exports-missing` (the symbol no longer exists), and every `allow`
  entry no object references any more (tightening only); report each.
Anything else the symbols check reports (a new libc symbol, a public export): stop and report it, do not add it.

## Acceptance
Clone `/var/tmp/src/annas-c` at `696252d` into `/var/tmp/cache/T083/annas`, build its facts and release and san results,
and run the gates up to `symbols` as T082 did: `symbols` PASS with 0 findings after your change (and say what it
reported before). Do **not** run the full grade. Then `selftest/gate.sh`. Report the policy diff and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T083/tmp`; never write to `/tmp`. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill
processes you did not start. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
