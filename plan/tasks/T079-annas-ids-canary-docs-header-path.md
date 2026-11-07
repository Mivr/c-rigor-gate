# T079: catch-up: annas-c expected ids (A050, A052), docs/canaries.md, source paths in `unmutated-function`

Repo: `Mivr/c-rigor-gate`. Branch `task/T079`. Read `AGENTS.md`, `plan/tasks/T075-annas-config-new-tests.md` (same
procedure for ids), `docs/canaries.md`, and `docs/mutate.md` (`unmutated-function`).

## Parts
1. **Expected ids.** annas-c main `f729d69` adds cases to existing test targets: A050 adds 6 to `//http:request_test`
   (suite `http_request`, `arg_*` and `empty_null_slices_invalid`), and A052 adds 5 to core (`arena/exact_fit_*`,
   `str/trim_*`). Clone annas-c at `f729d69` into your cache dir (gate submodule from the local gate clone), build
   release and san results, and run `gate/tools/expected.py add`. It must be add-only, exactly 11 ids. If no new symbols
   are needed, nothing changes in `policy.toml`; check that with the symbols check as T075 did.
2. **docs/canaries.md.** Add the canaries that are missing from its tables, `third-party-link` (T070), `crash-oracle` and
   `crash-oracle-green` (T078), plus any other canary under `canaries/` that the tables lack. Match the existing table format.
   A unit test that fails when a canary directory is missing from `docs/canaries.md` is welcome, if a docs-consistency
   test already exists to extend; do not add a new framework.
3. **Source paths.** The mutants gate reports `unmutated-function` for a function defined in a private header with `file`
   set to a `buck-out/.../buck-headers/<pkg>/src/internal.h` path (annas-c `ctx_key`). Report the product-relative
   source path instead (`annas/src/internal.h`), wherever the record is built. Add a unit test with a buck-out header path.

## Allowed paths
`products/annas-c/expected-tests.json`, `products/annas-c/policy.toml` (only if part 1 needs it, which it should not),
`docs/canaries.md`, `docs/mutate.md`, `gate/rigor_lib/mutants_*.py`, `gate/rigor_lib/grade_mutants.py` (part 3 only, minimal),
`mutate/gen.py` (only if the path comes from there), `gate/tests/test_mutants*.py`, `gate/tests/test_mutate*.py`,
`gate/tests/test_docs*.py` (if it exists).
**In flight in parallel:** T073 in validation (grade pipeline, `canaries/runner.py`). Do not touch its files.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutants*.py'
selftest/gate.sh
```
Plus the symbols check from part 1. Report the id diff count per target, the docs rows added, the path fix with its
test, and every deviation.
