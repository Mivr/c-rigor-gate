# The UI contract (P004 section 6.2, task U10)

One owner-sealed TOML file per product holds everything a UI judge needs as a threshold, timer, policy or exception:
`products/business-apps/ui/lockers.toml` for the lockers kiosk. A product-owned contract would be the first thing an
agent edits, so the file is gate-owned and sealed (the signature check is U18, not this task). The loader is
`gate/rigor_lib/ui_contract.py`; it is strict: an unknown key, a missing key, a wrong type, a duplicate row or a
dangling reference is an `InternalError` (exit 2), never a default.

## Schema (`schema = "ui-contract/1"`)

Top level: `schema`, `product`, then the sections below. Nothing else is allowed.

**Scalar sections** hold named entries; every key listed is required, none else is allowed. An entry is an inline
table `{ value = ..., provenance = "..." }` or `{ pending = "<n>", provenance = "..." }`.

| Section | Keys |
|---|---|
| `[window]` | `width_px`, `height_px`, `unit_px`, `pad_px`, `gap_px` |
| `[panel]` | `diagonal_in`, `viewing_distance_mm` (the mm thresholds and `ppi()` need them) |
| `[type_scale]` | `display`, `headline`, `title`, `body`, `staff`, `caption` (KioskMetrics, px = dp) |
| `[reading]` | `rate_wpm` |
| `[clock]` | `tick_ms` (the reactor tick, runtime.h C2) |
| `[policy]` | `error_dialog` (`fixed` or `until-acknowledged`), `target_population` (`younger-adult` or `inclusive`) |
| `[thresholds]` | the 26 quantities of P004 3.10 (touch targets, spacing, probe region, feedback, busy, dwell, flicker, legibility, contrast, pseudo-locale, tolerances, hierarchy ratio); each has a range, and the orderings P004 implies are checked (touch <= button floor <= recommended <= keypad, hard <= recommended spacing, ...) |
| `[pending_tables]` | whole tables the owner has not decided: `importance = { pending = "7", provenance = ... }` |

**Tables** are arrays of rows; each row has the listed keys, an id that must be unique in its table, and a
`provenance`. All are required except `[[exception]]`, which may be absent (no exceptions).

| Table | Id | Other keys |
|---|---|---|
| `[[style]]` | `id` | `token` (1..21 of ui-look.md 4.2), `scale` (a `type_scale` key, so style to px is `style_px()`), `weight` (400/600), `usage` (`text`/`button`) |
| `[[role]]` | `id` | `style`, `align` (`centre`/`left`), optional `align_banner` |
| `[[role_min]]` | `role` | `font_px_min`, `touch_dp_min` (0 means not applicable) |
| `[[timer]]` | `kind` | `class` (`screen`/`message`), `lifetime_ms` (0 means no limit), `countdown_shown`, `dismiss` (list) |
| `[[state_class]]` | `id` | `required` (element ids that must be present) |
| `[[importance]]` | `level` | `roles` |
| `[[toggle_group]]` | `id` | `members` (`[[element]]` ids), `exactly_one`, `shown_on` (state class ids), `marks` (U06: what tells the selected member apart: `bg`, `bg_opa`, `style`) |
| `[[input_layer]]` | `layer` | `blocks_input_below`, `tap_outside_dismisses`, `accepts_input` |
| `[[wrap]]` | `scope` | `wrap` (`word`/`char`/`none`), `max_lines` (0 means no cap), `ellipsis`, `clip` |
| `[[exception]]` | `id` | `rule` (a finding id of P004 3.1 to 3.9, closed list in the loader), `target` (a concrete node id, no wildcard), `reason`, `expires` (a date); the provenance must be `owner:` |
| `[[style_role]]` (U06) | `style` | `role`: the typographic role of a style no `[[role]]` row names (a colour variant: lockers' action, cancel and language buttons) |
| `[[role_wrap]]` (U06) | `role` | `scope` (a `[[wrap]]` scope): the wrap scope of EVERY node of the role, only where the spec decides it for all of them |
| `[[element]]` (U06) | `id` | `key` (a scene key, unique in the table), optional `wrap` (the scope of that node, where the spec decides it per node), optional `label = "accessible"` (the label is an accessible label only, never drawn) |
| `[[style_line]]` (U06) | `style` | `line_height_px`: a regression baseline of the style's font line height, read from the product; its provenance must be `product-baseline:<commit>` |

References are checked: a style's `scale`, a role's `style`, `role_min.role`, `importance.roles` and
`toggle_group.shown_on` must name existing entries.

## Provenance rule

Every entry and every row carries `provenance`, matched whole (a trailing newline is an error), one of

- `spec:<doc>#<anchor>`: a spec document of the closed list `ui-rules.md`, `ui-look.md`, `hardware-safety.md`,
  `P004`, and the section it comes from (`spec:ui-look.md#4.2`);
- `oracle:<what>`: a value read from the Rust oracle (free text);
- `literature:<key>`: a cited study or standard. A threshold P004 3.10 cites a source for is
  `literature:3.10/<threshold key>`;
- `design:P004#<section>`: a value P004 marks [I] or [P] (its own design or draft value, no source). The
  thresholds that are design values are `design:P004#3.10-<key>`, and the loader fixes which keys they are;
- `owner:<decision id>`: an owner decision (`owner:D17`, `owner:Q9`);
- `product-baseline:<commit>` (U06): a value read from the product under test at that commit (7 to 40 hex digits): a
  regression baseline, not a decision. Only `[[style_line]]` may use it, and that table no other form.

An entry without a provenance, or with one of another shape, is an error. A pending entry has one too (the question,
e.g. `spec:P004#11-q9`).

## Pending rule

An entry the owner has not decided is `pending = "<n>"`, `n` a P004 section 11 question number, instead of `value`.
It never has a default, and **what may be pending is a closed list in the loader** (`PENDING_ENTRIES`,
`PENDING_TABLES`), each with its question number: any other entry, or the wrong number, is an error. A whole table
is pending through `[pending_tables]`; its rows are then absent and `Contract.rows()` raises.

`Contract.get(section, key)` raises `ContractPending` (not an `InternalError`) for a pending entry. A judge turns it
into the finding `contract-pending` with `pending_finding(error)`; **its severity is fixed to `error`** in the
loader and a judge cannot choose it (reporting first, before enforcing, is a later task's business). `ppi()` and
`mm_to_px()` are pending while `panel.diagonal_in` is.

Pending in the lockers contract today: panel diagonal and viewing distance (Q9); the target-size population and the
mm button thresholds (Q10); the reading rate and the error-dialog policy (Q11); the flicker floor and the hierarchy
ratio (Q5); contrast ratios (Q15); the whole importance table (Q7).

`policy.error_dialog` means "the owner may change the dialog policy". It does not replace the dialog timer: the
`dialog` timer keeps the value of ui-rules.md (8000 ms, `spec:` provenance) until the owner decides otherwise.

## Consistency the loader enforces

U06 adds (`gate/rigor_lib/ui_judge_contract.py`, which holds these tables, their checks and the judges' lookups): a
style is named by at most one role (a `[[style_role]]` style is not a `[[role]]` style, and no two roles share a style),
so a style token has one typographic role; `[[role_wrap]]` names roles and scopes; `[[element]]` keys are unique and
their `wrap` names a scope; toggle group members are `[[element]]` ids; `[[style_line]]` names styles. No row of these
tables may be pending: where the spec does not decide, the row is absent and the judges report `contract-incomplete`.
A layer's input policy is the sealed `[[input_layer]]` table's, by the structural role; there is no other policy table.

**The input-layer naming rule (a gate rule, U06).** An `[[input_layer]]` row is the policy of a layer role of the scene
vocabulary (`scrim`, `dialog`, `banner`, `snackbar`) when it is named the role or `<role>_<kind>` (lockers: `dialog`,
`snackbar`, `banner_notice`, `banner_persistent`; the kinds of one role must agree, or the judges report
`contract-incomplete`). Any other row is a screen-level layer and must be named `screen` (the base layer, the scene's
root) or a `[[state_class]]` id (lockers: `splash`, `lockout`). A row named otherwise is a LOADER ERROR (exit 2), not a
finding: a typo (`dialgo`, `bnner_notice`) would detach the row from every judge without any check noticing, and the
loader refuses every other malformation of a sealed file the same way.

**Accepted, not judged (U07).** Of the names the rule accepts, only the layer-role rows (the role or `<role>_<kind>`)
are read by a judge (ui-scene's layers, R8). A `screen` row and a row named a `[[state_class]]` id are accepted and read
by NO judge today: no check of ui-scene, ui-fit or ui-render takes a screen-level input policy (lockers: `screen`,
`splash`, `lockout`). The stricter rule, accepting only names a judge reads, would refuse
`products/business-apps/ui/lockers.toml`, which has those three rows, so the rule stays as it is and this paragraph
names what it accepts without a reader. The layer roles are defined once, `ui_judge_contract.LAYER_ROLES`, which the
scene vocabulary (`ui_judge_vocab`) imports.

The loader is split across modules (fix-up 3, the series' 500-line limit): `ui_contract.py` (schema, entries, tables,
the Contract), `ui_contract_checks.py` (the consistency checks), `ui_contract_dwell.py` (the dwell table) and
`ui_judge_contract.py` (the judges' tables); `ui_contract` re-exports every public name.

## Checks

- `incomplete(contract, timer_kinds, state_classes, roles)` returns one `contract-incomplete` finding for every
  timer kind, state class or role a product declares that the contract has no row for, and for every role of the
  contract with no `role_min` row or (unless the table is pending) no importance level.
- `dwell_table(contract, messages)` takes dicts `{msgid, lang, kind, text[, max_expansion]}` and gives, per message
  and language, the characters as displayed, the reading time `ceil(chars * 60000 / (rate_wpm * chars_per_word))` in
  ms (exact arithmetic; P004 3.10: `chars / (r * 5.6 / 60)` seconds), the minimum dwell `max(dwell_floor_ms,
  dwell_base_ms + reading)` and the contract timer of its kind. Characters are Unicode code points (NFC), so
  Bulgarian is not under-counted. A `{placeholder}` needs its longest expansion in `max_expansion` (a plain text per
  placeholder); an unexpanded placeholder, an expansion the text does not use, a duplicate (msgid, lang) or a missing
  text is an error. `dwell_findings(rows)` reports `dwell-below-reading-time` for a timed message (`lifetime_ms`
  above 0) shorter than its minimum, and one `contract-incomplete` per timer kind the contract lacks. The table
  raises `ContractPending` while `reading.rate_wpm` is pending.

## The derivation script

`python3 -I gate/tools/ui_contract_derive.py --ui-rules docs/lockers/ui-rules.md --contract
products/business-apps/ui/lockers.toml [--print]` re-derives, for every timer kind, `class`, `lifetime_ms`,
`countdown_shown` and `dismiss` from the "Screen timers" and "Message catalogue" tables of ui-rules.md and compares
them with the `[[timer]]` rows. Exit 0: equal. Exit 1: they differ (each difference on stderr). Exit 2: an
unreadable file, a table whose header differs, a row with the wrong number of cells, an escaped pipe, an unknown row
name or catalogue kind (only the named "not a notice" row is skipped), a duplicate Screen timers row, a catalogue row
without a dismiss intent, or a ui-rules.md that contradicts itself between its two tables.

The gate cannot read business-apps at test time, so the unit tests run the script on a copy,
`gate/tests/data/ui_contract/ui-rules.md`, whose sha256 is recorded in `ui-rules.md.sha256` next to it (a test
checks it). To refresh it: copy `docs/lockers/ui-rules.md` from business-apps over the copy, write its digest with
`sha256sum ui-rules.md | cut -d' ' -f1 > ui-rules.md.sha256`, run the script against the real file and the contract,
and update the contract and the tests if the derivation changed.
