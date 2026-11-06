# T038: the build and mutants steps run on a given tree (P002 step 3, refactor only)

Repo: `Mivr/c-rigor-gate`. Branch `task/T038`. The contract is the section "### T038" of `plan/P002-witness-grading.md`
(allowed paths, requirements, acceptance). Read `AGENTS.md` ("Working efficiently") first. No behaviour change.
**In flight in parallel:** T049 (`trajectory*`); batch3 validation of T032 (`grade_structure.py`, `grade_pipeline.py`,
`selftest/grade.sh`), T037 (`grade.py`, `grade_context.py`, `verdict_inputs.py`, `approvals.py`), T046, T048. Touch
none of their files. Do not edit `plan/backlog.md`.

## Acceptance
As in the P002 section: `selftest/gate.sh`; `selftest/grade.sh` with `RIGOR_GRADE_KEEP=1` before (on `main`) and after
(on your branch), and a script that compares `core.gates` of every kept verdict and prints identical / the diff.
