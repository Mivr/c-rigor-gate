# UI deviations: tags, baseline, sections and ratchet (U13, P004 T1xx.13)

Every place where the C kiosk knowingly differs from its Rust oracle is a **tag** in a C comment of a product header.
`rigor ui-deviations` reads the tags, checks them strictly, counts them against an owner-sealed baseline, finds header prose
that records deviations and compares it with an owner-sealed list of acknowledged entries. Code:
`gate/rigor_lib/ui_deviations.py` (analysis, tree walk, command) with `ui_deviations_lex.py` (comments),
`ui_deviations_tags.py` (grammar), `ui_deviations_sections.py` (deviation sections) and `ui_deviations_baseline.py` (the two
sealed files); tests `gate/tests/test_ui_deviations*.py`. Not in this task: tagging the product's headers, the parity judge,
the signature check of the two sealed files and the wiring into `rigor grade`.

## Command

    rigor ui-deviations --root <product tree> --product products/<name>/product.toml --today YYYY-MM-DD [--out FILE]

Exit 0 = no error finding, 1 = an error finding, 2 = the gate could not decide (the house error: one line on stderr, no
traceback; with no arguments it prints one line; `--today`, `--root` or `--product` missing or given twice, `--today` not an ISO calendar date, root or
product.toml unreadable, a sealed file missing or malformed). `--today` is the only date the check knows; the wall clock is
never read. The two sealed files are read from `<directory of product.toml>/ui/deviations.toml` and
`.../ui/deviation-sections.toml`. The output is the house result shape (findings sorted by their canonical JSON) and is
byte-identical for identical inputs, whatever the order of the files.

## What is scanned

Every C-family file (extensions `c h inc def cc cpp cxx c++ hpp hh hxx ipp tpp inl`, any letter case) under `--root` that
`product.toml`'s layout copies (`product_layout.classify == copy`). A directory is skipped only when the layout itself
classifies a file in it as `excluded-by-gate`, exactly the classification `grade` copies by (no case folding of its own). Only a
`.h` file is a **header**: a tag or a deviation section in any other file is `deviation-misplaced` (error; `what` = `tag` or
`section`), so moving prose into a `.c` hides nothing (a tag there still counts against the baseline). A symlinked file, a
symlinked directory that the layout would copy and a non-regular C file are `deviation-malformed` (`why` = `symlink` /
`not-a-regular-file`, line 0); a file over 2,000,000 bytes is `deviation-malformed` (`file-too-large`) and is not read;
a file that is not UTF-8 is `deviation-malformed` (`not-utf-8`). A directory the walk cannot read is the house error (exit 2). None is skipped silently.

## Where a tag may stand

Only inside a C comment: `/* ... */` or a run of `//` lines. Comment-looking text in a string or character literal is not a
comment; a tag there or in code is **ignored**. Line splices and `\r\n`/`\r` line ends are read like C does. A tag in a comment
inside `#if 0` is found (C removes comments in translation phase 3, before directives run); code inside `#if 0` is code and is
ignored. An unterminated comment, string or character literal is `deviation-malformed` (`unterminated-comment`,
`unterminated-literal`). In a block comment the leading `*` of a line is decoration.

**Tag-shaped text is never ignored.** Every occurrence of `@deviation` in a comment, in any letter case and with an ASCII or
fullwidth at-sign (`x@deviation(`, `@@deviation(`, `@Deviation(`, `@deviations(`, `@deviation` in prose, ...), that is not
exactly `@deviation(` preceded by something other than `[A-Za-z0-9_@]` or the fullwidth at-sign, is `deviation-malformed`
(`bad-tag-start`). Do not write the word in prose.

### Confusables

A comment line that is not a heading or does not hold a tag as written, but would after invisible characters were removed
(zero width spaces and joiners, bidi controls, soft hyphen, BOM: every Unicode format character) and NFKC folding (fullwidth and
small forms) and the mapping of the Cyrillic and Greek look-alikes of Latin letters (`ui_deviations_conf.TABLE`), is
`deviation-malformed` with `why=confusable` (once per line): a heading or a tag written that way hides nothing.

## Grammar

    @deviation(<id>, oracle="<what in the oracle>", state="<state list>", reason="<reason>", link="<link>", until="<until>")

White space (including line breaks and comment decoration) may stand between the tokens. Exactly the five keys, each once, in
any order; a value is a double-quoted string on one line (escapes `\"` and `\\` only, no control character), non-empty, without
leading or trailing white space, at most 512 characters.

| Part | Rule |
|---|---|
| id | `[A-Z][A-Z0-9]*-[A-Z0-9.-]+`, at most 64 characters, unique in the product |
| oracle | any text |
| state | comma-separated names, each `[A-Za-z0-9][A-Za-z0-9_.:/-]*` (spaces after commas allowed), no repeats |
| reason | one of `intentional`, `substrate`, `reference-bug` |
| link | no white space; for `reference-bug` it is the baseline's literal `reference_bug_link_prefix` followed by an issue number of 1 to 7 digits and nothing else (a fixed grammar, no regular expression) |
| until | a task id `[A-Z][0-9]{2,4}[a-z]?` (`T123`, `L045`, `U13`, `U04a`) or a real ISO date no later than `--today` + 366 days (`why=until-too-far`) |

Every defect is `deviation-malformed` (error) with `path`, `line`, `why` (and `id` when it was read). A malformed tag is not a
tag: it is not counted and does not count towards `deviation-untagged`. `why` codes: `bad-tag-start`, `bad-id`,
`expected-comma-or-close`, `bad-key`, `unknown-key:<key>`, `duplicate-key:<key>`, `expected-equals`, `expected-string`,
`bad-escape`, `newline-in-string`, `control-character`, `value-too-long`, `unterminated-tag`, `missing-key:<key>`,
`empty-or-padded-value:<key>`, `bad-state`, `bad-reason`, `bad-link`, `reference-bug-link-not-an-oracle-issue`, `bad-until`,
`bad-until-date`, `until-too-far`, `duplicate-id` (every occurrence after the first, with `first` = `path:line`).

## The baseline: `products/<name>/ui/deviations.toml` (owner-sealed)

Strict loader; any defect is exit 2. Exactly these keys:

    schema = "ui-deviations/3"
    product = "<name>"                          # must equal product.toml's name
    cap = 0                                     # integer 0..1000, at least the number of accepted ids
    reference_bug_link_prefix = "https://github.com/Mivr/club-apps/issues/"   # literal https:// prefix ending in "/"
    [accepted."UI-A1"]                          # one table per accepted id, sorted by id
    until = "T200"                              # a task id or a real ISO date no more than 366 days after --today
    sha256 = "<64 lower-case hex digits>"

`sha256` is the hash of the **canonical form** of the tag: the canonical JSON (sorted keys, compact separators, ASCII only, one
trailing newline, as `jsonio.canonical_dumps`) of the object `{"id", "link", "oracle", "path", "reason", "state" (a list in the
written order), "until"}`, where `path` is the header the tag stands in, so a tag cannot move to another header unnoticed. It
does not depend on key order, spacing or comment layout. The reference-bug link is a fixed grammar (the prefix and 1 to 7
digits), so the product config loader (`product_layout`, strict and outside this task's paths) is not involved and no regular
expression is read from a sealed file (no ReDoS).

The baseline is **owner-sealed**: a new accepted id, a changed tag or a higher cap needs the owner's signature (P004 8.5).
Sealing and its signature check are a later task; until then nothing in the gate verifies the seal. The ratchet only goes down.
**A task-id `until` never expires** in the gate (only an ISO date can be `deviation-expired`); it is controlled only by the
sealed baseline: the hash pins it, so changing it is `deviation-changed`.

| Finding | Severity | Meaning |
|---|---|---|
| `deviation-new` | error | a tag id not in `accepted` (the baseline must change) |
| `deviation-changed` | error | an accepted id whose tag has other fields or another header (so `until` cannot be pushed out and an id cannot be reused for another deviation) |
| `deviation-over-cap` | error | more distinct tag ids than `cap` (`count`, `cap`) |
| `deviation-removed` | info | an accepted id with no tag: delete it from the baseline |
| `deviation-expired` | error | `until` is an ISO date earlier than `--today` (the day itself is still valid) |

## The hook for the parity judge

`judge_tags(tags, diverging)` is pure and total for any iterable of tags. The subject key of a tag is its id; `diverging` is the
set of ids whose subject really differs from the oracle. A tag in the set is `pinned-deviation` (info); a tag outside it is
`deviation-stale` (**error**). P004 8.3 says `deviation-stale` is info ("delete the tag"); it is kept an error here as a
**deliberate deviation from P004, flagged for the owner**: a stale accepted id is a reusable slot, a baseline entry for a
deviation that no longer exists that could later be filled with something else. A key naming no tag is the judge's own finding
(a divergence without a tag). Arguments of the wrong type raise `InternalError`. The judge itself is not implemented here.

## Untagged prose is debt

The **sealed expectation file is the primary control**: it is completed by reading the headers. The heading heuristic exists to
catch NEW sections and errs on the side of reporting.

### Heading rule (heuristic)

The closed list of heading words is `ui_deviations_sections.HEADING_WORDS` (one place): `disagreement(s)`, `deviation(s)`,
`difference(s) from`, `deviates`, `RS vs C`, `Rust vs` and `differ` / `differs` / `differing`, case-insensitive, whole words. A
**section heading** is a comment line (comment decoration removed) that is

* a `---- title ----` rule line (three or more dashes) with a heading word anywhere in the title; or
* a line that **starts** with a heading word after any run of `*`, `/`, `#`, `=`, `-` and white space, **whatever follows and
  whatever the line before** (`Disagreements with Rust:`, `Differences from Rust:`, `Deviations from the oracle are:`, `RS vs C,
  listed`); a phrase may wrap onto the next line; or
* a line that is not itself an entry line (see below) and holds a noun heading word (`MID_WORDS`: the list without `differ`,
  `differs`, `differing`), not inside double quotes, followed **in the same sentence** (to the next `.`, `!` or `?` followed by white
  space, wrapping included) by a colon or by the first entry label of any style (`(1)`, `1)`, `a)`, `D1`, `#1`, `Note 1`, ...).

A wrapped sentence that merely begins with one of the words (`deviation is a VIOLATION: ...`) is therefore reported as a section
too: the product must reword it (below).

A section runs from its heading to the next heading, to a `---- title ----` rule line, to an all-upper-case title line (at least
four letters, no lower-case letter, at most 80 characters; **never a line that carries an entry label**, `D2 NO CAP IN RUST`) or to the
end of the **group**: the run of adjacent comments with only white space between them. A bare `---` line, a blank line between `//`
runs and a comment split in two do not end it. The text of tags is left out of the prose (only the tag's own characters, so an entry
line that ends in a tag is still an entry).

### Entry count

An entry is **at an entry-start position**: the left-stripped start of a line at the indent of the first label (or less), or inside
text right after a sentence end (`. ; : ! ?`) or a line break. A label inside the text of an entry (a cross-reference such as
`(A1)`, `(P1)`, `see D1`) is not an entry. Entries are the union of

1. the **labelled lines at the indent of the first label**, so sub-bullets and numbered steps inside an entry are not counted. A
   label is `L1`, `L1:`, `L1.`, `D1`, `N3`, `D1-D4` (a range counts once), `D-1`, `DISAGREE-1`, `GAP-V1`, `GAP-T` (capitals, a dash and
   a number or a short suffix), `(D4,`, optionally after `Note`; `Note 3`; `1.`, `1)`, `1:`, `(1)`, `#1`; `a)`, `(a)`; roman numerals
   `i.`, `i)`, `(i)` in either case; and the bullets `-`, `*`, `+`, `•`, `–`. One to three capitals and a number without a leading zero.
   Each is followed by white space and text on the same line; and
2. the **longest in-order inline chain** from 1 in any of those styles (`(1) ... . (2) ...`, `D1 ... . D2 ...`) over the heading line and
   the unlabelled lines at that indent, counting only labels at an entry-start position.

Each (style, number) counts once, so a label that is also part of a chain is one entry; a repeated number counts again.

Only the **run of paragraphs that carry a label of a style already seen** counts: the section ends at a blank line followed by a
paragraph without such a label (styles are compared without their prefix letters, so `B10` then `D1` is one style; the first
labelled paragraph always counts). A later unrelated list (`Usage: 1. 2.`, `Note 1:` after an unlabelled paragraph) is not counted.
If a labelled continuation in the section's style follows **after code** (a section that ran to the end of its group, then a comment
whose first lines carry a label of that style) it is `deviation-section-split` (error, `path`, `line`), not a silent count.

A section with **no** recognised entry is `deviation-unlabelled` (error, `path`, `line`): the author must label its entries. It is
never counted as one entry.

### The sealed expectation: `products/<name>/ui/deviation-sections.toml` (owner-sealed)

    schema = "ui-deviation-sections/2"
    product = "<name>"
    [headers."apps/lockers/lk/selftest/selftest.h"]   # sorted by path; the path ends in `.h`, in the layout's own spelling
    count = 3                                         # 1..999, must equal the number of labels
    labels = ["(1)", "(2)", "(3)"]                    # the entry labels counted, distinct, so the owner can check the count

It records the expected count and does **not** excuse anything. For a header with `detected` entries (sum over its sections),
`acknowledged` entries (0 when not listed) and `tags` distinct well-formed tag ids in the file:

* `deviation-untagged` (error): `tags` < max(`detected`, `acknowledged`); fields `entries` (that maximum), `detected`,
  `acknowledged`, `tags`, `line` of the first section. So an unlisted detected section, a section that grew, and one that shrank
  while its entries are still acknowledged all count.
* `deviation-section-missing` (error): the header is listed, nothing can be detected in it (the section was deleted or
  renamed) and `tags` < `acknowledged`; also for a listed header that is not in the tree (`header` = `absent`; if a file with the
  same stem in another letter case or extension exists, `actual` names it). Deleting or renaming a section does not make its debt
  vanish.
* `deviation-unlabelled`, `deviation-section-split` as above.

Distinct ids count, not occurrences (`UI-A1` written twice is one, and the second is also `duplicate-id`).

### First file for business-apps

`deviation-sections.toml` in the tree was made by **reading** the headers of `/home/user/business-apps` (40 headers, 214 entries,
every label listed) and **must be reviewed by the owner**. Where a header has bullets or prose instead of labels, the label is a
short name chosen in the file. Whether a Rust-vs-docs note is a deviation of the C code from the oracle is the owner's call; the file
lists the notes the headers themselves call disagreements, differences or notes of RS vs C / Rust vs docs. Headers that mention a
deviation from something else (the design sketch, `jdom`, an earlier module) are not listed: `lib/fmt/fp/fp.h`, `lib/fmt/jw/jw.h`,
`lib/fmt/jpull/jpull.h`, `boot.h:83` (a closed item) and `opener_sm.h:62`.

## What the product must reword

The gate reports these today and the tagging task has to handle each (reword the prose, label it, move it into a header, or tag it):

* false positives of the heading rule (wrapped sentences and pointers that start with, or hold a heading word with a colon):
  `lib/io/pfscript/pfscript.h:12` (`deviation is a VIOLATION: ...`), `lib/ui/scenediff/scenediff.h:26`, `lib/sim/trace/trace.h:92`,
  `apps/lockers/relay/frame/frame.h:12`, `apps/lockers/lkapp/e2e/e2e.h:112`, `apps/lockers/lkadp/codeshttp/codeshttp.h:10` and `:231`,
  `apps/lockers/lkadp/synchttp/synchttp.h:11`, `apps/lockers/lk/codesfile/codesfile.h:10` (counts the doc list that follows),
  `apps/lockers/lkrx/sync/sync.h:86` (counts four more entries);
* prose sections with no label (`deviation-unlabelled`): `apps/lockers/lk/preflight/preflight.h:139` (three deviations by reading),
  `lib/fmt/jw/jw.h:5`, `lib/fmt/kv/kv.h:31`, `lib/fmt/fp/fp.h:10`, `apps/lockers/lk/audit/audit.h:12`,
  `apps/lockers/relay/frame/frame.h:132`, `apps/lockers/relay/pulse/pulse.h:120`, `apps/lockers/lkui/input/input.h:26`;
* section-like text in a `.c` file (`deviation-misplaced`): `lib/fmt/kv/tests/kv_corpus_test.c:273`,
  `lib/sim/simfs_tab/tests/simfs_tab_test.c:253-255` and `apps/lockers/lkrx/vstate/tests/vstate_rust_test.c:61` (a comment that starts
  with `differs` or `differ`);
* a bullet that is not a deviation inside a list: `apps/lockers/lk/booktext/booktext.h` (`docs: none contradicts ...`).
