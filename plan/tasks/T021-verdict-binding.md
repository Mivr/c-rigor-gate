# T021: the signed verdict binds every input that decides it (backlog B16, R001 R4)

Repo: `Mivr/c-rigor-gate`. Branch `task/T021`. Read `AGENTS.md`, `plan/audits/R001-gate-audit.md` (R4), `plan/backlog.md`
(B16), `docs/grade.md` ("Verdict determinism"), `gate/rigor_lib/verdict.py`, `gate/rigor_lib/grade.py`,
`gate/rigor_lib/grade_context.py`, `gate/rigor_lib/approvals.py`. **In parallel:** T011 (`structure*`, a line in
`cli.py`), T013 (`product_layout.py`, `grade_tree.py`, `grade_checks.py`, `grade_policy.py`, `products/**`). Don't
touch those files.

## Why
`core_sha256` today commits only to the per-gate statuses and finding hashes (plus the manifest via an info finding).
The gate commit, graded head, task contract, policy, expected tests, toolchain and RE pins, and the `--uncached` mode
live in unhashed metadata. Signature verification covers the whole file, but anything that keys trust on
`core_sha256`, as the docs say to, cannot tell a verdict from a weaker gate or another policy apart.

## Allowed paths
`gate/rigor_lib/verdict.py`, `gate/rigor_lib/grade.py`, `gate/rigor_lib/grade_context.py`, a new
`gate/rigor_lib/verdict_inputs.py`, `gate/rigor_lib/approvals.py` (verify side only), `gate/tests/test_verdict*.py`,
`gate/tests/test_grade_verdict*.py`, `docs/grade.md`, `plan/backlog.md` (mark B16).

## Requirements
1. `core` gains `inputs`: the gate commit sha (and whether its tree is clean), the graded head sha, the merge base, the
   product name, and sha256 of the exact bytes of the task contract, `policy.toml`, `expected-tests.json`,
   `product.toml`, the approvals bundle actually used, the generated `.buckconfig`, the toolchain pins (the LLVM and
   sysroot sha256 and the Buck2 binary sha256) and `gate/order.txt`. Also `uncached`. Every one of these is read from what the
   grade actually used, never re-read later.
2. A dirty gate tree (uncommitted changes to tracked files) makes the grade exit 2 unless `--allow-dirty-gate` is given,
   and then `inputs.gate_clean = false` is in core and the verdict can never be PASS-signed (`rigor verify` rejects it).
3. `rigor verify` (or the existing verify path) checks the signature, then recomputes `core_sha256`, and optionally takes
   `--expect-head`, `--expect-gate` and `--expect-policy-sha` and fails on any mismatch. Document a one-liner for a consumer
   such as a merge bot.
4. Determinism: two grades of the same inputs give identical `core_sha256`; change any single input and it changes.
   Test each input on its own.

## Acceptance
```sh
selftest/gate.sh
selftest/grade.sh
```
Report: the new core schema, the per-input change tests, and the verify one-liner.
