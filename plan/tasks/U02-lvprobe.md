# U02: `gate//ui/lvprobe`, the rendered-stage observer (P004 T1xx.02)

Repo `Mivr/c-rigor-gate`, branch `task/U02`. Read first: `plan/tasks/U00-ui-gate-rules.md`; P004 §2.1, §3.3, §4.2,
§16 (H6); `plan/metrics/ui-probe-2026-11-13.md` sections 1, 3, 4 and its "settle" and ink-attribution notes;
`third_party/lvgl/` (BUCK, `gate_lv_conf.h`, `lvgl_gate.h`); `docs/third-party.md`; `docs/ctest.md`.

## Why
Seven of the eleven escaped kiosk defects were in the renderer while the scene was right. Every later judge needs
facts taken from what LVGL actually laid out and drew, through production LVGL paths (layout, `lv_text_get_size`, the
indev hit-test, the real flush), never a re-implementation that can drift (H6).

## Do
A C library `ui/lvprobe/` (public header `ui/lvprobe/lvprobe.h`) over gate LVGL, static memory, bounded, no product
types. Given an `lv_display_t *` whose screen has been drawn into a caller-supplied XRGB8888 buffer, it provides:
1. **O3 tree walk**: for every object in depth-first order: a stable index, parent index, class name, absolute
   coords, hidden, clickable, the ancestor that clips it, bg colour and opa; for labels the text, resolved font
   (line height and a font identity the caller can map), text align, long mode, laid-out line count, natural size
   from `lv_text_get_size`, and the union box of the per-glyph ink boxes.
2. **Verdict facts per node**: `clipped` (glyph union outside the label's visible box or a clip ancestor), `ink`
   count and ink box by hide/redraw/diff/unhide attribution, with the "once per structure class" split left to the
   caller (expose it as a separate call; it is 96% of the cost).
3. **Hit injection**: a press+release at a point through a real LVGL pointer indev, returning the object that
   received `LV_EVENT_CLICKED` (or none). No own hit-test.
4. **Frame facts**: frame CRC (FNV-1a over the buffer), per-object region hash, luminance samples of glyph ink and
   background for a node (for contrast), an RGBA crop into a caller buffer.
5. **Lifecycle log**: object create/delete events since the previous call (bounded ring; overflow is reported, not
   dropped silently).
6. A line-oriented **text encoder** of 1, 2 and 4 into a caller buffer (one fact per line, fixed field order,
   documented in `docs/ui-lvprobe.md`). Truncation is an error return, never silent.

## Not in this task
`model.h`, the probe main and the macro (U03); any judge or Python; anything product-specific; PNG.

## Acceptance
Tests through the public header on LVGL with a memory display, in `ui/lvprobe/tests/`, run by
`tools/buck2 test //ui/lvprobe/...` in release and in the san mode (`--target-platforms toolchains//:linux_san`):
a hidden label has ink 0; a label in a box too small is `clipped` and one that fits is not; a full-parent transparent
clickable object steals a centre tap from the button under it (the F3b canary) and the same tap reaches the button
when the overlay is not clickable; a Cyrillic `Й` in a tight row is clipped and in a row of the font's line height is
not; two renders of one tree give equal CRCs and a one-pixel change gives a different CRC and region hash; the
lifecycle log reports a node created and deleted between two calls; encoder truncation returns the error.
Each test must be seen failing once against a deliberately broken build (say which, in the report). Run the tests
twice in a row. Then `python3 -I -B gate/tests/run_parallel.py` and `python3 -I tools/affected.py --check`.

## Allowed paths
`ui/lvprobe/**`, `docs/ui-lvprobe.md`, `tools/affected.toml` (add rules for the new paths only),
`third_party/lvgl/**` only to export LVGL headers or symbols the probe needs (say exactly what and why).
