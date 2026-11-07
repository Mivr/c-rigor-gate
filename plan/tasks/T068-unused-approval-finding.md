# T068: make unused approvals visible (`unused-approval`, T058 deviation 2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T068`. Read `AGENTS.md`, `docs/grade.md` (approvals), and
`gate/rigor_lib/approvals.py`, `grade.py`, `verdict*.py`.
Since T058, mutant ids are bound to the function body. After a refactor, an old `equivalent-mutant` approval names
nothing and is **silently** unused. The same is true of any approval kind whose scope no longer matches. Nothing
grants anything by accident, but stale approvals pile up and hide which ones still do work.

## Requirement
1. After all gates have run, compare the valid approvals loaded from `--approvals` against the union of every
   gate's `approvals_used` metadata. Each valid approval that no gate used becomes one finding, `unused-approval`,
   with its `kind`, `stem` and `scope`. Put it in the verdict as a separate verdict-level entry, not inside any
   gate.
2. Severity is **info**. An unused approval grants nothing; this is housekeeping, not a failure. The verdict hash
   must cover the entry, so the list cannot be dropped silently.
3. Approvals that failed validation (forged, wrong signer, wrong repo) are already reported. Do not double-report
   them.
4. Tests: an unused `equivalent-mutant` approval after a body change (the T058 approval-drift shape) is reported;
   a used one is not; a gate that never ran (NOT_RUN) makes its approvals "unknown". Say how you treat that case
   and why; the fail-closed default is to report them as unused, with a `gate_not_run` reason.
5. `docs/grade.md`: document the entry.

## Allowed paths
`gate/rigor_lib/grade.py`, `gate/rigor_lib/verdict.py`, `gate/rigor_lib/verdict_inputs.py`,
`gate/rigor_lib/approvals.py` (read helpers only), `gate/tests/test_grade*.py`, `gate/tests/test_verdict*.py`,
`gate/tests/test_approv*.py`, `docs/grade.md` (the approvals section).
**In flight in parallel:** T041 (`grade_pipeline.py`, `gate/order.txt`, `grade_steps.py`, `tests_gate.py`,
`grade_witness.py`, `selftest/grade.sh`) and T064 (`mutate/**`, `mutants_*`). Touch none of them. Do not edit
`plan/backlog.md` or `plan/backlog.d/`.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_grade*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_verdict*.py'
selftest/gate.sh
```
Report the verdict format change, the NOT_RUN choice, and every deviation.
