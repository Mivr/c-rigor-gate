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
| hit (observation, U05c) | the product's own reads of its pointer indev; LVGL's `LV_EVENT_PRESSED` and `LV_EVENT_CLICKED` on that indev |
| hit (query) | `lv_indev_search_obj` (it sends LVGL's own `LV_EVENT_HIT_TEST` to objects with `LV_OBJ_FLAG_ADV_HITTEST`) |
| ink | a real refresh with the node not drawn (its own `hidden` bit), a real refresh with it, the pixel diff |
| pixels | the display's single full-size buffer the real flush wrote |

Where LVGL has no entry point, the probe repeats LVGL's logic. Each repetition is pinned by a differential test
against real pixels or real events, so an LVGL upgrade that changes the logic fails a test:

| Mirror (LVGL source) | Pinned by |
|---|---|
| clip chain: display area cut by each ancestor's child clip box, coords or coords + ext when overflow is visible (`lv_obj_redraw`, lv_refr.c:105) | `lvprobe_diff/glyphs_match_the_render_under_parents` (scrolled, `opa_layered`, `clip_corner` parents, off-screen) and `..._in_every_long_mode`: rendered ink box = glyphs cut by the visible box |
| draw chain: hidden, `opa_layered` <= `LV_OPA_MIN`, transform scale <= 0, a parent's layer opacity <= `LV_OPA_MIN` (`lv_obj_refr`, `lv_obj_redraw`) | `lvprobe_diff/not_drawn_means_no_pixels` |
| layer opacity: every `opa` below `LV_OPA_MAX` mixed with `LV_OPA_MIX2` (`lv_obj_refr`) | `lvprobe_diff/not_drawn_means_no_pixels` (a label of own `opa` 1) |
| `bg_opa_drawn`: `bg_opa`, inherited `opa`, own and ancestors' `opa_layered`, combined so that a factor at or above `LV_OPA_MAX` is opaque | `lvprobe_diff/bg_opa_drawn_matches_the_pixel`: equal to the rendered pixel whenever `bg_opa_exact` is 1; `bg_opa_exact` is 0 under any `opa_layered` ancestor (LVGL composes a sub-layer and rounds differently: measured 2 levels off), and a judge must not use the value then |
| not-drawn `clipped`: no part of the content box survives the clip chain (`draw_main`, lv_label.c:908) | `lvprobe_diff/not_drawn_means_no_pixels` (padded label) |
| `label_flags` (`get_label_flags`, lv_label.c:1516) and the DOTS laid-out size (`lv_label_refr_text`) | `lvprobe_diff/glyphs_match_the_render_in_every_long_mode` (DOTS width against the rendered `AA...`) |
| line count = (h + line space) / (line height + line space) | the same test (wrapped rows against the rendered rows) |
| `full_text` from `dot_begin`/`dot[]` (`lv_label_set_dots`) and `LV_LABEL_DOT_BEGIN_INV` (lv_label.c:33) | `lvprobe_label/long_modes_dots_scroll_and_clip` |
| tap blocked: no display, disabled, `prev_scr` (`lv_indev_read`), `wait_until_release` (`indev_proc_press`); the same check for the query | `lvprobe_hit/a_tap_during_a_screen_load_animation_is_blocked` (LVGL's own test mouse agrees; only `scr_to_load` set is processed) |
| scrollbar areas (`lv_obj_get_scrollbar_area`) of the ancestors where they touch the diff box, with the node's bit set and cleared | `lvprobe_ink2/a_scrollbar_change_makes_ink_unstable` |
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
| `lvprobe_observe_begin(p, x, y)`, `lvprobe_observe_end(p, &hit)` | 3, observation of a tap the product delivers to its own indev (U05c) | nothing: no event sent, nothing allocated |
| `lvprobe_frame(p)`, `lvprobe_frame_crc(p)` | 4 (CRC, region hashes); needs a settled display | no redraw |
| `lvprobe_crop(p, box, rgba, cap, &len)` | 4 (RGBA crop) | |
| `lvprobe_life(p, out, cap, &n, &lost)`, `lvprobe_life_pending(p)` | 5; **call it every frame** | |
| `lvprobe_encode_head`, `lvprobe_encode_node`, `lvprobe_encode` | 6 | |

Seam loop per frame: `lvprobe_life` until `lvprobe_life_pending` is 0; `lvprobe_settle` until `flushed` is false;
`lvprobe_walk`; then `lvprobe_frame`, `lvprobe_ink`, `lvprobe_hit_test`/`lvprobe_hit` as needed; encode the head and
then node by node into the reply buffer. After a tap, settle again before the next walk or frame.

Errors. **Settle and retry** (the state moved under the call): `LVPROBE_ERR_UNSETTLED` (settle), `LVPROBE_ERR_STALE`
(walk again; also the encoder after a failed or stale walk), `LVPROBE_ERR_BLOCKED` (settle or advance time, then tap
again), `LVPROBE_ERR_UNSTABLE` (settle and retry once; again unstable: report the node as unmeasurable),
`LVPROBE_ERR_GONE` for a node (walk again), `LVPROBE_ERR_TRUNC` (a larger buffer or node by node). **Per node, not
measured** (the judge fails closed on that node, the session goes on): `LVPROBE_ERR_UNSUPPORTED` from `lvprobe_ink` (a
transformed node, or under a transformed ancestor; `ink_unsupported`), and the walk's `unsupported` flag of a label
LVGL draws through a sub-layer. **Fatal for the session**: `LVPROBE_ERR_FULL` (a capacity), `LVPROBE_ERR_FORMAT` (not
one full-size XRGB8888 buffer in DIRECT mode, no refresh timer, or a rotated display), `LVPROBE_ERR_LVGL`,
`LVPROBE_ERR_ARG` (also the ink of a screen or layer root, which is refused), and `LVPROBE_ERR_GONE` from every call
after `lv_display_delete` (the probe hears the display's `LV_EVENT_DELETE` and touches it no more). **Data lost**:
`LVPROBE_ERR_OVERFLOW` (lifecycle events did not fit the ring).

### Observing a tap (U05c)

A product with a pointer entry (docs/ui-model.md, "The pointer entry") feeds its own pointer indev; the probe must see
what LVGL made of those samples without injecting anything. `lvprobe_observe_begin(p, x, y)` checks what `lvprobe_hit`
checks (the point inside the display, a current walk; not the walk when a press would be blocked now, since a screen
load changes the tree) and records whether LVGL would process a press now (`blocked`: no display, the indev disabled,
`prev_scr`, `wait_until_release`). The product then delivers its samples and processes them. `lvprobe_observe_end(p,
&hit)` returns what LVGL's own events on the indev named: the object of `LV_EVENT_PRESSED` and of `LV_EVENT_CLICKED`
(each the event's parameter, alive while LVGL sends it, mapped to its walk index at once by `lvprobe_find`; the probe
keeps the pointer for comparison only and never dereferences it). Statuses of the end: `LVPROBE_ERR_BLOCKED` when
nothing was pressed or clicked and a press would have been blocked at the begin, or when the indev is left pressed
(`act_obj`, `state` or `wait_until_release`: LVGL did not process the release); `LVPROBE_ERR_UNSTABLE` for more than one
press or click (not one tap: the probe never picks one); `LVPROBE_ERR_GONE` when the indev is no longer in LVGL's list
(found by traversal; the probe then forgets it and touches it no more, close included); `LVPROBE_ERR_LVGL` when the
probe's listener is no longer on the indev (also at the begin). `LVPROBE_ERR_FORMAT` at the begin: the probe opened
with its own indev, so there is no product indev to observe. `lvprobe_hit` is refused while an observation is open.

The listener is the probe's one event callback on the indev, added at `lvprobe_open` (now with the filter
`LV_EVENT_ALL`, so it also hears `LV_EVENT_PRESSED`; outside a tap or an observation it ignores every event) and removed
at `lvprobe_close`: an observation adds, allocates and removes nothing (adding and removing a callback per tap would
leave LVGL's event array grown, a pool change the tests catch), and an observation left open is closed with the probe.
LVGL sends `LV_EVENT_PRESSED` only for an enabled object, so a disabled target observed reads as nothing pressed,
where an injected tap names LVGL's pressed object (`act_obj`). The probe leaves the indev as LVGL left it, also a
pressed one: on this path the indev state is the product's, made by its own samples. Tests:
`ui/lvprobe/tests/lvprobe_observe_test.c` (the product's tap observed with nothing left behind, the F3b overlay, a
disabled target, the indev disabled, a screen-load animation, a release LVGL did not process, two taps, every
precondition, a removed listener, close during an observation, an indev deleted during one).

## Configuration and storage

`lvprobe_config_t` gives the probe its storage and capacities: `nodes`/`max_nodes` (default 512, at most 32767),
`text`/`text_bytes` (default 16384, all label texts of one walk), `life`/`life_cap` (default 1024: a screen switch of
512 objects deleted and 512 created), `screens`/`max_screens` (default 16), `scratch`/`scratch_px` (pixels for ink: a
node's box + ext draw size; width x height always suffices), and `indev` (below). Fixed: depth 32, 16 fonts.
`lvprobe_t` itself is small (no capacity-sized array). The lifecycle ring drains in chunks: `lvprobe_life` copies at
most `cap` entries, oldest first, and keeps the rest; `lost` counts only what the ring could not hold.

`lvprobe_close` is safe in any order: it looks the display and the indev up in LVGL's own lists (by address) and
touches neither when they are gone; it deletes its own indev only if that indev still has the probe's read callback (a
new indev at the same address is someone else's: `lvprobe_io/calls_after_the_display_is_gone_fail`).

LVGL pool: one event descriptor per observed object, one on the display, the probe's indev when it creates one; a walk
gives back every byte it takes (pinned by `lvprobe_diff/a_walk_leaves_lvgl_as_it_was`); ink allocates nothing and
leaves every style list as it was (`lvprobe_ink/ink_leaves_styles_and_the_pool_as_they_were`).

## Definitions

* **Walk order and index.** Bottom layer, active screen, top layer, sys layer; each depth-first pre-order. A node's
  index is its position in that order, nothing more: **judges key nodes through the scene (O2), never through the
  index**. `parent`, `clip` and `scroll` are indexes, `-1` for none; a root has depth 0.
* **Liveness.** A stored object pointer is used only when a fresh traversal from the display's screens and layers
  reaches it **and** it still carries the probe's event callback; nothing else is dereferenced. One traversal per call
  (an index stack, depth 32), each object looked up by binary search in the nodes sorted by address after the walk:
  inking all 512 nodes of a flat screen is not quadratic (`lvprobe_ink2/inking_512_nodes_is_not_quadratic`). A deleted
  object the probe saw is `obj` NULL. If the app removed the probe's callbacks and an object at the same address
  appeared since, that object lacks the callback (under an observed parent its creation would have changed the
  generation instead): `LVPROBE_ERR_GONE` (`lvprobe_ink/a_reused_address_is_gone`).
* **Staleness: what is and is not detected.** The walk's generation changes on every create and delete, on
  `LV_EVENT_CHILD_CHANGED` and `LV_EVENT_CHILD_DELETED` of an observed parent (a child added, removed, reparented,
  reordered with `lv_obj_move_to_index`, moved or resized), on a new screen and on a change of the active screen. What
  sends no event is compared at use time (ink, tap, query): each node's parent, index among its siblings, `hidden` and
  `clickable` against the walk (`lvprobe_walk/tree_changes_without_events_make_the_walk_stale`). Not detected: style
  changes (colours, fonts, opacity), label text changes, other flags and states (`LV_STATE_DISABLED` included); their
  facts are those of the walk until the next one.
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
* **`unsupported`** (labels). LVGL would draw the label through a sub-layer it really renders (a drop shadow, or a
  descendant with a layer): not measured, `drawn` 0, no boxes, not clipped; the walk goes on and every other node is
  measured as usual (`lvprobe_walk/a_label_with_a_drop_shadow_is_unsupported`). The dry redraw restores LVGL's
  `rendered` mark of the label and of every walked node below it.
* **Ink.** Refused: a screen or layer root (`LVPROBE_ERR_ARG`), a transformed node or one under a transformed ancestor
  (`LVPROBE_ERR_UNSUPPORTED`, `ink_unsupported`), a node whose walked parent, index or flags changed
  (`LVPROBE_ERR_STALE`: in particular a node the product hid after the walk is never un-hidden by ink), and, before
  anything is touched, while LVGL runs any animation or a style transition of the node (`LVPROBE_ERR_UNSTABLE`).
  Otherwise, on a settled display, for a node LVGL draws: save its box (coords + ext draw size, inside the display) and
  every walked node's `rendered` mark; invalidate the node and set its own `hidden` bit directly (`lv_obj_refr` skips it
  and its subtree; unlike `lv_obj_set_hidden` no layout is marked and no focus moves); refresh; if a product handler
  deleted the node during the refresh, stop with `LVPROBE_ERR_GONE` and touch nothing more; diff; put the saved bit back
  and invalidate; if any node moved, mark the node's parent for layout so the second refresh lays the siblings out
  again with the node drawn; refresh; put the `rendered` marks back. `LVPROBE_ERR_UNSTABLE` (and `unstable`, no ink)
  when an ancestor's scrollbar changed inside the box, a refresh flushed nothing or left the display unsettled, any
  walked node's coords, the focus or the restored pixels changed, or objects were created or deleted. Ink is subtree ink
  inside the node's box: a child drawn outside it (overflow visible beyond the ext draw size) is not counted. A node LVGL
  does not draw has ink 0.
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
  callback on the indev. With NULL the probe creates a pointer indev in event mode with LVGL's defaults. Two residual
  behaviours on the product's indev: the reset before a tap also clears a genuine press in progress on it (the product's
  own pointer is not held while the gate taps), and a product handler that calls `lv_timer_handler` or `lv_indev_read`
  during a tap reads the probe's callback, not its own.
* **Hit query vs injection.** `lvprobe_hit_test` asks LVGL's search which object is under the point and sends no
  input event (an object with `LV_OBJ_FLAG_ADV_HITTEST` gets LVGL's `LV_EVENT_HIT_TEST`, which is part of the search);
  `lvprobe_hit` presses and releases, so states, focus and the product's handlers change.

## What the probe changes in the product

One event descriptor per object and on the display (and on the product's indev: the listener, filter `LV_EVENT_ALL`;
an observation adds none); extra refreshes and flushes
(`lvprobe_settle`, two per `lvprobe_ink`); the dry redraw runs each label's draw events once more per walk (tasks a
product handler adds there are freed, never drawn; an object it creates makes the walk `LVPROBE_ERR_STALE`); taps run
the product's input handlers. Nothing else: no style, flag, focus or layout change survives a call.

## Text format (`lvprobe_encode*`)

Records of the ui-probe/1 grammar (docs/ui-model.md): one fact per line, LF-terminated, fields separated by single
TABs in a fixed order and number, only printable ASCII; no field is ever empty and no line ends in a TAB. A label text
field is the prefix `=` followed by the escaped text (an empty text is `=`), so it can never be confused with the
marker `-` (no font id, no box, `full_text` equal to `text`). Inside a field `\\` is a backslash, `\t` a TAB, `\n` an LF and
`\xHH` (lowercase) every other byte outside 0x20..0x7e, every UTF-8 byte included (Bulgarian text round-trips:
`lvprobe_io/the_encoder_writes_valid_records`). Integers decimal, colours 6 lowercase hex digits, hashes 8. A box field
is `x1,y1,x2,y2` or `-`; a node's own coords are four fields, always numbers (a zero-size node shows its position).

| Line | Fields | Order |
|---|---|---|
| `lvprobe` | 3 | `lvprobe`, `1`, nodes |
| `frame` | 4 | `frame`, w, h, crc (after `lvprobe_frame`) |
| `node` | 21 | `node`, i, parent, depth, class, x1, y1, x2, y2, hidden, clickable, clip, scroll, scroll_x, scroll_y, bg, bg_opa, bg_opa_drawn, bg_opa_exact, bg_grad, bg_image |
| `label` | 15 | `label`, i, font id or `-`, line_h, align, align_drawn, long, dotted, lines, natural_w, natural_h, laid_w, laid_h, text, full_text (`-` unless dotted) |
| `fit` | 8 | `fit`, i, drawn, unsupported, glyphs box, visible box, missing, clipped |
| `ink` | 8 | `ink`, i, count, box, ink_lo, ink_hi, bg_lo, bg_hi |
| `noink` | 3 | `noink`, i, `unstable` or `transformed` (the last `lvprobe_ink` of the node measured nothing) |
| `region` | 3 | `region`, i, hash (after `lvprobe_frame`) |

`lvprobe_encode_head` writes `lvprobe` and `frame`, `lvprobe_encode_node` the lines of one node, `lvprobe_encode`
everything; the seam streams head and nodes into its reply. Each call writes only the facts of a walk that succeeded
and is still current (`LVPROBE_ERR_STALE` otherwise). It needs `cap >= *len + 1` (a NUL follows the text); otherwise
`LVPROBE_ERR_TRUNC`, an empty string, and `*len` is the exact text length needed.

Byte budget against the probe protocol's 65536-byte `frame` payload (`UIM_BUF_MAX`, docs/ui-model.md): a node line is
about 60 to 90 bytes, a label adds its `label` and `fit` lines (about 100 bytes) plus 4 bytes per UTF-8 byte of its text
(a Cyrillic letter is 2 bytes, so 8 bytes escaped), `region` about 20 bytes. Measured: a screen of 84 objects with 25
Bulgarian labels of 30 letters, after `lvprobe_frame`, encodes to 14,790 bytes, 23% of the payload
(`lvprobe_io/a_bulgarian_screen_fits_the_payload`); the payload holds about four such screens, or 512 plain nodes. Bound: the lines of one node take
at most `LVPROBE_LINE_FIXED` (1024) + 4 x (bytes of class name + text + full text) bytes (every number at most 11
characters, every escaped byte at most 4).

## LVGL headers

The probe includes LVGL private headers through `gate//third_party/lvgl:lvgl_private_headers`
(`c_third_party_private_headers`, docs/third-party.md). It reads `lv_obj_class_t.name`, `lv_obj_t` (`hidden`,
`rendered`, layout bits, style list), `lv_label_t`, `lv_draw_task_t`, `lv_draw_glyph_dsc_t`, `lv_display_t` and
`lv_indev_t`, and writes only `lv_obj_t.hidden` and `.rendered` (restored), the probe layer, the indev's read
callback (restored) and reset fields, and the layout mark of a parent after an unstable ink.

## Tests (`ui/lvprobe/tests/`)

`tools/buck2 test //ui/lvprobe/...` in release and san: the test binaries over `testkit` (U05c added `lvprobe_observe_test`) (320x240 memory display, an open
probe, a monospace font of solid glyphs so pixel facts are exact, helpers that read LVGL's pool and layer list). Each
item of the review was seen failing against its own broken build (the report lists them).

## Limits

* Occlusion, corner masks and transform layers are not modelled in `drawn`/`clipped` (see the top).
* Only label draw tasks give glyph facts; images and style symbols are ink, not glyphs.
* `bg_opa_drawn` is only exact when `bg_opa_exact` is 1.
* Ink misses children drawn outside the node's box.
* The walk covers what is shown; other screens only feed the lifecycle log.
