# T008: mutation testing inside `rigor grade`; unviable-ratio countermetric; annas-c json policy

Repo: `Mivr/c-rigor-gate`. Branch `task/T008`. Read `AGENTS.md`, `plan/phase1.md`, `docs/grade.md`,
`docs/mutate.md`, `docs/product-checks.md`, `plan/backlog.md`.

## Allowed paths
`gate/rigor_lib/grade*.py`, `gate/rigor_lib/mutants_*.py`, `gate/order.txt`, `gate/tests/**`, `rules/mutate.bzl`,
`products/**`, `selftest/grade.sh`, `selftest/grade_product/**`, `selftest/mutate.sh`, `docs/grade.md`,
`docs/mutate.md`, `plan/backlog.md` (mark B11 done).

## 1. Mutants in the pipeline
- Policy modules gain `level = "L1".."L5"` (required for every non-test product module) in
  `products/<p>/policy.toml`.
- After `build`, `rigor grade` writes a **gate-owned** package into the grading tree (outside the product's
  paths, so `buckfiles` never sees it) with one `c_mutants` target per product module at L2 or above. The tests
  for a module are every product `c_test` that depends on it directly (resolved with `buck2 uquery` in the
  tree, never declared by the product).
- Build them (release), collect the reports, and run the `mutants` gate (`rigor mutants`) with the policy.
  Register the gate as `mutants` in `GATES` and `gate/order.txt` after `tests-san`. `--uncached` applies.
- If `build` or `tests-*` failed, `mutants` is NOT_RUN.

## 2. Unviable-ratio countermetric (backlog B11)
A module whose mutants are > 25 % `unviable` (of all generated) is a finding `unviable-ratio` at L3+ (L2: info):
code shaped so that mutants fail to compile would otherwise escape mutation testing. Red test: a module written
so most mutants trip `-Werror` must fail.

## 3. annas-c
- Add `//json:json` and its tests to `products/annas-c/policy.toml` with the smallest `allow` list its code at
  annas-c `main` needs; set levels: core, json, url, fsname = L3.
- Update `products/annas-c/expected-tests.json` with `gate/tools/expected.py add` from a grade of annas-c `main`.
- Grade annas-c `main` (`/var/tmp/src/annas-c`, read-only) once cached and once `--uncached`. Report the
  verdict verbatim and, for `mutants`, per module: total, per-verdict counts, and every survivor
  (file:line, operator, replacement). Survivors are **findings to report, not to fix** (you cannot change
  annas-c). Report wall times for the cold mutants step and the warm re-grade.

## Acceptance
```sh
selftest/grade.sh && selftest/mutate.sh && selftest/gate.sh     # all green, twice for grade.sh
gate/rigor grade ... annas-c main ...                            # verdicts reported verbatim
```
