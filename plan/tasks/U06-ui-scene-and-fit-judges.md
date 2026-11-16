# U06: the `ui-scene` and `ui-fit` judges (P004 T1xx.06)

Repo `Mivr/c-rigor-gate`, branch `task/U06`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §1.1, §1.3, §2.1,
§3.0, §3.1, §3.2, §3.10, §4.5, §6.4, §16; `docs/ui-explore.md` IN FULL (the judge interface: step, run-level and
exploration-level judges, evidence, findings; you plug into it and do not change the engine); `docs/ui-model.md`
(the semantic record and the frame record types) and `docs/ui-lvprobe.md` ("What the facts mean", "Definitions",
"Text format", "Limits"); `docs/ui-contract.md` and `gate/rigor_lib/ui_contract.py` (thresholds, roles, styles,
required elements, wrap policy, pending values, exceptions); `docs/ui-pseudo.md`; the toy and frame-toy products
under `selftest/ui_product/` and `selftest/ui_frame_product/`.

## Why
The explorer reaches states and records what the scene says and what LVGL drew. Nothing yet says whether a state
is acceptable. These two judges turn the escaped defect classes "a button under an overlay", "a target too small",
"a value split in two", "a required element missing", "text that does not fit or is cut" into findings, from the
scene and the rendered tree, without the oracle.

## Do
Python, stdlib only, `gate/rigor_lib/ui_judge_scene.py` and `ui_judge_fit.py` (split further if a file would pass
500 lines), registered as explorer judges selected by `rigor ui-explore --judges ui-scene,ui-fit --contract <toml>`.
1. **Inputs.** A judge sees, per step, the semantic records (stage O2), the frame records (stage O3: node, label,
   fit, region; ink on request) and the UI contract. Decide and document how a semantic node is associated with a
   rendered node (there is no key in the frame records): the association must be exact and conservative (for
   example by identical text and containment of boxes), an ambiguous or absent association is reported as its own
   finding (`stage-unmatched`, info for now) and never guessed, and every check says which stage it reads.
2. **`ui-scene`** (P004 §3.1), each check with the exact rule of the table and the finding id of §3:
   `occluded-target`, `overlay-policy`, `touch-target-small`, `target-spacing`, `node-out-of-bounds`,
   `text-overlap`, `font-below-min`, `hierarchy-violated`, `value-split`, `required-element-missing`,
   `toggle-group-indistinct`, `raw-text`, `wrap-policy-undeclared`. Probe points P(n) and every threshold come from
   the contract (§3.10); nothing is a constant in the judge. `toggle-group-indistinct` compares two states and is a
   run-level or exploration-level judge.
3. **`ui-fit`** (P004 §3.2): `text-overflow`, `text-clipped`, `full-string-shown`, `font-shrunk` from the rendered
   facts (`fit` records: clipped, drawn, dotted, natural and laid-out sizes, glyph union, missing glyphs,
   unsupported); `phrase-too-long` is a product build check and is out. A label the probe marks `unsupported` or
   whose facts are not exact is `fit-unmeasurable` (error: the judge fails closed on what it cannot measure).
   A label with missing glyphs is `glyph-missing` (error).
4. **Pending and exceptions.** A check that needs a contract value the owner has not decided emits the contract's
   `contract-pending` finding once per run (not per node) and skips only that check; it never uses a default. A
   contract `exception` suppresses exactly the finding it names (rule id and target), is reported as info with its
   expiry, and an exception that matched nothing is `exception-unused` (error).
5. **Honesty table.** `docs/ui-judges.md` lists every check of §3.1 and §3.2 with: implemented / needs a contract
   value that is pending (which question) / blocked (what observation is missing and which task would add it). A
   check you cannot implement soundly from the observations that exist is listed as blocked with the reason; do not
   approximate it.
6. **Canaries.** A canary product `selftest/ui_canary_product/` (an LVGL toy with a model adapter, built through
   `c_ui_probe`) with one input per check that puts the app into a state with exactly that defect, plus a clean
   state; its event catalogue and a contract for it. `selftest/ui_judges.sh` (called from `selftest/ui.sh` by one
   line before the "no probe process left" step) runs the explorer with the judges and asserts, per check, exactly
   one finding of that check with the expected id in the canary state and none in the clean state; byte-identical
   findings twice; every finding replays.
7. **The historic defects.** In `docs/ui-judges.md`, map F2, F3, F5, F6, F8, F9, F10, F11 and X2 (P004 §1.1) to the
   check(s) of these two judges that would catch them, and say for each whether your canary reproduces that
   defect's mechanism.

## Not in this task
The engine, the probe or lvprobe (if an observation is missing, say so in the honesty table); `ui-render`,
`ui-input`, `ui-time`, `ui-parity`, `ui-meta` judges; the lockers contract's pending values; wiring into
`rigor grade`.

## Acceptance
`selftest/ui.sh` (with `ui_judges.sh`) green twice in a row; `python3 -I -B gate/tests/run_parallel.py` at the host
baseline with new `gate/tests/test_ui_judge_*.py` unit tests over hand-built observations for every check (the
positive case, the nearest negative case on each side of every threshold, the pending case, the exception case);
`python3 -I tools/affected.py --check`. Each check seen failing once against a deliberately broken judge (say how).
No stub or probe process left; never kill by name.

## Allowed paths
`gate/rigor_lib/ui_judge_*.py`, `gate/rigor_lib/ui_explore.py` and `ui_explore_judges.py` only to register the new
judges and the `--judges`/`--contract` arguments (no other engine change; if the interface lacks something, report
it), `gate/tests/test_ui_judge_*.py`, `gate/tests/data/ui_judge/**`, `selftest/ui.sh` (the one line),
`selftest/ui_judges.sh`, `selftest/ui_canary_product/**`, `docs/ui-judges.md`, `tools/affected.toml` (new paths
only), `gate/rigor_lib/ui_contract.py` only to extend the closed list of exception rule ids with the new finding
ids (and its test).
