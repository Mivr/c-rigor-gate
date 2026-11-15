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
| `[thresholds]` | the 26 quantities of P004 3.10 (touch targets, spacing, probe region, feedback, busy, dwell, flicker, legibility, contrast, pseudo-locale, tolerances, hierarchy ratio) |

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
| `[[toggle_group]]` | `id` | `members`, `exactly_one`, `shown_on` (state class ids) |
| `[[input_layer]]` | `layer` | `blocks_input_below`, `tap_outside_dismisses`, `accepts_input` |
| `[[wrap]]` | `scope` | `wrap` (`word`/`char`/`none`), `max_lines` (0 means no cap), `ellipsis`, `clip` |
| `[[exception]]` | `id` | `rule`, `target`, `reason` |

References are checked: a style's `scale`, a role's `style`, `role_min.role`, `importance.roles` and
`toggle_group.shown_on` must name existing entries.

## Provenance rule

Every entry and every row carries `provenance`, one of

- `spec:<doc>#<anchor>`: a spec document and the section it comes from (`spec:ui-look.md#4.2`);
- `oracle:<what>`: a value derived from the Rust oracle (free text);
- `literature:<key>`: a cited study or standard. A threshold must cite its own P004 3.10 key, written
  `literature:3.10/<threshold key>`; any other provenance on a threshold is an error;
- `owner:<decision id>`: an owner decision.

An entry without a provenance, or with one of another shape, is an error. A pending entry also has one (the
question, e.g. `spec:P004#11-q9`).

## Pending rule

An entry the owner has not decided is `pending = "<n>"`, `n` a P004 section 11 question number ("1" to "17"),
instead of `value`. It never has a default. `Contract.get(section, key)` raises `ContractPending` (not an
`InternalError`) for it; a judge turns that into the finding `contract-pending` with `pending_finding(error)`, whose
severity is the judge's choice (P004 3.10 reports mm checks as info until the panel is sealed). `ppi()` and
`mm_to_px()` are pending while `panel.diagonal_in` is. Pending in the lockers contract today: panel diagonal and
viewing distance (Q9), the target-size population and the mm button thresholds (Q10), the reading rate and the
error-dialog policy (Q11), the flicker floor and the hierarchy ratio (Q5).

## Checks

- `incomplete(contract, timer_kinds, state_classes, roles)` returns one `contract-incomplete` finding for every
  timer kind, state class or role a product declares that the contract has no row for.
- `dwell_table(contract, messages)` takes `(msgid, lang, kind, text)` and gives, per message and language, the word
  count, the reading time `ceil(words * 60000 / rate_wpm)`, the minimum dwell `max(dwell_floor_ms, dwell_base_ms +
  reading)` and the contract timer of its kind. `dwell_findings(rows)` reports `dwell-below-reading-time` for a timed
  message (`lifetime_ms` above 0) shorter than its minimum, and `contract-incomplete` for a kind without a timer.
  P004 3.10 writes the reading time from characters (chars / 5.6 per word); the table counts real words, as the U10
  contract says. The table raises `ContractPending` while `reading.rate_wpm` is pending.

## The derivation script

`python3 -I gate/tools/ui_contract_derive.py --ui-rules docs/lockers/ui-rules.md --contract
products/business-apps/ui/lockers.toml [--print]` re-derives the timer kinds, limits and countdown flags from the
"Screen timers" and "Message catalogue" tables of ui-rules.md and compares them with the `[[timer]]` rows. Exit 0:
equal. Exit 1: they differ (each difference on stderr). Exit 2: an unreadable file, an unknown row (the row names are
fixed in the script) or a ui-rules.md that contradicts itself between its two tables. The unit tests run it on a copy
of ui-rules.md under `gate/tests/data/ui_contract/`.
