# T064: batched mutant actions (speed-up plan item 11, R006 #9)

Repo: `Mivr/c-rigor-gate`. Branch `task/T064`. Read `AGENTS.md` ("Working efficiently"), `docs/mutate.md`,
`rules/mutate.bzl`, `gate/rigor_lib/grade_mutants.py`, and R006 #9 in `/var/tmp/cache/T064/R006-report.md`
(read-only copy).

## Problem (orchestrator audit grade of annas-c, 2026-11-07)
The annas-c `mutants` step is one Buck2 build of about **110,000 actions**: one compile per mutant (plus the
-O0 cross-check compile from T051), and one link-and-run per mutant and test binary. The Buck2 daemon was
**OOM-killed** in the 8 GiB container (`memory.events oom_kill 1`, "h2 protocol error ... broken pipe") after
391 s, with about 109k actions still pending. Every module then reported `mutants-build-failed`. An earlier run
did not finish within 3600 s. The decisive annas-c grade therefore cannot run today.

## Requirement
1. **Cut the action count by about an order of magnitude**, with **one verdict per mutant unchanged**.
   - Group the mutants of one module into batches of at most `BATCH` (default 16, a `c_mutants` attribute).
   - One action compiles every mutant of a batch, so N objects come out of one action.
   - One action per batch and test binary links and runs each mutant **in its own process**, one after another,
     with the same per-test and per-binary timeouts as today, and writes one result record per mutant.
   - Mutants must not interfere: a fresh process per mutant, no state on disk shared between runs (each gets
     its own scratch dir), and a crash or timeout of one mutant does not change another's verdict.
2. **Caching:** a batch's key is the sorted ids and contents of its mutants. Batches are formed
   deterministically, sorted by mutant id (T058's content-bound ids), so an edit to one function changes only
   the batches that hold that function's mutants. Report how many batches a one-function edit invalidates on
   annas-c.
3. **Equivalence and verdicts unchanged:** the -O2 object identity check, the T051 -O0 cross-check, `unviable`
   (compile failure of one mutant must not fail its batch: record that mutant as `unviable`, compile the others),
   `killed-assert`/`killed-crash`/`survived`, and the baseline comparison. Prove it: on the selftest product
   and on `canaries/_base`, the per-mutant verdict lists before and after must be **byte-identical**. Add a
   test or selftest step that checks this.
4. **Memory and wall time:** measure the annas-c mutants step before and after: action count, peak RSS of the
   Buck2 daemon (from `/proc/<pid>/status` VmHWM, or the build report), and wall time. Use a scratch clone of
   `/var/tmp/src/annas-c` in your cache dir and a grade with `--work` in your cache dir. If the "before" run
   cannot finish, record how far it got. Do not run more than one annas mutants build at a time.
5. Fail closed: a batch whose action fails as a whole is `mutants-build-failed` for its module, exactly as
   today. A missing result record for any mutant is exit 2, never a pass.

## Allowed paths
`rules/mutate.bzl`, `mutate/**`, `gate/rigor_lib/grade_mutants.py`, `gate/rigor_lib/mutants_report.py`,
`gate/rigor_lib/mutants_verdict.py` (record parsing only), `gate/tests/test_mutants*.py`,
`gate/tests/test_mutate*.py`, `selftest/mutate.sh`, `docs/mutate.md`.
**In flight in parallel:** T039 (`grade_pipeline.py`, `grade_tree.py`, `grade_steps.py`, `grade_policy.py`,
**`grade_mutants.py`**: it extracts the gate-package writer). Keep your `grade_mutants.py` change minimal and in
its own commit. T063 (`structure*`), T062 (`trajectory*`). Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutants*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutate*.py'
selftest/mutate.sh
selftest/gate.sh
TMPDIR=/var/tmp/cache/T064/tmp selftest/canaries.sh      # via tools/job, full pack, 0 misses
```
Report the before and after numbers from requirement 4, the byte-identical verdict check, the invalidation count
from requirement 2, and every deviation.
