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
- **`rigor verify` checks bindings, not authorship.** It requires the head, the gate commit, the policy and the product
  directory the caller names (`--expect-head`, `--expect-gate`, `--expect-policy-sha`, `--expect-product-dir`, or
  `--product-dir` for a product directory outside the gate checkout), recomputes `core_sha256`, the gate list, the toolchain pins, the generated
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
  `approval-in-repo`; `rigor grade` and `rigor lane-mutants` refuse an `--approvals` directory inside the product
  repository, the work directory, a `--witness`/`--oracle`/`--perf` bundle or the directory of `--task`.
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
1. `rigor verify --verdict V --expect-head H --expect-gate G --expect-policy-sha P
   (--expect-product-dir products/<name> | --product-dir D) [--expect-task-sha T] [--approvals A] [--require-tier ...]`
   exits 0, and no `not listed in the verdict` line names an approval the reader did not expect to be out of force.
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
- **Grader-chosen inputs.** The grader chooses the task file, the product directory and the approvals directory. The
  product directory is pinned (`--expect-product-dir`, mandatory unless `--product-dir`), its files recomputed from the
  gate commit. `product_dir: null` means the grade read its product files from outside the gate checkout: the product
  configuration is then whatever the verifier supplies with `--product-dir`, checked only against the verdict's own
  shas. The task file is pinned only with `--expect-task-sha`, the approvals directory only with `--approvals`, which
  is one-directional (an approval in the directory that the verdict omits is reported, not rejected). The approvals
  directory is refused only inside the graded side's directories; anyone who can write it can loosen any gate.
- **Untracked files in the gate checkout.** `gate_clean` is computed with untracked files ignored
  (`--untracked-files=no`), so untracked or ignored files in the gate checkout (a planted `__pycache__/*.pyc`, a stray
  module) are not covered by `gate_sha`: a grade run from such a checkout can behave unlike the commit it names.
- **Scopes not bound to content.** A ratchet approval binds a file and key, not the old and new values; a suppression
  binds path, line and pattern, not the line's text; a test removal binds the test id. Proposal: values and content
  hashes in these scopes.

## What is weaker than with signatures
Each item says whether this change, its fix-ups or nothing closes it.
1. **Authorship of a verdict:** open. Nothing proves who ran a grade or that one ran; the self-reported part of `core`
   (gate statuses and findings digests, `gate_clean`, `tier`, `uncached`, `base`, `merge_base`, `sim_seed_digest`) can be
   written by hand. Re-grading and comparing `core_sha256` is the check.
2. **Approved gate revision:** closed by `--expect-gate` (mandatory) and the gate list, toolchain pins and generated
   `.buckconfig` recomputed from that commit. Untracked files in the gate checkout stay open (known gaps).
3. **Grade inputs chosen by the grader:** product directory closed (`--expect-product-dir` or `--product-dir`, files
   recomputed); policy closed (`--expect-policy-sha`, mandatory); task file closed only with `--expect-task-sha`
   (optional); approvals directory closed only with `--approvals` (optional, one-directional); witness, oracle and perf
   bundles closed only with their `--expect-*-sha` (optional). Open otherwise.
4. **Who can write approvals:** open. Anyone who can write the approvals directory can loosen any gate; mitigated by the
   count and list in `core.approvals` and by the refusal of directories on the graded side.
5. **Scopes not bound to content** (ratchet file and key, suppression path, line and pattern, test-removal id): open
   (known gaps, with a proposal).
6. **Migration:** open until each approvals directory is migrated as below; unsigned or revoked JSONs become approvals in
   force once their `.sig` files are deleted.
7. **Loosenings other than approvals** (baselines, thresholds, levels, expected lists, task roles and paths): bound, so a
   change changes the verdict, but not counted: open (known gaps, with a proposal).
8. **UI-contract signatures** (P004 8.5, U18): cancelled. The UI contract files are not bound by any verdict yet: open.
9. **Signer roles** (a per-key limit on approval kinds, T132): a planned feature that was never enforced (off by
   default, no gate passed it); gone.

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
