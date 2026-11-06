# T051: an equivalent mutant must be equivalent at -O0 too (B15; R001 R2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T051`. Read `AGENTS.md` ("Working efficiently") and `docs/mutate.md` first.
R001 R2 (`plan/audits/R001-gate-audit.md`): a mutant is `equivalent` (and never run) when its `-O2` object is
byte-identical to the baseline's (`mutants_verdict.py` ~467, `rules/mutate.bzl` `_stage2`). The optimizer can fold
a behaviour-changing mutation to the baseline object, so a real defect is silently excluded.
**In flight in parallel:** T050 (`mutate/gen.py`, new steps in `selftest/mutate.sh`, `canaries/struct-return-untested/`),
T038 (`grade_build.py`, `grade_mutants.py`, `mutants_gate.py`), T049 (`trajectory*`), T047 (backlog), batch3. Touch none
of their files except appending new steps at the end of `selftest/mutate.sh` (the orchestrator merges the two).
Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Allowed paths
`rules/mutate.bzl`, `mutate/tool.py`, `gate/rigor_lib/mutants_verdict.py`, `gate/tests/test_mutants*.py`,
`gate/tests/test_mutate_tool*.py`, `gate/tests/fixtures/mutate/**` (new files only), `selftest/mutate.sh` (new steps at
the end only), new `canaries/o2-folded-mutant/`, `docs/mutate.md`.

## Requirements
1. Only mutants whose `-O2` object equals the baseline's are re-checked: compile the mutant and the baseline again at
   `-O0` (same flags otherwise); the mutant is `equivalent` only if identical in both. Otherwise it is live and runs
   against the tests like any other mutant. Same for `duplicate` (two mutants identical to each other at -O2): they
   are duplicates only if identical at -O0 too.
2. The extra compiles are separate cached actions keyed on their inputs (no change to the cost of mutants that
   already differ at -O2). Report the action count added on the selftest product and on annas-c (estimate from the
   share of equivalent/duplicate mutants).
3. A fixture with a hand-made mutation that `-O2` folds to the baseline but changes behaviour (for example a
   comparison the optimizer canonicalises under an assumption the test violates, or UB-adjacent arithmetic; find a
   real one and explain it) must now run and be killed (or survive) instead of being `equivalent`. Canary
   `o2-folded-mutant`: such a mutation left untested must fail `mutants:survived-mutant`.
4. Verdict metadata records, per module, how many mutants were equivalent at -O2 and how many of those stayed
   equivalent at -O0.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_mutat*.py'
selftest/mutate.sh
selftest/canaries.sh --only o2-folded-mutant --only control --only weak-test
selftest/gate.sh
```
