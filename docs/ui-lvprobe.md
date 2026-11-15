# `gate//ui/lvprobe`: the rendered-stage observer (U02, P004 T1xx.02)

`ui/lvprobe/` is a gate-owned C library over gate LVGL (`gate//third_party/lvgl`) that reads what LVGL laid out and
drew: P004 §2.1 stage O3 (the object tree after layout) and O4 (the framebuffer). Every later `ui-*` judge takes its
facts from here, through the `frame` seam of the probe (`ui/model/probe_frame.c`, docs/ui-model.md). Header:
`ui/lvprobe/lvprobe.h` (the only interface; `lvprobe_int.h` is shared by the library's own files). Target:
`gate//ui/lvprobe:lvprobe`. Tests: `ui/lvprobe/tests/`.

## What the facts mean

`drawn`, `glyphs`, `visible` and `clipped` say **where LVGL's own draw code would place the glyphs** of a label and
the clip it would draw them with. They are not a visibility verdict: occlusion by objects drawn later, corner masks
(`clip_corner` with a radius) and transform layers are **not modelled**. Coordinates and glyph boxes are untransformed
(style transforms are not applied). Pixels (ink, region hashes, CRC, crops) are what LVGL really rendered.

## Production paths, and every mirror

The probe takes its facts from LVGL's own code wherever LVGL exposes it (H6):

| Fact | Taken from |
|---|---|
| coords, flags, styles | `lv_obj_get_coords`, `lv_obj_is_hidden`/`_clickable`, `lv_obj_get_style_*` of a settled display |
| laid-out size | `lv_label_t.text_size` (what `lv_label` laid out) |
| natural size | `lv_text_get_size_attributes` of the label's own text, no width limit |
| glyph boxes, visible box, `drawn`, `align_drawn` | `lv_obj_redraw` of the label into a probe-owned layer that is never rendered or flushed (`opa` = the layer opacity `lv_obj_refr` would hand it); LVGL's `draw_main` creates the draw task; `lv_draw_label_iterate_characters` on it, clip opened, places every glyph; the task's `clip_area` is the visible box; the tasks are freed with `lv_draw_cleanup_task` and the label's `rendered` mark is restored |
| hit (injection) | the pointer indev: `lv_indev_read` press and release, LVGL's own search and events |
| hit (query) | `lv_indev_search_obj` |
| ink | a real refresh with the node not drawn (its own `hidden` bit), a real refresh with it, the pixel diff |
| pixels | the display's single full-size buffer the real flush wrote |

Where LVGL has no entry point, the probe repeats LVGL's logic. Each repetition is pinned by a differential test
against real pixels or real events, so an LVGL upgrade that changes the logic fails a test:

| Mirror (LVGL source) | Pinned by |
|---|---|
| clip chain: display area cut by each ancestor's child clip box, coords or coords + ext when overflow is visible (`lv_obj_redraw`, lv_refr.c:105) | `lvprobe_diff/glyphs_match_the_render_under_parents` (scrolled, `opa_layered`, `clip_corner` parents, off-screen) and `..._in_every_long_mode`: rendered ink box = glyphs cut by the visible box |
| draw chain: hidden, `opa_layered` <= `LV_OPA_MIN`, transform scale <= 0, a parent's layer opacity <= `LV_OPA_MIN` (`lv_obj_refr`, `lv_obj_redraw`) | `lvprobe_diff/not_drawn_means_no_pixels` |
| layer opacity: every `opa` below `LV_OPA_MAX` mixed with `LV_OPA_MIX2` (`lv_obj_refr`) | `lvprobe_diff/not_drawn_means_no_pixels` (a label of own `opa` 1) |
| `bg_opa_drawn`: `bg_opa`, inherited `opa`, own and ancestors' `opa_layered`, combined so that a factor at or above `LV_OPA_MAX` is opaque | `lvprobe_diff/bg_opa_drawn_matches_the_pixel`: exact under `opa`; under an `opa_layered` parent LVGL composes a sub-layer and the pixel is **2 levels** off the model (measured) |
| not-drawn `clipped`: no part of the content box survives the clip chain (`draw_main`, lv_label.c:908) | `lvprobe_diff/not_drawn_means_no_pixels` (padded label) |
| `label_flags` (`get_label_flags`, lv_label.c:1516) and the DOTS laid-out size (`lv_label_refr_text`) | `lvprobe_diff/glyphs_match_the_render_in_every_long_mode` (DOTS width against the rendered `AA...`) |
| line count = (h + line space) / (line height + line space) | the same test (wrapped rows against the rendered rows) |
| `full_text` from `dot_begin`/`dot[]` (`lv_label_set_dots`) and `LV_LABEL_DOT_BEGIN_INV` (lv_label.c:33) | `lvprobe_label/long_modes_dots_scroll_and_clip` |
| tap blocked: no display, disabled, `prev_scr` (`lv_indev_read`), `wait_until_release` (`indev_proc_press`) | `lvprobe_hit/a_tap_during_a_screen_load_animation_is_blocked` (LVGL's own test mouse agrees; only `scr_to_load` set is processed) |
| query order sys, top, active, bottom (`pointer_search_obj`) | `lvprobe_hit/the_hit_query_agrees_with_the_tap_and_fires_nothing` |
| indev reset of the click streak and timestamps (private fields) | `lvprobe_hit/three_taps_are_three_single_clicks` |

## Calls and the seam

| Call | Contract part | Cost |
|---|---|---|
| `lvprobe_open(p, disp, &cfg)` / `lvprobe_close(p)` | setup | one event descriptor per object |
| `lvprobe_map_font(p, font, id)` | font identities (up to 16) | |
| `lvprobe_settle(p, &flushed)` | one `lv_refr_now`: animations advance by the ticks elapsed, then layout and dirty areas (no other timer); `flushed` false = a quiet frame | one refresh |
| `lvprobe_walk(p)` | 1 (O3 tree), `clipped` (2); needs a settled display | no render, no flush |
| `lvprobe_ink(p, i)` | 2 (ink), 4 (luminance samples) | two refreshes (nodes LVGL does not draw: none) |
| `lvprobe_hit(p, x, y, &hit)` | 3, input injection | one press and release; product handlers run |
| `lvprobe_hit_test(p, x, y, &node, &obj)` | 3, query: what LVGL's search finds, no event sent | |
| `lvprobe_frame(p)`, `lvprobe_frame_crc(p)` | 4 (CRC, region hashes); needs a settled display | no redraw |
| `lvprobe_crop(p, box, rgba, cap, &len)` | 4 (RGBA crop) | |
| `lvprobe_life(p, out, cap, &n, &lost)`, `lvprobe_life_pending(p)` | 5; **call it every frame** | |
| `lvprobe_encode_head`, `lvprobe_encode_node`, `lvprobe_encode` | 6 | |

Seam loop per frame: `lvprobe_life` until `lvprobe_life_pending` is 0; `lvprobe_settle` until `flushed` is false;
`lvprobe_walk`; then `lvprobe_frame`, `lvprobe_ink`, `lvprobe_hit_test`/`lvprobe_hit` as needed; encode the head and
then node by node into the reply buffer. After a tap, settle again before the next walk or frame.

Errors. **Settle and retry** (the state moved under the call): `LVPROBE_ERR_UNSETTLED` (settle), `LVPROBE_ERR_STALE`
(walk again), `LVPROBE_ERR_BLOCKED` (settle or advance time, then tap again), `LVPROBE_ERR_UNSTABLE` (settle and retry
once; again unstable: report the node as unmeasurable), `LVPROBE_ERR_GONE` (walk again), `LVPROBE_ERR_TRUNC` (a larger
buffer or node by node). **Fatal for the session**: `LVPROBE_ERR_FULL` (a capacity), `LVPROBE_ERR_FORMAT` (the display
is not one full-size XRGB8888 buffer in DIRECT mode, or has no refresh timer), `LVPROBE_ERR_LVGL`,
`LVPROBE_ERR_UNSUPPORTED` (a label LVGL draws through a sub-layer), `LVPROBE_ERR_ARG`. **Data lost**:
`LVPROBE_ERR_OVERFLOW` (lifecycle events did not fit the ring).

## Configuration and storage

`lvprobe_config_t` gives the probe its storage and capacities: `nodes`/`max_nodes` (default 512, at most 32767),
`text`/`text_bytes` (default 16384, all label texts of one walk), `life`/`life_cap` (default 1024: a screen switch of
512 objects deleted and 512 created), `screens`/`max_screens` (default 16), `scratch`/`scratch_px` (pixels for ink: a
node's box + ext draw size; width x height always suffices), and `indev` (below). Fixed: depth 32, 16 fonts.
`lvprobe_t` itself is small (no capacity-sized array). The lifecycle ring drains in chunks: `lvprobe_life` copies at
most `cap` entries, oldest first, and keeps the rest; `lost` counts only what the ring could not hold.

`lvprobe_close` is safe in any order: it looks the display and the indev up in LVGL's own lists (by address) and
touches neither when they are gone.

LVGL pool: one event descriptor per observed object, one on the display, the probe's indev when it creates one; a walk
gives back every byte it takes (pinned by `lvprobe_diff/a_walk_leaves_lvgl_as_it_was`); ink allocates nothing and
leaves every style list as it was (`lvprobe_ink/ink_leaves_styles_and_the_pool_as_they_were`).

## Definitions

* **Walk order and index.** Bottom layer, active screen, top layer, sys layer; each depth-first pre-order. A node's
  index is its position in that order, nothing more: **judges key nodes through the scene (O2), never through the
  index**. `parent`, `clip` and `scroll` are indexes, `-1` for none; a root has depth 0.
* **Liveness.** A stored object pointer is used only when a fresh traversal from the display's screens and layers
  reaches it **and** it still carries the probe's event callback; nothing else is dereferenced. A deleted object the
  probe saw is `obj` NULL. If the app removed the probe's callback and an object at the same address appeared since,
  that object lacks the callback (under an observed parent its creation would have changed the generation instead):
  `LVPROBE_ERR_GONE` (`lvprobe_ink/a_reused_address_is_gone`).
* **Clip ancestor, scroll context.** `clip`: the nearest ancestor whose child clip box does not contain the coords.
  `scroll`: the nearest ancestor with the scrollable flag and content beyond its box; `scroll_x`/`scroll_y` its
  offsets. An item a list scrolled out has `clip` and `scroll` = the list, which tells it from text that does not
  fit. Labels in a list are labels like any other; LVGL's roller and list widgets are not in the gate's configuration.
* **Background.** `bg` is `lv_obj_get_style_bg_color_filtered`; `bg_opa_drawn` as in the mirror table; `bg_grad`,
  `bg_image` say a gradient or a bg image is set.
* **Labels.** `lv_label` and subclasses. `text` is what LVGL draws; `full_text` the label's own text (DOTS mode
  replaced its end with dots: `dotted`). `natural` is the size of `full_text` without limit; `laid_out` and `lines`
  describe what is drawn. `align` is the style value, `align_drawn` the draw task's. `missing` counts placeholder
  glyphs.
* **Visible box per long mode** (`draw_main`): WRAP and DOTS: the coords widened by the ext draw size (line height / 4)
  left, top and right, the bottom cut at the content box, all cut by the clip chain. CLIP, SCROLL, SCROLL_CIRCULAR: the
  content box cut by the clip chain. SCROLL_CIRCULAR draws the text twice; both copies are in `glyphs`.
* **`clipped`.** Drawn: the glyph union is not inside the visible box. Not drawn although nothing hides it or makes it
  transparent: the text takes room and no part of its content box survives the clip chain. Otherwise not clipped.
* **Ink.** On a settled display, for a node LVGL draws: save its box (coords + ext draw size, inside the display),
  invalidate it and set its own `hidden` bit directly (`lv_obj_refr` skips it and its subtree; unlike
  `lv_obj_set_hidden` no layout is marked and no focus moves), refresh, diff, clear the bit, invalidate, refresh.
  `LVPROBE_ERR_UNSTABLE` (and `unstable`, no ink) when a style transition of the node is running (refused before
  anything is touched), a refresh flushed nothing or left the display unsettled, any walked node's coords, the focus or
  the restored pixels changed, or objects were created or deleted. Ink is subtree ink inside the node's box: a child
  drawn outside it (overflow visible beyond the ext draw size) is not counted. A node LVGL does not draw has ink 0.
* **Luminance samples, CRC, crop.** As before: `ink_lo`/`ink_hi`, `bg_lo`/`bg_hi` by `2126 R + 7152 G + 722 B`;
  FNV-1a over B, G, R of each pixel; RGBA8888 rows of a box inside the display.
* **Lifecycle log.** Creation under an observed object and deletion of one are logged from LVGL's events; a new screen
  (`lv_obj_create(NULL)` sends no event) is found at the next life, walk, ink, hit or frame call and its subtree logged
  as created with `late=1`. A deleted child keeps its parent's index when the parent went first.
* **Hit injection.** The indev is reset before each tap (`lv_indev_reset`, the click streak, timestamps, pressed and
  long-press state), so every tap is a first single click. Before the tap `LVPROBE_ERR_BLOCKED` exactly when LVGL would
  not process the press (mirror table); a point outside the display is `LVPROBE_ERR_ARG`. After the tap, if LVGL did
  not process the release (a press handler started a screen-load animation), the probe takes the pressed state back,
  resets the indev and returns `LVPROBE_ERR_BLOCKED`. A press handler that calls `lv_indev_wait_release` is processed
  by LVGL on the release: the tap is `pressed` but not `clicked`. `pressed_obj` is LVGL's pressed object, `obj` the
  one that got `LV_EVENT_CLICKED`.
* **Which indev.** With `cfg.indev` (the product's pointer indev, on the same display) the taps go through it: only
  its read callback is replaced for the two reads of a tap and put back (its user data, display, settings and event
  callbacks stay; the product's read callback is not called during a tap); the probe finds itself from its own event
  callback on the indev. With NULL the probe creates a pointer indev in event mode with LVGL's defaults.
* **Hit query vs injection.** `lvprobe_hit_test` asks LVGL's search which object is under the point and sends no
  input event (an object with `LV_OBJ_FLAG_ADV_HITTEST` gets LVGL's `LV_EVENT_HIT_TEST`, which is part of the search);
  `lvprobe_hit` presses and releases, so states, focus and the product's handlers change.

## What the probe changes in the product

One event descriptor per object and on the display (and on the product's indev); extra refreshes and flushes
(`lvprobe_settle`, two per `lvprobe_ink`); the dry redraw runs each label's draw events once more per walk (tasks a
product handler adds there are freed, never drawn; an object it creates makes the walk `LVPROBE_ERR_STALE`); taps run
the product's input handlers. Nothing else: no style, flag, focus or layout change survives a call.

## Text format (`lvprobe_encode*`)

Records of the ui-probe/1 grammar (docs/ui-model.md): one fact per line, LF-terminated, fields separated by single
TABs in a fixed order and number, only printable ASCII. Inside a field `\\` is a backslash, `\t` a TAB, `\n` an LF and
`\xHH` (lowercase) every other byte outside 0x20..0x7e, every UTF-8 byte included (Bulgarian text round-trips:
`lvprobe_io/the_encoder_writes_valid_records`). Integers decimal, colours 6 lowercase hex digits, hashes 8. A box field
is `x1,y1,x2,y2` or `-`; a node's own coords are four fields, always numbers (a zero-size node shows its position).

| Line | Fields | Order |
|---|---|---|
| `lvprobe` | 3 | `lvprobe`, `1`, nodes |
| `frame` | 4 | `frame`, w, h, crc (after `lvprobe_frame`) |
| `node` | 20 | `node`, i, parent, depth, class, x1, y1, x2, y2, hidden, clickable, clip, scroll, scroll_x, scroll_y, bg, bg_opa, bg_opa_drawn, bg_grad, bg_image |
| `label` | 15 | `label`, i, font id or `-`, line_h, align, align_drawn, long, dotted, lines, natural_w, natural_h, laid_w, laid_h, text, full_text |
| `fit` | 7 | `fit`, i, drawn, glyphs box, visible box, missing, clipped |
| `ink` | 9 | `ink`, i, unstable, count, box, ink_lo, ink_hi, bg_lo, bg_hi (empty after unstable `1`) |
| `region` | 3 | `region`, i, hash (after `lvprobe_frame`) |

`lvprobe_encode_head` writes `lvprobe` and `frame`, `lvprobe_encode_node` the lines of one node, `lvprobe_encode`
everything; the seam streams head and nodes into its reply. Each call needs `cap` > the text length (a NUL follows);
otherwise `LVPROBE_ERR_TRUNC`, an empty string, and `*len` = the exact length needed. Bound: the lines of one node take
at most `LVPROBE_LINE_FIXED` (1024) + 4 x (bytes of class name + text + full text) bytes (every number at most 11
characters, every escaped byte at most 4).

## LVGL headers

The probe includes LVGL private headers through `gate//third_party/lvgl:lvgl_private_headers`
(`c_third_party_private_headers`, docs/third-party.md). It reads `lv_obj_class_t.name`, `lv_obj_t` (`hidden`,
`rendered`, layout bits, style list), `lv_label_t`, `lv_draw_task_t`, `lv_draw_glyph_dsc_t`, `lv_display_t` and
`lv_indev_t`, and writes only `lv_obj_t.hidden` and `.rendered` (restored), the probe layer and the indev's read
callback (restored) and reset fields.

## Tests (`ui/lvprobe/tests/`)

`tools/buck2 test //ui/lvprobe/...` in release and san: six binaries over `testkit` (320x240 memory display, an open
probe, a monospace font of solid glyphs so pixel facts are exact, helpers that read LVGL's pool and layer list). Each
item of the review was seen failing against its own broken build (the report lists them).

## Limits

* Occlusion, corner masks and transform layers are not modelled in `drawn`/`clipped` (see the top).
* Only label draw tasks give glyph facts; images and style symbols are ink, not glyphs.
* `bg_opa_drawn` under an `opa_layered` ancestor is 2 levels off the rendered pixel (measured).
* Ink misses children drawn outside the node's box.
* The walk covers what is shown; other screens only feed the lifecycle log.
