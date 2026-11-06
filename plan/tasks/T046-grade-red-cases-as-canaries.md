# T046: the 7 red cases only `selftest/grade.sh` has become canaries (speed-up R006 #1, step 1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T046`. Read `AGENTS.md` (including "Working efficiently") first.
R006 found 14 of grade.sh's 21 red cases are byte-identical to canaries, and grade.sh runs its copies cold
every time (fresh nonce). Step 1 (this task) adds the 7 cases canaries lack; step 2 (later, after T032 merges)
removes all 21 from grade.sh. Nothing is removed in this task.
**In flight in parallel:** T032 owns `selftest/grade.sh` (read it, don't edit it), T037 (`grade.py`, `approvals.py`,
`verdict_inputs.py`, `grade_context.py`), T045 (`trajectory*`). Do not edit `plan/backlog.md`.

## Allowed paths
new `canaries/deleted-target/`, `canaries/kills/`, `canaries/spliced-optnone/`, `canaries/excluded-code/`,
`canaries/stale-include/`, `canaries/third-party-copy/`, `canaries/case-collision/` (use these ids unless a canary of
that name exists; then pick a clear name and say so); `canaries/runner.py` (the leaked-daemon check only);
`gate/tests/test_canaries_runner.py`; `docs/canaries.md`.

## Requirements
1. For each of `edit_deleted_target`, `edit_kills`, `edit_spliced_optnone`, `edit_excluded_code`, `edit_stale_include`,
   `edit_third_party_copy`, `edit_case_collision` in `selftest/grade.sh`: a canary whose `edit.sh` makes exactly
   the same change (copy it verbatim; adapt only paths, since canaries edit `canaries/_base/product`), with any
   product/policy variant the grade.sh case uses, and an `expect.json` with the **exact** failing gates/rules,
   NOT_RUN list and exit code. First check whether an existing canary already covers it byte for byte; if so, say
   which and skip it. Get the expected verdicts by running the canary, then compare with what grade.sh asserts
   (grade.sh only checks a rule is present; your expectation must be exact and must include it).
2. `canaries/runner.py`: port grade.sh's leaked-daemon check (`find_daemons`): after each canary, no process may
   still run in its tree; a leak is a canary failure. Test it in `test_canaries_runner.py`.
3. `docs/canaries.md`: list the new canaries with the grade.sh step each mirrors.

## Acceptance
```sh
selftest/canaries.sh --only deleted-target --only kills --only spliced-optnone --only excluded-code \
  --only stale-include --only third-party-copy --only case-collision --only control
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_canaries*.py'
selftest/gate.sh
```
