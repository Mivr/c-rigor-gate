# Trust without a human in the loop (P003 section 10, as built by T132)

No human approves anything. P003 section 10 replaces "one trusted signer" with: a check where a program can decide;
otherwise a **claim** signed by a separate identity, limited by kind and by a debt cap, open to refutation, and
recorded in an append-only ledger that every verdict will bind. T132 builds the mechanisms as a **library with a
command-line surface**. No existing gate calls them: nothing changes in any grade.

## Built (library, tested, not wired)

### Signer roles
`gate/signer_roles.toml` (`[principal.<name>] kinds = [...]`), read by `approvals.load_roles`. With the roles file
given to `load_approvals` (`--signer-roles`), an approval counts only if the signer's principal is listed with its
kind, else `forged-approval` / `kind-not-allowed-for-signer`. A principal not listed signs nothing. The shipped file
gives `orchestrator` every kind that exists today. Details: `docs/gate.md`.

### The ledger (`gate/rigor_lib/ledger.py`)
A directory of `NNNNNN.jsonl` files (at most 1000 entries each) forming one hash chain. An entry is canonical JSON:
`seq` (dense from 1), `prev` (sha256 of the previous entry's bytes; 64 zeros first), `kind` (`claim`, `revocation`,
`ratchet`, `gate-change`, `tighten-only-on`, `tighten-only-off`), `subject`, `evidence` (sha256 or empty) and `at`
(UTC seconds from the caller; the library never reads a clock). The **head** is the sha256 of the last entry's bytes.

`rigor ledger verify` exits 0 only if there is no edited, non-canonical, reordered, duplicated or missing entry, no
stray or missing file, no empty file and no entry without its newline. With `--head SHA` the chain must also contain
that head: a longer chain is growth, a chain without it is truncation or a rewrite. `rigor ledger append` verifies
first and refuses on a broken chain. The last entry has no successor, so editing only it is caught by the head a
verdict binds, not by the chain alone.

### Claims
Subject `<approval kind>:<scope>:<sha256 of the approval file>` (the scope may contain colons). A `revocation` has
the same subject and the sha256 of the refuting evidence; it must name a standing claim. `standing_claims` lists the
claims not revoked (a later claim of a revoked subject stands again); `rigor ledger claims` prints them sorted.

### Debt cap
`debt(standing, module_mutants)` counts standing `equivalent-mutant` claims per module (`module_mutants` maps a module
to its mutant ids; an approval's scope is a mutant id). `over_cap(count, mutants, cap_ppm)` holds when
`count > mutants * cap_ppm // 10^6`; a module with fewer than 50 mutants may hold one. `DEFAULT_CAP_PPM = 20000` (2%).

### Tighten-only
`tighten_only(ledger)` is true from a `tighten-only-on` entry to the next `tighten-only-off`. With `--ledger DIR`
(`load_approvals(..., ledger=DIR)`) an approval whose claim entry comes after the `tighten-only-on` entry is a
`forged-approval` with reason `tighten-only`. An approval with **no** claim entry is not affected by this rule: the
rule is defined on claim order. Making every approval need a claim is part of the verdict binding below.

## Not built (later tasks)
- The **arbiter** identity and its key as the only one in `allowed_signers`; removing kinds from `orchestrator`.
- The **refuter** (nightly, runs a refutation test and appends a `revocation`).
- **Verdict binding:** `core.inputs` carries the ledger head; `rigor verify` rejects a rewritten history. The gates
  passing `--signer-roles` and `--ledger`, and reading the debt cap.
- Automatic entry of the three tighten-only events (tripwire green, canary passes, more than five revocations a week).
- The **previous-gate rule** (section 10.3), ratchet and gate-change entries written by the tools, the weekly digest.
- The identities still share a uid and a host, so separation is detective (P003 10.6).
