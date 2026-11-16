# U14: the UI gates in `rigor grade`, and a development grade that runs under local execution

Repo `Mivr/c-rigor-gate`, branch `task/U14` (from the integration branch after U30, signing removed). Read first:
`AGENTS.md`; `docs/grade.md` in full (the gate list, grade tiers, the grading tree, verdict determinism and bound
inputs, `rigor verify`, the sealed environment), `docs/trust.md`, `docs/gate.md`, `docs/toolchain.md` ("Local
execution"); `gate/order.txt`; `gate/rigor_lib/grade*.py`, `verdict_verify.py`; `plan/P004-visual-gate.md` 6.1
(gates, tiers, budgets), 6.3; `docs/ui-explore.md` (the CLI, exit codes, cost, budget), `docs/ui-judges*.md`,
`docs/product-checks.md` (`c_ui_probe`, `c_ui_probe_session`); `rules/ui.bzl`; `products/business-apps/` (product
configuration; `ui/` holds the contract, catalogue and class paths); `selftest/grade.sh`, `selftest/ui*.sh`.

## Why
The UI gate exists as `rigor ui-explore` with four judges, and a product's probe sessions are `buck2 test` targets,
but nothing in `rigor grade` runs any of it: a merge is graded without the UI gate. And `rigor grade` cannot run at
all on a development host without the farm client (its grading tree looks for the farm's Buck2 path), so nothing
about grading can be tried before the farm.

## Do
### A. A development grade under local execution
1. `rigor grade` honours the owner-sanctioned local-execution switches (`.buckconfig.local` `[gate] local_exec`,
   `tools/buck2.local`, the mirror entries) when, and only when, a new explicit flag `--dev-local` is given: the
   grading tree then gets the same three switches the checkout has. The verdict of such a grade carries
   `dev_local: true` inside the hashed core, prints `DEVELOPMENT GRADE (local execution): not a merge verdict`, and
   `rigor verify` REJECTS it by name. Without the flag nothing changes (byte-identical verdicts; prove it on a unit
   level since the farm is not reachable). Tests for the flag, the mark and the rejection.
2. Say in `docs/grade.md` and `docs/trust.md` what a development grade is for and that it is never evidence.
3. With it, run `selftest/grade.sh` here as far as it goes and report which steps pass, and which fail for a host
   reason (name it: e.g. the remote action cache assumptions of the WARM steps, IPv6, the stack-frame differences of
   the local toolchain); do not edit an expectation to make a host-specific failure pass.

### B. The UI gates as grade steps
1. New gates in `gate/order.txt`, after the build and test gates and before the mutation gates (say exactly where and
   why): `ui-probe-sessions` (every `kind(ui_probe_session_run, //...)` target of the tree ran and passed in release
   and san: the build/test gates' `result_targets` must already collect them — make them do so and fail when a
   `c_ui_probe` exists without any session target) and `ui-explore` (the explorer with the judges).
2. `ui-explore` step: for each app the product declares in a new product file `products/<product>/ui/gate.toml`
   (per app: the `c_ui_probe` target, contract, catalogue, the class paths file, per tier the strategies with their
   bounds and budgets, the judges, `--today` taken from the grade's own pinned date input, never the wall clock):
   build the probe in the grading tree, run the declared strategies, collect findings. The step's result follows the
   gate's result shape (findings with ids, severity, digests) so the verdict's determinism rules hold: findings sorted,
   digests stable, run-twice already inside the explorer. Exit mapping: explorer exit 1 -> gate FAIL with its error
   findings; exit 2 -> gate ERROR (the gate could not decide), never PASS.
3. Tiers (P004 6.1; `docs/grade.md` "Grade tiers"): merge = replay of the class paths + a bounded bfs with a budget
   that fits the merge budget (declare it; the measured kiosk numbers are in `docs/ui-lockers-first-run.md`);
   nightly = longer bfs + walks. A product without `ui/gate.toml` has no UI gate (the step is SKIP with a reason, as
   other optional gates do) — but a product that has a `c_ui_probe` target and no `ui/gate.toml` FAILS the step.
4. Bound inputs: the contract, catalogue, class paths and `gate.toml` shas, the probe binary's sha, and the
   explorer's summary digest are verdict inputs; `rigor verify` recomputes the file shas from the gate commit like the
   other product configuration.
5. Exceptions and pending entries: a `contract-pending` / `contract-incomplete` finding is an error like any other
   (the gate FAILS until the product's contract is complete or the finding is covered by an approval of a new kind
   `ui-finding`, bound to the finding id and the contract sha, counted in the verdict like every approval). No other
   way to pass with findings.
6. `products/business-apps/ui/gate.toml` for the lockers app (a product configuration file: provenance comments,
   budgets from the measured runs). Expect the lockers UI gate to FAIL today (pending contract questions and open
   product findings): that is the correct result; record the finding counts.
7. Canaries for the new gates (a product whose probe session output differs; a product with a seeded UI defect the
   scene judge reports; a product with a probe and no `gate.toml`), wired into the canary runner's expectations.
8. Docs: `docs/grade.md` (the gate list, the tiers table, the bound inputs table), `docs/ui-explore.md` (how the
   grade runs it), `docs/trust.md` (the new approval kind).

## Paths
`gate/order.txt`, `gate/rigor_lib/grade*.py`, `verdict_verify.py`, `approvals.py` (the new kind only),
`gate/rigor_lib/cli.py`, `gate/rigor_lib/ui_explore*.py` only for a result-shape export the step needs (no behaviour
change), `gate/tests/**`, `canaries/**`, `selftest/grade.sh` (new steps; existing expectations untouched),
`products/business-apps/ui/gate.toml` (new), `products/business-apps/policy.toml` / `expected-tests.json` ONLY if
the new test-kind collection requires entries for the session targets (say exactly what and why; these are counted
configuration changes), `docs/**`, `tools/affected.toml`. Not `rules/`, `ui/`, `toolchains/` (except: if `--dev-local`
needs the grading tree to copy the switch files, that is in `grade_tree.py`, not in `toolchains/`).

## Acceptance (the orchestrator re-runs)
- `python3 -I -B gate/tests/run_parallel.py`: zero errors, only the known `tests.test_job…` failure.
- `bash selftest/ui.sh` twice; `python3 -I tools/affected.py --check`; sizes (files <= 500 lines, functions <= 50).
- A development grade of the gate's own selftest product and of business-apps
  (`/home/user/business-apps`, read only; `--dev-local`): report the verdict's gate list with each gate's result and
  the UI gates' finding counts; `rigor verify` rejects both verdicts as development grades.

## Report
What changed; real output; which `selftest/grade.sh` steps pass here; the two development grades; every weakened or
new guarantee; deviations; what could not be run. Never kill a process by name. Scratch under `/var/tmp/cache/U14/`.
