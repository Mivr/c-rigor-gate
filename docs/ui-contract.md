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
| `[[role_wrap]]` (U06) | `role` | `scope` (a `[[wrap]]` scope) or `pending = "7"`: the wrap scope the judges use for the role's nodes |
| `[[layer]]` (U06) | `id` | `role` (`scrim`, `dialog`, `banner`, `snackbar`), `card` (only and always for a scrim: the role of the card it belongs to), `policy` (`pass-through`, `capture-modal-inert`, `capture-and-dismiss`) or `pending = "7"` |
| `[[element]]` (U06) | `id` | `key`: the scene key of the element's node (the toggle group members) |
| `[[style_line]]` (U06) | `style` | `line_height_px`: the line height of the style's font (`font-shrunk`) |

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
- `owner:<decision id>`: an owner decision (`owner:D17`, `owner:Q9`).

An entry without a provenance, or with one of another shape, is an error. A pending entry has one too (the question,
e.g. `spec:P004#11-q9`).

## Pending rule

An entry the owner has not decided is `pending = "<n>"`, `n` a P004 section 11 question number, instead of `value`.
It never has a default, and **what may be pending is a closed list in the loader** (`PENDING_ENTRIES`,
`PENDING_TABLES`, and `PENDING_ROWS` for single rows of `[[role_wrap]]` and `[[layer]]`, U06), each with its question
number: any other entry, or the wrong number, is an error. A whole table
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

U06 adds: a style is named by at most one role (a `[[style_role]]` style is not a `[[role]]` style, and no two roles
share a style), so a style token has one typographic role; `[[role_wrap]]` names roles and scopes; one `[[layer]]` row
per role and card; toggle group members are `[[element]]` ids; `[[style_line]]` names styles. `Contract.row_value()`
raises `ContractPending` for a pending row; `style_by_token()`, `role_of_style()` and `layer_row()` are the judges'
lookups. Pending rows are listed by `pending_entries()` as `<table>.<id>`.

Pending in the lockers contract since U06 (`spec:P004#11-q7`): the wrap scope of `screen_headline`, `staff_strong`,
`key_label` and `small_button_label` (ui-look.md 5 decides wrapping per node: each of these roles has a one-line node
and a wrapped one), and the banner's layer policy, card and scrim (a notice of kind banner dismisses on a tap outside,
a banner of the persistent set has no tap-outside area; the structural role does not tell them apart). Its
`[[style_line]]` values are read from the C kiosk's transcript (`oracle:` provenance, owner review pending).

Types and ranges of every value; unique ids; references (style to type scale, role to style, role_min and importance
to roles, toggle groups to state classes, state class elements to roles or the closed element list); unique style
tokens 1 to 21; a role in at most one importance level; `role_min.font_px_min` not above the role's style size and
buttons with a touch minimum of at least `touch_min_dp`; left alignment only for notice roles, `align_banner` only
there, buttons centred; `wrap = none` means one line and an ellipsis needs a line cap; a countdown needs a lifetime
above 0; every message timer has a dismiss control (UI rule 1). What the loader returns is immutable (tuples and
read-only mappings).

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
