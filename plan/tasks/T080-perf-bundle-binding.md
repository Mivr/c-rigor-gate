# T080: perf bundle format, `--perf DIR` and its verdict binding (R011 task 2, B13)

Repo: `Mivr/c-rigor-gate`. Branch `task/T080`. Read `AGENTS.md`, the R011 summary `/var/tmp/cache/T080/R011-report.md`,
`docs/perf.md` (T076: `c_perf`, `ctest/perf.h`, the `perf.jsonl` record), and `docs/witness.md` plus
`gate/rigor_lib/witness_bundle.py` (load, validate, digest) and `verdict_inputs.py` (snapshot, `core.inputs`, `rigor verify` and its `--expect-*` options). The perf bundle is bound
**the same way** as the witness bundle: snapshot, digest, `core.inputs` key, and a `rigor verify` expectation.

## Goal
The perf gate (a later task) judges an implementation against **hidden** performance tests. This task defines the hidden
bundle, loads and validates it, snapshots it into `<work>/inputs/perf`, binds its digest into the verdict, and lets
`rigor verify` check it. **No gate and no judgement yet**: with `--perf`, the grade still runs exactly the gates it runs
today. The bundle is only loaded, checked and bound.

## Bundle format (`docs/perf.md`, new section)
`<dir>/perf.toml`, schema version 1, one table per target:
```toml
version = 1
product = "annas-c"
[[target]]
id = "json-many-keys"            # unique, [a-z0-9-]
module = "//json:json"           # must be in the product policy, level L3 or above
srcs = ["gen/json_keys.c"]       # generator + driver (ctest/perf.h API), paths inside the bundle
sizes = [1000, 4000]             # exactly two, second = k * first, k >= 2
seed = 1
class = "linear"                 # linear | nlogn
```
Plus the source files it names. Reject anything else: unknown keys, missing files, files the bundle does not name,
symlinks, absolute or `..` paths, duplicate ids, a module not in the policy or below L3, or a bad `sizes` or `class`.
Each rejection is exit 2 with a clear message, as for a bad witness bundle.

## Requirements
1. `gate/rigor_lib/perf_bundle.py`: load, validate and snapshot. The canonical digest uses the same scheme as
   the witness bundle's digest in `witness_bundle.py`, over `perf.toml` plus the named sources.
2. `rigor grade --perf DIR`: the snapshot goes to `<work>/inputs/perf` before any gate runs, and readers use only the
   snapshot (T071's rule). `core.inputs.perf_sha256` is the digest, or `null` without `--perf`. A bundle for another
   product is exit 2.
3. `rigor verify --expect-perf-sha SHA`, next to `--expect-witness-sha`. Without `--perf` on the grade, the expected value
   must be `none` or absent.
4. `gate/tools/perf.py check DIR --product products/<p>/product.toml`: validates a bundle offline and prints its digest,
   as `witness.py check` does.
5. Tests: unit tests for every rejection above, the digest's stability (byte-identical across two loads, and changed by any
   byte of any file), snapshot-only reads (the live dir changed mid-grade does not change the verdict), and the verify
   expectations. A tiny valid bundle for the selftest product in `gate/tests/fixtures/perf/`.

## Allowed paths
`gate/rigor_lib/perf_bundle.py` (new), `gate/tools/perf.py` (new), `gate/rigor_lib/grade_pipeline.py` and
`gate/rigor_lib/grade.py` (the flag and snapshot only), `gate/rigor_lib/verdict_inputs.py`, `gate/rigor_lib/witness_bundle.py` (only to share the digest helper, no behaviour change),
`gate/rigor_lib/grade_context.py` (if the args object needs the field), `gate/tests/test_perf*.py`,
`gate/tests/test_verify*.py`, `gate/tests/test_verdict*.py`, `gate/tests/fixtures/perf/**`, `docs/perf.md`, `docs/grade.md`
(one paragraph).
**In flight in parallel:** T079 (`expected-tests.json`, `docs/canaries.md`, `mutants_*`). Do not touch them.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_perf*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_verify*.py'
selftest/gate.sh
TMPDIR=/var/tmp/cache/T080/tmp selftest/grade.sh     # via tools/job; unchanged
```
Plus one grade of the selftest product with `--perf gate/tests/fixtures/perf/selftest` in your cache dir: the verdict carries
`perf_sha256`, `rigor verify --expect-perf-sha` accepts it, and a wrong sha is rejected. Report the format, the digest
scheme, the tests and every deviation.
