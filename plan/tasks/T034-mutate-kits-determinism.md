# T034: mutation grading works with header-only test kits (R004 T0 blocker) and mutant results are deterministic

Repo: `Mivr/c-rigor-gate`. Branch `task/T034`. Read `AGENTS.md`, `docs/mutate.md`, `rules/mutate.bzl`, `mutate/tool.py`,
`gate/rigor_lib/grade_mutants.py`, and annas-c's R004 report (`plan/audits/R004-test-adequacy.md` in annas-c, "Gate-side
notes"). **T030 (`toolchains/**`, `grade_build.py`), T032 (`grade_steps.py`, `grade_pipeline.py`, `grade_checks.py`,
`grade_tree.py`, `grade_policy.py`, `buckfiles.py`, `gate/order.txt`) and T033 (`facts_symbols.py`, `facts_policy.py`) run
in parallel**: don't touch their files. `mutate/gen.py` is reserved for the next task (G2/G3 operators): touch it only if a
fix is impossible elsewhere, and say so.

## Why
1. **Crash on header-only kits.** `rules/mutate.bzl` takes `d[DefaultInfo].default_outputs[0]` for every test dep. Since
   annas-c A028, its `testkit` libraries (`annas`, `app`, `wire`, `posix_fs`, `tls_stream`) are header-only `c_library`s with no
   default output, so every annas-c grade fails `mutants-build-failed` (`index 0 out of bound`, reproduced on
   `//annas:testkit`).
2. **Non-deterministic mutant results.** In T021's validation a warm re-grade of the same head executed one `mutant_report`:
   two `report.json` files differed only in garbage numbers inside failure reasons (`32770` vs `32772`,
   `-781801958` vs `-859197798`), e.g. a mutant reading past an array. A cached `mutant_run` result that varies by execution
   makes downstream action keys unstable and lets the reported reasons change between identical grades.

## Allowed paths
`rules/mutate.bzl`, `mutate/**` except `mutate/gen.py` (see above), `gate/tests/test_mutants*.py`, `gate/tests/test_mutate*.py`,
`gate/tests/fixtures/mutate/**`, `selftest/mutate.sh`, a new `canaries/header-only-kit/`, `docs/mutate.md`, `plan/backlog.md`
(add B34 for the determinism item and mark it).

## Requirements
1. Header-only deps (no default output) contribute their headers and no library; a dep that provides neither is a build
   error, not silently dropped. Canary `header-only-kit`: a module whose tests use a header-only kit grades cleanly at L3
   (as a green `"control": true` canary, or a selftest step if a green canary doesn't fit).
2. What a mutant run stores and what `mutant_report` reads must be a deterministic function of the action's inputs: keep the
   verdict (killed by assert, killed by crash/signal, timeout, survived) and a normalised reason (no addresses, no numbers
   that come from uninitialised memory, no PIDs). Prove it: run `selftest/mutate.sh` twice cold-keyed (a nonce) and show the
   reports are byte-identical; a mutant that reads uninitialised memory is in the fixture.
3. No verdict changes: `selftest/mutate.sh` and `selftest/grade.sh` stay green with the same mutant counts.

## Acceptance
```sh
selftest/mutate.sh
selftest/grade.sh
selftest/gate.sh
selftest/canaries.sh --only header-only-kit --only control
```
