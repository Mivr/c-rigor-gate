# T082: annas-c expected ids for A058 (3 http request tests)

Repo: `Mivr/c-rigor-gate`. Branch `task/T082`. Read `AGENTS.md`, `plan/tasks/T075-annas-config-new-tests.md` (the same job
with new targets) and `docs/grade.md` "Audit grade of annas-c (T059)".
annas-c main `3d75ca3` adds three cases to the existing target `//http:request_test` (no new target, no BUCK change):
- `http_request/arg_beats_overflow_each_slice`
- `http_request/arg_beats_invalid_each_position`
- `http_request/empty_null_slices_beat_overflow`

Without this, the next grade reports them as `unexpected-test`.

## Allowed paths
`products/annas-c/expected-tests.json` only (add-only, through `gate/tools/expected.py add`). No policy change is expected:
if the symbols check shows one is needed, stop and report it.
**In flight in parallel:** T081 (`gate/rigor_lib/mutants_gate.py`, `gate/tests/test_mutants*.py`, `docs/mutate.md`, and it
also adds 8 ids to `expected-tests.json`). Do not touch its files. Your add must be add-only, so it merges with T081's.

## Acceptance
Clone `/var/tmp/src/annas-c` at `3d75ca3` into `/var/tmp/cache/T082/annas` (submodule from the local gate clone), then:
- build the facts and the release and san results of that clone;
- run the symbols check over them as T075 did: `symbols` PASS, 0 findings;
- `expected.py add` from those results: report exactly how many ids were added (expect 3, unless T081's 8 are not yet on
  main, in which case report those separately and add only the A058 three plus whatever `add` requires; say which).

Do **not** run the full grade. Then run `selftest/gate.sh`. Report the ids added, the symbols result and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T082/tmp`; never write to `/tmp`. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill
processes you did not start. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
