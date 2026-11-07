# T041: the stub check `tests-stub` and the test-author role (P002, closes B27)

Repo: `Mivr/c-rigor-gate`. Branch `task/T041`. Read `AGENTS.md` ("Working efficiently"), `docs/grade.md`,
`docs/witness.md`, `docs/canaries.md`, and **P002 in full** (`plan/P002-witness-grading.md`), especially Q2 and the
"### T041" section. That section is the contract; follow it exactly. T039 and T040 are merged (`146eee4`).

Changes since P002:
- T053 cut `selftest/grade.sh` to property steps. Add the six P002 steps in that style. A step that a canary
  covers better may become a canary instead, as long as each of the six behaviours is pinned somewhere; say which.
- T040 grades every canary with `--witness` (`canaries/_base/witness/` or per-canary bundles), and every canary
  policy has `impl` and `exports` keys. Your two canaries need the same.
- The backlog is fragments now: close B27 in `plan/backlog.d/B27.md` (not `plan/backlog.md`), then run
  `tools/backlog_fold.py` as `AGENTS.md` says.
- T064 (in flight) edits `rules/mutate.bzl`, `mutate/**`, `mutants_*` and makes a minimal `grade_mutants.py`
  change. Keep your `grade_mutants.py` change (role test-author: not applicable) small and in its own commit.

**Allowed paths:** P002's T041 list, with `plan/backlog.d/B27.md` and the folded `plan/backlog.md` in place of
`plan/backlog.md`.

## Acceptance
```sh
selftest/gate.sh
selftest/grade.sh                                       # via tools/job
TMPDIR=/var/tmp/cache/T041/tmp selftest/canaries.sh     # via tools/job: 0 live misses, 0 pending
```
Report each of the six grade.sh behaviours and where it is pinned, the canary results, and every deviation. This
gate decides whether a test author's tests really fail on stubs, so fail closed wherever the role or inputs are
unclear.
