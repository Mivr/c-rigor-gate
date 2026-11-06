# T029: `selftest/toolchain.sh` step 14 is state-dependent (flake); make every selftest re-runnable on a warm farm

Repo: `Mivr/c-rigor-gate`. Branch `task/T029`. Read `AGENTS.md`, `selftest/toolchain.sh`, `docs/toolchain.md`,
`docs/lanes.md`. **T013, T021, T023, T025 and T028 run in parallel**: touch only the paths below.

## Why
During T024's validation, step 14 ("compile, link and test all execute on RE (fresh, uncached sources)") failed once and
passed on an immediate re-run of the same tree. The failing log (copy at `/var/tmp/cache/T029/flaky-toolchain.log`) shows
every fresh-nonce action on `re(...)`, plus `cache` lines for the untouched deps (`fetched_tree llvm`, `sysroot`, ctest's
`c_compile ctest.c`/`sanlog.c`, `archive libctest.a`). The check `awk ... $3 !~ /^re\(/` treats any `cache` line as "not
on RE". Whether those deps appear in `what-ran` depends on daemon and farm state, not on the product. Earlier, T011's
`structure.sh` step 11 had the same class of bug (a fixed edit that later runs see as cached).

## Allowed paths
`selftest/toolchain.sh`, and any other `selftest/*.sh` where you find the same class of state-dependence (list each),
`docs/toolchain.md`.

## Requirements
1. Step 14 asserts what it means: every action of the **fresh-nonce** targets (`//selftest/scratch:l`, `:t`) executed on
   RE (never `local`), and nothing executed locally at all. Dependency actions may be `cache` or `re`. Reject `local`
   anywhere.
2. Audit every selftest for assertions that depend on farm or daemon history (fixed edits expected to miss the cache,
   exact cached/executed counts across runs, `what-ran` filters). Fix each with a per-run nonce or a precise filter;
   never by loosening what the step proves. List them in your report.
3. Prove it: run `selftest/toolchain.sh` three times in a row with no `buck2 kill` in between, then once after
   `tools/buck2 kill`. All four pass.

## Acceptance
```sh
selftest/toolchain.sh   # x3, then after a kill
selftest/gate.sh
```
