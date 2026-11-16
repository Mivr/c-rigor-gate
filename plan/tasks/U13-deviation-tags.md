# U13: machine-readable deviation tags and their ratchet (P004 T1xx.13, gate half)

Repo `Mivr/c-rigor-gate`, branch `task/U13`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §5, §8.3, §8.5 and
§1.2 (the "Parity docs" row: deviations were recorded but nothing counted, capped or re-checked them);
`gate/rigor_lib/ratchet.py`, `ledger.py`, `findings.py`, `jsonio.py`, `errors.py`, `cscan.py`, `cli.py` and one
existing scanner with its tests for the house style; `docs/ui-contract.md` (the provenance and `exception` rules this
must agree with); `/home/user/business-apps/apps/lockers/lkui/screens/screens.h`,
`apps/lockers/lk/selftest/selftest.h` and `apps/lockers/lk/preflight/preflight.h` (read only: the DISAGREEMENTS
sections that exist today).

## Why
Every place where the C kiosk knowingly differs from its Rust oracle is written as prose in a header. Prose is not
counted, has no expiry and is never re-checked, which is how eleven visible defects stayed "recorded" and unfixed.
A tag the gate can read turns each pinned deviation into counted debt with a reason, a link and an expiry.

## Do
1. **Tag grammar** (documented in `docs/ui-deviations.md`), written inside a C comment in a product header:
   `@deviation(<id>, oracle="<what in the oracle>", state="<screen or state class list>", reason="intentional|substrate|reference-bug", link="<doc anchor or issue>", until="<task id or ISO date>")`.
   Ids are unique per product (`[A-Z][A-Z0-9]*-[A-Z0-9.-]+`). Strict: unknown key, missing key, duplicate key,
   duplicate id, a reason outside the closed list, an empty value, a malformed tag that starts with `@deviation(`
   — all are findings (`deviation-malformed`, error), never skipped. A `reference-bug` must link an issue of the
   oracle's repository (pattern in the product config); an `until` date in the past (against a date passed in, never
   the wall clock) is `deviation-expired` (error).
2. **Scanner** `gate/rigor_lib/ui_deviations.py` (stdlib): walks the product's tracked headers (use the product
   layout helpers the other scanners use; gate and third-party paths excluded), finds tags only inside comments (a
   tag in a string literal or in code is not a tag; say what a tag in a `#if 0` block is), and returns the list
   sorted by id with file and line.
3. **Debt accounting**: a per-product baseline file (`products/<product>/ui/deviations.toml`, strict loader): the
   list of accepted tag ids with the count cap. Findings: `deviation-new` (a tag not in the baseline; error — a new
   deviation needs the baseline changed, and the baseline is an owner-sealed file: say so, sealing itself is a later
   task), `deviation-over-cap` (count above the cap; error), `deviation-removed` (in the baseline, no longer in the
   tree; info: delete it from the baseline — the ratchet only goes down), and a function for the later parity judge
   to mark a tag `pinned-deviation` (its subject really diverges) or `deviation-stale` (it no longer diverges).
   Provide the hook as a pure function over (tags, set of diverging subject keys); do not implement the judge.
4. **Untagged prose is debt too**: a header that contains a `DISAGREEMENTS` section (the existing convention) with
   numbered or bulleted entries but fewer `@deviation` tags than entries is `deviation-untagged` (error), with the
   file and the count of entries and tags. Define precisely how entries are counted and test it on copies of the
   three real headers (checked in under `gate/tests/data/ui_deviations/` with recorded sha256, as earlier tasks
   did).
5. CLI `rigor ui-deviations --root <product tree> --product <product.toml> --today <ISO date>` printing findings in
   the house result shape; deterministic, byte-identical for identical inputs.
6. `products/business-apps/ui/deviations.toml`: the first baseline, EMPTY with cap 0 (no tag exists in the product
   yet), so that running the scanner on business-apps today reports exactly the `deviation-untagged` findings for
   the real headers. Report those counts; do not change business-apps.

## Not in this task
Tagging the product's headers (a business-apps task); the parity judge; signature checking of the baseline; wiring
into `rigor grade`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py` at the host baseline with new `gate/tests/test_ui_deviations*.py`: every
malformed form; a tag in a string or in code is ignored and one in a comment is found; duplicate ids across files;
expired vs not expired against the passed date; reference-bug link pattern; new / over-cap / removed against a
baseline; the pinned/stale hook; `deviation-untagged` on the copies of the three real headers with exact entry
counts, and no finding once a copy carries one tag per entry; byte-identical output twice and under shuffled file
order. Each check seen failing once against a deliberately broken version (say how). The CLI run on
`/home/user/business-apps` (read only) with its exact output in the report. `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/ui_deviations.py`, `gate/rigor_lib/cli.py` (register the subcommand only),
`gate/tests/test_ui_deviations*.py`, `gate/tests/data/ui_deviations/**`, `products/business-apps/ui/deviations.toml`,
`docs/ui-deviations.md`, `tools/affected.toml` (new paths only).
