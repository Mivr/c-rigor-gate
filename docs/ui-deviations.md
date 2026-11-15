# UI deviations: tags, baseline and ratchet (U13, P004 T1xx.13)

Every place where the C kiosk knowingly differs from its Rust oracle is a **tag** in a C comment of a product header.
`rigor ui-deviations` reads the tags, checks them strictly, counts them against an owner-sealed baseline and reports
header prose that lists deviations without a tag. Code: `gate/rigor_lib/ui_deviations.py`; tests:
`gate/tests/test_ui_deviations*.py`. Not in this task: tagging the product's headers, the parity judge, the signature
check of the baseline and the wiring into `rigor grade`.

## Command

    rigor ui-deviations --root <product tree> --product products/<name>/product.toml --today YYYY-MM-DD [--out FILE]

Exit 0 = no error finding, 1 = an error finding, 2 = the gate could not decide (the house error: one line on stderr, no
traceback; `--today` not an ISO calendar date, root or product.toml unreadable, baseline missing or malformed).
`--today` is the only date the check knows; the wall clock is never read. The baseline is read from
`<directory of product.toml>/ui/deviations.toml`. The output is the house result shape (findings sorted by their
canonical JSON) and is byte-identical for identical inputs, whatever the order of the files.

## What is scanned

Every file whose name ends in `.h` (any letter case) under `--root` that `product.toml`'s layout copies
(`product_layout.classify == copy`: gate paths such as `third_party/**`, `tools/**`, `gate/**`, `.git*` and the
product's own excludes are left out). Symlinked headers, symlinked directories that would be graded and
non-regular `.h` files are `deviation-malformed` (`why` = `symlink` / `not-a-regular-file`, line 0): they cannot be read
safely and are never skipped silently. A header that is not UTF-8 is `deviation-malformed` (`not-utf-8`).

## Where a tag may stand

Only inside a C comment: `/* ... */` or a run of `//` lines. A comment-looking text in a string or character literal is
not a comment and a tag there (or in code) is **ignored**. Line splices (backslash-newline) and `\r\n`/`\r` line ends
are read like C does. A tag inside `#if 0` is found when it stands in a comment (C removes comments in translation phase
3, before directives run); code inside `#if 0` is code and is ignored. An unterminated comment, string or character
literal is `deviation-malformed` (`unterminated-comment`, `unterminated-literal`) because what follows cannot be trusted.
In a block comment the leading `*` of a line is decoration. `@deviation` counts as a tag start only when it is not
preceded by `[A-Za-z0-9_@]` and not followed by `[A-Za-z0-9_]` (so `@deviations` in prose is not one); anything else
that starts `@deviation` and is not followed by `(` is `deviation-malformed` (`missing-paren`).

## Grammar

    @deviation(<id>, oracle="<what in the oracle>", state="<state list>", reason="<reason>", link="<link>", until="<until>")

White space (including line breaks and comment decoration) may stand between the tokens. Exactly the five keys, each
once, in any order; a value is a double-quoted string on one line (escapes `\"` and `\\` only, no control character),
non-empty and without leading or trailing white space.

| Part | Rule |
|---|---|
| id | `[A-Z][A-Z0-9]*-[A-Z0-9.-]+`, unique in the product |
| oracle | any text |
| state | comma-separated names, each `[A-Za-z0-9][A-Za-z0-9_.:/-]*` (spaces after commas allowed), no repeats |
| reason | one of `intentional`, `substrate`, `reference-bug` |
| link | no white space; for `reference-bug` it must match, in full, the product's `reference_bug_link_pattern` (an issue of the oracle's repository) |
| until | a task id `[A-Z][A-Z0-9]*-?[0-9]+` (`T104`, `U13`) or a real ISO date |

Every defect is `deviation-malformed` (error) with `path`, `line`, `why` (and `id` when it was read). A malformed tag is
not a tag: it is not counted and does not count towards `deviation-untagged`. `why` codes: `missing-paren`, `bad-id`,
`expected-comma-or-close`, `bad-key`, `unknown-key:<key>`, `duplicate-key:<key>`, `expected-equals`, `expected-string`,
`bad-escape`, `newline-in-string`, `control-character`, `unterminated-tag`, `missing-key:<key>`,
`empty-or-padded-value:<key>`, `bad-state`, `bad-reason`, `bad-link`, `reference-bug-link-not-an-oracle-issue`,
`bad-until`, `bad-until-date`, `duplicate-id` (every occurrence after the first, with `first` = `path:line`).

## Debt accounting

`products/<name>/ui/deviations.toml` (strict loader; any defect is exit 2) holds exactly:

    schema = "ui-deviations/1"
    product = "<name>"                 # must equal product.toml's name
    cap = 0                            # integer >= 0, at least the number of accepted ids
    accepted = []                      # sorted, unique, valid ids
    reference_bug_link_pattern = '...' # a regular expression, matched against the whole link

It is **owner-sealed**: a new accepted id or a higher cap needs the owner's signature (P004 8.5). Sealing and its
signature check are a later task; until then nothing in the gate verifies the seal. The ratchet only goes down.

| Finding | Severity | Meaning |
|---|---|---|
| `deviation-new` | error | a tag id not in `accepted` (the baseline must change) |
| `deviation-over-cap` | error | more distinct tag ids than `cap` (`count`, `cap`) |
| `deviation-removed` | info | an accepted id with no tag: delete it from the baseline |
| `deviation-expired` | error | `until` is an ISO date earlier than `--today` (the day itself is still valid; task ids never expire here) |
| `deviation-untagged` | error | see below |

### The hook for the parity judge

`judge_tags(tags, diverging)` is pure. The subject key of a tag is its id; `diverging` is the set of ids whose subject
really differs from the oracle. A tag in the set is `pinned-deviation` (info); a tag outside it is `deviation-stale`
(error: it no longer diverges, delete it). A key naming no tag is the judge's own finding (a divergence without a tag).
Arguments of the wrong type raise `InternalError`. The judge itself is not implemented here.

## Untagged prose is debt

A **section** starts at a comment line whose text (after the decoration, optional `--`/`----` and spaces) begins with the
upper-case word `DISAGREEMENTS` and runs to the next line that begins with `---` or to the end of the comment (for `//`
lines, the end of the run of consecutive `//` lines). A mention of the word elsewhere in a line is not a heading.

Entries of a section are the larger of

1. the lines that begin with a label: `L1`/`SC12` (one to three capitals and one to three digits), `1.`, `1)`, `(1)` or a
   `-`, `*`, `+` bullet, each followed by white space and text, and
2. the longest in-order chain `(1)`, `(2)`, `(3)` ... anywhere in the section text (the inline style),

and **one** if neither is found (the prose is one undeclared deviation; a section is never silently free). A header with
sections whose entries add up to more than its number of well-formed tags gets `deviation-untagged` (`path`, `line` of
the first heading, `entries`, `tags`).

On the three real headers of business-apps (copies with recorded sha256 in `gate/tests/data/ui_deviations/`): `screens.h`
12 entries (labels `L1`..`L12`), `selftest.h` 3 (inline `(1)`..`(3)`), `preflight.h` 1 (prose only).
