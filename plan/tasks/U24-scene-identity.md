# U24: scene identity (state class, element ids, message ids) and the three scene checks it unblocks

Repo `Mivr/c-rigor-gate`, branch `task/U24`. Read first: `plan/tasks/U00-ui-gate-rules.md`; `ui/model/model.h` in
full and `docs/ui-model.md` (how `uim_pointer_supported` / `uim_pointer` and the `pointer` capability were added:
required symbols, a capability in the greeting, no weak symbols in product code); `ui/model/probe_*.c`;
`docs/ui-judges.md` ("Honesty table", "Deviations and interface gaps", "The historic defects");
`docs/ui-contract.md` (`[[state_class]]`, `[[element]]`, `[[toggle_group]]`); `plan/P004-visual-gate.md` 3.1 (the
rules of `value-split`, `required-element-missing`, `raw-text`) and 1.1 (F2, F5, F10, F11); `gate/rigor_lib/ui_judge_*.py`;
`gate/rigor_lib/ui_explore_probe.py`, `ui_explore_grammar.py`; `rules/ui.bzl` and the symbols gate's reserved prefixes;
the selftest products (`selftest/ui_product`, `ui_frame_product`, `ui_canary_product`) and the explorer stub.

## Why
Three P004 3.1 checks are blocked because the scene says what is drawn but not what it IS: `required-element-missing`
needs the state class of each state and an element id per node (the splash without its version line, F10; the report
without its columns, F11; the pad without its echo, F2); `value-split` needs to know which nodes make one value (the
locker number "82" drawn as two labels, F5); `raw-text` needs the message id and arguments of a text (a raw msgid on
screen, F6a). The semantic record has 14 fields and none of these.

## Do
1. Model interface, by the U05c pattern (no change to the 14 semantic fields, so every recorded transcript stays
   valid): two REQUIRED symbols, `bool uim_identity_supported(void)` (a constant) and
   `bool uim_identity(uim_t *m, uim_buf_t *out)`, read-only like `uim_semantic` (never changes the model; callable
   whenever `uim_semantic` is). Records, TAB-separated, the grammar rules of the other records (no empty field, `-`
   for none, the same escaping):
   - one `state` line: the state class id (the product's name for the screen class shown; `-` is not allowed);
   - one `node` line per semantic node that has any identity: key, element id or `-`, msgid or `-`, the formatted
     arguments (count, then each escaped) or `0`.
   Say in `docs/ui-model.md` exactly what each means and what a product may not do (an element id is a stable name
   from the product's UI spec, never derived from the text; msgid is the catalogue key the text was formatted from).
2. Probe: command `identity` (`ok identity lines <n>` + the records; needs no frame), capability `identity` in the
   greeting after `pointer` when supported; `err identity unsupported` otherwise. Gate-owned adapters (toy, frame toy,
   canary) implement both symbols; the canary really supports identity, the toys may return false.
3. Explorer: `requires` may name `identity`; when a selected judge needs identity the explorer takes `identity` once per
   step it judges (it is cheap and read-only; say the measured cost) and puts it in the step observation and in
   run-twice. A probe without the capability with a judge selected: the identity checks are `check-blocked` findings
   (error, one per check, identity: the check), never a silent pass. Do not key states on identity (the key stays the
   catalogue's business) but allow `[key]` to name the state class if the key grammar makes that a small, exact
   addition; otherwise leave it and say so.
4. Contract (loader + docs; no values in `products/**`): `[[state_class]].required` already lists element ids; add
   `[[value]]` (`id`, `element`: the element id whose nodes make ONE value, `max_nodes` default 1, provenance) and
   whatever `raw-text` needs if anything. Every table with provenance and the loader's usual refusals.
5. Checks in `ui-scene` (P004 ids, exact rules; exceptions, `checks-examined`, `check-vacuous` as the other checks):
   - `required-element-missing`: in a state of class C, an element id in C's `required` that no shown node carries
     (hidden per the scene flag does not count as present); an unknown state class (not in the contract) is
     `contract-incomplete`;
   - `value-split`: the nodes carrying a `[[value]]` element's id number more than `max_nodes`;
   - `raw-text`: replace or complete U06's heuristic with the exact rule: a text node whose label equals its msgid
     byte for byte while the msgid has a translation in the active language cannot be decided without the catalogue,
     so define what IS decidable from identity alone (label == msgid and msgid is not a declared "identity-literal";
     a node of role text with a label and NO msgid where the contract requires catalogue text) and table the rest as
     blocked on the catalogue task (U17b). Keep U06's id; do not create a second id for the same defect.
6. Canary variants: a state missing a required element; a value split in two nodes; a raw msgid; a clean state; each
   check fires exactly where seeded. `selftest/ui_judges.sh` asserts ids and targets. Each check seen failing once
   against a broken judge (table in the doc).
7. Docs: `docs/ui-model.md`, `docs/ui-judges.md` (honesty table rows move from blocked to implemented; the historic
   defects table F2, F5, F10, F11), `docs/ui-contract.md`, `docs/ui-explore.md` (the capability, the cost).
8. The real kiosk does not have the calls yet (business-apps pins an older gate; its adapter gains them in a product
   task). Write in the doc exactly what the lockers adapter must emit: the state class ids of `lockers.toml`, the
   element ids its `required` lists and `[[element]]` rows use, the value elements (locker number, entered code).

## Paths
`ui/model/**`, `rules/ui.bzl` and the symbols-gate prefix list only if a new symbol needs it, `gate/rigor_lib/ui_judge*.py`,
`gate/rigor_lib/ui_contract*.py`, `gate/rigor_lib/ui_explore*.py` (probe, grammar, run, strategies, the judge
interface), `gate/rigor_lib/cli.py` only if an option is needed, `gate/tests/test_ui_*.py`, `gate/tests/data/ui_explore/**`,
`selftest/ui_product/**`, `selftest/ui_frame_product/**`, `selftest/ui_canary_product/**`, `selftest/ui*.sh`,
`docs/ui-*.md`, `tools/affected.toml` for new files only. Nothing under `products/`.

## Acceptance (the orchestrator re-runs all of it)
- `bash selftest/ui.sh` twice in a row, exit 0, tree clean, no process left.
- `tools/buck2 test //ui/...` in release and with `--target-platforms toolchains//:linux_san`.
- `python3 -I -B gate/tests/run_parallel.py` at the host baseline (the `ssh-keygen` errors and
  `test_job…test_the_deadline_kills_the_whole_process_group` only).
- `python3 -I tools/affected.py --check`. Files <= 500 lines, functions <= 50 lines; C17 rules for C.

## Report
What changed; real output of each acceptance command; every recorded transcript you regenerated and exactly which
lines changed and why; each check seen failing; deviations; what you could not do. Never kill a process by name.
Scratch under `/var/tmp/cache/U24/`.
