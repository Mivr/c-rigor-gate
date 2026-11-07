# T067: `selftest/mutate.sh` DETERMINISM step flakes (uninit reports depend on garbage)

Repo: `Mivr/c-rigor-gate`. Branch `task/T067`. Read `AGENTS.md` ("Working efficiently"), `docs/mutate.md` ("Deterministic
results", T034, and T064's batching), `mutate/tool.py` (`linkrun-batch`, how a record's reason, `asserts` and `rc` are
normalised) and `selftest/mutate.sh`. Look at the step "DETERMINISM: two cold-keyed grades of the same module give
byte-identical reports (T034)" and T064's batch-size comparison, which compares `uninit` by verdict list only.

## Problem
The DETERMINISM step failed in two orchestrator validations (before T064) and passed on re-run. The `uninit` module
reads uninitialised memory on purpose. Which check of `uninit_test` fails first depends on that garbage, and something
derived from it still reaches the report. T064 hit the same thing with different batch sizes and worked around it by
comparing verdicts only for `uninit`. A selftest that flakes hides real nondeterminism, and the report is part of a
cached action's output, so a garbage-dependent byte makes downstream keys unstable (B34).

## Requirement
1. Find exactly which report bytes vary between two cold-keyed runs of `uninit_mutants`. Run the step's two builds
   repeatedly in your scratch (at least 10 pairs), diff the reports, and name each field and its source.
2. Fix it in the recorder, not in the selftest: the stored record keeps only what the verdict needs (killed-assert vs
   killed-crash vs survived, normalised as T034 intends), so two runs with different garbage store identical bytes.
   Do not loosen what decides a verdict. If a field must stay because a verdict reads it, explain why, and make the
   fixture deterministic instead.
3. Then the DETERMINISM step and T064's batch comparison compare `uninit` **byte for byte** again (drop the verdict-only
   special case), and both pass in 10 consecutive runs of the step. Report the pass count.
4. A unit test in `gate/tests/test_mutate*.py` for the normalisation (two raw outputs that differ only in the garbage
   give one record).

## Allowed paths
`mutate/tool.py`, `rules/mutate.bzl` (only if needed), `gate/tests/test_mutate*.py`, `selftest/mutate.sh` (the DETERMINISM
step, T064's batch comparison and the `uninit` fixture), `docs/mutate.md`.
**In flight in parallel:** T070 (`grade_mutants.py`, and maybe a new step appended at the **end** of `selftest/mutate.sh`;
keep your edits to the steps named above). Batch8 (T069, T071, T072) is in validation.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutate*.py'
selftest/mutate.sh          # via tools/job; then run it twice more, all three passing
selftest/gate.sh
```
Report the varying fields you found, the fix, the 10-run count and every deviation.
