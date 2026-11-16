# Trust without a key holder (U30, owner decision 2026-11-16)

Owner, verbatim: "Lets remove the signing at all, the whole idea is that agents can scale and work on this at large
scale on their own." Nothing in the gate is signed any more: no verdict signature, no signed approvals, no
`allowed_signers`, no signer roles, no `ssh-keygen`. Trust comes from checks anyone can re-run, from content bindings
`rigor verify` recomputes, and from listing every approval in force where a reader sees it.

## What the gate guarantees mechanically
- **A verdict is a deterministic function of its inputs.** `core.inputs` binds by sha256 the task, every product
  configuration file the grade reads (`verdict_inputs.PRODUCT_FILE_KEYS`: product, policy, expected tests and their
  previous list, RAM budget, architecture, decoupling and its baseline, fuzz and sim regressions, sim spec, oracle
  policy, normalisation and exclusions) and where they came from (`product_dir`), the approvals bundle, the gate commit
  and its order, the toolchain pins and the generated `.buckconfig`, the witness, oracle and perf bundles, the commits
  graded, the tier and the cache mode (`docs/grade.md`, "Verdict determinism and bound inputs"). The same inputs give the
  same `core_sha256`, cold or cached. A change to any configuration file changes the verdict.
- **`rigor verify` checks bindings, not authorship.** It requires the head and the gate commit the caller names
  (`--expect-head`, `--expect-gate`), recomputes `core_sha256`, the gate list, the toolchain pins, the generated
  `.buckconfig` and the product configuration from that gate commit (or from `--product-dir`), and with `--approvals` the
  approvals bundle and every approval listed in force; it refuses a dirty gate, a FAIL, a malformed input and a verdict
  of the old signing gate. The table of what is recomputed and what is self-reported is in `docs/grade.md`
  ("`rigor verify`"). It does **not** prove who ran the grade, or that a grade ran: a `core` that matches every
  recomputable binding can be written by hand. A verdict is trusted because anyone can grade again from the same inputs
  and compare `core_sha256`.
- **An approval covers exactly its kind and scope.** Scope: file, line and pattern (suppression); test id (test
  removal); ratchet file and key; mutant id bound to its token and function body (equivalent mutant). It is named by the
  sha256 of its bytes and applies only to heads that descend from its `repo_sha`. A tampered, malformed or stray file,
  or a `.json.sig` left by the old gate, is a `forged-approval` error; an approval-like file inside the graded repo is
  `approval-in-repo`; `rigor grade` refuses an `--approvals` directory inside the product repository or the work
  directory.
- **Unchanged by U30:** every gate, threshold, baseline, tripwire, canary and expected list.

## Loosenings: what is counted, and what is only visible
A loosening lets a finding pass that would fail without it.
- **Approvals** (`suppression`, `test-removal`, `ratchet`, `equivalent-mutant`, `witness-equivalent-mutant`) are
  **counted and listed** in the verdict: `core.approvals = {"count", "in_force": [{kind, scope, reason, repo_sha,
  stem}]}`, hashed with the rest of `core`, printed by `rigor grade` (`approvals in force (loosenings): N`) and by
  `rigor verify`. Unused ones are in `core.unused_approvals`.
- **Every other loosening** (a raised baseline such as `decoupling-baseline.toml` or `ram-budget.toml`, a relaxed level,
  deny list or threshold in `policy.toml`, a grown `oracle-excluded.toml`, an edited `architecture.toml`, an expected-test
  list edited together with its previous file, a role or path list in `TASK.toml`, an edited fuzz or sim regression
  list) changes a bound input sha of the verdict and shows in the diff of the task that made it. **The gate does not
  count it**: see the known gaps.
- The UI contract files (`products/*/ui/*.toml`: contract, event catalogue, deviation baselines) are ordinary reviewed
  contract files; no gate of the grade reads them yet, so no verdict binds or counts a change to them today.

## What an agent may and may not do
- May write an approval, raise a baseline, relax a threshold, edit an expected list or add an exception **only** inside
  a task whose contract names that loosening, with the reason recorded (in the approval, or in the file's provenance)
  and in the report.
- May not weaken any other check (`AGENTS.md`, hard rule 2, unchanged), put approvals in the graded repo or the work
  directory, or present a hand-written or edited verdict as a grade.

## What a reader of a verdict should check
1. `rigor verify --verdict V --expect-head H --expect-gate G --expect-policy-sha P [--expect-task-sha T]
   [--product-dir D] [--approvals A] [--require-tier ...]` exits 0.
2. `approvals in force` is what the task contract allows, and every listed scope is one the contract names.
3. The diff of the task, for configuration files whose binding changed (the loosenings the gate does not count).
4. If the writer of `V` is not trusted, grade again with the same inputs and compare `core_sha256`.

## Known gaps (U30)
- **Loosenings other than approvals are not counted.** A raised baseline or a relaxed threshold is bound (the verdict
  changes) but nothing in the verdict says "this grade is looser than its base". Proposal (follow-up task): a base→head
  loosening summary in the verdict, per configuration file, computed by the gate from the merge base's and the head's
  gate-owned files (keys that went up where a ratchet says down, ids removed from expected lists, levels lowered, deny
  entries dropped), counted next to `core.approvals`.
- **Authorship.** Nothing proves who ran a grade (see above); re-grading is the check.
- **Grader-chosen inputs.** The grader chooses the task file, the product directory and the approvals directory.
  `--expect-task-sha`, the product files recomputed from the gate commit (or `--product-dir`) and `--approvals` let a
  reader pin all three; a reader who passes none of them accepts the grader's choice. The approvals directory is
  refused only inside the product repository or the work directory; anyone who can write it can loosen any gate.
- **Scopes not bound to content.** A ratchet approval binds a file and key, not the old and new values; a suppression
  binds path, line and pattern, not the line's text; a test removal binds the test id. Proposal: values and content
  hashes in these scopes.

## Migration of approval directories (product owners must read this)
1. Leftover `.sig` files stay fail-closed: after U30 every gate that loads a directory with a `.json.sig` reports
   `forged-approval` (`signature-file`).
2. **Before deleting any `.sig`**, run the pre-U30 gate (commit `3ef3e48`) once over each approvals directory, against
   the `allowed_signers` that was in force when the approvals were made, and move out every JSON that it reports as
   unsigned, signature-rejected or orphaned, or that was signed by a key since rotated out. After U30 each of those would
   silently become an approval in force.
3. Only then delete the `.sig` files.
4. After U30 every approval in the directory is counted in every verdict, and anyone who can write the directory can
   loosen any gate: keep it where only the orchestrator writes.
5. A branch that rotates keys by editing `gate/allowed_signers` conflicts with U30 and is moot after it.

## The ledger (T132; a library, not wired into any gate)
`gate/rigor_lib/ledger.py` keeps an append-only, hash-chained directory of `NNNNNN.jsonl` entries (`claim`,
`revocation`, `ratchet`, `gate-change`, `tighten-only-on`, `tighten-only-off`; canonical JSON with `seq`, `prev`,
`kind`, `subject`, `evidence`, `at`). `rigor ledger verify [--head SHA]` exits 0 only for an intact chain that contains
the head. A claim's subject is `<approval kind>:<scope>:<sha256 of the approval file>`; a `revocation` names a standing
claim. With `--ledger DIR`, an approval whose claim entry comes after a `tighten-only-on` entry does not count
(`forged-approval`, reason `tighten-only`). The debt cap (`over_cap`, `DEFAULT_CAP_PPM` = 2% of a module's mutants, one
claim below 50 mutants) is a library function. Not built: a gate passing `--ledger`, the ledger head in the verdict,
the refuter, automatic tighten-only events.
