# T040: the witness canaries (P002; stacked on T039, merged together with it)

Repo: `Mivr/c-rigor-gate`. Branch `task/T040`, which already holds `task/T039` plus current `main`; the orchestrator
merged them and resolved a `products/annas-c/policy.toml` conflict. Read `AGENTS.md` ("Working efficiently"),
`docs/canaries.md`, `docs/witness.md`, `docs/grade.md`, and **P002's "### T040" section** in
`plan/P002-witness-grading.md`. That section is the contract; follow it exactly.

Changes since P002:
- T039 reports that `impl-missing` fails every grade of a product whose L2+ module has no `impl` key, and that no
  canary lists `impl` yet. Adding `impl` to **every** `canaries/*/policy.toml` (`<module dir>/src/**` or the
  module's actual source globs, mechanically) is part of this task, exactly as P002 allows.
- main has since gained `//wire:wire` at L2 in `products/annas-c/policy.toml` without an `impl` key. Add
  `impl = ["wire/src/**"]` there (the only `products/annas-c` edit allowed).
- Every canary policy carries `exports` lists now (T055). The new canaries need them as well, including any symbol
  their edit adds.
- T039 did not put the red witness cases in `selftest/grade.sh`. Your canaries `witness-survivor`,
  `witness-test-fails` and `witness-missing` are those red cases; `witness-green` is the control.

**Allowed paths:** P002's T040 list, plus `products/annas-c/policy.toml` (`impl` for wire only).
**In flight in parallel:** T064 (`rules/mutate.bzl`, `mutate/**`, `mutants_*`, a minimal `grade_mutants.py`
change). Do not edit `plan/backlog.md` or `plan/backlog.d/`.

## Acceptance
```sh
selftest/gate.sh
selftest/grade.sh                                       # via tools/job
TMPDIR=/var/tmp/cache/T040/tmp selftest/canaries.sh     # via tools/job: 0 live misses, 0 pending
```
Report the wall-time change of the canary pack, justify each changed `expect.json` line by line, and confirm that
every gate in `gate/order.txt` is the expected failing gate of some live canary. Report every deviation.
