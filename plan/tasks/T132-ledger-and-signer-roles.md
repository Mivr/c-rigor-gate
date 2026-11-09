# T132: signer roles, the claim ledger, debt cap and tighten-only switch as a library (P003 W3b part 1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T132` from main. Read P003 §10 in full, then `docs/gate.md` ("Approvals",
`approve`), `gate/rigor_lib/approvals.py`, `approve.py`, `approval_args.py`, `verdict_inputs.py`, `jsonio.py`,
`gate/allowed_signers`, and the canaries `approval-in-repo` and `ancestor-suppression`.

## Why
The system has no human in the loop. Today one key, `orchestrator`, may sign every kind of approval, and the same
agent requests, signs and merges. P003 §10 replaces that with: a check where one exists; otherwise a **claim** signed
by a separate identity, limited by kind and by a debt cap, open to revocation, and recorded in an append-only ledger
that every verdict will bind. This task builds those mechanisms as a library with a command-line surface. It changes
no behaviour of any existing gate: the roles file it adds reproduces what is allowed today.

## Do
1. **Signer roles.** A gate-owned file `gate/signer_roles.toml`: `[principal.<name>] kinds = ["equivalent-mutant", ...]`.
   An approval counts only if its signer's principal (as `ssh-keygen -Y find-principals` reports it) is listed with
   that kind; otherwise it is a `forged-approval` finding with reason `kind-not-allowed-for-signer`. A principal in
   `allowed_signers` that the roles file does not list may sign nothing. Ship the file with `orchestrator` holding
   exactly the kinds that exist today, so nothing changes yet; a unit test proves that removing a kind from a
   principal turns its approvals of that kind into `forged-approval`.
2. **Ledger** (`gate/rigor_lib/ledger.py`, stdlib only). A directory of JSONL files forming one hash chain: each entry
   is canonical JSON with `seq` (dense, from 1), `prev` (sha256 of the previous entry's bytes; 64 zeros for the
   first), `kind` (`claim`, `revocation`, `ratchet`, `gate-change`, `tighten-only-on`, `tighten-only-off`), `subject`
   (a string that identifies what it is about), `evidence` (sha256 of the evidence bytes, or empty) and `at` (UTC
   seconds, supplied by the caller: the library never reads a clock). Functions and subcommands:
   - `rigor ledger append --ledger DIR --kind K --subject S [--evidence FILE] --at N`: appends one entry; refuses if
     the existing chain does not verify;
   - `rigor ledger verify --ledger DIR [--head SHA]`: exit 0 only if the chain is intact (no edit, gap, reorder,
     duplicate `seq`, stray file, or truncation relative to `--head`); prints the head sha256;
   - `head(ledger)`: the value a verdict will bind (wiring is a later task).
3. **Claims.** A claim's `subject` is `<approval kind>:<scope>:<sha256 of the approval file>`. A `revocation` names the
   same subject and carries the sha256 of the refuting evidence. `standing_claims(ledger)` returns the claims not
   revoked. `rigor ledger claims --ledger DIR` lists them, sorted.
4. **Debt cap.** `debt(standing, module_mutants)` and `over_cap(count, mutants, cap_ppm)` for `equivalent-mutant`
   claims per module: the cap is a fraction of the module's mutants, given in parts per million with the default
   20000 (2%) in one named constant; a module with fewer than 50 mutants may hold one. Pure functions with tests; no
   gate reads them yet.
5. **Tighten-only.** `tighten_only(ledger)` is true after a `tighten-only-on` entry until a later `tighten-only-off`.
   `approvals` gets one optional argument, a ledger directory: when the switch is on, an approval whose claim entry
   comes after the `tighten-only-on` entry does not count (finding `forged-approval`, reason `tighten-only`). With no
   ledger argument nothing changes.
6. **Tests.** Unit tests for every refusal of `verify` (each tamper kind), append-after-tamper, claims and
   revocations, the cap arithmetic at its boundaries, the roles rule and the tighten-only rule. A fixture ledger with
   a known head sha256.
7. **Docs.** `docs/trust.md`: the model of P003 §10 as built here, what is library only, and what the later tasks
   wire (arbiter identity, refuter, verdict binding, the previous-gate rule). `docs/gate.md`: the roles file.

## Not in this task
Removing any kind from `orchestrator`, creating keys or identities, `gate/rigor_lib/grade*.py`, `gate/order.txt`,
`verdict_inputs.py` (no binding yet), `products/**`, canaries (nothing is wired, so no grade can turn red on it).

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/grade.sh`; `selftest/canaries.sh --jobs 8`;
`python3 -I tools/affected.py --check`. Every existing approval fixture must verify exactly as before.

## Allowed paths
`gate/rigor_lib/ledger.py`, `gate/rigor_lib/approvals.py`, `gate/rigor_lib/approve.py`,
`gate/rigor_lib/approval_args.py`, `gate/rigor_lib/cli.py` (registering the subcommand only), `gate/signer_roles.toml`,
`gate/tests/**`, `docs/trust.md`, `docs/gate.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T132`. `TMPDIR=/var/tmp/cache/T132/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Test keys are generated inside your cache directory with `ssh-keygen`, as the existing approval tests do;
never look for a real key. If you need a throwaway script, write it with the Write tool or a heredoc so its text is
in your transcript. Commit on `task/T132`; your last message is the report (what works, what does not, every
deviation).
