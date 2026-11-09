# T121: make the whole-repo mutants gate fast: reuse unchanged modules, overlap the chunks

Repo: `Mivr/c-rigor-gate`. Branch `task/T121` from main. Read `AGENTS.md`, `docs/mutate.md`, `docs/grade.md`,
`gate/rigor_lib/grade_mutants.py` (`MUTANTS_CHUNK`, `build_reports`, the chunk ranges, the per-chunk timeout and retry
from T115), the `c_mutants` / `mutant_run` rules in `rules/`, and `plan/tasks/T115-mutants-build-chunks.md`.

## Why (measured on business-apps, 116 modules)
- A whole-repo grade builds the `gate-mutants` package in 10 SEQUENTIAL chunks of 12 modules; each chunk waits for its
  slowest module, so the farm is mostly idle (T119: chunk 0 took about 30 min, the projection was about 8 h).
- Every grade re-runs every mutant, although `mutant_run` is a Buck2 action: for a module whose sources, tests,
  toolchain and gate rules are unchanged, the action key should be identical and the RE action cache should answer.
  It evidently does not (each grade generates the tree under a fresh `--work` dir, `gate-mutants/BUCK` is generated
  per grade, ...). Find out exactly what makes the action keys differ between two grades of the same product commit.

## Do
1. **Measure first.** Grade a small fixture product (or business-apps' smallest few modules via a narrowed task) twice
   in a row with different `--work` dirs; record the action digests of `mutant_run` actions both times and show what
   differs (paths, generated files, env, nonce). Report it.
2. **Make unchanged modules cache hits**: make the mutant action inputs hermetic (no work-dir path, timestamp, nonce
   or per-grade generated content in the key) so a second grade of the same commit re-executes ZERO `mutant_run`
   actions, and a grade after a one-module change re-executes only that module's. Correctness must not weaken: the key
   must still cover the module sources, its tests and their deps, the mutation operator set, toolchain and gate
   version. Never add a cache the gate itself trusts outside Buck2/RE (no verdict files reused across grades).
3. **Overlap the chunks**: replace the sequential chunk loop with bounded concurrency (for example all modules in one
   `buck2 build --keep-going` with the per-chunk failure isolation and retry of T115 preserved by another mechanism, or N
   chunk builds in flight); keep the memory safety T115 wanted (say how). Keep the deadline semantics.
4. Tests in `gate/tests` and a selftest proving (a) a repeat grade re-executes zero mutant actions, (b) a one-module
   change re-executes only that module, (c) a mutant that survives is still reported as surviving on a cache hit (the
   verdict comes from the cached action OUTPUT, not from skipping it).

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`, `selftest/product_checks.sh`, `selftest/canaries.sh`, plus the timing
table before/after (wall time of the mutants gate on the same input, cold and warm).

## Allowed paths
`gate/**`, `rules/**`, `selftest/**`, `docs/**`, `tools/**`. NOT `products/**` (T120 owns it).

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T121`. `TMPDIR=/var/tmp/cache/T121/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm` (`cp -f`, or `mv` into your cache
dir). No stash, merge or push. **Never use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src`, other worktrees or other cache dirs; never search from `/` or `/var/tmp`. Do not print the
environment. Kill only your own buck2d by pid (`pgrep -f '^buck2d\['` plus `readlink /proc/<pid>/cwd`). One buck2
build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is running.
Commit on `task/T121`; your last message is the report (findings of step 1, the design, the timings).
