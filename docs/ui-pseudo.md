# The pseudo-locale generator (`rigor ui-pseudo`, `c_catalog_pseudo`)

P004 3.8, task U17a. Text that fits in English and Bulgarian today can overflow with the next translation. The
generator makes a third language, `xx`, whose every string is as long as text can plausibly get and as tall as
Cyrillic text gets, with delimiters so that a cut-off is visible to a machine. The `ui-meta` judges (U17b) render it
and compare; this document covers only the generator.

## Use

    rigor ui-pseudo --source-lang en --pot lockers.pot --po bg bg/lockers.po [--overall-pct 40]   # prints the .po
    rigor ui-pseudo --source-lang en --pot a.pot --pot b.pot --po bg bg/a.po --po bg bg/b.po --out a.xx.po --out b.xx.po

`--pot` and `--po LANG FILE` are given once per `.pot` (in the same order), exactly as `c_catalog` takes them; `--out`
once per `--pot`. `--lang` (default `xx`), `--overall-pct` (the contract's `thresholds.pseudo_expansion_overall_pct`),
`--extended` (below). Exit 0 = written; exit 2 = refused (message on stderr, no output file). The same program runs
standalone: `python3 -I -B gate/rigor_lib/ui_pseudo.py ...` (this is what the Buck2 action does; `po2c.py` must be
next to it).

## What it produces

The output is a pure function of the file bytes: entries are written sorted by (msgctxt, msgid), nothing depends on the
order of the inputs, a clock, a path or the locale.

**Length** of the pseudo text of a msgid, in characters (delimiters and placeholders included):

    max( longest real translation of it,
         ceil(len(msgid) * IBM(len(msgid)) / 100),
         ceil(len(msgid) * (100 + overall_pct) / 100)        # only when --overall-pct is given )

`IBM` is the expansion table of IBM's globalization guidelines ("text expansion"), as reproduced in Microsoft's
pseudolocalisation note (P004 3.8, Practitioner 2022), at the upper end of each band:

| English length | 1-10 | 11-20 | 21-30 | 31-50 | 51-70 | over 70 |
|---|---|---|---|---|---|---|
| expansion | 300% | 200% | 180% | 160% | 140% | 130% |

Boundaries: 10 characters give 30, 11 give 22; 70 give 98, 71 give 93 (the table is not monotonic in the result, as
the source). The table is data (`IBM_TABLE`) in `ui_pseudo.py`. The length is exact whenever it is feasible (the text
has room for its delimiters, placeholders and one padding glyph per piece of text between placeholders).

**Content.** `[` (start) and `]` (end), then padding. Both delimiters are ASCII, so every font of the product has them
(the Cyrillic and Latin kiosk fonts cover ASCII; the probe renders them with the real font anyway). The padding is made
of the glyph cycle `ЙщрЩуцЩйр`: `Й` (breve above the cap height), `Щ`, `ц`, `щ` (tail below the baseline), `р`, `у`
(descenders): the tallest and the deepest Cyrillic shapes, so vertical clipping shows. Padding words are at most
5 glyphs, separated by a space, so a long string wraps the way text does (a block without spaces would overflow instead
of wrapping). No space is ever next to a delimiter.

**Kept verbatim, in the same count and order:** `{0}`..`{9}`, `{name}`, `{{`, `}}`, printf conversions (`%d`, `%s`,
`%5.2f`, `%%`, ...) and line breaks. The padding between them is shared in proportion to the English text between them,
and the white space at the edges of those pieces is kept (`"{0} opened"` becomes `"[{0} ЙщрЩу ...]"`). The generator
checks this on every string it writes and fails the run otherwise. A msgid with nothing but placeholders and white
space (`{0}`, `{0} {1}`) is refused: there is nothing to pad and the text would not be a string.

**Refused (exit 2):** everything `po2c` refuses (it is run on the same files first: no msgctxt, no plural, no fuzzy,
charset other than UTF-8, empty or missing translation, different placeholders in a translation, a msgid twice, a
msgid not in its `.pot`, a malformed template), a pseudo language that equals the source language or a real one,
missing or unreadable files, a count of `--po`/`--out` files that does not match the `--pot` files.

**`--extended`** (a deviation from the contract's "refuse what po2c refuses", see below): skips the `po2c` check and
also reads and writes `msgctxt`, `msgid_plural` and `msgstr[n]`. A plural entry gets one pseudo string per form, where
the number of forms is the largest number of `msgstr[n]` any real language has (at least 2); form 0 pads the msgid, the
others the msgid_plural; a language with fewer forms is compared through its last form. `msgctxt` is written back.
`po2c` itself refuses plural and context today, so a catalogue that uses them cannot go through `c_catalog_gen`
yet: the flag is for the day it can.

## The Buck2 rule

`rules/ui_pseudo.bzl`: `c_catalog_pseudo(name, pots, po, source_lang, lang = "xx", overall_pct = -1, extended = False)`
runs one action and yields one `<stem>.xx.po` per pot; the sub-target `:name[<stem>]` is that file, a valid `.po`
source of `c_catalog_gen` for the language `xx` (`gate/tests/data/ui_pseudo/BUCK` is a worked instance, built once by
hand; the bytes equal those of `rigor ui-pseudo`).

**Kept out of the shipped binary.** The pseudo `.po` exists only as the output of this target. The shipped catalogue
(`c_catalog`) never names it and lists only the real languages, so no string of it is in the product's `.c`. The probe's
catalogue is a second catalogue over the same `.pot` files with `xx` added to its languages, and only the probe links it.
This separation is by construction (two targets), not yet by a judge: a gate check that the shipped binary does not
depend on a `c_catalog_pseudo` output is for U17b or the layering checks.

Known gap: the `c_catalog` macro of `rules/c.bzl` takes plain file names only (`_plain_files`), so the generated `.po`
cannot be passed to it; today it can go to the `c_catalog_gen` rule directly. Letting `c_catalog` take the sub-target
is a change of `rules/c.bzl`, outside U17a.

## Tests

`gate/tests/test_ui_pseudo.py`, data `gate/tests/data/ui_pseudo/` (a copy of the lockers catalogue of business-apps
`apps/lockers/lkui/catalog/i18n` at commit `996a82f`, hashes in `SHA256SUMS`, checked by a test).
