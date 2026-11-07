# T071: approvals and gate order read from the snapshot, not the live checkout (B16 open part)

Repo: `Mivr/c-rigor-gate`. Branch `task/T071`. Read `AGENTS.md` ("Working efficiently"), `docs/grade.md` (T021: `core.inputs`,
snapshotted inputs), `plan/backlog.d/B16.md`, `gate/rigor_lib/verdict_inputs.py`, `grade_context.py` (`ORDER_FILE`),
`grade_steps.py` (`allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS`), `approvals.py` and `approval_args.py`.

## Problem
T021 binds `gate/allowed_signers` and `gate/order.txt` into `core.inputs` by hash. But the gates then **read them from
the live gate checkout** (`grade_context.ORDER_FILE`, `approval_args.DEFAULT_ALLOWED_SIGNERS`), not from the bytes that
were hashed. A change to either file during a grade (or between hashing and use) makes the verdict claim inputs
it did not use.

## Requirement
1. Snapshot both files into `<work>/inputs/` with the other T021 inputs, before any gate runs. Hash the snapshot, and have
   every reader use only the snapshot: the gate order, approval loading in every step that loads approvals, and anything
   else that reads them during a grade. `--allowed-signers PATH`, if given, is snapshotted the same way.
2. Outside `rigor grade` (the standalone `rigor approvals`/`rigor verify` style commands), keep today's behaviour,
   unless they are part of a grade.
3. A test that fails on today's `main`: it changes the live `allowed_signers` (or `order.txt`) after the snapshot,
   before the step that reads it, through a hook or a test seam the gate already has, never a new `pub`-for-tests
   switch in production code. The verdict must reflect the snapshot bytes. Plus a test that a missing snapshot is exit 2.
4. Verdict compatibility: `core.inputs` keeps its keys. If any key's meaning changes, document it in `docs/grade.md`.

## Allowed paths
`gate/rigor_lib/grade_context.py`, `grade_steps.py`, `grade_pipeline.py`, `verdict_inputs.py`, `approvals.py`,
`approval_args.py`, `gate/tests/test_grade*.py`, `gate/tests/test_verdict*.py`, `gate/tests/test_approvals*.py`, `docs/grade.md`
(a short section of its own).
**In flight in parallel:** T069 (`selftest/grade.sh`, `products/selftest/policy.toml`, `docs/grade.md`), T072 (`trajectory*`).

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_grade*.py'
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_approvals*.py'
selftest/gate.sh
TMPDIR=/var/tmp/cache/T071/tmp selftest/grade.sh       # via tools/job
```
Report the readers you moved to the snapshot, the new tests and every deviation.
