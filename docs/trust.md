# Trust without a key holder (U30, owner decision 2026-11-16)

Owner, verbatim: "Lets remove the signing at all, the whole idea is that agents can scale and work on this at large
scale on their own." Nothing in the gate is signed any more: no verdict signature, no signed approvals, no
`allowed_signers`, no signer roles, no `ssh-keygen`. Trust comes from checks anyone can re-run, from content bindings,
and from counting every loosening where a reader sees it.

## What the gate guarantees mechanically
- **A verdict is a deterministic function of its inputs.** `core` binds by sha256 the task, the product files, the
  approvals bundle, the gate commit and its order, the toolchain pins, the witness, oracle and perf bundles, the
  commits graded, the tier and the cache mode (`docs/grade.md`, "Verdict determinism and bound inputs"). The same
  inputs give the same `core_sha256`, cold or cached.
- **`rigor verify` checks consistency, not authorship.** It recomputes `core_sha256`; refuses a dirty gate, a FAIL, a
  malformed or missing input and a verdict of the old signing gate; recomputes the gate order and the toolchain pins
  from the gate commit the verdict names and requires that full gate list (no `--only` grade, no reordering); checks
  the approvals count; and requires the head it is asked about (`--expect-head` is mandatory). It does **not** prove
  who ran the grade, or that a grade ran: a self-consistent `core` can be written by hand. A verdict is trusted
  because anyone can grade again from the same inputs and compare `core_sha256`.
- **An approval covers exactly its bound target.** Kind plus exact scope (file, line and pattern; test id; ratchet
  file and key; mutant id bound to its token and function body), named by the sha256 of its bytes, applicable only to
  heads that descend from its `repo_sha`. A tampered, malformed or stray file, or a `.json.sig` left by the old gate,
  is a `forged-approval` error; an approval-like file inside the graded repo is `approval-in-repo`.
- **Unchanged by U30:** every gate, threshold, baseline, ratchet, tripwire, canary and expected list. Ratchets still
  only go down without a `ratchet` approval; a removed test still needs a `test-removal` approval.

## What counts as a loosening, and where it shows
A loosening lets a finding pass that would fail without it: an approval of any kind (`suppression`, `test-removal`,
`ratchet` for a raised baseline or a relaxed ratchet key, `equivalent-mutant`, `witness-equivalent-mutant`), a relaxed
threshold or policy value, an exception row, a raised baseline.
- **Approvals** are counted and listed in the verdict: `core.approvals = {"count", "in_force": [{kind, scope, reason,
  stem}]}`, hashed with the rest of `core`, printed by `rigor grade` (`approvals in force (loosenings): N`) and by
  `rigor verify`. A change that adds one raises the count; it is never silent. Unused ones are in
  `core.unused_approvals`.
- **Gate-owned files** (policy, expected tests, baselines) are bound by sha256 where the grade reads them
  (`policy_sha256`, `expected_tests_sha256`, ...): a change to one changes its binding and shows in the diff of the
  task that made it. The UI contract files (`products/*/ui/*.toml`: contract, event catalogue, deviation baselines) are
  ordinary reviewed contract files; no gate of the grade reads them yet, so no verdict counts a change to them today.

## What an agent may and may not do
- May write an approval, raise a baseline, relax a threshold or add an exception **only** inside a task whose
  contract names that loosening, with the reason recorded (in the approval, or in the file's provenance) and in the
  report.
- May not weaken any other check (`AGENTS.md`, hard rule 2, unchanged), put approvals in the graded repo, or present a
  hand-written or edited verdict as a grade.

## What a reader of a verdict should check
1. `rigor verify --verdict V --expect-head H --expect-gate G [--expect-policy-sha ...] [--require-tier ...]` exits 0.
2. `approvals in force` is what the task contract allows, and every listed scope is one the contract names.
3. If the writer of `V` is not trusted, grade again with the same inputs and compare `core_sha256`.

## The ledger (T132; a library, not wired into any gate)
`gate/rigor_lib/ledger.py` keeps an append-only, hash-chained directory of `NNNNNN.jsonl` entries (`claim`,
`revocation`, `ratchet`, `gate-change`, `tighten-only-on`, `tighten-only-off`; canonical JSON with `seq`, `prev`,
`kind`, `subject`, `evidence`, `at`). `rigor ledger verify [--head SHA]` exits 0 only for an intact chain that contains
the head. A claim's subject is `<approval kind>:<scope>:<sha256 of the approval file>`; a `revocation` names a standing
claim. With `--ledger DIR`, an approval whose claim entry comes after a `tighten-only-on` entry does not count
(`forged-approval`, reason `tighten-only`). The debt cap (`over_cap`, `DEFAULT_CAP_PPM` = 2% of a module's mutants, one
claim below 50 mutants) is a library function. Not built: a gate passing `--ledger`, the ledger head in the verdict,
the refuter, automatic tighten-only events.
