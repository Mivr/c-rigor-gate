# T097: resource limits on every test and mutant run (RE disk safety)

Repo: `Mivr/c-rigor-gate`. Branch `task/T097`. **Urgent: protects the shared RE farm.** Read `AGENTS.md`, `rules/c.bzl`,
`rules/mutate.bzl` (the `mutant_run` and `mutant_compile*` actions), `ctest/ctest.c` (the test harness `main`),
`ctest/perf.c` (it already uses `alarm`), `docs/mutate.md`, `docs/grade.md`, `docs/canaries.md`.

## Why
A business-apps `posix_fs` mutant (a write retry whose condition was mutated) made a real-directory test write the
same bytes forever. On RE that filled the worker CAS temp disk (`No space left on device ... /data/cas/tmp`) and broke
every lane's builds for hours. Tests may legitimately write small real files under `$TMPDIR` (posix_fs, posix_lock),
so the gate must bound what any single test or mutant run can consume, and a mutant that hits a bound must count as
**killed** (its test failed), never as an infrastructure error.

## Build
In the harness that every `c_test` and `mutant_run` executes under (`ctest.c`'s `main`, before any test runs; and the
perf harness), set hard limits with `setrlimit`, the same values in every mode:
- `RLIMIT_FSIZE`: 64 MiB per file (a write past it gets `EFBIG`/`SIGXFSZ`: ignore `SIGXFSZ` so the write fails with
  `EFBIG` and the test's own check fails);
- `RLIMIT_CPU`: a CPU-time bound per test binary, comfortably above the slowest honest test today (measure it; for
  example 60 s), so an infinite loop dies by `SIGXCPU` instead of the action timeout;
- `RLIMIT_NOFILE`: 256 (a leaking loop of opens fails fast);
- `RLIMIT_CORE`: 0.
Also add a per-binary total-bytes-written guard for files under `$TMPDIR` if `RLIMIT_FSIZE` alone does not bound the
total (many files): for example remove the test's `$TMPDIR` scratch at exit and cap the number of files, or run each
test binary with a private `$TMPDIR` sized by a quota if the RE sandbox offers one. Choose the simplest robust option
and document it.
- Mutant verdicts: a mutant run that dies by `SIGXCPU`/`SIGXFSZ`/`EFBIG`-driven failure is `killed-crash` or
  `killed-assert` exactly as other crashes and failures are; it never becomes `unrun` or an action error.
- Docs: the limits, where they are set, why (this incident), in `docs/mutate.md` and the ctest docs.
- A canary/selftest fixture: a test that writes forever under `$TMPDIR` must fail fast (seconds) in release and san,
  and its mutant-run analogue must be judged killed.

## Allowed paths
`ctest/**`, `rules/**`, `gate/rigor_lib/**`, `gate/tests/**`, `docs/**`, `canaries/**`, `selftest/**`, fixture products
used by selftests. Not `products/business-apps/**` or `products/annas-c/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/toolchain.sh
```
plus the fixture: wall time and verdict of the write-forever test in release and san, and of its mutant run.

## Rules
Use `TMPDIR=/var/tmp/cache/T097/tmp`; never write to `/tmp`. Build only with `gate/tools/buck2`. No `git stash`, no
merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other
worktrees or other cache dirs. Kill only processes you started, by the pid `tools/job` recorded (never by pattern).
No sleep-poll loops. Your write-forever fixture must itself be bounded from the first run (set the limit before you
ever run it). 2 CPUs and 8 GiB are shared and loaded; RE "No space left on device" or daemon errors are load: re-run.
