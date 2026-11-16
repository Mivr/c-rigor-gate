# U03: `ui/model/model.h`, the probe main, the `c_ui_probe` macro and its symbols rule (P004 T1xx.03)

Repo `Mivr/c-rigor-gate`, branch `task/U03`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §4.1, §4.2, §6.2,
§6.3; `rules/sim.bzl`, `docs/sim.md` and `selftest/sim/toy` (the existing `c_sim` pattern this mirrors);
`rules/c.bzl`, `rules/facts.bzl`, `docs/product-checks.md` (symbols policy), `gate/rigor_lib/facts_symbols.py`.

## Why
The explorer drives a product through one small trusted interface. The interface, the binary that speaks it and the
rule that keeps its symbols out of shipped code are gate-owned so that a product cannot weaken the observation.

## Do
1. `ui/model/model.h`: the `uim_*` interface of P004 §4.2 that a product implements (`uim_open`, `uim_env_inputs`,
   `uim_apply`, `uim_next_due`, `uim_advance`, `uim_frame`, `uim_semantic`, `uim_patches`, `uim_domain_count`,
   `uim_domain_at`, `uim_trace`), with gate-owned types only, static storage, and the contract of each call written
   in the header (determinism, what "stable scene" means, 16 ms frame stepping that stops exactly at every deadline,
   failure returns).
2. `ui/model/probe_main.c`: the gate-owned `main` of a probe binary. It reads commands on stdin and writes one reply
   per command on stdout, line oriented, strict (an unknown or malformed command is an error reply and a non-zero
   exit at EOF). Commands cover every `uim_*` call plus `quit`. Protocol versioned (`ui-probe/1` greeting) and
   documented in `docs/ui-model.md`. It does not call `lvprobe` yet (U05 joins them); leave one documented seam.
3. `rules/ui.bzl`: `c_ui_probe(name, model, ...)` builds the probe binary from a product `c_library` that implements
   `model.h`, in the modes the gate grades (release and san).
4. Symbols rule: `uim_*` symbols may be referenced or defined only by targets built through `c_ui_probe` (the model
   library and the probe). Any other product target that references one gets the existing `symbol-not-allowed`
   finding. Follow how `c_sim` confines its symbols.
5. `selftest/ui_product/`: a toy LVGL app (one screen, one button, one timed notice) with a model adapter, and
   `selftest/ui.sh` that builds its probe and drives a scripted session, comparing stdout with a checked-in
   transcript; plus a second toy library that calls a `uim_*` symbol from ordinary product code and must be flagged.

## Not in this task
`lvprobe` (U02); the Python driver (U05); judges; wiring into `rigor grade` (U14).

## Acceptance
`selftest/ui.sh` green twice in a row (release and san probe build; the scripted session byte-identical to the
transcript both times; the bad library produces `symbol-not-allowed` and the good one does not);
`python3 -I -B gate/tests/run_parallel.py`; `python3 -I tools/affected.py --check`.

## Allowed paths
`ui/model/**`, `rules/ui.bzl`, `rules/BUCK` (export the new file only), `selftest/ui.sh`, `selftest/ui_product/**`,
`docs/ui-model.md`, `tools/affected.toml` (rules for the new paths only), `gate/rigor_lib/facts_symbols.py` and its
test only if the confinement cannot be expressed with the existing policy (explain), `gate/tests/test_ui_*.py`.
