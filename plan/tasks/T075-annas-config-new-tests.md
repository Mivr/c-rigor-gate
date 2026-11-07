# T075: annas-c product config for the A044/A045/A046 test targets

Repo: `Mivr/c-rigor-gate`. Branch `task/T075`. Read `AGENTS.md`, `plan/tasks/T065-annas-config-after-a042.md` (the same
job for A042) and `docs/grade.md` "Audit grade of annas-c (T059)".
annas-c main `0e5d9a5` adds six test targets:
- `//fsname:fsname_edge_test`
- `//url:url_edge_test`
- `//http:survivor_chars_test`
- `//json:survivor_input_test`
- `//json:survivor_keys_test`
- `//json:survivor_text_test`

Without config changes, the next grade fails `symbols` (`module-not-in-policy`) and reports their ids as
`unexpected-test`.

## Allowed paths
`products/annas-c/policy.toml` (six new test tables, modelled on the neighbouring tables of the same package; `allow` lists
only the symbols the facts show each target needs; `exports = ["main"]` and no level), and
`products/annas-c/expected-tests.json` (add-only, through `gate/tools/expected.py add`).
**Ruling (orchestrator):** `//url:url_edge_test` uses `mmap`/`mprotect` (plus whatever page-size call it makes) for a guard page
that catches one-byte over-reads. Allow exactly those calls in that one table. If any other new table needs a symbol
outside its package's existing test allow lists, stop and report it rather than adding it.
**In flight in parallel:** T070 (grade_mutants), T073 (grade pipeline), T074 (trajectory). Do not touch their files.

## Acceptance
Clone `/var/tmp/src/annas-c` at `0e5d9a5` into `/var/tmp/cache/T075/annas` (submodule from the local gate clone), then:
- build the facts and the release and san results of that clone;
- run the symbols check over them as T065 did: `symbols` PASS, 0 findings;
- `expected.py add` from those results: report exactly how many ids were added, per target.

Do **not** run the full grade. Then run `selftest/gate.sh`. Report the policy diff, the symbols result, the added ids per
target and every deviation.
