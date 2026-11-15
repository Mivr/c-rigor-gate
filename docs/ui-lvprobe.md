# `gate//ui/lvprobe`: the rendered-stage observer (U02, P004 T1xx.02)

`ui/lvprobe/` is a gate-owned C library over gate LVGL (`gate//third_party/lvgl`) that reads what LVGL laid out and
drew: P004 §2.1 stage O3 (the object tree after layout) and O4 (the framebuffer). Every later `ui-*` judge takes its
facts from here. Header: `ui/lvprobe/lvprobe.h` (the only interface; `lvprobe_int.h` is shared by the library's own
files). Target: `gate//ui/lvprobe:lvprobe`. Tests: `ui/lvprobe/tests/`.

## Why production paths only (H6)

Seven of the eleven escaped kiosk defects were in the renderer while the scene was right, and a re-implemented
hit-test or layout drifts from LVGL (P004 §16 H6). The probe computes nothing LVGL computes:

| Fact | Taken from |
|---|---|
| coords, flags, styles | `lv_obj_get_coords`, `lv_obj_is_hidden`/`_clickable`, `lv_obj_get_style_*` of a settled display (LVGL's own layout ran) |
| laid-out size, lines | `lv_label_t.text_size` (what `lv_label` laid out); in DOTS mode `lv_text_get_size_attributes` of the dotted text with the attributes `lv_label_refr_text` uses (a mirror of `get_label_flags`, lv_label.c:1516) |
| natural size | `lv_text_get_size_attributes` of the label's own text (dots reverted), no width limit |
| glyph boxes, visible box | the label is redrawn with `lv_obj_redraw` into a layer the probe owns, which is never rendered or flushed; LVGL's own `draw_main` creates the label draw task there; `lv_draw_label_iterate_characters` on that task, with its clip opened, places every glyph (`letter_coords`); the task's `clip_area` is the visible box; the tasks are freed with `lv_draw_cleanup_task` |
| hit | the product's pointer indev (or the probe's): LVGL's `lv_indev_read` press and release and its own object search; the pressed object is `pointer.act_obj` after the press, the clicked one the parameter of `LV_EVENT_CLICKED` on the indev |
| pixels | the display's one full-size buffer, which the real flush wrote |

The one piece of LVGL logic the probe mirrors is the clip chain handed to `lv_obj_redraw` for a label: the display
area cut by each ancestor's child clip box (its coords, or coords + ext draw size when overflow is visible), which is
what `lv_obj_redraw` passes down (lv_refr.c:105). Style transforms are not applied: coords and glyph boxes are
untransformed.

## Calls

| Call | Contract part | Cost |
|---|---|---|
| `lvprobe_open(p, disp, indev, scratch, scratch_px)` / `lvprobe_close(p)` | setup; opening an open probe is `LVPROBE_ERR_ARG` | one event callback per object |
| `lvprobe_map_font(p, font, id)` | the caller's font identities (up to 16) | |
| `lvprobe_settle(p, &flushed)` | `lv_refr_now` once; `flushed` false = a quiet frame (metrics §4.1) | one refresh (no timers) |
| `lvprobe_walk(p)` | 1 (O3 tree) and `clipped` (2); needs a settled display | no render, no flush |
| `lvprobe_ink(p, i)` | 2 (ink count and box), 4 (luminance samples) | two refreshes; the caller chooses the nodes (e.g. once per structure class) |
| `lvprobe_hit(p, x, y, &hit)` | 3 | one press and one release |
| `lvprobe_frame(p)`, `lvprobe_frame_crc(p)` | 4 (frame CRC, region hash of every node); needs a settled display | no redraw |
| `lvprobe_crop(p, box, rgba, cap, &len)` | 4 (RGBA crop) | no redraw |
| `lvprobe_life(p, out, cap, &n, &lost)` | 5 | |
| `lvprobe_encode(p, buf, cap, &len)` | 6 (text of 1, 2, 4) | |

A gate's loop per state: drive the product, `lvprobe_settle` until `flushed` is false (stepping the product's timers
in between is the caller's job), `lvprobe_walk`, then `lvprobe_frame`, `lvprobe_ink` and `lvprobe_hit` as needed.
**After a tap the frame is not settled** (pressed states, the product's handlers): settle again before the next walk
or frame. `lvprobe_ink` leaves the display settled.

Errors are never silent. Besides argument errors: `LVPROBE_ERR_FULL` (a capacity: 512 nodes, depth 32, 16 KiB of label
text per walk, 16 fonts, 16 observed screens, the scratch pixels), `LVPROBE_ERR_TRUNC` (an output buffer),
`LVPROBE_ERR_OVERFLOW` (lifecycle events lost), `LVPROBE_ERR_UNSETTLED` (dirty areas or pending layout: walk, ink and
frame refuse), `LVPROBE_ERR_STALE` (objects were created or deleted, or the active screen changed, since the walk the
call refers to: ink, hit and frame refuse), `LVPROBE_ERR_GONE` (a node's object is no longer a valid LVGL object,
checked with `lv_obj_is_valid` before every use of a stored pointer, so an app that removed the probe's callback
cannot make it touch freed memory), `LVPROBE_ERR_UNSTABLE` (ink attribution changed something it must not),
`LVPROBE_ERR_FORMAT` (the frame is not one full-size XRGB8888 buffer in DIRECT mode) and `LVPROBE_ERR_BLOCKED` (LVGL
would not process a tap now).

## Definitions

* **Walk order and index.** Bottom layer, active screen, top layer, sys layer; each depth-first pre-order (parent
  before children, children in LVGL's index order). A node's index is its position in that order, nothing more: it
  changes whenever the tree changes, so **judges key nodes through the scene (O2), never through the index**. `parent`,
  `clip` and `scroll` are indexes, `-1` for none; a root has depth 0.
* **Clip ancestor.** The nearest ancestor whose child clip box does not contain the node's coords.
* **Scroll context.** `scroll` is the nearest ancestor with the scrollable flag and content beyond its box
  (`lv_obj_get_scroll_top/bottom/left/right` > 0); `scroll_x`/`scroll_y` are its `lv_obj_get_scroll_x/y`. An item a list
  scrolled out has `clip` = the list *and* `scroll` = the list with its offset, which tells it from text that does not fit.
* **Hidden, clickable.** The object's own flags. A node below a hidden ancestor keeps `hidden=0`; it is not drawn.
* **Background.** `bg` is `lv_obj_get_style_bg_color_filtered`. `bg_opa_drawn` is `bg_opa` scaled as the renderer
  scales it: by the object's inherited `opa` (`lv_obj_get_style_opa_recursive`) and by the `opa_layered` of the object
  and of each ancestor, each factor applied with `LV_OPA_MIX2` only when below `LV_OPA_MAX`, as `lv_obj_refr` does.
  `bg_grad` and `bg_image` say a gradient or a bg image is set (then the colour alone does not describe the pixels).
* **Labels.** Every object of class `lv_label` or a subclass (`lv_obj_has_class`). `text` is what LVGL draws;
  `full_text` the label's own text: in DOTS mode LVGL overwrote the end with dots (`dotted=1`) and `full_text` puts the
  saved bytes back. `natural` is the size of `full_text` without width limit; `laid_out` and `lines` describe `text`
  laid out to the content width, i.e. what is drawn (for a dotted label the shortened text). `align` is the style value
  (0 = auto); `align_drawn` the alignment of the label draw task (after auto/bidi resolution and the SCROLL rule of
  `draw_main`).
* **Glyph boxes and `missing`.** The union of the `letter_coords` of every glyph the iterator places (spaces have
  none). `missing` counts glyphs drawn as LVGL's placeholder box (no font of the fallback chain has them).
* **Visible box per long mode** (the clip `draw_main`, lv_label.c:908, gives the label draw task): WRAP and DOTS: the
  label's coords widened by its ext draw size (line height / 4) left, top and right, the bottom cut at the content
  box's bottom, all cut by the clip chain. CLIP, SCROLL and SCROLL_CIRCULAR: the content box cut by the clip chain.
* **`clipped`.** If LVGL created a label draw task: the glyph union is not inside the visible box. If it did not,
  although neither the label nor an ancestor is hidden or fully transparent: the text takes room (`natural.x > 0`) and
  no part of its content box survives the clip chain (a label outside every visible area, or one whose padding shows
  but whose text area is cut away). A label LVGL does not draw for another reason (text opacity 0, empty text, spaces
  only) is not `clipped`; its ink is 0.
* **Ink** (`lvprobe_ink`). On a settled display: save the pixels of the node's coords + ext draw size (inside the
  display), set a local `opa_layered` = 0 on the node for its current state (LVGL then skips the node and its subtree
  in `lv_obj_refr`: no flag, so no layout re-flow and no focus move), refresh, count the pixels that differ and their
  bounding box, restore the local style exactly (or remove it), refresh. `LVPROBE_ERR_UNSTABLE` when, before, during
  or after, any walked node's coords differ from the walk, the restored pixels differ, the default group's or the
  node's group's focused object changed, or objects were created or deleted; the node then has `unstable=1` and no
  ink. Ink is subtree ink.
* **Luminance samples.** Among the ink pixels: `ink_lo`/`ink_hi` the darkest and lightest pixel with the node,
  `bg_lo`/`bg_hi` the darkest and lightest without it, ordered by `2126 R + 7152 G + 722 B`, values `0xRRGGBB` (sRGB);
  a judge computes the WCAG contrast from them.
* **Frame CRC and region hash.** 32-bit FNV-1a (basis 2166136261, prime 16777619) over the B, G, R bytes of each
  pixel, row-major, of the whole frame or of the node's coords inside the display (X of XRGB8888 is not hashed). The
  frame must be the display's single buffer (no second buffer), DIRECT render mode, the display's size, XRGB8888.
* **Crop.** RGBA8888 rows (R, G, B, 255) of a box that lies inside the display.
* **Lifecycle log.** `LV_EVENT_CHILD_CREATED` on an observed object logs the new child and everything below it and
  observes them; `LV_EVENT_DELETE` logs the object and marks its node gone (`obj` NULL). A deleted child keeps its
  parent's index even when the parent was deleted first (LVGL frees a parent after its children; a later object at the
  same address is not taken for it). A screen made with `lv_obj_create(NULL)` sends no event: at every
  `lvprobe_life`, walk, ink, hit and frame call the probe compares the display's screens with the observed ones and
  logs a new screen's whole subtree as created with `late=1` (objects created and deleted on it before that are not
  seen). Each entry: running number, created/deleted, late, node index in the last walk (`-1` for an object created
  after it), parent index, LVGL's class name. 64 entries are kept; more are counted in `lost` and the call returns
  `LVPROBE_ERR_OVERFLOW`.
* **Hit.** Before each tap the indev is reset (`lv_indev_reset` plus its private click streak, timestamps, pressed and
  long-press state), so every tap is a first single click whatever came before (no DOUBLE/TRIPLE_CLICKED, no hover or
  scroll left over). A tap is refused with `LVPROBE_ERR_BLOCKED` when LVGL would not process it: a screen-load
  animation is running or pending (`prev_scr`, `scr_to_load`), the indev is disabled, waits for a release, or belongs
  to another display. A point outside the display is `LVPROBE_ERR_ARG` (LVGL would clamp it onto the edge).
  `pressed`/`pressed_obj`/`pressed_node` name the object under the press (a disabled receiver that swallows the tap is
  seen); `clicked`/`obj`/`node` the one that got `LV_EVENT_CLICKED`.
* **Which indev.** With the product's pointer indev (`lvprobe_open(..., indev, ...)`) the tap goes through the indev
  the product configured (its display, scroll limit, double-click time, its event callbacks); for the two reads of a
  tap its read callback and user data are the probe's and are restored right after (a product handler that reads the
  indev's user data during the tap sees the probe). With NULL the probe creates a pointer indev in
  `LV_INDEV_MODE_EVENT` (read only when the probe taps) with LVGL's defaults; product code that listens on its own
  indev does not see those taps.

## Text format (`lvprobe_encode`)

One fact per line, `\n`-terminated, fields in this fixed order, `key=value` separated by one space. Integers in
decimal, colours as 6 lowercase hex digits, hashes as 8. A box is `x1,y1,x2,y2` (inclusive, absolute) or `-` when
empty or unknown; a node's own `box` is always the four numbers, so a zero-size node still shows its position
(`x2 = x1 - 1`). The header comes first; `frame` follows when `lvprobe_frame` ran after the walk; then per node, in
index order, `node`, `label` and `fit` for a label, `ink` when `lvprobe_ink` ran for it, `region` when `lvprobe_frame`
ran.

```
lvprobe/1 nodes=<n>
frame w=<w> h=<h> crc=<8 hex>
node <i> parent=<i|-1> depth=<d> class="<name>" box=<x1,y1,x2,y2> hidden=<0|1> clickable=<0|1> clip=<i|-1> scroll=<i|-1> scroll_x=<px> scroll_y=<px> bg=<rrggbb> bg_opa=<0..255> bg_opa_drawn=<0..255> bg_grad=<0|1> bg_image=<0|1>
label <i> font=<id|-> line_h=<px> align=<n> align_drawn=<n> long=<n> dotted=<0|1> lines=<n> natural_w=<px> natural_h=<px> laid_w=<px> laid_h=<px> text="<text>" full_text="<text>"
fit <i> drawn=<0|1> glyphs=<box> visible=<box> missing=<n> clipped=<0|1>
ink <i> unstable=0 count=<px> box=<box> ink_lo=<rrggbb> ink_hi=<rrggbb> bg_lo=<rrggbb> bg_hi=<rrggbb>
ink <i> unstable=1
region <i> hash=<8 hex>
```

Quoted strings (`class`, `text`, `full_text`): `"` and `\` are preceded by `\`; bytes below 0x20, 0x7f and every byte
that is not part of a valid UTF-8 sequence (stray continuation, truncated, overlong, surrogate, above U+10FFFF) are
written `\xHH`; valid UTF-8 is copied. The text needs `cap > length` (a NUL follows it); otherwise the call returns
`LVPROBE_ERR_TRUNC`, `*len` is 0 and the buffer holds an empty string.

## LVGL headers and memory

The probe includes LVGL private headers through `gate//third_party/lvgl:lvgl_private_headers`
(`c_third_party_private_headers`, docs/third-party.md "Private headers for gate code"; facts
`:lvgl_private_headers_symbols`). It reads `lv_obj_class_t.name`, the `lv_obj_t` layout bits, `lv_label_t`
(`text_size`, `recolor`, `expand`, dots), `lv_draw_task_t` (`clip_area`, the task list), `lv_draw_glyph_dsc_t`
(`letter_coords`, `g->resolved_font`), `lv_display_t` (screens, layers, render mode, buffers, dirty areas, screen
loads) and `lv_indev_t` (click streak, timestamps, pressed object). `LV_LABEL_DOT_BEGIN_INV` is private to lv_label.c
(line 33) and is repeated in label.c.

LVGL pool cost (measured, release, 101 objects on the screen): `lvprobe_open` takes 12,800 bytes (one event
descriptor per observed object, the display callback and the probe's indev); a walk gives back everything it takes
(the draw tasks of one label exist only while it is measured); `lvprobe_close` returns 5,624 bytes (LVGL keeps the
capacity of the objects' event arrays). `lvprobe_t` itself is 133,192 bytes of caller storage (224 a node); the scratch is 4 bytes
a pixel.

## Tests (`ui/lvprobe/tests/`)

`tools/buck2 test //ui/lvprobe/...` in release and with `--target-platforms toolchains//:linux_san`: 32 tests in five
binaries over `testkit` (a 320x240 memory display, an open probe, and a monospace test font whose glyphs are solid
boxes, so ink counts and glyph boxes are exact numbers). Each item was seen failing against a deliberately broken
build, one change at a time and then restored; item 8 in san, where that broken build reads freed memory:

| Broken build | Test that failed |
|---|---|
| ink hides the node with the HIDDEN flag (items 1, 2) | `ink_in_a_flex_column_counts_only_the_node`, `ink_keeps_the_focus`, `ink_of_a_box_a_label_and_a_hidden_label` |
| ink without the coords checks (1) | `a_node_that_moves_when_restyled_is_unstable` |
| a new screen not logged (3) | `a_new_screen_is_logged_late` |
| no indev reset (4) | `three_taps_are_three_single_clicks` |
| no blocked check (5) | `a_tap_during_a_screen_load_animation_is_blocked` |
| DOTS laid-out size from the full text (6) | `long_modes_dots_scroll_and_clip` |
| bg opacity not scaled (7) | `bg_facts_are_what_is_drawn` |
| no `lv_obj_is_valid` (8, san) | `an_object_deleted_unseen_is_gone` |
| no walk generation (9) | `ink_needs_room_a_current_walk_and_a_settled_frame`, `a_new_screen_is_logged_late`, `the_lifecycle_log_reports_create_and_delete` |
| unstable encoded as an ink line (10) | `a_node_that_moves_when_restyled_is_unstable` |
| any render mode accepted (11) | `a_partial_or_double_buffered_display_is_a_format_error` |
| exact label class only (12) | `a_label_subclass_is_a_label` |
| `align_drawn` from the style (13) | `recolor_empty_spaces_missing_and_align` |
| not-drawn labels never clipped (14) | `labels_lvgl_does_not_draw` |
| a second open accepted (15) | `ink_needs_room_a_current_walk_and_a_settled_frame` |
| parent lookup among live nodes only (16) | `the_lifecycle_log_reports_create_and_delete` |
| pressed object not recorded (17) | `a_disabled_target_is_pressed_but_not_clicked`, `a_transparent_clickable_overlay_steals_the_tap` |
| the probe's own indev always (18) | `taps_go_through_the_products_indev` |
| placeholders not counted (19) | `recolor_empty_spaces_missing_and_align` |
| depth, node, text, font and screen limits not enforced (20) | `every_capacity_limit_is_an_error` |
| scratch limit not enforced (20) | `ink_needs_room_a_current_walk_and_a_settled_frame` |
| a crop past the edge accepted; a point outside accepted (20) | `a_crop_at_the_display_edge`; `a_point_outside_the_display_is_refused` |
| class unescaped; invalid UTF-8 copied; zero-size box as `-` (21) | `the_encoder_escapes_and_truncation_is_an_error` |
| walk forces a redraw; settle reports nothing (23) | `the_walk_needs_a_settled_frame_and_flushes_nothing` |
| no scroll context (25) | `an_item_scrolled_out_has_its_scroll_context` |
| ink counts every pixel; `clipped` inverted; hit reports the parent; hash of one row; deletion not logged; loss not counted; truncation ignored | the ink, clip, hit, CRC, lifecycle, overflow and encoder tests |

## Limits

* Ink costs two refreshes per call; reusing it per structure class is the caller's job (P004 metrics 3.2).
* Only label draw tasks give glyph facts; an image or a symbol drawn by a style is ink, not glyphs.
* The probe's dry redraw of a label runs the label's draw events again: a product draw handler on a label runs once
  more per walk; tasks it adds to the probe's layer are freed, never drawn, and an object it creates makes the walk
  `LVPROBE_ERR_STALE`.
* The walk covers what is shown (bottom, active screen, top, sys); other screens are observed for the lifecycle log.
* The probe's event callback sees every event of every observed object; it acts on two (child created, delete) and
  never stops one.
