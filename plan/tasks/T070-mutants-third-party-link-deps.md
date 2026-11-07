# T070: mutant test links keep third-party libraries (annas-c: 9 modules `mutants-build-failed`)

Repo: `Mivr/c-rigor-gate`. Branch `task/T070`. Read `AGENTS.md` ("Working efficiently"), `docs/mutate.md`
(including T064's batching), `gate/rigor_lib/grade_mutants.py` (`_link_deps`, `plan`, `build_file_text`) and
whatever builds its `layout` (`layout.libs`, `layout.deps`).

## Problem (T064's annas-c grade, annas-c `02090de`)
The `mutants` step reports `mutants-build-failed` for 9 of the 13 annas-c modules: annas, app, core, ports, posix_clock,
posix_env, posix_fs, tls_stream and wire. Each of those modules' test sets contains a test binary that depends on
`//tls_stream:tls_stream`, and `tls_stream` depends on `gate//third_party/mbedtls:mbedtls`. `_link_deps` keeps only
labels in `layout.libs` (first-party libraries), so that cell-qualified third-party library is dropped from the
generated `c_mutants(deps = ...)`. The baseline link then fails with undefined `mbedtls_*` symbols, which fails
the whole module.

## Requirement
1. The generated mutant targets link every library the tests link in a normal build, including third-party ones
   (any cell, `gate//third_party/...` in particular), in a valid static link order, with the module itself still
   replaced by its mutant objects. Do not special-case mbedtls by name. Do not link anything the normal test build
   does not.
2. Fail closed as today: a dep that cannot be resolved is a finding (pick a clear rule name, document it), never a silent
   drop.
3. A regression test that fails on today's `main`: a unit test of the dep closure, plus a selftest or canary product
   whose mutated module's tests depend on a gate third-party library. Use the smallest one available under
   `third_party/`, so the step stays cheap. Its mutant verdicts must be real: killed and survived as expected, not
   build failures.
4. Prove it on annas-c. In a scratch clone of `/var/tmp/src/annas-c` (main) in your cache dir, run a grade with `--work` in
   your cache dir: 0 `mutants-build-failed`. Report the per-module survivor counts, the action count, the daemon
   VmHWM and the wall time. Run only one annas-c mutants build at a time, and only after the cheap tests pass. The
   orchestrator's validation may run alongside, and the container has 8 GiB, so keep the daemon under about 5 GiB with
   a guard scoped to your own work dir, as T064 did.

## Allowed paths
`gate/rigor_lib/grade_mutants.py`, the layout module it uses (only if needed), `rules/mutate.bzl` (only if needed),
`gate/tests/test_mutants*.py`, `gate/tests/test_grade*.py` (new cases only), `selftest/mutate.sh` or
`selftest/grade.sh` (a new step), `canaries/<new>/**`, `docs/mutate.md`, `docs/grade.md`.
**In flight in parallel:** T069 (`products/selftest/policy.toml`, `selftest/grade.sh`, `selftest/grade_product/**`,
`docs/grade.md`). If you add a step to `selftest/grade.sh`, append it at the end, and keep your docs edit in a
section of its own.
New canaries need both `exports` (T055) and `impl` (T040) keys in their policy.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutants*.py'
selftest/mutate.sh
selftest/gate.sh
TMPDIR=/var/tmp/cache/T070/tmp selftest/canaries.sh      # via tools/job, full pack, 0 misses
```
Then run the annas-c grade from requirement 4. Report the numbers and every deviation.
