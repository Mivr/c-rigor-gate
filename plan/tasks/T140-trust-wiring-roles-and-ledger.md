# T140: signer roles enforced and the ledger bound into every verdict (P003 §10, W3b part 2)

Repo: `Mivr/c-rigor-gate`. Branch `task/T140` from main. Read P003 §10 in full, `docs/trust.md`, `docs/gate.md`
("Approvals"), `gate/rigor_lib/approvals.py`, `approval_args.py`, `ledger.py`, `grade.py` and every `grade_*.py` that
loads approvals, `verdict_inputs.py`, `gate/signer_roles.toml`, `gate/allowed_signers`, the approval canaries
(`approval-in-repo`, `ancestor-suppression`, and any that sign an approval), `docs/canaries.md`.

## Why
T132 built signer roles, a claim ledger, a debt cap and a tighten-only switch as an opt-in library: no gate passes a
roles file or a ledger, so one key may still sign every kind and nothing is recorded. There is no human in the loop
(P003 §10), so the mechanisms have to be what the gate actually enforces. This task wires the mechanical part. It does
not create identities or keys and does not change who holds which key: the roles file keeps giving `orchestrator`
today's kinds.

## Do
1. **Roles are always enforced.** Every gate and subcommand that loads approvals uses the gate's own
   `gate/signer_roles.toml` (the sealed checkout's file, never a product's and never an argument a product controls).
   An approval whose signer is not listed for its kind is `forged-approval`, reason `kind-not-allowed-for-signer`.
   Bind the sha256 of the roles file and of `allowed_signers` into `core.inputs`. Existing tests and canaries that
   sign as some other principal get a roles file through the test seam the code already has for `allowed_signers`;
   say how you kept that seam from being reachable by a product.
2. **A ledger is part of the grade.** `rigor grade --ledger DIR` (gate-owned input, snapshotted like the approvals
   bundle): the chain must verify, its head is bound into `core.inputs`, and `rigor verify` prints it. With a ledger:
   - every approval that counts must have a standing `claim` entry for exactly that approval (kind, scope, sha256 of
     the approval file); an approval without one is `forged-approval`, reason `no-claim` (this closes the gap T132
     reported: an unrecorded approval slipped past tighten-only);
   - a revoked claim's approval does not count (`forged-approval`, reason `claim-revoked`);
   - while tighten-only is on, a claim entered after the switch does not count (`tighten-only`, as T132 built).
   Without `--ledger` the grade behaves as today and the verdict says the ledger is absent (an explicit input value,
   so a ledger-less PASS cannot be passed off as a ledgered one). Add `rigor verify --require-ledger`.
3. **Debt cap in the mutants gate.** With a ledger, the unproved `equivalent-mutant` claims of a module are counted
   against T132's cap (2% of the module's mutants; one for a module under 50): over the cap is the error
   `equivalent-debt-over-cap` (module, claims, cap). Without a ledger nothing changes.
4. **`rigor approve` writes the claim.** With `--ledger DIR --at N` it appends the claim entry for the approval it
   signs, atomically with writing the approval; without them it behaves as today.
5. **Canaries** (follow `docs/canaries.md`): `approval-wrong-kind` (a validly signed approval by a principal not
   listed for that kind), `approval-without-claim`, `approval-claim-revoked`, `approval-after-tighten-only`,
   `ledger-edited` (one byte of a middle entry changed: the grade must refuse), `equivalent-debt-over-cap`. The control
   stays green, with and without a ledger.
6. **Docs.** `docs/trust.md` (what is enforced now, what is still not: there is one signer, the orchestrator; the
   arbiter and the refuter of P003 §10.2 do not exist yet), `docs/gate.md`, `docs/grade.md` (the inputs),
   `gate/signer_roles.toml` (fix its comment: no human owns this file; a change to it is a gate change).

## Not in this task
Creating keys or principals; removing a kind from `orchestrator`; the arbiter and refuter agents; the rule that the
previous gate grades the next; `products/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/grade.sh`; `selftest/canaries.sh --jobs 8` and
`selftest/canaries.sh --jobs 8 --tier merge`; `selftest/tripwires.sh --jobs 5`; `selftest/mutate.sh`;
`python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/approvals.py`, `gate/rigor_lib/approve.py`, `gate/rigor_lib/approval_args.py`,
`gate/rigor_lib/ledger.py`, `gate/rigor_lib/grade*.py`, `gate/rigor_lib/mutants_gate.py`,
`gate/rigor_lib/verdict*.py`, the other callers of `load_approvals`, `gate/signer_roles.toml`, `gate/tests/**`,
`canaries/**`, `tripwires/**` (expectations only), `selftest/grade.sh`, `selftest/canaries.sh`, `docs/trust.md`,
`docs/gate.md`, `docs/grade.md`, `docs/canaries.md`, `docs/mutate.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T140`. `TMPDIR=/var/tmp/cache/T140/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Test keys are generated inside your cache directory or the test's scratch directory with `ssh-keygen`, as
the existing approval tests do; never look for a real key. If you need a throwaway script, write the whole file with
the Write tool or a heredoc so its text is in your transcript. `rigor grade` and the canary runner refuse a dirty
checkout: commit before you run them. Commit on `task/T140`; your last message is the report (what works, what does
not, every deviation).
