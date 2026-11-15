# The UI model interface and the probe (U03, U05a, P004 4.2, 6.2, 6.3)

The UI gate drives a product through one small, gate-owned interface, `ui/model/model.h`. A product implements it in a
model adapter (a `c_library`); `c_ui_probe` links the adapter with the gate's `main` (`ui/model/probe_main.c` and its
helpers) into a probe binary that speaks a line protocol on stdin and stdout. The probe reads the rendered frame through
`gate//ui/lvprobe` (U02, docs/ui-lvprobe.md; "Frame facts" below, U05a); the Python driver is U05. Selftest:
`selftest/ui.sh` on the toy app in `selftest/ui_product/`, and `selftest/ui_frame.sh` (called by it) on the frame toy in
`selftest/ui_frame_product/`.

## The interface (`ui/model/model.h`)

Gate-owned types only (`uim_t` is opaque and defined by the product; `uim_buf_t {data, cap, len}`;
`uim_input_t {kind, id, arg, text}`; `uim_result_t` = `UIM_ERROR | UIM_OK | UIM_REFUSED | UIM_MISSED`). Rules for every call, written in
the header: static storage (no allocation; the one model object comes from `uim_instance()`), determinism (only the
virtual clock and the seed of `uim_open` influence output), and:

* **A failure poisons the session.** A call that returns false (or `UIM_ERROR`) may have changed the model halfway
  (LVGL cannot be rolled back); the gate calls nothing but `uim_open` afterwards. The read-only `uim_env_inputs` and
  `uim_semantic` are the exceptions. `fail open` leaves the model closed.
* **A refusal is not a failure.** `uim_apply` returns `UIM_REFUSED` for an input that is not enabled in this state; the
  model is unchanged and the session goes on.
* **Neither is a miss.** `uim_apply` returns `UIM_MISSED` when the input was delivered through the production path (an
  input handler, a tap through the product's own pointer indev) but the product did not produce the intent it was aimed
  at, for example because an overlay took the tap (the F3b class). The model may have changed; the scene is stable, the
  session goes on. Reply `ok apply missed`. The toy produces it: a press while its notice shows is taken by the notice's
  transparent clickable scrim.
* **Time is the gate's.** The model exposes one time primitive, `uim_step(m, ms)`, `1 <= ms <= 16`: move the clock by
  `ms`, advance LVGL's tick by `ms`, run the LVGL timer handler once, run the product's due timers. The probe's
  `advance` owns the loop: frames are the grid `origin + k * 16 ms`; every step ends at the next grid boundary, at the
  next deadline (`uim_next_due`, re-read before every step, so a deadline created during an advance is honoured) or at the
  target, whichever is first. Longest `advance`: `UIM_ADVANCE_MAX_MS` (600000) per command; `clock_origin_ms <=
  UIM_ORIGIN_MAX_MS` (2^48); the clock never passes `UIM_TIME_MAX_MS` (2^52), so origin plus any timeout cannot overflow.
* A listed env input must be replayable byte for byte through `uim_apply`. Text of an input is any bytes `0x01..0xff`,
  at most `UIM_TEXT_MAX` (256).

| Call | Meaning |
|---|---|
| `uim_open(m, origin_ms, seed)` | cold boot to the first stable scene; callable again to restart |
| `uim_env_inputs(m, out, cap, &count)` | the enabled env and fault inputs, fixed order, at most `UIM_ENV_MAX` (64), kind `UIM_IN_ENV` |
| `uim_apply(m, in)` | deliver an env input, a wedge line or an intent; `UIM_OK`, `UIM_REFUSED`, `UIM_MISSED` or `UIM_ERROR` |
| `uim_next_due(m)` | the next deadline or `UIM_NO_DEADLINE` (also before `open`), strictly later than now on a stable scene |
| `uim_step(m, ms)` | the time primitive above |
| `uim_settle(m, &worked)` | run every piece of product work due at the current virtual time (an intent a handler queued, work an animation callback posted) to a stable scene, without moving the clock; `*worked` if anything ran. `UIM_OK` or `UIM_ERROR` (poisons); `UIM_REFUSED`/`UIM_MISSED` break the contract. The gate calls it after a tap and while taking a frame |
| `uim_frame(m, &disp)` | adopt and render the scene; `disp` must not be NULL. **Display lifetime:** one display from the first `uim_frame` after `uim_open` until the next `uim_open`, always in LVGL's display list |
| `uim_semantic`, `uim_patches`, `uim_trace` | text records (below); patches and trace clear their log |
| `uim_domain_count()`, `uim_domain_at(m, i)` | the optional view-domain sweep (the gate only asks for `i < count`) |

Deviations from P004's sketch: `uim_instance()` (the gate needs the one static model object and `uim_t` must not be a
product type in a gate header), `uim_frame` takes `struct _lv_display_t **` so the header includes no LVGL, and
`uim_advance` is gate code (the probe) over `uim_step`.

### Record grammar of `uim_semantic`, `uim_patches`, `uim_trace`

Gate-owned, line oriented. A buffer is zero or more records, one line each, LF terminated, printable ASCII and TAB
separators only; the fields of a record are separated by single TABs, in a fixed order and number, and may be empty.
Escaping: inside a field `\\` is a backslash, `\t` a TAB, `\n` an LF, `\xHH` (lowercase hex) any other byte outside
`0x20..0x7e` (never a printable byte, TAB or LF, which have their own spelling); any other backslash sequence or byte, and
more fields than the call has (refused at the first surplus TAB), is a violation. The probe checks every line.

| Call | Fields |
|---|---|
| `uim_semantic` (14, one line per node, tree order, P004 4.2 "a11y+") | `key`, `role`, `label`, `x`, `y`, `w`, `h` (signed decimal), `enabled` (exactly `0` or `1`), `intent:arg` (`-` if none), `flags`, `style`, `importance`, `input_policy`, `wrap_policy` |
| `uim_patches` (5, one line per scene patch since the last call) | `op`, `key`, `field`, `old`, `new` |
| `uim_trace` (3, one line per emitted event since the last call) | `seq` (from 0 at `open`), `type`, `mono_ms` (unsigned decimal) |

## The probe protocol `ui-probe/1`

One command per line on stdin; one reply per command on stdout, flushed after each. A command line is printable ASCII
(`0x20..0x7e`), single-space separated tokens, no leading, trailing or doubled space, at most 640 bytes, at most 8 tokens
and ended by LF; any other byte (TAB, CR, NUL, anything above `0x7e`) makes it malformed. Numbers are decimal, no
leading zeros, no overflow; `arg` may carry a `-` (never `-0`) and must fit `int32`; `id` must fit `uint32`. Text is `-`
(empty) or lowercase hex of 1 to 256 bytes, none of them `00`. The first line the probe writes is the greeting.

**The greeting.** `ui-probe/1 ready` followed by the capabilities, each a single space and a token of lowercase letters,
digits and `-`, each at most once; today exactly `ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop`. The
protocol name stays `ui-probe/1`: a capability only adds commands or replies, it never changes an existing one. A driver
reads the tokens after `ready` as a set and refuses a catalogue that needs one the probe does not announce.
`frame-facts`: `frame` carries the lvprobe records below; `ink`, `hit-test`, `tap`, `crop`: those commands;
`apply-missed`: `apply` can reply `ok apply missed`.

| Command | Reply |
|---|---|
| `open <origin_ms> <seed>` | `ok open` or `fail open` (clears "open") |
| `env-inputs` | `ok env-inputs <n> <kind>:<id>:<arg>:<hex\|->...`: ONE unframed line, up to about 35 KB (64 inputs of 256 bytes, hex); a driver must read lines of that length |
| `apply <kind 1..3> <id> <arg> <hex\|->` | `ok apply`, `ok apply refused`, `ok apply missed` or `fail apply` (poisons); a result outside the enum is `err apply model-contract` |
| `next-due` | `ok next-due <ms>` or `ok next-due none` |
| `advance <to_ms>` | `ok advance <now_ms>` or `fail advance` (poisons); `to_ms` before now, more than 600000 ms ahead or past 2^52 is `err advance bad-arguments` |
| `frame` | `ok frame lines <n>` and the n frame-fact lines ("Frame facts"), `fail frame` (poisons), or an `err frame` (poisons) |
| `ink` / `ink <i>` | `ok ink lines <n>`: one `ink` or `noink` record per node of the current frame's walk that is not a root (or of node i). Never run implicitly; costs two refreshes per drawn node. `i` out of range or a root: `bad-arguments` |
| `hit-test <x> <y>` | `ok hit-test <i>`, `ok hit-test none` or `ok hit-test blocked`: what LVGL's own pointer search finds at the point. No input event is sent, so no product handler runs, EXCEPT LVGL's own `LV_EVENT_HIT_TEST`, which the search sends to objects with `LV_OBJ_FLAG_ADV_HITTEST` (advanced hit-testing) and which a product may handle. Read-only: an `err` does not poison |
| `tap <x> <y>` | `ok tap <pressed> <clicked>` (node indexes or `none`) or `ok tap blocked`: a press and release through the production pointer path, then `uim_settle` (so an intent the click queued runs at the tap's time: `trace`, `semantic` and `next-due` right after the tap show it), then refreshes to a quiet frame. An input: an `err` or `fail tap` (the settle failed) poisons, `blocked` does not |
| `crop <x> <y> <w> <h>` | `ok crop lines <h>`: one line per row, 8 lowercase hex digits (`rrggbbaa`) per pixel. The region must lie inside the display and `h x (8 w + 1) <= 65535` (160x51 fits, 160x52 does not); otherwise `bad-arguments`. Read-only |
| `semantic`, `patches`, `trace` | `ok <name> lines <n>` followed by exactly n record lines, verbatim; `fail <name>` (patches and trace poison) |
| `domain-count` | `ok domain-count <n>` (allowed before `open`) |
| `domain-at <i>` | `ok domain-at` or `fail domain-at` (poisons); `i >= count` is `err domain-at bad-arguments` |
| `quit` | `ok quit`; the probe then reads to EOF and any further non-empty line is `err ? after-quit` (once) and counted |

`ink`, `hit-test`, `tap` and `crop` need a current frame: a `frame` that succeeded with no `open`, `apply`, `advance`,
`domain-at` or `tap` after it (a tap changes the model; take a frame before the next one). Without one they are `err
<command> no-frame` (after a syntax check of the arguments: a malformed number is `bad-arguments` first). Points and
regions are in display pixels, decimal without sign; `x y` must lie inside the display.

Replies: `ok ...` success; `fail <command>` the model returned false (an ordinary reply that poisons the session: every
later command but `open`, `domain-count` and `quit` is `err <command> not-open` until a successful `open`); `err
<command|?> <why>` a protocol error, counted. Whys: `malformed`, `unknown-command`, `no-frame`, `too-large` (a frame
whose facts exceed a cap or the payload: never a truncation; poisons), `bad-arguments` (also a wrong
argument count), `not-open`, `line-too-long`, `eof-without-quit`, `model-contract` (the model broke the interface:
`n > UIM_ENV_MAX`, `len > cap` or a changed buffer pointer or capacity, a record that breaks the grammar, a NULL display from
`uim_frame`, an env input that is not kind env, a `uim_next_due` at or before now on a stable scene, an `apply` result
outside the enum, a display lvprobe cannot read, a changed display, a scene that never settles or keeps changing under
the probe; it poisons the session except after `env-inputs`, `semantic` and `hit-test`), `internal` (a handler failed without an `err` line: never a partial `ok`).
A last line without LF is `err ? malformed` followed by `err ? eof-without-quit`. Exit status 0 when no protocol error
occurred and `quit` ended the session, 1 otherwise, 2 if stdout cannot be written. Static memory only.

## Frame facts (U05a; `probe_frame.c`, `probe_input.c`, `probe_pixels.c`, `probe_seam.c`)

`frame` calls `uim_frame` and checks the display against LVGL's display list (by address, before anything touches it)
and against the session's display: no display, a pointer that is not in the list, or another display than the session's
is `err frame model-contract`. On the first frame of a session it opens lvprobe on it. Then it takes a snapshot, in the
order docs/ui-lvprobe.md ("Calls and the seam") prescribes: the lifecycle events queued since the previous frame
(`lvprobe_life`), refreshes until one flushes nothing (`lvprobe_settle`, at most `PROBE_SETTLE_MAX` = 8), then
**`uim_settle`**, then `lvprobe_walk` and `lvprobe_frame` (checksum and region hashes). The refreshes run the LVGL
animations and the refresh that are due at the current tick (`lv_refr_now`), and an animation's callback may post product
work: `uim_settle` runs it, and if anything ran (`worked`), or a status says "settle and retry" (`STALE`, `UNSETTLED`, an
event during the snapshot), the whole snapshot is taken again, at most `PROBE_FRAME_TRIES` = 4 times; still moving is
`err frame model-contract`, a failing `uim_settle` is `fail frame`. A product whose steps run its animations at the step's
tick (the frame toy sets LVGL's animation timer period to 1 ms) sees no difference in timing whether frames are taken or
not (`selftest/ui_frame.sh`, "a frame changes no timing"). The reply is then streamed into the payload:
`lvprobe_encode_head`, one `lvprobe_encode_node` call per node at its offset (never one buffer for the whole tree), then
one `life` line per lifecycle event. The probe checks every byte (printable ASCII and TAB, LF-terminated) before the
header goes out, so a reply is whole or it is one `err` line.

**The records of a `frame` reply**, in this order (fields TAB-separated, never empty; integers decimal, colours 6 and
hashes 8 lowercase hex digits; boxes `x1,y1,x2,y2` or `-`; escaping as in "Record grammar" above). All but `life` are
lvprobe's, defined in docs/ui-lvprobe.md ("Text format", "Definitions"):

| Line | Fields | Meaning (docs/ui-lvprobe.md) |
|---|---|---|
| `lvprobe` | 3 | `lvprobe`, format version `1`, node count of the walk |
| `frame` | 4 | `frame`, w, h, crc (FNV-1a over B, G, R of every pixel) |
| `node` | 21 | `node`, i, parent, depth, class, x1, y1, x2, y2, hidden, clickable, clip, scroll, scroll_x, scroll_y, bg, bg_opa, bg_opa_drawn, bg_opa_exact, bg_grad, bg_image (one per node, walk order: bottom layer, active screen, top layer, sys layer) |
| `label` | 15 | `label`, i, font id or `-`, line_h, align, align_drawn, long, dotted, lines, natural_w, natural_h, laid_w, laid_h, `=`text, full_text or `-` (after its node, labels only) |
| `fit` | 8 | `fit`, i, drawn, unsupported, glyphs box, visible box, missing (placeholder glyphs), clipped (after `label`) |
| `region` | 3 | `region`, i, hash (FNV-1a of the node's coords inside the display) |
| `life` | 7 | written by the probe: `life`, seq (lvprobe's running number since `open`), `created` or `deleted`, late (`1`: found on a screen observed late), node, parent, class |

`life`: node is the walk index of a deleted object in the **previous reported** frame's walk (-1 for a creation), parent
its parent's index there (or -1). An event drained after a walk this same `frame` command took and did not report (a
retried snapshot) would carry indexes of that unreported walk: it is written with node and parent -1. class is the
object's class name escaped by the record grammar (a TAB is `\t`, a non-ASCII byte `\xHH`), `-` when it is empty; a
long or non-ASCII name is data (the line takes at most 64 + 4 x its length bytes). The first frame after an `open` has no
`life` lines: lvprobe starts observing at that frame and logs what changes after it. `ink` and `noink` records (8 and 3
fields, docs/ui-lvprobe.md) come from the `ink` command only. A judge keys nodes through the scene, never through the
index (lvprobe, "Walk order and index").

**Statuses.** A per-node `unsupported` (walk) or an unmeasurable ink (`noink unstable`, `noink transformed`) is data.
`FULL` (a cap), `OVERFLOW` (lifecycle events lost) and a payload that cannot hold the lines are `err frame too-large`.
`model-contract`: `FORMAT` (not one full-size XRGB8888 buffer in DIRECT mode, no refresh timer, a rotated display),
`GONE` (the display was deleted), `LVGL` (LVGL refused something: normally the product's doing, such as its pool), a
display that never settles or keeps changing, a display with more pixels than the ink scratch, a display with more than
one pointer indev, a `uim_settle` result other than `UIM_OK`/`UIM_ERROR`, and a moved tick (below). Anything else is
`err frame internal`. Each poisons the session. In `ink`, an unstable or unsettled node is settled and retried once
(lvprobe's rule); still unstable is `noink unstable`; a retry settle that flushed drops the frame (the checksum the last
`frame` reported would be older than the buffer `crop` reads), so the next `crop`, `tap` or `hit-test` needs a new frame.

**The tick is the gate's.** The probe reads `lv_tick_get()` before and after the snapshot of `frame`, the tap and its
settle, `ink` and `crop`; if it moved, a product drives LVGL's tick from something other than `uim_step` (a real clock, a
tick callback): `err <command> model-contract` (poisons, except after the read-only `crop`).

**Caps and the per-frame byte budget** (`ui/model/probe.h`): `PROBE_LV_NODES` 512 objects, `PROBE_LV_TEXT` 16384 bytes
of label text, `PROBE_LV_LIFE` 1024 lifecycle events between two frames, 16 screens, `PROBE_LV_SCRATCH_PX` = 1280 x 800
ink pixels. A display with more pixels than the scratch is refused when lvprobe is opened (`err frame model-contract`), so
`ink` can never run out of scratch later. The lines of one reply hold at most `UIM_BUF_MAX` - 1 = 65535 bytes. A node
takes at most `LVPROBE_LINE_FIXED` (1024) + 4 x (class name + text + full text) bytes, a `life` line at most 64 + 4 x
its class name; typical: 60 to 90 bytes for a plain node with its region, a label about 100 more plus 4 per UTF-8 byte of
its text. lvprobe measured a Bulgarian screen of 84 objects at 14,790 bytes; the frame toy's frame (15 objects) is about
2 KB. A frame over the budget (the frame toy's 400 labels, `selftest/ui_frame_product/bad.in`) is `err frame too-large`,
never a truncated reply.

**Storage and order.** The probe owns the lvprobe object (`probe_main.c`) and all its storage (`probe_frame.c`,
`probe_pixels.c`), static. lvprobe is closed before every `uim_open` (the model may delete the display) and before exit;
`lvprobe_close` finds neither display nor indev when they are already gone. **Which indev:** the pointer indev of the
display at the moment lvprobe is opened (the first `frame` of the session) carries the taps; a display with none gets a
pointer indev lvprobe creates; a display with more than one is ambiguous and refused (`err frame model-contract`); one the
product creates later in the session is not used (docs/ui-lvprobe.md, "Which indev").

**Hit query and tap.** `hit-test` is `lvprobe_hit_test` (LVGL's `lv_indev_search_obj` over sys, top, active and bottom
roots): no input event is sent; only LVGL's own `LV_EVENT_HIT_TEST` reaches objects with `LV_OBJ_FLAG_ADV_HITTEST`.
`tap` is `lvprobe_hit` (the product's handlers run), then `uim_settle`, then refreshes to a quiet frame. The reply names
the walk index of the pressed and of the clicked object; an object outside the walk is `err tap internal`.

## `c_ui_probe` (`rules/ui.bzl`)

`c_ui_probe(name, model)`: `model` is the `c_library` of the adapter. There is no `deps`: the adapter carries its own
dependencies, which every gate judges as for any library (`rigor buckfiles` refuses `deps` and `visibility`). It is a
`c_binary` (sealed C17 flags, the facts targets of every mode) of the adapter plus `gate//ui/model:probe`, built in the
modes of any `c_binary`; the grade uses release and san. A product BUCK file loads it with
`load("@gate//rules:ui.bzl", "c_ui_probe")` (next to the `c.bzl` load; `rigor buckfiles` accepts exactly these two loads)
and may name `gate//ui/model:model` (the header) in the `deps` of a library, binary or test; it can never name the probe
library, in any spelling.

## Confinement of the `uim_`, `lvprobe_` and `lvp_` symbols (P004 6.3)

The `symbols` gate reserves the prefix itself (`ui-model-symbol`, `gate/rigor_lib/facts_symbols.py`), whatever the
product's policy file says (a `trusted` entry included) and with no policy entry of any kind: a product module that
**defines or references** any symbol starting with `uim_` is a finding (`use` = `defined` or `referenced`), except (a) the
`model` of a `c_ui_probe`, exactly one target, and (b) the gate's probe library. The set is derived from the prefix, not from
a list of names, and from the build graph, not from hand-written labels. A library that depends on the adapter and calls
it is flagged; so is a module that defines and calls its own `uim_` name, and the header library if it ever defined one.
The probe library's undeclared references to the adapter's symbols are accepted; its other symbols are judged as before.

Only the gate's own targets can be exempt: labels are compared exactly, in the spelling a product build prints for the gate
cell, `gate//ui/model:probe` (and `gate//ui/model:model`). A product's own `//ui/model:probe`, `root//ui/model:probe` and
every other spelling never match. A product cannot have the package either: `rigor buckfiles` refuses any file under
`ui/model/` (`reserved-package`) and any dep label `//ui/model:...`, and the product layout excludes `ui/model/**` like
`third_party/**`. A probe binary that does not have exactly one dependency besides the gate's two libraries is
`ui-probe-shape`, and then nothing is exempt for it.

**The lvprobe prefixes (U05a).** The same gate rule reserves `lvprobe_` and `lvp_` (`ui-lvprobe-symbol`,
`UI_LVPROBE_PREFIXES`): a product module that defines or references such a symbol is a finding, whatever its policy says
(a `trusted` entry included). Only `gate//ui/lvprobe:lvprobe`, in exactly that spelling, may define them, and only the
gate's probe library may reference them (it may not define one). `//ui/lvprobe:lvprobe`, `root//...` and every other
spelling are not the gate's (`gate/tests/test_ui_symbols.py`). The lvprobe library is a gate-owned library like
`ctest`: a product's facts include it, its policy lists it as `trusted`, and its exports grant the probe library's calls
(there is no "no facts" exception for it).

A product policy still needs ordinary entries for the gate libraries in the product's facts, keyed `gate//ui/model:model`
and `gate//ui/model:probe` (`selftest/ui.sh` relabels the root-cell facts of `//ui/model:...` and `//ui/lvprobe:...` to that
spelling), and `gate//ui/lvprobe:lvprobe` in `trusted`: the probe library with `allow` = the symbols it imports that no
gate dependency defines (libc and the few LVGL calls it makes itself), `allow_mutable_data = true` and its `exports`
(`main` and the `probe_*` helpers). `selftest/ui_product/probe_imports.expected` is the checked-in list of those imports;
`ui.sh` derives it from the facts and fails on any difference, and builds the policy's `allow` from it. Making the gate's UI libraries exempt from a product's
policy, layering and RAM budget, as `gate//rt:require` is, is a separate task.

## Known gaps

* lvprobe's font ids are not mapped (`lvprobe_map_font`): every label's font field is `-`. The gate does not know the
  product's fonts; mapping them needs a model call or a sealed table (a later task).

* `tools/validate.sh` learned the `ui` name (one case and the lane order) so that a selected `ui` runs.
* The `model-contract` cases for a NULL display, an env input of the wrong kind, `n > UIM_ENV_MAX` and a changed buffer
  are implemented in the probe but not driven by the toy (the record grammar, the two-TAB overflow and `due <= now` are).
