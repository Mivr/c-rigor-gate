# U10: the UI contract schema and the lockers contract (P004 T1xx.10)

Repo `Mivr/c-rigor-gate`, branch `task/U10`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §3.10, §6.2, §8.5,
§11; `/home/user/business-apps/docs/lockers/ui-rules.md` and `ui-look.md` (read only; sections 0, 1, 3, 4, 6);
`gate/rigor_lib/contract.py`, `jsonio.py`, `errors.py` and one existing TOML loader with its tests for the house
style (strict: unknown key, missing key, wrong type are all errors).

## Why
Every UI judge needs its thresholds, timers, policies and exceptions from one owner-sealed file with a provenance per
entry, so that a threshold cannot be loosened quietly and a missing entry fails instead of switching a check off.

## Do
1. `gate/rigor_lib/ui_contract.py`: a strict loader and validator for a UI contract TOML. Sections (P004 §6.2):
   window and panel (pixels, physical size, viewing distance), thresholds of §3.10, style-to-font table, role
   minimums, alignment per role, importance levels, timers (message kind, lifetime, countdown shown), toggle groups,
   input policy per layer, required elements per state class, wrap/ellipsis/clip policy, exceptions. **Every entry
   carries `provenance`** (`spec:<doc>#<anchor>`, `oracle:<what>`, `literature:<P004 §3.10 key>` or
   `owner:<decision id>`); an entry without one is an error. An entry whose value the owner has not decided is
   written `pending = "<P004 §11 question number>"` instead of a value; a judge asking for a pending value must get a
   typed "contract-pending" result, never a default.
2. `contract-incomplete`: a function that, given the set of timer kinds / state classes / roles a product declares,
   reports every one the contract does not cover.
3. A dwell table per msgid and language: reading time from word count at the contract's reading rate;
   `dwell-below-reading-time` for a timer shorter than that.
4. `products/business-apps/ui/lockers.toml`: the first lockers contract, derived from ui-rules.md and ui-look.md with
   a provenance on every entry. Panel size, viewing distance, target-size population, error-dialog policy and reading
   rate are P004 §11 questions 9, 10, 11 without an owner answer: write them as `pending`. Style-to-px must equal
   `KioskMetrics` (display 200, headline 48, title 40, body 32, staff 24, caption 16).
5. A derivation script `gate/tools/ui_contract_derive.py` (stdlib) that re-derives the timers table from
   ui-rules.md and fails if the checked-in contract disagrees.
6. `docs/ui-contract.md`: the schema, the provenance rule, the pending rule.

## Not in this task
Signature checking of sealed files (U18); judges; changing any business-apps file.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py` with new `gate/tests/test_ui_contract*.py` covering: every entry has a
provenance (remove one: error); removing a timer row gives `contract-incomplete`; a pending value read by a judge
gives `contract-pending`; unknown key, wrong type, duplicate entry are errors; style-to-px matches `KioskMetrics`;
every threshold cites its §3.10 key; the derivation script agrees with the checked-in contract and fails on an edited
copy. `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/ui_contract.py`, `gate/tests/test_ui_contract*.py`, `gate/tests/data/ui_contract/**`,
`gate/tools/ui_contract_derive.py`, `products/business-apps/ui/**`, `docs/ui-contract.md`,
`tools/affected.toml` (rules for the new paths only), `gate/rigor_lib/BUCK` (list the new module only).
