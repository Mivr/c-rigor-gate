# U30: remove signing from the gate (owner decision, 2026-11-16)

Repo `Mivr/c-rigor-gate`, branch `task/U30`. Owner decision, verbatim: "Lets remove the signing at all, the whole idea
is that agents can scale and work on this at large scale on their own." This task removes every use of a signature and
of `ssh-keygen` from the gate and replaces what the signature protected by deterministic, content-bound checks an
agent fleet can run without a key holder.

Read first: `AGENTS.md`, `CLAUDE.md`; `docs/gate.md`, `docs/grade.md` ("Verdict determinism and bound inputs",
"`rigor verify`", "The witness gates", "Mutation testing"), `docs/toolchain.md` ("Local execution": "no `ssh-keygen`
means the signing tests cannot run"); `gate/rigor_lib/approvals.py`, `grade.py`, `grade_context.py`, everything that
imports them; `canaries/runner.py`; `selftest/grade.sh`, `selftest/mutate.sh`; `gate/tests/helpers.py` and the tests
that create keys; `plan/tasks/T132-ledger-and-signer-roles.md`, `T140-trust-wiring-roles-and-ledger.md` (what the
signer roles and the ledger were for); `plan/P004-visual-gate.md` 8.5 (sealed artefacts) and
`docs/ui-contract.md`, `docs/ui-explore.md`, `docs/ui-deviations.md` where they say "sealed", "unsigned", "signature".

## What signing did, and what replaces it
1. **The grade verdict was signed** so a merge bot could trust it. Replacement: the verdict is content-bound only. It
   already binds its inputs by sha256 (tree, gate revision, toolchain, bundles); `rigor verify` recomputes every
   binding and the verdict's own canonical sha256 and re-checks the gate list, and accepts no verdict whose bindings
   do not match the tree it is asked about. No key, no signature field. Say in `docs/grade.md` exactly what `verify`
   now proves (the verdict is consistent with this tree and this gate revision) and what it no longer proves (who ran
   it): a verdict is trusted because anyone can re-run the grade, not because of who signed it.
2. **Approvals / loosenings were signed by the owner** (surviving mutants, exceptions, baselines that go up, sealed
   contract changes). Replacement: an approval is a checked-in, schema-checked record with a reason, the exact
   target it covers (the same content binding as today: mutant id, module sha, finding id, file sha), and an expiry
   where the schema has one. No signer. The guard that stays, and must be at least as strict as today in every
   respect except the signature: an approval covers exactly its bound target and nothing else; a stale or unused
   approval is reported as today; every approval in force is COUNTED and listed in the verdict (the "debt" a reader
   sees), and the ratchets that only go down stay ratchets (a change that raises a baseline or adds an approval is
   visible in the verdict's summary as a loosening of N items, never silent).
3. **Sealed files** (UI contract, event catalogue, deviation baselines) were to be owner-signed. Replacement: they are
   ordinary reviewed files; the words "sealed", "owner-signed", "unsigned", "DRAFT … unsigned" are replaced by what is
   now true (a contract file: changes to it are loosenings or tightenings the verdict counts). Do not change any
   VALUE in a contract file; only header comments that talk about signatures. Pending entries stay pending.
4. **Roles text**: `AGENTS.md` / `CLAUDE.md` say the owner "holds the signing key for loosening any gate". Replace
   with the new rule: nobody signs; loosening a gate (an approval, a raised baseline, a relaxed threshold, an
   exception) is allowed only inside a task whose contract names it, is recorded with its reason, and is counted in
   the verdict. "Never weaken a check" stays exactly as it is for everything else.

## Do
- Remove the signature fields, key handling, signer roles and every `ssh-keygen` call from gate code, canaries,
  selftests and tests; keep every non-signature check those code paths made (schema, binding, expiry, uniqueness,
  staleness, counting). Where a test asserted "a forged signature is rejected", the replacement test asserts the
  corresponding content rule ("a verdict whose binding does not match is rejected", "an approval bound to another
  target covers nothing").
- A verdict written by the old gate (with a signature field) is rejected by the new `verify` with a clear message,
  or accepted ignoring the field: pick one, say which, test it.
- The 149 tests that could not run on a host without `ssh-keygen` must now run and pass anywhere. After this task
  `python3 -I -B gate/tests/run_parallel.py` has NO `ssh-keygen` error on this host; the only allowed failure left is
  `tests.test_job…test_the_deadline_kills_the_whole_process_group` (a host issue; do not touch it).
- `selftest/grade.sh` and `selftest/mutate.sh`: no key generation; every red case that was about signatures is
  replaced by its content-bound equivalent or removed with a line in the report saying which and why. They need the
  farm or local execution to run; run what this host can run (see below) and say exactly what you could not run.
- Docs: `docs/gate.md`, `docs/grade.md`, `docs/toolchain.md`, the UI docs, P-plans are history (do not rewrite plans;
  add one line at the top of `plan/P004-visual-gate.md` 8.5 pointing to this decision).
- A short `docs/trust.md`: the trust model after this change in one page — what the gate guarantees mechanically,
  what counts as a loosening and where it shows, what an agent may and may not do, what a reader of a verdict should
  check.

## Paths
Anything under `gate/`, `canaries/`, `selftest/`, `docs/`, `tools/`, `AGENTS.md`, `CLAUDE.md`, header comments of
files under `products/**` (no values), `plan/P004-visual-gate.md` (the one pointer line). Not `rules/`,
`toolchains/`, `ui/`, product values, thresholds, baselines, expected-test lists, canary expectations other than the
signature ones.

## Rules
This task removes one mechanism on the owner's order; it is not licence to loosen anything else. Every other check,
threshold, baseline, tripwire and expected list stays byte-identical. Python stdlib only. Files <= 500 lines,
functions <= 50 lines. If removing the signature from some path would silently remove another guarantee (for example
an approval file that was only trustworthy because it was signed and has no content binding), STOP on that path and
report it with a proposal instead of removing it.

## Acceptance (the orchestrator re-runs)
- `python3 -I -B gate/tests/run_parallel.py`: zero errors; the single allowed failure named above.
- `grep -rn "ssh-keygen\|ssh_keygen" gate canaries selftest tools rules toolchains` prints nothing.
- `bash selftest/ui.sh` twice (unchanged behaviour), `python3 -I tools/affected.py --check`.
- `selftest/grade.sh` and the other selftests this host can run under local execution (`.buckconfig.local`,
  `tools/buck2.local` are already in the worktree; never commit them): run them, report exit codes and what each
  could not do here and why.

## Report
What was removed, what replaced it, every test that changed meaning (old assertion -> new assertion), every guarantee
that is weaker than before (there must be an explicit list, even if it is only "who ran the grade"), what you could
not run. Never kill a process by name. Scratch under `/var/tmp/cache/U30/`.
