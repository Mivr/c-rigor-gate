# T085: report allow-list entries that no object references (`unused-allow`, info)

Repo: `Mivr/c-rigor-gate`. Branch `task/T085`. **Gate task** (implementer + its own tests). Read `AGENTS.md`,
`docs/product-checks.md` (the `symbols` gate, `allow`, `deny_exempt`, `exports`), `docs/grade.md` ("unused-approval", the
precedent for an info finding about stale configuration), `gate/rigor_lib/facts_symbols.py` and its tests.

## Why
T083 found, by dropping allow entries one at a time, that `//app:app` allowed `bcmp` although no object referenced it,
that header-only `testkit` libraries carry allow lists no object can use, and that several `//wire:*_test` allows of
`tls_peer_*` are covered by the trusted dependency's exports. Stale allow entries widen what a later change may use
without review. The gate should say so.

## Requirements
- In the `symbols` gate, for every module of the policy: every `allow` entry (and every `deny_exempt` entry, if it is a
  list of symbols) that **no object of that module references** is a finding `unused-allow`, severity **info**, with the
  module label and the symbol. Sorted, deterministic. A module with no objects at all (header-only) reports each entry.
- An entry that a trusted dependency's exports already cover is reported the same way (`unused-allow`, with
  `reason = "covered by <dep>"`), since the entry grants nothing.
- Never an error: it must not change any PASS/FAIL. Document it in `docs/product-checks.md` next to `exports-missing`.
- Tests: green and red fixtures for each case (used entry not reported; unused entry reported; header-only module; entry
  covered by a trusted dep; `deny_exempt`). A canary is not needed for an info finding; say if you think one is.
- Then run it on annas-c `main` (clone into your cache dir as T083 did, build the facts, run `symbols`) and list every
  `unused-allow` it reports. Do **not** edit `products/annas-c/policy.toml`: report only.

## Allowed paths
`gate/rigor_lib/facts_symbols.py` (and a small helper module if needed), `gate/tests/test_*symbols*.py`,
`gate/tests/fixtures/**` (new symbols fixtures only), `docs/product-checks.md`.

## Acceptance
```sh
python3 -I -m unittest discover -s gate/tests -t gate -p 'test_*symbols*.py'
selftest/gate.sh
selftest/product_checks.sh
```
Report the change, the tests, the annas-c list, and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T085/tmp`; never write to `/tmp`. No `git stash`, no merge of `main`, no push. Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill
processes you did not start. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
