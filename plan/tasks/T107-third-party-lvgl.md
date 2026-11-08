# T107: gate-owned third-party LVGL 9.6.0 (software renderer, product-owned pool, no OS)

Repo: `Mivr/c-rigor-gate`. Branch `task/T107`. Read `AGENTS.md`, `docs/third-party.md` (all of it: the pin, targets,
flags, configuration, the self-test, "Adding another library"), `rules/third_party.bzl`, `third_party/extract.py`,
`third_party/mbedtls/*`, `third_party/ALLOWED_LABELS`, `third_party/RESERVED_PREFIXES`, `selftest/third_party.sh`.

## Why
business-apps (lockers kiosk, later stock) draws its UI with LVGL behind a pure scene layer: `lib/ui/uikit` (widgets,
M3-like theme) and `lib/ui/lvrender` (applies scene patches, maps input to intents) are the only product modules that
may include it. The owner accepted LVGL (business-apps design D7). The product rules forbid allocation after init and
any libc `malloc`, so LVGL must run from a pool the product hands in.

## The pin
| What | Value |
|---|---|
| Release | LVGL **9.6.0** (the version business-apps `docs/design.md` cites) |
| URL | `https://github.com/lvgl/lvgl/archive/refs/tags/v9.6.0.tar.gz` |
| sha256 | `b20ee3acc1bba13c62d854f9ebd62e4c51e0b443b1e0225892e86442defa84df` |
| size | 111467067 bytes |
| top | `lvgl-9.6.0` (7208 entries; `lvgl.h`, `lv_version.h`, `lvgl_private.h` at the top, code under `src/`) |

A copy of the tarball is at `/var/tmp/cache/T107/dl/lvgl-9.6.0.tar.gz` for `extract.py --list` and for reading the
sources; the build itself fetches the pinned URL with Buck2's `download_file` like mbedTLS (sha256 + size checked).

## Deliverables
1. `third_party/lvgl/BUCK` with `c_third_party(...)` and a `files.bzl` manifest (`*.c`/`*.h` of the unpacked dirs equal
   to the archive exactly). Unpack only what is needed (`src/` plus the top-level headers; extend `extract.py` /
   `rules/third_party.bzl` minimally if top-level files need it, keeping mbedTLS byte-identical). Compile only the
   sources the configuration uses; list the rest as not compiled with a reason per directory (drivers, libs, other
   draw backends, OS ports, file systems).
2. `third_party/lvgl/gate_lv_conf.h` (via `LV_CONF_PATH`/`LV_CONF_INCLUDE_SIMPLE`, the way mbedTLS gets its config):
   - `LV_USE_STDLIB_MALLOC LV_STDLIB_BUILTIN`, `LV_USE_STDLIB_STRING`/`SPRINTF` builtin; no static pool inside the
     library: the product hands in its pool (`LV_MEM_POOL_INCLUDE`/`LV_MEM_POOL_ALLOC` or `lv_mem_add_pool`, whichever
     9.6.0 supports; document the call). `LV_MEM_SIZE` 512 KiB default ceiling.
   - `LV_USE_OS LV_OS_NONE` (LVGL lives only on the product's UI thread). No threads, no `pthread`.
   - Software renderer only (`LV_USE_DRAW_SW`), `LV_COLOR_DEPTH 32`; every GPU/other draw unit off.
   - No file system drivers, no image decoders that need files, no `LV_USE_LOG` printf (route logs to a product
     callback or off), assert handler that does not spin forever (`abort()`-like is fine; say what).
   - Widgets: the minimal set a kiosk needs (obj, label, button, image for icons, plus flex/grid layout); the default
     theme may stay on. Say what you turned off.
   - Fonts: the built-in Montserrat glyphs have no Cyrillic, and the kiosk is Bulgarian by default. Enable
     `LV_USE_TINY_TTF` (with `LV_TINY_TTF_CACHE_GLYPH_CNT`) so a product can load a TTF it ships from memory; do NOT
     vendor a font in this task (note it as a follow-up).
   - A memory test display and test input for product tests (`LV_USE_TEST` or the 9.6.0 equivalent: a display that
     renders into a buffer, simulated touch/keys, an object-tree walk). Screenshot compare that needs a file system or
     PNG decoding stays off; products compare buffers or CRCs themselves.
3. Targets like mbedTLS: `gate//third_party/lvgl:lvgl` (the only product label), headers exported `-isystem`, the
   symbols facts file; add the label to `ALLOWED_LABELS` and `lv_`, `_lv_`, `LV_`, `lvgl_` to `RESERVED_PREFIXES`
   (and any other global prefix the compiled objects export; the facts file tells you).
4. Self-test in `selftest/third_party.sh` (same shape as mbedTLS): build in every mode mbedTLS builds in; the libc import
   set of the compiled LVGL objects reviewed (no `malloc`/`calloc`/`realloc`/`free`, no `pthread_*`, no file or
   socket calls; each remaining import with a reason in `REVIEWED_IMPORTS`); a test program that hands in a pool,
   creates a memory display (e.g. 320x240), draws a label and a button, renders, checks a few pixels or a CRC,
   simulates a click on the button and sees its event, deletes everything and checks `lv_mem_monitor` returns to the
   baseline (no leak); and that allocation past the pool fails cleanly (`lv_malloc` returns NULL, no abort).
5. `docs/third-party.md`: an LVGL section (pin, targets, config decisions, the pool call, test display, fonts, how to
   bump) and the measured numbers (objects, compiled files, library size, pool peak of the self-test).

## Acceptance
```sh
selftest/third_party.sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
All green; report the numbers. Note for later (not this task): LVGL event callbacks are third-party callback
registrations; T106 is making `indirect-cycle-possible` precise for gate-owned libraries.

## Allowed paths
`third_party/lvgl/**`, `third_party/ALLOWED_LABELS`, `third_party/RESERVED_PREFIXES`, `third_party/extract.py` and
`rules/third_party.bzl` (minimal, mbedTLS unchanged), `third_party/BUCK`, `selftest/third_party.sh`,
`selftest/third_party/**` (new), `docs/third-party.md`, `gate/tests/**` (only for rule/extract changes).

## Rules
Use `TMPDIR=/var/tmp/cache/T107/tmp`; never write `/tmp`. Build only with `tools/buck2` / `gate/tools/buck2` as the
docs say. Redirect every output to a file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never
`rm` (`cp -f`). No stash, merge or push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs; never search from `/` or `/var/tmp`. Do not print the
environment. Kill only your own buck2d by pid (`readlink /proc/<pid>/cwd`); never `buck2 kill`. 2 CPUs shared. No
network except the build's own pinned `download_file`.
