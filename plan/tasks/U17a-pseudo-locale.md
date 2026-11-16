# U17a: the pseudo-locale generator (first half of P004 T1xx.17)

Repo `Mivr/c-rigor-gate`, branch `task/U17a`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §3.8 (the
"Pseudo-locale" paragraph), §3.2, §3.10; `rules/catalog.bzl`, `gate/rigor_lib/po2c.py` and its tests (the gettext
reader this must agree with); `docs/ui-contract.md` and `gate/rigor_lib/ui_contract.py` (`pseudo_expansion_*`
thresholds); `/home/user/business-apps/apps/lockers/lkui/catalog/i18n/` (read only: the real `.pot`/`.po` files).

## Why
Text that fits in English and Bulgarian today can still overflow with the next translation or the next message. A
generated third language that is as long and as tall as text can plausibly get makes text-fit a property of the
layout instead of a property of today's strings, and delimiters make truncation visible to a machine.

## Do
1. `gate/rigor_lib/ui_pseudo.py` (stdlib): from a `.pot` and the product's `.po` files, produce a pseudo-locale
   `.po` (language code `xx`), deterministic: the same inputs give the same bytes.
   - Length per msgid: max(length of the longest real translation, expansion of the English length by the IBM
     table: about 3x for <= 10 characters falling to 1.3x above 70). The table is data in the module with its
     source cited; the overall floor comes from the UI contract when one is passed.
   - Content: starts with a fixed start delimiter and ends with a fixed end delimiter (both documented, chosen from
     characters the kiosk fonts have), padded with the tallest and the deepest Cyrillic glyphs (ascender and
     descender extremes, e.g. `Й`, `Щ`, `р`, `у`, `ц`, `щ`) so that vertical clipping shows.
   - Arguments and format placeholders (`{0}`, `%d`, ...) are kept verbatim, same count and order; plural forms get
     one pseudo string per form; line breaks in the source are preserved; msgctxt is preserved.
   - Refuse (house error, exit 2) anything `po2c.py` would refuse, and a msgid that is only a placeholder.
2. A rule `c_catalog_pseudo` in `rules/catalog.bzl` (or a new `rules/ui_pseudo.bzl`) that runs it as one Buck2
   action and yields a `.po` that `c_catalog_gen` accepts, so a product can build its catalogue with the extra
   language for the probe only (never in the shipped binary: say how that is kept apart).
3. `rigor ui-pseudo` CLI entry (follow how other subcommands are registered) printing the generated `.po`.
4. `docs/ui-pseudo.md`.

## Not in this task
The `ui-meta` judges (U17b); rendering; any business-apps change.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py` with new `gate/tests/test_ui_pseudo*.py`: byte-identical output on two
runs and under a shuffled input order; every pseudo string starts and ends with the delimiters; length rule at the
table boundaries (10/11, 70/71 characters) and when the Bulgarian string is the longer one; placeholders preserved
in count and order (a dropped placeholder is seen failing); plural forms; the generated file is accepted by
`po2c.py` together with the real lockers catalogue (use a checked-in copy under `gate/tests/data/ui_pseudo/` with a
recorded sha256, as U10 did for ui-rules.md). One Buck2 build of a tiny catalogue through the new rule in
`selftest/ui_product/` is NOT required here (U03 owns that tree until it merges); instead build a fixture under
`gate/tests/data/ui_pseudo/` only if it needs no BUCK changes, otherwise say so. `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/ui_pseudo.py`, `gate/rigor_lib/cli.py` (register the subcommand only), `gate/rigor_lib/BUCK`,
`gate/tests/test_ui_pseudo*.py`, `gate/tests/data/ui_pseudo/**`, `rules/catalog.bzl` or `rules/ui_pseudo.bzl`,
`docs/ui-pseudo.md`, `tools/affected.toml` (rules for new paths only).
