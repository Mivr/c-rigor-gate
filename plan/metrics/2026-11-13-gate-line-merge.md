# Gate line merge: main (5723f85) + business-apps pin a5b91f4 (W33)

`git merge --no-ff a5b91f4` on lane/W33. Both lines now share one graph. Five files conflicted; every other file merged
automatically (the decoupling rule code, tests, canaries and docs are additions on the a5b91f4 line only).

| file | main side (T125-T139) | a5b91f4 side | combination |
|---|---|---|---|
| `gate/rigor_lib/grade_pipeline.py` | imports `grade_fuzz`, `grade_sanmodes` (msan/tsan, fuzz gates) | imports `grade_decoupling` | union of imports. `GATES` merged cleanly: `decoupling` after `layering`, `tests-msan/tsan` and `fuzz` kept in place; no gate dropped. |
| `gate/rigor_lib/grade_mutants.py` | imports `grade_tier`, `perf_package`, `perf_policy` | imports `grade_decoupling`; moved perf imports to their own line (already present once merged) | one import line with `grade_decoupling` and `grade_tier`; perf imports stay on their own line. |
| `gate/rigor_lib/grade_witness.py` | imports `grade_tier` | imports `globs`, `witness_bundle` | union of both import lists. |
| `gate/rigor_lib/verdict_inputs.py` | `PRODUCT_FILES` gains `fuzz-regressions.json` | `PRODUCT_FILES` gains `decoupling.toml`, `decoupling-baseline.toml` | tuple has all of both, so both file sets are snapshotted and hashed into the verdict. |
| `docs/canaries.md` | sections for T129/T133/T135/T137 (fuzz, vendor-path, tier, merge pass) | section "Canaries of gate `decoupling`" | both sections kept, main's first. |

## Comparison with PR #1 (origin/lessons/decoupling)
All 11 `decoupling_*.py`, `grade_decoupling.py`, `gate/tools/decoupling.py`, `docs/decoupling.md`, `docs/lessons-decoupling.md`,
the 3 decoupling test files and all `canaries/decoupling-*` files are byte-identical to PR #1's. Differences that remain are
only files where PR #1 is based on the older main (docs/perf.md, docs/toolchain.md, grade_sanmodes.py, grade_structure.py,
test_grade_structure.py, rules/c.bzl, selftest/perf.sh, selftest/toolchain.sh, the msan-bump note): the merge result has
main's newer version of each. `grade_mutants.py` differs from PR #1 by main's tier/perf wiring. PR #1 would therefore merge
into this result without conflicts in the decoupling files.

## Tests
See the lane report: `run_parallel.py` 2301 tests OK (no test needed changing), `selftest/grade.sh` all 20 steps passed,
`selftest/canaries.sh --jobs 4 --tier merge`: 127 canaries, 127 live, 0 misses (1637 s).
