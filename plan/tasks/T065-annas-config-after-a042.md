# T065: annas-c product config after A042 (new posix_fs exports, fs_direct_test)

Repo: `Mivr/c-rigor-gate`. Branch `task/T065`. Read `AGENTS.md`, plus `docs/grade.md` "Audit grade of annas-c (T059)".
annas-c main `ec9d3ca` (A042) adds four exported functions to `//posix_fs:posix_fs` (`posix_fs_create_temp`,
`posix_fs_write`, `posix_fs_commit`, `posix_fs_discard`) and a new test target `//posix_fs:fs_direct_test` with 5
ids (`posix_fs_direct/...`). Without config changes, the next annas-c grade fails `symbols` (`unexpected-export`,
`module-not-in-policy`) and reports the 5 ids as `unexpected-test`.

## Allowed paths
`products/annas-c/policy.toml` (the `//posix_fs:posix_fs` `exports` list, and a new `//posix_fs:fs_direct_test`
table modelled on the other posix_fs test tables: same allow and deny_exempt lists as `fs_commit_test`, but only
the symbols the facts show it needs, and no level), and `products/annas-c/expected-tests.json` (add-only, through
`gate/tools/expected.py add`).
**In flight in parallel:** T039 adds `impl` keys to the same `policy.toml`; keep your edit to the keys named here.

## Acceptance
Clone `/var/tmp/src/annas-c` at `ec9d3ca` into `/var/tmp/cache/T065/annas`, then:
- build the facts and the release and san results of that clone;
- run the symbols check over them as T059 did (in-process `facts_symbols.run` with the new policy, or a grade
  stopped after `symbols`): `symbols` PASS, 0 findings;
- run `expected.py add` from those results: exactly 5 ids added.

Do **not** run the full grade (mutants takes over an hour here). Then run `selftest/gate.sh`. Report the policy
diff, the symbols result and the expected-tests diff count.
