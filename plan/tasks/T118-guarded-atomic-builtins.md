# T118: guarded atomic builtins (`__atomic_load_n`, `__atomic_store_n`) per module via `allow_builtins`

Repo: `Mivr/c-rigor-gate`. Branch `task/T118` from main. Read `AGENTS.md`, `docs/product-checks.md` (the
`forbidden-builtin` row, `allow_builtins`, the builtin survey near line 261), `gate/rigor_lib/semantic_table.py`
(`GUARDED_BUILTINS`, `BUILTIN_PREFIXES`), `gate/rigor_lib/facts_policy.py`, `gate/rigor_lib/facts_semantic.py`,
`gate/rigor_lib/cscan.py`, and `selftest/`.

## Why
The T116 whole-repo grade of business-apps fails `semantic-suppressions` `forbidden-builtin`: the lockers composition
root (`apps/lockers/lkapp/wire`, L2) shares two flags between its threads with `__atomic_load_n(&x, __ATOMIC_ACQUIRE)`
and `__atomic_store_n(&x, v, __ATOMIC_RELEASE)`. `<stdatomic.h>` would not help (it expands to `__c11_atomic_*`, also
forbidden), and a mutex is heavier than the need. Orchestrator ruling: a lock-free flag is a legitimate primitive for a
module that owns threads, so the gate allows exactly these two builtins as **guarded** builtins, opt-in per module, the
same way it already allows `__builtin_trap`.

## Do
1. Add `__atomic_load_n` and `__atomic_store_n` to `GUARDED_BUILTINS` (only these two; every other `__atomic_*`,
   `__sync_*`, `__c11_atomic_*` stays forbidden). A module may use them only when its policy entry lists them in
   `allow_builtins`; everywhere else they stay `forbidden-builtin`.
2. Memory-order argument: only `__ATOMIC_ACQUIRE`, `__ATOMIC_RELEASE` and `__ATOMIC_SEQ_CST` are accepted as the order
   argument, and only as those literal macro names (not a variable, not `__ATOMIC_RELAXED`/`CONSUME`/`ACQ_REL`). If the
   facts pipeline cannot see the argument tokens reliably, say so and implement only step 1, documenting the limit.
3. Docs: update the `forbidden-builtin` row, the `allow_builtins` comment in the policy example, and the survey text in
   `docs/product-checks.md`; mention why `<stdatomic.h>` stays out.
4. Selftests and canaries: a fixture module that uses both builtins with `allow_builtins` listing them passes; the same
   code without the listing fails `forbidden-builtin`; a module listing them but using `__atomic_fetch_add` fails; (if
   step 2 is implemented) `__ATOMIC_RELAXED` fails. `gate/tests` unit tests for the table and the policy parse.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
all green. Report the diff summary, the new fixtures/canaries, and the outputs.

## Allowed paths
`gate/rigor_lib/**`, `gate/tests/**`, `selftest/**` (add fixtures; do not weaken existing ones), `docs/**`,
`tools/affected.toml`. NOT `products/**` (the business-apps config refresh sets wire's `allow_builtins` later).

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T118`. Use `TMPDIR=/var/tmp/cache/T118/tmp`; never write `/tmp`. Build only with
`tools/buck2` / `gate/tools/buck2` as the docs say. Redirect every output to a file and read it; never pipe into
`tail`/`head`. Long runs via `tools/job`. Never `rm` (`cp -f`, or `mv` into your cache dir). No stash, merge or push.
**Never use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or
other cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid
(`pgrep -f '^buck2d\['` plus `readlink /proc/<pid>/cwd`); never `pgrep -f buck2d`, `buck2 kill` or `pkill`. One buck2
build at a time (16 GiB shared by three lanes). No network except Buck2's pinned downloads. Commit on `task/T118` when
done; your last message is the report.
