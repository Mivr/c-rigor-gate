# T115: the mutants gate builds `c_mutants` in bounded chunks (one huge build dies with h2 BrokenPipe)

Branch `task/T115` from main. Gate change, in `gate/rigor_lib/grade_mutants.py` and its tests.

## Why
T113 graded business-apps in full, and the `mutants` gate failed three times out of three. All of the work happens in
one `buck2 build --keep-going` with every `c_mutants` target, about 112 modules and 42k actions.
- Each attempt died with `h2 protocol error ... BrokenPipe`. The cause is the daemon or RE stream dropping under
  memory pressure: the cgroup is 8 GiB and shared.
- After that, every module was reported `mutants-build-failed` and no verdict came out, because one stream failure
  fails every target that is still pending.
- Re-running kept the cached progress but never finished.

## Do
1. `build_reports` builds the labels in **chunks** of at most `MUTANTS_CHUNK` modules each.
   - Pick a small default, 8 to 16, and justify it.
   - Allow an override by a grade option or env only if the gate already has such a mechanism (check
     `grade_context` / `docs`). Otherwise use a constant.
   - Each chunk has its own `--build-report` file under the run dir and includes the chunk's `[perf]` labels.
   - The results are merged, so each finding, report file (`%03d.json` keeps the GLOBAL index) and perf copy is exactly
     what one build would give. Order is deterministic, by index.
2. **A transient transport failure retries that chunk once.** It is transient only when the build exit is non-zero,
   at least one of the chunk's labels has no SUCCESS entry, and stderr matches the transport patterns.
   - Look for an existing classifier first (`grade_build`, the `broken pipe` / `h2 protocol error` handling elsewhere
     in the gate) and reuse it. If there is none, add one in `grade_build` with tests.
   - A real compile or test failure is never retried.
   - A chunk that still fails after its retry yields `mutants-build-failed` for its missing modules only. The other
     chunks' verdicts stand.
3. **Metadata:**
   - `executed_actions` and `cached_actions` are summed over the chunks. The existing callers and the perf budget
     (`mutants_perf`, `perf_policy`) must keep working, so check how they read these.
   - `exit_code` is the first non-zero exit, or 0.
   - Add `chunks` (count) and `retried` (list of chunk indexes).
   - `stderr_tail` comes from the last failing chunk.
4. Between chunks, do not kill the daemon. Keep its cache warm: the same daemon is reused across the chunks.
5. **Tests in `gate/tests/test_grade_mutants.py`, using fake `run_buck` and fake reports:**
   - chunking boundaries: 1, exactly N, N + 1 and 2N + 1 modules;
   - the global indexes in the report names;
   - a transient failure in chunk 2 that succeeds on retry, giving the same output as a clean run;
   - a transient failure twice, so only that chunk's modules fail;
   - a non-transient failure, which is not retried;
   - the metadata sums;
   - perf labels kept per chunk.
6. Update the docs that describe the mutants build (`docs/mutate.md` or the gate's grade doc): one build becomes chunked
   builds.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
Report the chunk size and why, the transient classifier used, the test ids and the outputs.

## Allowed paths
`gate/rigor_lib/grade_mutants.py`, `gate/rigor_lib/grade_build.py` (only for the classifier), `gate/tests/**`,
`docs/**`, `tools/affected.toml`.

## Rules
- Use `TMPDIR=/var/tmp/cache/T115/tmp`; never write `/tmp`.
- Build only with `tools/buck2` / `gate/tools/buck2`, as the docs say.
- Redirect every output to a file and read it; never pipe into `tail` or `head`.
- Run long jobs via `tools/job`.
- Never use `rm`; use `cp -f`.
- No stash, no merge, no push.
- Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache
  dirs. Never search from `/` or `/var/tmp`.
- Do not print the environment.
- Kill only your own buck2d, by pid (`readlink /proc/<pid>/cwd`); never `buck2 kill`.
- 2 CPUs are shared.
- No network except Buck2's pinned downloads.
