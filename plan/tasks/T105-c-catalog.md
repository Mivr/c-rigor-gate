# T105: `c_catalog` macro (G9): gettext `.pot`/`.po` → a const C catalog, hard build errors on bad translations

Repo: `Mivr/c-rigor-gate`. Branch `task/T105`. Read `AGENTS.md`, `docs/grade.md` (`buckfiles`, `structure`, `facts`,
`policy` rows), `docs/canaries.md`, `rules/c.bzl` (how `c_library` is built and how the gate already runs its own
Python actions, e.g. `fuzz_run`), `gate/rigor_lib/buckfiles.py` and its tests. The runtime the generated code targets
is business-apps `lib/fmt/i18n/i18n.h`, staged read-only at `/var/tmp/cache/T105/ref/i18n.h`. Real inputs are staged in
`/var/tmp/cache/T105/ref/`: `lockers.pot`, `lockers.bg.po` (100 msgids), `kit.pot`, `kit.bg.po` (33 msgids). Read the
header comment of `i18n.h` first: it defines the template grammar and the table layout.

## Why
The lockers UI (business-apps `lkui/*`) must show only translated phrases, Bulgarian by default. The Rust kiosk enforces
this with a guard test; in C it must be a build error, and code must reference msgids by enum, never by string.

## Build
1. A macro `c_catalog(name, pots, po, langs, source_lang, symbol, runtime)` in `rules/` (exported like `c_library`):
   - `pots`: ordered list of `.pot` files; `po`: dict lang → list of `.po` files, one per pot, same order;
     `langs`: ordered list of language codes (index = the runtime `lang`); `source_lang`: the language whose text is
     the msgid itself (no `.po` for it); `symbol`: C identifier of the generated `const i18n_catalog_t`;
     `runtime`: the i18n library target (dep of the generated library; header path derived from it or a separate
     `runtime_header` attribute, your choice, documented).
   - Produces a `c_library` named `name` whose header `<name>.h` declares `extern const i18n_catalog_t <symbol>;` and
     an enum of msgids, and whose one `.c` defines the tables. Generated sources live in buck-out only, never checked in.
   - Runs a gate-owned, stdlib-only `po2c.py` (under `gate/` or `rules/`, your choice) as a Buck action. Deterministic,
     byte-identical output for identical inputs.
2. `po2c.py` semantics (every violation is a build error naming file, line and msgid):
   - Parse the PO subset: `msgid`/`msgstr` with continuation lines (concatenated), `#` comments ignored, the header entry
     (`msgid ""`) ignored except that a `Content-Type` charset other than UTF-8 fails. Escapes `\\ \" \n \t`; any other
     escape fails. `msgctxt`, `msgid_plural`, `msgstr[n]` and `#, fuzzy` fail (unsupported). Invalid UTF-8 fails.
   - Msgids are numbered in first-appearance order over `pots` in order. A msgid repeated across pots is merged into
     one id if every language's translation is byte-identical, otherwise fails. A msgid repeated within one file fails.
   - Every pot msgid needs a non-empty `msgstr` in every non-source language. A `.po` msgid not in its pot fails.
   - Templates follow the `i18n.h` grammar exactly (`{0}`..`{9}`, `{{`, `}}`; everything else malformed → fail).
     `n_args[m]` = number of distinct placeholder indices in the source msgid; they must be exactly `0..n-1`. Every
     language's template must use the same set of indices (count of each may differ only if the source repeats one;
     state your rule). `n_args` > 10 is impossible by the grammar; assert it anyway.
   - Enum names: `<PREFIX>_<WORDS>` where PREFIX is the upper-cased `symbol`, WORDS is the source msgid with every run
     of non-`[A-Za-z0-9]` bytes turned into one `_`, upper-cased, leading/trailing `_` dropped, truncated to 48
     characters, a leading digit prefixed with `N`. A collision between two different msgids fails the build (no
     silent suffixes). Also emit `<PREFIX>__COUNT`.
   - C output: strings as literals with every non-printable-ASCII byte as a 3-digit octal escape (never `\x`, which
     swallows following hex digits); `str` is `n_msgs * n_langs` row-major per the header; `n_args` a const array; no
     non-const object; `_Static_assert` on the counts. Must compile under the business-apps flags
     (`-Werror -Wall -Wextra -Wvla -Wcast-qual`, C17) and pass the gate's facts/policy for an **L1** module (no tests,
     no mutants). Find how the gate treats an L1 package with no `c_test` today and make a `c_catalog` package grade
     clean: structure, facts, symbol policy, exports. Say what you changed and why.
3. `buckfiles` admits `c_catalog` with only literal arguments (strings, lists of strings, dict of lists of strings);
   anything else is `bad-argument` as for other macros. Check every other gate step that parses BUCK text or lists
   macros (search for the macro names) handles it, or prove it needs nothing.
4. Unit tests for `po2c.py` in `gate/tests/` covering every failure above and the octal/escape and merge rules.
5. Canaries (red with the exact rule): `catalog-empty-bg` (empty msgstr), `catalog-extra-msgid` (po msgid not in pot),
   `catalog-placeholder` (bg drops `{0}`), `catalog-name-collision`; control `catalog-ok` (PASS: two pots with one
   shared msgid, bg+en, a `c_test` in the canary that calls `i18n_format` on three ids in both languages). Use the
   canary-local copy of the i18n runtime pattern the existing canaries use for library deps (look at how canaries get
   their deps; do not reach into business-apps).
6. Docs: `docs/grade.md` (buckfiles row, and a short `c_catalog` section), `docs/canaries.md` rows.

## Acceptance (the orchestrator re-runs it)
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
plus a smoke on a business-apps clone (`git clone -q /var/tmp/src/business-apps /var/tmp/cache/T105/biz`, then
`git -C ... submodule update --init` with `-c protocol.file.allow=always -c submodule.gate.url=<your worktree>`): a
scratch package `apps/lockers/lkui/catalog/` (not committed anywhere) with the four staged files and
`c_catalog(name="catalog", pots=[lockers.pot, kit.pot], po={"bg": [...]}, langs=["bg","en"], source_lang="en",
symbol="lk_catalog", runtime="//lib/fmt/i18n:i18n")`; `gate/tools/buck2 build //apps/lockers/lkui/catalog:catalog`
on `linux_release` and `linux_san` succeeds, and the report states n_msgs (expect 130 = 100 + 33 − 3 shared) and any
enum-name collisions found on the real files (if any, stop and report them; do not invent an override mechanism).

## Report
What changed (files), the three acceptance outputs (counts), the smoke result, the generated header's first 20 enum
lines, and deviations.

## Rules
Edit only `gate/**`, `rules/**`, `docs/**`, `selftest/**`, `canaries/**`, `policy/**` (say why if you touch policy).
Use `TMPDIR=/var/tmp/cache/T105/tmp`, and never write to `/tmp`. Build only with `tools/buck2` (in the clone,
`gate/tools/buck2`). Redirect every build and test output to a file (`cmd > file 2>&1; echo rc=$?`) and read the file;
never pipe into tail or head. Launch long builds with `tools/job run` and wait with `tools/job wait`. Never use `rm`;
overwrite with `cp -f`. Keep each tool call short. A foreign `buck2 kill` may kill your daemon: just re-run. No `git
stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`,
other worktrees or other cache dirs, and never search from `/`. Do not print the environment. Kill only processes you
started, by the pid `tools/job` recorded; run `tools/buck2 kill` in the worktree and the clone when done. No sleep-poll
loops. 2 CPUs and 8 GiB, shared and loaded. No network.
