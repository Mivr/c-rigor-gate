# The pseudo-locale generator (`rigor ui-pseudo`, `c_catalog_pseudo`)

P004 3.8, task U17a. Text that fits in English and Bulgarian today can overflow with the next translation. The
generator makes a third language, `xx`, whose every string is longer than every real translation and as tall as
Cyrillic text gets, with delimiters so that a cut-off is visible to a machine. The `ui-meta` judges (U17b) render it
and compare; this document covers only the generator.

## Use

    rigor ui-pseudo --source-lang en --contract products/business-apps/ui/lockers.toml \
        --pot lockers.pot --po bg bg/lockers.po                     # prints the .po
    rigor ui-pseudo ... --pot a.pot --pot b.pot --po bg bg/a.po --po bg bg/b.po --out a.xx.po --out b.xx.po

`--pot` and `--po LANG FILE` are given once per `.pot` (same order), as `c_catalog` takes them; `--out` once per
`--pot`. `--contract` is required: the overall expansion floor is `thresholds.pseudo_expansion_overall_pct` of the UI
contract; a missing, pending or malformed value is a refusal, never "no floor". `--lang` defaults to `xx`.
Exit 0 = written; exit 2 = refused (`rigor: ui-pseudo: refused: ...` on stderr, no output file). All outputs are
written under a temporary name and renamed only when every one succeeded; an I/O error is a refusal too.

## One mode: the grammar of `po2c`

Placeholders are exactly what `po2c` recognises: `{0}`..`{9}`, `{{`, `}}`. Anything else is plain text (`100% done` is
padded over entirely, `%d` is not special); a brace left over after those is refused. The generator refuses everything
`po2c` refuses (msgctxt, plural forms, fuzzy, charset other than UTF-8, empty or missing translation, other
placeholders in a translation, a msgid twice, a `.po` msgid not in its `.pot`, a malformed template), and a msgid
that is only placeholders and white space (`{0}`, `{0} {1}`), named in the message. `po2c`'s checks (without its enum
names) are run over the inputs, and again over the inputs plus the generated file, before anything is written.
There is no `--extended`: msgctxt and plurals will be supported when `po2c` supports them.

## What it produces

The output is a pure function of the file bytes; entries are sorted by msgid; nothing depends on input order, clock,
path or locale. Golden output: `gate/tests/data/ui_pseudo/golden/*.xx.po` (sha256 in `GOLDEN.sha256`) for the copied
lockers catalogue at floor 40; any change of bytes, the tie-break of the padding shares included, fails a test.

**Length**, per line of a msgid (the rule is applied to every line; the line count is kept), of the CONTENT, i.e. the
text between the delimiters, which come on top. A placeholder counts as its own characters, `{{` and `}}` as one:

    content = max( ENVELOPE(n), ceil(n * (100 + pct) / 100), longest real translation of the line + 1 )

with `n` the English line length. The content is strictly longer than every real translation (P004 wants the
pseudo-locale to exceed every real language per message). A real version with another number of lines contributes
its longest line to each line.

`ENVELOPE(n)` is the running maximum of the IBM table, so a longer English text never gets a shorter result. This is an
orchestrator ruling of 2026-11-15, open to the owner. The table (`IBM_TABLE`) is IBM's globalization guideline "text
expansion", as reproduced in Microsoft's pseudolocalisation note (P004 3.8, Practitioner 2022), at the upper end of each
band:

| English length | 1-10 | 11-20 | 21-30 | 31-50 | 51-70 | over 70 |
|---|---|---|---|---|---|---|
| expansion | 300% | 200% | 180% | 160% | 140% | 130% |

Raw table values would give 30 for 10 characters and 22 for 11; the envelope gives 30 for both (and 80/80 at 50/51,
98/98 at 70/71). `OK` gets 6, a one-character msgid 3. The length is exact whenever feasible (room for the
placeholders, the preserved white space and one glyph per piece of text).

**Content.** `[` and `]` (ASCII, so every font has them), then padding from the glyph cycle `ЙщрЩуцЩйр`: `Й` (breve above
the cap height), `Щ`, `ц`, `щ` (tail below the baseline), `р`, `у` (descenders): the tallest and deepest Cyrillic
shapes, so vertical clipping shows.

**Padding words.** Each word is at least as long as the longest real word of that line in any real language (the
English source counts as one), so a label narrower than one real word is exercised. Spaces appear only where the real
text has word breaks to offer: at most as many padding spaces as the real versions have breaks (minus the breaks kept at
placeholders); a single-word source stays one word.

**Placeholders, `{{`, `}}` and line breaks** stay verbatim, in the same count and order, with the padding shared between
them in proportion to the English text between them. White space at the edge of a piece next to a placeholder is kept.
At the delimiters the rule is exact: white space next to a delimiter is dropped, and there is always at least one padding
glyph between a delimiter and an adjacent placeholder, so an argument value ending in `]` cannot fake the end
delimiter. The generator checks every string it writes, with `po2c.placeholders()` rather than its own tokenizer.

## The Buck2 rule (open items)

`rules/ui_pseudo.bzl`: `c_catalog_pseudo(name, pots, po, source_lang, contract, lang = "xx")` runs one action
(`python3 -I -B` over the whole `gate//gate/rigor_lib:pkg`, because the generator imports `po2c` and the contract
loader) and yields one `<stem>.xx.po` per pot, as sub-target `:name[<stem>]`. It was built once by hand in U17a and its
bytes equal those of `rigor ui-pseudo`; **no selftest builds it yet**.

**Open, for U17b:** (1) building a catalogue that includes the pseudo language through `c_catalog` (the macro of
`rules/c.bzl` takes plain file names only, so it cannot take the generated `.po` today); (2) a check that the pseudo
language never reaches a shipped binary. Until then the separation is only the convention that the shipped catalogue
never names this target and the probe's catalogue is a second one.

## Tests

`gate/tests/test_ui_pseudo.py`; data `gate/tests/data/ui_pseudo/`: a copy of the lockers catalogue of business-apps
`apps/lockers/lkui/catalog/i18n` at commit `996a82f` (hashes in `SHA256SUMS`) and the golden output.
