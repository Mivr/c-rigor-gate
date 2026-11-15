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
traceback; `--today`, `--root` or `--product` missing or given twice, `--today` not an ISO calendar date, root or
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
a file that is not UTF-8 is `deviation-malformed` (`not-utf-8`). None is skipped silently.

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
| link | no white space; for `reference-bug` it must start with the baseline's literal `reference_bug_link_prefix` and match, in full, its `reference_bug_link_pattern` |
| until | a task id `[A-Z][0-9]{2,4}[a-z]?` (`T123`, `L045`, `U13`, `U04a`) or a real ISO date no later than `--today` + 366 days (`why=until-too-far`) |

Every defect is `deviation-malformed` (error) with `path`, `line`, `why` (and `id` when it was read). A malformed tag is not a
tag: it is not counted and does not count towards `deviation-untagged`. `why` codes: `bad-tag-start`, `bad-id`,
`expected-comma-or-close`, `bad-key`, `unknown-key:<key>`, `duplicate-key:<key>`, `expected-equals`, `expected-string`,
`bad-escape`, `newline-in-string`, `control-character`, `value-too-long`, `unterminated-tag`, `missing-key:<key>`,
`empty-or-padded-value:<key>`, `bad-state`, `bad-reason`, `bad-link`, `reference-bug-link-not-an-oracle-issue`, `bad-until`,
`bad-until-date`, `until-too-far`, `duplicate-id` (every occurrence after the first, with `first` = `path:line`).

## The baseline: `products/<name>/ui/deviations.toml` (owner-sealed)

Strict loader; any defect is exit 2. Exactly these keys:

    schema = "ui-deviations/2"
    product = "<name>"                          # must equal product.toml's name
    cap = 0                                     # integer 0..1000, at least the number of accepted ids
    reference_bug_link_prefix = "https://github.com/Mivr/club-apps/issues/"   # literal https:// prefix
    reference_bug_link_pattern = 'https://github\.com/Mivr/club-apps/issues/[0-9]+'   # at most 200 characters, never matches ""
    [accepted."UI-A1"]                          # one table per accepted id, sorted by id
    until = "T200"
    sha256 = "<64 lower-case hex digits>"

`sha256` is the hash of the **canonical form** of the tag: the canonical JSON (sorted keys, compact separators, ASCII only,
one trailing newline, as `jsonio.canonical_dumps`) of the object `{"id", "link", "oracle", "reason", "state" (a list in
the written order), "until"}`. It does not depend on key order, spacing or comment layout. The reference-bug pattern lives
here, not in `product.toml`, because the product config loader (`product_layout`) is strict and outside this task's paths; it
is sealed together with the baseline. The prefix is checked first, then the pattern, on a value of at most 512 characters.

The baseline is **owner-sealed**: a new accepted id, a changed tag or a higher cap needs the owner's signature (P004 8.5).
Sealing and its signature check are a later task; until then nothing in the gate verifies the seal. The ratchet only goes down.

| Finding | Severity | Meaning |
|---|---|---|
| `deviation-new` | error | a tag id not in `accepted` (the baseline must change) |
| `deviation-changed` | error | an accepted id whose tag has other fields (any field, so `until` cannot be pushed out and an id cannot be reused for another deviation) |
| `deviation-over-cap` | error | more distinct tag ids than `cap` (`count`, `cap`) |
| `deviation-removed` | info | an accepted id with no tag: delete it from the baseline |
| `deviation-expired` | error | `until` is an ISO date earlier than `--today` (the day itself is still valid; a task-id `until` never expires here, it is pinned by the baseline hash) |

## The hook for the parity judge

`judge_tags(tags, diverging)` is pure and total for any iterable of tags. The subject key of a tag is its id; `diverging` is the
set of ids whose subject really differs from the oracle. A tag in the set is `pinned-deviation` (info); a tag outside it is
`deviation-stale` (**error**). P004 8.3 says `deviation-stale` is info ("delete the tag"); it is kept an error here as a
**deliberate deviation from P004, flagged for the owner**: a stale accepted id is a reusable slot, a baseline entry for a
deviation that no longer exists that could later be filled with something else. A key naming no tag is the judge's own finding
(a divergence without a tag). Arguments of the wrong type raise `InternalError`. The judge itself is not implemented here.

## Untagged prose is debt

### Heading rule (heuristic, layer a)

A **section heading** is a comment line (after the comment decoration is removed) whose text, case-insensitively, contains one
of the words `disagreement(s)`, `deviation(s)`, `difference(s) from`, `differs from`, `deviates` (whole words) either

* in a `---- title ----` rule line (three or more dashes, a title, any dashes after), anywhere in the title, or
* at the start of the line after any run of `*`, `/`, `#`, `=`, `-` and white space, and then **ends**, or goes on with `:`, `(`,
  `,`, `.`, `;` or a dash (`Deviations: D1 ...`, `DISAGREEMENTS (Rust wins).`), or begins a paragraph (the line before it is blank,
  a rule line, or the group starts there). A wrapped sentence that merely begins with the word (`deviation is a VIOLATION: ...`
  in the middle of a paragraph) is therefore not a heading. This is a refinement of the amendment's "start of the line":
  without it a continuation line of prose is reported as a section.

A section runs from its heading to the next heading, to a `---- title ----` rule line, to an all-upper-case title line (at least
four letters, no lower-case letter, at most 80 characters) or to the end of the **group**: the run of adjacent comments with only
white space between them. A bare `---` line, a blank line between `//` runs and a comment split in two do not end it. The text
of tags is left out of the prose.

### Entry count

Entries are the union of

1. the **labelled lines at the indent of the first label** (or less), so sub-bullets and numbered steps inside an entry are
   not counted. A label is `L1`, `L1:`, `L1.`, `D1`, `N3`, `D-1`, `DISAGREE-1`, `(D4,` (one to three capitals and a number
   without leading zero, or capitals, a dash and a number), optionally after `Note`; `Note 3`; `1.`, `1)`, `1:`, `(1)`, `#1`;
   `a)`, `(a)`; roman numerals `i.`, `i)`, `(i)` in either case; and the bullets `-`, `*`, `+`, `•`, `–`. Each must be followed by
   white space and text on the same line; and
2. the **longest in-order inline chain** from 1 (`(1) ... (2) ... (3)`, `D1 ... D2`, `a) ... b)` and every other label style) over
   the heading line and the unlabelled lines at that indent.

Each (style, number) counts once, so a label that is also part of a chain is one entry; a repeated number counts again.

A section with **no** recognised entry is `deviation-unlabelled` (error, `path`, `line`): the author must label its entries.
It is never counted as one entry.

### The sealed expectation: `products/<name>/ui/deviation-sections.toml` (owner-sealed)

    schema = "ui-deviation-sections/1"
    product = "<name>"
    [headers]
    "apps/lockers/lk/selftest/selftest.h" = 3     # sorted by path; the entries the owner has acknowledged, 1..999

It records the expected count and does **not** excuse anything. For a header with `detected` entries (sum over its sections),
`acknowledged` entries (0 when not listed) and `tags` distinct well-formed tag ids in the file:

* `deviation-untagged` (error): `tags` < max(`detected`, `acknowledged`); fields `entries` (that maximum), `detected`,
  `acknowledged`, `tags`, `line` of the first section. So an unlisted detected section, a section that grew, and one that shrank
  while its entries are still acknowledged all count.
* `deviation-section-missing` (error): the header is listed, nothing can be detected in it (the section was deleted or
  renamed) and `tags` < `acknowledged`; also for a listed header that is not in the tree (`header` = `absent`). Deleting or
  renaming a section does not make its debt vanish.
* `deviation-unlabelled` as above.

Distinct ids count, not occurrences (`UI-A1` written twice is one, and the second is also `duplicate-id`).

### First file for business-apps

The file in the tree was generated from a survey of `/home/user/business-apps` (20 headers) and **must be reviewed by the
owner**: the counts are those of this heuristic. Three headers record deviations under no heading the rule can find
(`checkconfig.h` `D1/D2/D4 (DEVIATION)`, `e2e.h` Notes N1 to N4, `e2eclock.h` Notes N1 to N2); their counts were made by hand
and the gate reports them as `deviation-section-missing` until they are tagged or the owner changes the file.
