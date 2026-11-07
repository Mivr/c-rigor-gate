# T081: `unmutated-function` ignores headers outside the product; annas-c ids for A057

Repo: `Mivr/c-rigor-gate`. Branch `task/T081`. Read `AGENTS.md`, `docs/mutate.md` (`unmutated-function`, reason `header`),
`gate/rigor_lib/mutants_gate.py` (`skipped_findings`, `product_path` from T079) and `plan/tasks/T079-annas-ids-canary-docs-header-path.md`.

## Parts
1. **Third-party header noise.** In the annas-c audit grade, `//tls_stream:tls_stream` reports 251 `unmutated-function` (reason
   `header`, info) for inline functions in mbedtls/psa headers (`psa/crypto_struct.h`, `mbedtls/ssl.h`, ...). They are not
   product code, so the gate must not report them. Report `unmutated-function` only for headers **inside the product's
   layout** (a product-relative path after `product_path`, under a package of the product). Third-party (`gate//third_party/**`
   or any other cell), toolchain and system headers are skipped silently. Product headers keep today's severity rules.
   Fail closed: a header path the gate cannot classify is still reported. Add unit tests for each class.
2. **Expected ids.** annas-c main `daed4a2` adds 8 cases to existing targets (A057): `survivor/fs_reinit_of_a_used_fs_starts_afresh`,
   `survivor/fs_reinit_restarts_the_call_count`, `survivor/fs_preload_content_pointer_and_length`,
   `survivor/fs_find_and_temp_content_of_null_fs`, `survivor/stream_mismatch_without_an_out_pointer`,
   `stream_init/invalid_script_leaves_a_failed_unusable_stream`, `posix_env/single_entry_one_byte_name_is_found`,
   `posix_env/name_with_an_embedded_nul_never_matches_an_entry_with_one`. Add them with `gate/tools/expected.py add` from release
   and san results of a clone at `daed4a2` (gate submodule from the local gate clone). It must be add-only, exactly 8.

## Allowed paths
`gate/rigor_lib/mutants_gate.py`, `gate/rigor_lib/mutants_report.py` (only if the header class is decided there),
`gate/tests/test_mutants*.py`, `docs/mutate.md`, `products/annas-c/expected-tests.json`.
**In flight in parallel:** T080 in validation (`verdict_inputs.py`, `grade.py`). Do not touch them.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutants*.py'
selftest/gate.sh
TMPDIR=/var/tmp/cache/T081/tmp selftest/canaries.sh      # via tools/job, full pack, 0 misses
```
Report the header classification rule, the tests, the id diff and every deviation.
