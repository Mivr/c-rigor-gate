# P002: design for grading against the gate-held witness and the stubs (backlog B27, R003 G1) (Opus, design only)

Repo: `Mivr/c-rigor-gate`. Output: `plan/P002-witness-grading.md` on branch `task/P002` (design doc only, no code).
Read `AGENTS.md`, `docs/grade.md`, `docs/mutate.md`, `gate/order.txt`, `gate/rigor_lib/grade_pipeline.py`,
`grade_steps.py`, `grade_tree.py`, `grade_mutants.py`, `verdict.py`/`verdict_inputs.py` (T021, on `task/T021`), the
annas-c two-context rule (`plan/phase1.md` in annas-c), how the orchestrator calibrates a test author's witness today
(stubs must fail, witness must pass, release and san; the witness is quarantined outside the repo), and R003
(`plan/audits/R003-test-adequacy.md`, G1: W4, S3n-w, S7b-w) and annas-c R004 (`plan/audits/R004-test-adequacy.md` there).

## Problem
`rigor grade` judges only the implementation under grade. Weak tests are flagged only if that implementation contains the
unpinned code, so an implementer who omits spec-required code passes. Nothing in the grade checks that every expected test
fails on the stubs, and the witness lives outside the gate's inputs.

## Design questions to settle (with a recommendation each)
1. Where the witness lives and how it's bound: a gate-held artifact (path, signature, sha256 in the verdict inputs) vs the
   orchestrator's quarantine dir; who may read it; how a test author's task produces it without an implementer seeing it.
2. `test-passes-on-stub`: grade the stub commit too (base or a named commit) and require every expected test id to fail on
   it, in release and san; what "fail" means (assert vs crash vs timeout); cost on the farm.
3. `witness-survived-mutant`: run the module's mutants against the witness with the same tests; a survivor there is a test
   weakness independent of the implementer. How it combines with the implementer's mutants (union? separate finding?),
   at which level it's an error, and whether approvals apply.
4. Off-spec tests the witness agrees with (S7b): what remains for hidden tests (B7), and the interface hidden tests need.
5. Cost and caching: action counts for annas-c (use R004's numbers: annas alone ~10,000 actions), what's reusable between
   the witness run and the implementer run, and how `--uncached` interacts (T030).
6. The task split: Sonnet-sized implementation tasks with allowed paths, acceptance commands and canaries
   (`witness-survivor`, `stub-passes-test`), in dependency order, avoiding the files T032 changes until it merges.

Commit the doc to `task/P002` (identity `P002 designer (Claude Opus)` / `noreply@anthropic.com`), nothing else.
