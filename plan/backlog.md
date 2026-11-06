# Gate backlog (found during phase 1; ordered by risk)

| # | Gap | Found by | Planned fix |
|---|---|---|---|
| B1 | **Recursion is not mechanically detected** (only the 512-byte frame limit pressures it). | A003 test author | Call-graph cycle check from the release objects (`llvm-objdump -dr` call relocations + intra-TU calls via clang `-Xclang -ast-dump` or `-fstack-usage`), as a facts field and a `structure` gate. |
| B2 | **Size/complexity rules are prompt-only**: functions <= 50 lines, files <= 500 lines, nesting, params. | orchestrator | `structure` gate from the clang AST (function extents, params, nesting), one table of limits per rigor level. |
| B3 | Code under `__SANITIZE_ADDRESS__` / `__has_feature(...sanitizer)` is invisible to the release-only semantic scan. | T004 | Also produce facts in `san` mode and diff the semantic facts between modes; any difference is a finding. |
| B4 | Action cache is client-writable on the shared RE farm, so cached results could be forged. Today: decisive grades use `--uncached`. | orchestrator (T005) | Dedicated grader instance with client-read-only AC on NativeLink (needs owner, sb-ws infra). |
| B5 | Contributor agents share uid, filesystem and credentials with the orchestrator; isolation is detective (transcript audit). | phase-1 known limit | orca-dev sandboxes (separate uid, no network, no credentials) on sb-ws. |
| B6 | Gate canary pack (every gate red on its known-bad fixture, run on every gate change) and impossible-obligation tripwires. | plan | T008. |
| B7 | Hidden tests in a private repo, fail-on-base / pass-on-witness, run only at grading. | plan | after mutation lands. |
| B8 | Red team: an Opus agent tries to pass a hidden task by cheating; every success becomes a canary. | plan | end of phase 1. |
| B9 | Sanitizer stack traces are unsymbolized (agent debugging cost). | T001 | wire `llvm-symbolizer` into san/fuzz runs. |
| B10 | Transcript audit is an orchestrator scratch script with false positives (URLs in test data). | orchestrator | move into the gate as `rigor trajectory` with structured rules and tests. |
| B11 | Unviable-mutant ratio countermetric. | orchestrator (T006 review) | T008. |
| B12 | `rigor grade` must build `gate//third_party/*:*_symbols` into the facts dir for products that use a vendored library; product layouts must always exclude `third_party/**`. | T009 | after T008 merges. |
| B13 | Quadratic paths in parsers bounded only by input caps (json duplicate keys; http dot-segment removal). | A004/A011 | hidden performance tests (private notes). |
| B14 | **Layout is an include-list, so a new product directory is silently ungraded** (annas-c `http/`, `app/` and the coming `posix_*` were never graded). | P001 planner | T013: every BUCK file and C source in the product must be covered by `layout.include` or a gate-known non-code exclusion (`docs/`, `plan/`, `fixtures/`); anything else is a finding `ungraded-path`; complete annas-c layout + policy entries + levels for ports, http, annas, app, posix_*. After T008. |
