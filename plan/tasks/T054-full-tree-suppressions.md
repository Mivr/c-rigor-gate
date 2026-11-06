# T054: the suppressions gate scans the whole graded tree, not only the diff (B17; R001 R5)

Repo: `Mivr/c-rigor-gate`. Branch `task/T054`. Read `AGENTS.md` ("Working efficiently") and `docs/grade.md` first.
`suppressions_gate` (`gate/rigor_lib/grade_steps.py`) runs `suppressions.run` over `base..head` only. A suppression
added in an ungraded ancestor (before `base`), e.g. under a sanitizer macro the release-only semantic scan never
compiles, is seen by nothing (R001 R5; `plan/audits/R001-gate-audit.md`). T023 covers the sanitizer-guarded case in
the compiled tree as `mode-divergent-code`; the full-tree scan is still open.
**In flight in parallel:** T038 (`grade_build.py`, `grade_mutants.py`, `mutants_gate.py`), T051, T052 (`trajectory*`),
T053 (`selftest/grade.sh`, new canaries, `canaries/runner.py`). Touch none of their files. Do not edit
`plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`gate/rigor_lib/suppressions.py`, `gate/rigor_lib/grade_steps.py` (`suppressions_gate` only), `gate/tests/test_suppressions*.py`,
`gate/tests/fixtures/suppressions/**`, new `canaries/ancestor-suppression/`, `docs/grade.md` (the suppressions section
only), `docs/product-checks.md` if it documents the scan.

## Requirements
1. At grade time the gate also scans every file the product layout grades at `head` (same file set as `assemble`,
   same patterns as the diff scan), reporting each hit with path and line. A hit that is also in the diff is reported
   once. Approvals keep working exactly as today (an approved suppression is not a finding).
2. Findings from lines outside the diff use a distinct rule name (`forbidden-pattern-in-tree`) so a verdict says
   where it came from; severity is error, the same as in the diff.
3. Canary `ancestor-suppression`: the suppression is committed **before** `base` (the canary's edit must create a
   base commit containing it; see how canaries set base/head) under `#if __has_feature(address_sanitizer)` or a
   NOLINT; must fail `suppressions:forbidden-pattern-in-tree`. `control` stays green.
4. Report how many in-tree hits today's annas-c main has (run `rigor suppressions` style scan over a clone; it should
   be 0; if not, list them).

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_suppressions*.py'
selftest/canaries.sh --only ancestor-suppression --only control --only nolint
selftest/gate.sh
```
