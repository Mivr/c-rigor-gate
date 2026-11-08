# T112: `c_embed` rule: a binary asset (a TTF font) as a const byte array, generated at build time

Repo: `Mivr/c-rigor-gate`. Branch `task/T112` from main. Read `AGENTS.md`, `rules/c.bzl` (`c_library`, `_check`,
`_plain_files`, `_facts`, the `generated` parameter of `_facts`), `rules/facts.bzl`, `rules/structure.bzl`,
`rigor buckfiles` (the allowed BUCK statements and keywords), `docs/product-checks.md` and the `c_library` docs,
`third_party/lvgl/gate_lv_conf.h` (LV_USE_TINY_TTF is 1, file support 0: fonts come from memory), and their tests and
selftests.

## Why
business-apps' kiosk UI is Bulgarian by default. The only built-in LVGL font is Montserrat 14 (Latin), so the UI needs
an OFL TrueType font with Cyrillic, loaded by TinyTTF from memory (`lv_tiny_ttf_create_data`). The font is about
400 KB. As a C source with a byte array it breaks the shape rules (500-line files, line length), and hand-written
hex is not reviewable. The gate needs one sanctioned way to put a binary file into a C program.

## Change
- A macro `c_embed(name, src, symbol, max_bytes = 1048576, visibility = [])` (rules file of your choice, loaded the
  same way as `c_library`). It produces a target usable in `deps` of `c_library`, `c_test` and `c_binary` exactly like a
  `c_library`, whose public header `<name>.h` (include path documented) declares
  `extern const unsigned char <symbol>[];` and `extern const size_t <symbol>_len;`. The bytes and the length are
  generated at BUILD time from `src` (a checked-in binary file in the package) by a hermetic tool in the gate (Python
  `-I`, no network). Nothing generated is checked in.
- Refuse at analysis or build time, with a clear message: `symbol` that is not a C identifier, `src` that is not a
  single file in the package, an empty file, a file over `max_bytes`, `max_bytes` over 16 MiB.
- The array is `const` (it must land in read-only data); `<symbol>_len` equals the file size; the bytes round-trip
  exactly (no terminator added to the array; if you add one for convenience, it is outside `_len` and documented).
- Gate checks: the generated source is exempt from the file-shape checks that are about hand-written code (lines per
  file, line length); it is still compiled with the same warnings and sanitizer modes, and facts/structure see one
  const object and no functions. `rigor buckfiles` accepts `c_embed` with literal arguments only. Architecture and
  layering treat a `c_embed` target as a leaf library of its package.
- Works on every platform `c_library` builds for (at least `linux_release`, `linux_san`; say which others you
  checked).
- Docs: where `c_library` is documented, plus the licensing note: an embedded asset needs its license file next to it
  in the package (the gate does not check the license text).

## Tests
gate/tests for the macro and the tool: bytes and length round-trip (including bytes 0x00, 0xFF, a file whose size is
not a multiple of any line width), every refusal above, the header text, `buckfiles` acceptance and rejection
(non-literal args). A selftest fixture product that embeds a small binary file and reads it back in a `c_test` in
both modes.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
Report the change, the outputs, and every deviation.

## Allowed paths
`rules/*.bzl`, `gate/rigor_lib/**`, `gate/tools/**` (new tool only), `gate/tests/**`, `selftest/**` (add fixtures; do
not weaken existing ones), `docs/**`.

## Rules
Use `TMPDIR=/var/tmp/cache/T112/tmp`; never write `/tmp`. Build only with `tools/buck2` / `gate/tools/buck2` as the docs
say. Redirect every output to a file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never `rm`
(`cp -f`). No stash, merge or push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`,
other worktrees or other cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your
own buck2d by pid (`readlink /proc/<pid>/cwd`); never `buck2 kill`. 2 CPUs shared. No network except Buck2's pinned
downloads.
