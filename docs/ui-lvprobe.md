# `gate//ui/lvprobe`: the rendered-stage observer (U02, P004 T1xx.02)

`ui/lvprobe/` is a gate-owned C library over gate LVGL (`gate//third_party/lvgl`) that reads what LVGL laid out and
drew: P004 §2.1 stage O3 (the object tree after layout) and O4 (the framebuffer). Every later `ui-*` judge takes its
facts from here. Header: `ui/lvprobe/lvprobe.h` (the only interface; `lvprobe_int.h` is shared by the library's own
files). Target: `gate//ui/lvprobe:lvprobe`. Tests: `ui/lvprobe/tests/`.

## Why production paths only (H6)

Seven of the eleven escaped kiosk defects were in the renderer while the scene was right, and a re-implemented
hit-test or layout drifts from LVGL (P004 §16 H6). The probe therefore computes nothing LVGL computes:

| Fact | Taken from |
|---|---|
| coords, flags, styles | `lv_obj_get_coords`, `lv_obj_is_hidden`/`_clickable`, `lv_obj_get_style_*` after LVGL's own layout (`lv_refr_now`) |
| laid-out size, line count | `lv_label_t.text_size` (what `lv_label` computed for its content width); lines = (h + line space) / (line height + line space) |
| natural size | `lv_text_get_size(text, font, letter space, line space, LV_COORD_MAX, flags)` |
| glyph boxes | the label draw task LVGL creates while rendering (`LV_EVENT_DRAW_TASK_ADDED`): `lv_draw_label_iterate_characters` on that task with its clip opened, so each `letter_coords` is placed by LVGL's own iterator, including glyphs the renderer cuts |
| visible box of a label | the task's `clip_area`: the clip LVGL draws that label with (own coords + ext draw size, cut by every clipping ancestor) |
| hit | a real `LV_INDEV_TYPE_POINTER` indev (`lv_indev_read`): LVGL's own `lv_indev_search_obj`, press, release, `LV_EVENT_CLICKED`, which the probe hears on the indev |
| pixels | the display's active draw buffer, which the real flush wrote |

## Calls

| Call | Part of the contract | Cost |
|---|---|---|
| `lvprobe_open(p, disp, scratch, scratch_px)` / `lvprobe_close(p)` | setup: creates the probe indev, registers one event callback (`LV_EVENT_ALL`) on every object of every screen and layer | |
| `lvprobe_map_font(p, font, id)` | the caller's font identities (up to 16) | |
| `lvprobe_walk(p)` | 1 (O3 tree) and `clipped` (2) | one full redraw of the screen (identical pixels) |
| `lvprobe_ink(p, i)` | 2 (ink count and box), 4 (luminance samples) | two redraws; the caller chooses which nodes (e.g. once per structure class) |
| `lvprobe_hit(p, x, y, &hit)` | 3 | one press and one release |
| `lvprobe_frame(p)`, `lvprobe_frame_crc(p)` | 4 (frame CRC, region hash of every node) | no redraw |
| `lvprobe_crop(p, box, rgba, cap, &len)` | 4 (RGBA crop) | no redraw |
| `lvprobe_life(p, out, cap, &n, &lost)` | 5 | |
| `lvprobe_encode(p, buf, cap, &len)` | 6 (text of 1, 2, 4) | |

Every call returns an `lvprobe_status_t`. Capacities are compile-time constants in the header: 512 nodes, depth 32,
16 KiB of label text per walk, 16 fonts, 64 lifecycle events between two `lvprobe_life` calls. Exceeding one is an
error (`LVPROBE_ERR_FULL`, `LVPROBE_ERR_TRUNC`, `LVPROBE_ERR_OVERFLOW`), never a silent cut. All state is in the
caller's `lvprobe_t` and scratch pixels (static storage); LVGL allocates from its own pool one event descriptor per
observed object and the indev.

## Definitions

* **Walk order.** Bottom layer, active screen, top layer, sys layer; each depth-first pre-order (parent before
  children, children in LVGL's index order). The index of a node is its position in that order; `parent` and `clip`
  are indexes, `-1` for none. A root (layer or screen) has depth 0.
* **Clip ancestor.** The nearest ancestor whose child clip box does not contain the node's coords. The child clip box
  is the ancestor's coords, or coords + ext draw size when `LV_OBJ_FLAG_OVERFLOW_VISIBLE` is set (`lv_obj_redraw`).
* **Hidden, clickable.** The object's own flags. A node below a hidden ancestor keeps `hidden=0`; it is not drawn.
* **`clipped`** (labels). If LVGL created a label draw task for the label: the union of its glyph boxes is not inside
  the union of the tasks' clip areas. If it did not: the text is non-empty, neither the label nor an ancestor is hidden,
  and no part of its coords survives the clip chain (the label lies outside every visible area). A label LVGL did not
  draw for another reason (text opacity 0) is not `clipped`; its ink is 0.
* **Ink** (`lvprobe_ink`). Settle the frame (`lv_refr_now`), save the pixels of the node's coords + ext draw size
  (inside the display), hide the node (`lv_obj_set_hidden`; a node that is already hidden stays hidden), redraw, count
  the pixels that differ and their bounding box, unhide, redraw, and check that every saved pixel is back
  (`LVPROBE_ERR_UNSTABLE` otherwise). Hiding hides the subtree, so ink is subtree ink. Pixels that change outside the
  box (a flex or grid parent re-flowing its other children) are not counted.
* **Luminance samples.** Among the ink pixels: `ink_lo`/`ink_hi` are the darkest and lightest pixel of the frame with
  the node, `bg_lo`/`bg_hi` the darkest and lightest pixel at the same places without it, ordered by
  `2126 R + 7152 G + 722 B`. Values are `0xRRGGBB` (sRGB); a judge computes the WCAG contrast from them.
* **Frame CRC and region hash.** 32-bit FNV-1a (basis 2166136261, prime 16777619) over the B, G, R bytes of each pixel,
  row-major, of the whole frame or of the node's coords inside the display. The X byte of XRGB8888 is not hashed.
  `lvprobe_frame` does not redraw: call it on a settled frame. The display buffer must be the full frame (DIRECT
  render mode, buffer size = resolution), XRGB8888; otherwise `LVPROBE_ERR_FORMAT`.
* **Crop.** RGBA8888 rows (R, G, B, 255) of a box that lies inside the display.
* **Lifecycle log.** `LV_EVENT_CHILD_CREATED` on an observed object logs the new child and everything already below
  it, and starts observing them; `LV_EVENT_DELETE` on an observed object logs it and marks its node gone (`obj` NULL,
  `lvprobe_ink` then returns `LVPROBE_ERR_GONE`). Each entry: running number, created/deleted, the node index in the
  last walk (`-1` for an object created after it), the parent's index, LVGL's class name. Objects of a screen created
  after the last `lvprobe_open`/`lvprobe_walk` are observed from the next walk on. The ring keeps 64 entries; more are
  counted in `lost` and the call returns `LVPROBE_ERR_OVERFLOW`.
* **Hit.** `clicked` is true when some object received `LV_EVENT_CLICKED` from the probe's indev; `obj` is that object
  and `node` its index in the last walk (`-1` if it is not in it). The indev runs in `LV_INDEV_MODE_EVENT`, so it is
  read only by `lvprobe_hit`. A tap may change object states (pressed); the next redraw repaints them.

## Text format (`lvprobe_encode`)

One fact per line, `\n`-terminated, fields in this fixed order, `key=value` separated by one space. Integers in
decimal, colours as 6 lowercase hex digits, hashes as 8. A box is `x1,y1,x2,y2` (inclusive, absolute) or `-` when
empty or unknown. The first line is always the header; `frame` follows when `lvprobe_frame` ran after the walk; then
per node, in index order, `node`, then `label` and `fit` for a label, `ink` when `lvprobe_ink` ran for it, `region`
when `lvprobe_frame` ran.

```
lvprobe/1 nodes=<n>
frame w=<w> h=<h> crc=<8 hex>
node <i> parent=<i|-1> depth=<d> class=<lv class name> box=<box> hidden=<0|1> clickable=<0|1> clip=<i|-1> bg=<rrggbb> bg_opa=<0..255>
label <i> font=<id|-> line_h=<px> align=<lv_text_align_t> long=<lv_label_long_mode_t> lines=<n> natural_w=<px> natural_h=<px> laid_w=<px> laid_h=<px> text="<text>"
fit <i> drawn=<0|1> glyphs=<box> visible=<box> clipped=<0|1>
ink <i> count=<px> box=<box> ink_lo=<rrggbb> ink_hi=<rrggbb> bg_lo=<rrggbb> bg_hi=<rrggbb>
region <i> hash=<8 hex>
```

`text` is the label's text in double quotes: `"` and `\` are preceded by `\`, bytes below 0x20 and 0x7f are written
`\xHH`, every other byte is copied (UTF-8 stays UTF-8). `align` is the main-part style value (0 = auto). The text
needs `cap > length` (a NUL follows it); otherwise the call returns `LVPROBE_ERR_TRUNC`, `*len` is 0 and the buffer
holds an empty string.

## LVGL headers the probe needs (`third_party/lvgl/BUCK`, `:lvgl_private_headers`)

LVGL 9.6 exports a public header tree (`include/lvgl/...`); the probe also needs four private structures that have no
public getter: `lv_obj_class_t.name` (class name), `lv_label_t.text_size` and `.recolor` (the laid-out size),
`lv_draw_task_t.clip_area` (the clip a label is drawn with) and `lv_draw_glyph_dsc_t.letter_coords` (each glyph box),
plus `lv_display_t.screens`/`.screen_cnt` (to observe every screen) and the private declarations of `lv_area_intersect`
and `lv_obj_get_ext_draw_size`. The new target `gate//third_party/lvgl:lvgl_private_headers` is header-only (no
sources, no flags, nothing linked) and exports every `.h` of the pinned manifest at its own path (the private headers
include each other and the public tree by relative path, `src/core/lv_obj_private.h` -> `../lvgl_public.h` ->
`../include/lvgl/lvgl.h`). It is visible to `//ui/...` only and is not in `third_party/ALLOWED_LABELS`, so no
product can name it. It is a `deps` of `:lvprobe`, not exported: `lvprobe.h` includes the public `lvgl.h` only. No
symbol export changed (the functions the probe calls are already exported by `:lvgl`).

## Tests (`ui/lvprobe/tests/`)

`tools/buck2 test //ui/lvprobe/...` in release and with `--target-platforms toolchains//:linux_san`. Both binaries use
a 320x240 memory display (`lvgl_gate_test_display_create`) and the public header only.

| Test | Shows | Broken build that made it fail |
|---|---|---|
| `lvprobe_tree/a_label_in_a_box_too_small_is_clipped` | "Hello" in an 80x8 label is clipped, a content-sized one is not | `clipped` with the containment inverted |
| `lvprobe_tree/a_label_cut_by_its_parent_is_clipped` | a label that sticks out of its 40x40 parent: `clip` = the parent, clipped | same |
| `lvprobe_tree/a_cyrillic_glyph_in_a_tight_row_is_clipped` | `Й` (a 14 px glyph of a 16 px test font) in a 10 px row is clipped, in a 16 px row is not; font id mapping | same |
| `lvprobe_tree/a_hidden_label_has_no_ink` | hidden label ink 0, shown label ink > 20 inside its box, white background sample, frame CRC unchanged after ink | ink counting every pixel of the box |
| `lvprobe_tree/encoder_truncation_is_an_error` | encoder lines, escaping; cap = length and cap 10 return `LVPROBE_ERR_TRUNC`, cap = length + 1 succeeds | encoder returning OK on truncation |
| `lvprobe_io/a_transparent_clickable_overlay_steals_the_tap` | F3b canary: a full-parent transparent clickable object takes the centre tap from the button under it; not clickable, the tap reaches the button (and its own callback) | hit reporting the receiver's parent |
| `lvprobe_io/one_pixel_changes_the_crc_and_the_region_hash` | two renders give equal CRC and region hash; one changed pixel (crop shows exactly one) changes both, another node's hash stays | hashing only the first row of a box |
| `lvprobe_io/the_lifecycle_log_reports_create_and_delete` | a label created and deleted between two calls, and a walked node deleted; node marked gone | deletion not logged |
| `lvprobe_io/a_full_lifecycle_ring_reports_overflow` | 70 creations: 64 kept, 6 lost, `LVPROBE_ERR_OVERFLOW` | lost events not counted |

## Limits

* Ink is per call and costs two redraws; the "once per structure class" reuse belongs to the caller (P004 metrics 3.2).
* Only label draw tasks give glyph facts; an image or a symbol drawn by a style is ink, not glyphs.
* The walk covers what is shown (bottom, active screen, top, sys); other screens are observed for the lifecycle log only.
* The probe's event callback sees every event of every observed object; it ignores all but three and never stops one.
