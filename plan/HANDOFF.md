# Orchestrator handoff (2026-11-10)

This file lets a new orchestrator session continue the gate v2 work (P003) with no memory of the previous session, on
any machine or account. Read in this order: this file, `AGENTS.md`, `plan/P003-gate-v2.md` (start with §13.1 and §15),
then the orchestrator-only notes on the build host (§8). The handoff of 2026-11-09 is in this file's git history.

## 1. State

- `main` was `49ec260` before the commit that adds this file. The checkout on the build host is clean. No lane is
  running. Nothing is waiting to be merged.
- **Merged under P003, thirteen tasks:** T127, T126, T128, T132, T130, T129, T125, T131, T135, T136, T133, T137, T138.
- **Enforced in every `rigor grade` now:** the `fuzz` gate (T126, T129, T135); the gates `tests-msan` and `tests-tsan`
  with the thread-declaration rules in `symbols` and the msan and tsan facts in `mode-divergence` (T125, T138); anchored
  gate and third-party path markers with the canary `vendor-path-spoof` (T131, T133); perf counts with a bound derived
  from 200 runs (T130, T136); `--tier merge|nightly` with the tier bound into the verdict (T137).
- **Merged but enforced by nothing:** profiles and floors (`rigor policy-check`, T127); guards (`gate//rt:require`,
  `CHECK_TRAPS`, guard facts, `rigor guards`; T128, T131); signer roles, ledger, debt cap and tighten-only switch (T132).
  The `orchestrator` key still signs every approval kind.
- **Cancelled by measurement:** the schema mutation engine (P003 §5.6, W2). The prototype and its numbers are on the
  branch `park/T124-schema-engine` (on origin; never merge it). The numbers are also in
  `plan/metrics/schema-engine-proto-2026-11.md`.
- **No product has been regraded under the new gates.** `business-apps` pins gate commit `78d1fc3`. Expect findings
  when it bumps: lockers has four threads and eight hand-written parsers, with no fuzz target and no `threads = True`.
- The full table per work package is P003 §13.1. The owner's decisions are P003 §15.

## 2. Why the work stopped

Both lanes launched on 2026-11-10 (T139, T140) ended after a few read-only turns with:
`You've hit your weekly limit · resets Nov 13, 7pm (Europe/Sofia)`. That limit belongs to the account the headless
agents were logged in with. Neither lane changed a file. A different account lifts the block at once; nothing else is
needed. Contributors are Sonnet unless the owner says otherwise (business-apps D9).

## 3. Restart

All gate work runs inside the sandbox container on the build host:

    ssh sb-ws 'docker exec -i -u ubuntu -e HOME=/var/tmp orca-sandbox-761d243e bash -l'

Send a script on stdin (a heredoc). Use `ssh -n` for any ssh inside such a script, or it eats the rest of the script.

1. Check the ground: in `/var/tmp/src/c-rigor-gate` run `git status --porcelain` (must be empty), `git worktree list`,
   and `/var/tmp/cache/orch2/st.sh` (lane status). A second orchestrator session works on `business-apps` from the same
   host; the limit of five lanes in `lane.sh` is shared with it.
2. Relaunch the two paused tasks. Their specs are on main, their worktrees are at main with no changes, and their
   prompt files exist:

       /var/tmp/cache/orch2/lane.sh T139 /var/tmp/wt/c-rigor-gate/T139 /var/tmp/cache/orch2/lanes/T139.prompt
       /var/tmp/cache/orch2/lane.sh T140 /var/tmp/wt/c-rigor-gate/T140 /var/tmp/cache/orch2/lanes/T140.prompt

   They may run together. Both may edit `tools/affected.toml` and add files under `gate/tests/`; on a conflict keep
   both sides.
3. While they run, write the next spec (§4). A spec is committed to main and pushed before its lane starts.

## 4. Queue, in this order

Each of the first three adds gates or changes expectations in every canary, so they go one at a time.

1. **T139** hardened release profile: measure, adopt only if the declared `c_perf` targets move under 3% (D5).
2. **T140** trust wiring: signer roles enforced, ledger bound into verdicts, claims required, debt cap, six canaries.
3. **Policy-floor gate** (not specified yet): `policy-check` as a gate, staged per product (`report`, then `enforce`).
   Known details: `--structure` must be mandatory in the gate (the parser floor needs it), missing facts must fail.
4. **Guards, second half** (not specified): a declared guard is exempt from mutation only if its condition is still
   mutated and a `CHECK_TRAPS` test or the coverage build shows the guard executed; the guard budget.
5. **Arbiter and refuter identities, the previous-gate rule** (P003 §10.2, §10.3), then remove kinds from the
   `orchestrator` role in `gate/signer_roles.toml`.
6. **`c_proof`** (CBMC, P003 §7.3) for the `safety` profile. It needs a release pinned by sha256: ask the owner before
   downloading anything to compute it.
7. **Simulation and oracle replay** (W8), **UI fit, limits, allocation trap** (W9), **sandbox** (W11).
8. **Nightly grader with a read-only cache** (G21): a farm change the owner makes; the gate side is the tier flag.
9. **Product side** (`business-apps`; that repo's own orchestrator session owns its lanes): gate bump, `threads = True`
   on the threaded tests, fuzz harnesses and corpora for the eight parsers, profiles in the policy, a `c_sim` target,
   deletion of the unreachable modules `kv`, `httpredir`, `fsm`, `winpolicy` (D11).

## 5. Procedure for one task

The orchestrator writes specs, validates, reviews and merges. It writes no gate code; a hole found in review goes back
to the lane as a fix-up message.

1. **Spec** `plan/tasks/T<N>-<slug>.md` with the sections Why, Do, Not in this task, Acceptance, Allowed paths, Rules
   (copy the Rules paragraph of T138 and change the number). Commit on main, push.
2. **Worktree and lane:** `git worktree add -q --lock -b task/T<N> /var/tmp/wt/c-rigor-gate/T<N> main`;
   `mkdir -p /var/tmp/cache/T<N>/tmp`; derive the prompt from `lanes/T139.prompt` (replace the task number and the spec
   file name); `lane.sh T<N> <worktree> <prompt>`. A fix-up: write the message to a file, then
   `resume.sh T<N> <worktree> <message file>`.
3. **When the lane ends**, in this order:
   - read the final `result` record of `lanes/T<N>.jsonl` (the report is a claim, not evidence);
   - scope: the files of every non-merge commit on the branch must be inside the allowed paths;
   - trajectory audit: `traj.sh T<N> <worktree> '<allowed globs as a TOML array>'`, and read every block by hand;
   - read the whole diff line by line. Look for: a check that is silently off when an input is missing, a path or name
     matched as a substring, an expectation loosened, a test that cannot fail;
   - trial merge in a validation worktree (`val-main`, `val-b`, `val-c` under `/var/tmp/wt/c-rigor-gate`):
     `git checkout --detach main; git merge --no-ff --no-commit task/T<N>`. **Only if it is clean or resolved and
     committed**, start `tools/validate.sh HEAD` in the background with `TMPDIR=/var/tmp/cache/val-T<N>/tmp`. For a
     change to the grade pipeline also run `selftest/canaries.sh --jobs 8 --tier merge`.
4. **Merge** in `/var/tmp/src/c-rigor-gate` only when `git status --porcelain` is empty and no `MERGE_HEAD` exists:
   `git merge --no-ff task/T<N> -F <message file>`. `-F -` does not work in this setup. The message says what was
   validated and what was not, and records every trajectory block that was accepted and why. Check the merged tree
   equals the validated tree (outside `plan/`), or rerun `python3 -I -B gate/tests/run_parallel.py`. Push, remove the
   worktree, update P003 §13.1.

Cost to plan with: `tools/validate.sh` on a change under `rules/` selects every selftest and takes about one hour.

## 6. What this round taught

- **Measure before building.** Three expectations of the design were wrong and a lane's measurement corrected each:
  the mutation engine (test run time dominates, not relinking), the cause of the perf count drift (twice), and the
  MSan start-up fix (a non-PIE link did not help; the cause was the workers' seccomp profile).
- **Review finds what tests do not.** Two spoofable path markers and a floor rule that switched itself off were found
  by reading the diff, after all selftests had passed.
- **Never start validation in the same command as a merge that may conflict.**
- **A spec's allowed paths are often one file short.** A lane that stops and reports it is behaving correctly; widen
  the paths in a fix-up.
- **Sanitizer modes need the farm.** MSan and TSan start only because the workers' seccomp profile allows
  `personality(ADDR_NO_RANDOMIZE)`. A new worker without it fails `tests-msan` and `tests-tsan` at start-up, not in
  product code. The owner applies such host changes; the orchestrator prepares the files and does not apply them.

## 7. Owner decisions in force

- D1 and D2 of P003 accepted. D8: **no human in the loop**; the system is made by and for agents. Every other decision
  in P003 §15 is a default the orchestrator set, revisable from data.
- The orchestrator does not change security settings on hosts (seccomp, sysctl, keys) even when it has access; it
  hands the owner a script.
- Lead time per task is tracked (`timeline.py`, `plan/metrics/`); make the gate cheaper by structure, never by
  weakening a check.

## 8. What exists only on the build host

None of this is in a repo, by design or because it is scratch. A new session needs it and should not recreate it.

- **Orchestrator-only notes:** `ORCHESTRATOR-NOTES.md` in the orchestrator's config directory under `/var/tmp/.config/`
  (contributors must never read that directory). It holds the key handling, the hidden-witness procedure, and the
  notes of this round on accepted trajectory findings.
- **Helpers:** `/var/tmp/cache/orch2/` (`lane.sh`, `resume.sh`, `st.sh`, `traj.sh`, `rcount.sh`, `timeline.py`); lane
  logs and prompts in `lanes/`; merge messages `merge-T<N>.msg`. A copy of the helpers is kept next to the notes.
- **Seccomp change for the workers:** `~/nl-seccomp-proposal/` in the owner's home on the host (profile, the patch to
  the release renderer, `apply-seccomp.sh`). The live worker release carries the suffix `-seccomp`.
- **The hidden witness repo** has no remote. It is the product orchestrator's.

## 9. Not verified

- The perf rule across CPU models was tested on synthetic records only.
- No nightly-tier grade of a real product has run; the tier flag was tested by selftests and canaries.
- Whether `resume.sh` can continue a session that another account started. T139 and T140 need a fresh launch anyway.
