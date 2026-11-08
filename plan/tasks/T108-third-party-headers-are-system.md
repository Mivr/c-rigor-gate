# T108: product scanners treat gate-owned third-party headers like toolchain headers

Repo: `Mivr/c-rigor-gate`. Branch `task/T108` from main (after T107 merges: base on main with T107). Read `AGENTS.md`,
`docs/product-checks.md` (the semantic checks, `reserved-macro`, how toolchain locations are skipped),
`gate/rigor_lib/facts_semantic.py`, `facts_modes.py` (`--system-root`), `semantic_table.py`, the rules that pass
system roots (`rules/*.bzl`), `docs/third-party.md` (LVGL, the "known gap" step in `selftest/third_party.sh`), and their
tests.

## Why
T107 vendored LVGL 9.6.0. Any product unit that includes `lvgl.h` gets 15 `reserved-macro` findings from macros LVGL's
own headers define (`_LV_CONCAT`, `_PARA`, `_LV_EVENT_LAST`, `_LV_FLEX_*`, `_LV_LL_READ*`, `__LV_UEFI_*_H__` guards), so
`semantic-suppressions` can never pass for `lib/ui/uikit` and `lib/ui/lvrender`. Those definitions are not product
code. mbedTLS headers would hit the same class if they used reserved names.

## Change
- Tokens and directives located in a gate-owned third-party header (the exported header tree of any label in
  `third_party/ALLOWED_LABELS`, wherever Buck2 materialises it) are treated exactly like toolchain-header locations by
  every product facts scanner that skips toolchain locations today (semantic, and any other scanner with the same
  notion: check `facts_*.py`). The cleanest way is to pass those roots as extra `--system-root`s from the rule that
  builds a product unit's facts, derived from its third-party deps; say what you chose.
- A product `#define`/`#undef` of a name that a third-party header also defines in that unit stays `reserved-macro`
  (same as for toolchain headers), so a product cannot redefine `LV_*` or `MBEDTLS_*` behind the library's back.
- Fail closed: a third-party root that cannot be resolved keeps today's behaviour.
- Turn the T107 "known gap" step in `selftest/third_party.sh` into a green case (a product unit including `lvgl.h` passes
  `semantic-suppressions`), and add a red case (a product unit that `#define _LV_CONCAT ...` or `#undef LV_COLOR_DEPTH`
  after including `lvgl.h` gets `reserved-macro`). Update `docs/product-checks.md` and `docs/third-party.md`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/third_party.sh
selftest/product_checks.sh
selftest/canaries.sh
```

## Allowed paths
`gate/rigor_lib/facts_*.py`, `gate/rigor_lib/semantic_table.py`, `rules/*.bzl` (minimal), `gate/tests/**`,
`selftest/third_party.sh`, `selftest/third_party/**`, `selftest/product_checks.sh` and its fixtures (add-only),
`docs/product-checks.md`, `docs/third-party.md`.

## Rules
Use `TMPDIR=/var/tmp/cache/T108/tmp`; never write `/tmp`. Build only with `tools/buck2` / `gate/tools/buck2` as the docs
say. Redirect every output to a file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never `rm`
(`cp -f`). No stash, merge or push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`,
other worktrees or other cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your
own buck2d by pid (`readlink /proc/<pid>/cwd`); never `buck2 kill`. 2 CPUs shared. No network except Buck2's pinned
downloads.
