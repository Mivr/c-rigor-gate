# T114: LVGL Tiny TTF glyph cache trips UBSan `-fsanitize=function` (lv_cache.c:179) in `linux_san`

Repo: `Mivr/c-rigor-gate`. Branch `task/T114` from main. Read `AGENTS.md`, `docs/third-party.md`, `rules/third_party.bzl`
(`_SAN`, `_MODE_FLAGS`, `instrument`), `third_party/lvgl/{BUCK,gate_lv_conf.h,lvgl_gate.c,lvgl_gate.h}`, and T107's plan
file for how LVGL is pinned (release tarball by sha256, file list checked).

## Why
business-apps L263 renders a TinyTTF font from memory (`lv_tiny_ttf_create_data`, LV_USE_TINY_TTF 1, file support 0,
LV_TINY_TTF_CACHE_GLYPH_CNT 128). In `linux_san` every test that reads a glyph aborts:
`lv_cache.c:179: runtime error: call to function through pointer to incorrect function type`. Release passes. The
product code is not involved: the indirect call is inside LVGL's cache, called from TinyTTF's glyph cache.

## Do
1. Reproduce in the gate alone: a selftest c_test (fixture product or the existing LVGL selftest, whichever fits) that
   creates a TinyTTF font from a small embedded TTF (use `c_embed`, T112; any small OFL/public-domain TTF you can
   build from material already in the repo or the LVGL tarball; say which) and reads glyph descriptors and draws a
   label, in `linux_release` and `linux_san`. It must fail in san today.
2. Find the exact cause: which callback type does `lv_cache` call (file:line in the pinned 9.6.0 sources), which
   function is installed (TinyTTF's or the gate glue's `lvgl_gate.c`), and the mismatching prototype.
3. Fix, in this order of preference, and say why the earlier options did not apply:
   a. the gate's own glue or config is the cause: fix it there;
   b. a minimal, recorded patch of the vendored LVGL source (only if the gate's third-party rule can apply a reviewed
      patch to the pinned tarball; if it cannot, do not invent a patch mechanism in this task: go to c);
   c. a narrow sanitizer exception for the LVGL target only: `-fno-sanitize=function` added to the LVGL third-party
      target's san/fuzz flags (nothing else, no other check, no other target), documented in `docs/third-party.md`
      with the cause, the call site and why it is harmless on the gate's ABIs; product code keeps
      `-fsanitize=function`, proven by a selftest canary where product code calls through a mismatched function
      pointer type and san still catches it.
4. The selftest from step 1 passes in both modes after the fix.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
plus the new selftest in both modes. Report the cause (file:line, both prototypes), the option taken and why, and the
outputs.

## Allowed paths
`third_party/lvgl/**`, `rules/third_party.bzl`, `selftest/**` (add fixtures; do not weaken existing ones),
`gate/tests/**`, `docs/**`, `tools/affected.toml`.

## Rules
Use `TMPDIR=/var/tmp/cache/T114/tmp`; never write `/tmp`. Build only with `tools/buck2` / `gate/tools/buck2` as the docs
say. Redirect every output to a file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never `rm`
(`cp -f`). No stash, merge or push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`,
other worktrees or other cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your
own buck2d by pid (`readlink /proc/<pid>/cwd`); never `buck2 kill`. 2 CPUs shared. No network except Buck2's pinned
downloads.
