# The UI model interface and the probe (U03, U05a, P004 4.2, 6.2, 6.3)

The UI gate drives a product through one small, gate-owned interface, `ui/model/model.h`. A product implements it in a
model adapter (a `c_library`); `c_ui_probe` links the adapter with the gate's `main` (`ui/model/probe_main.c` and its
helpers) into a probe binary that speaks a line protocol on stdin and stdout. The probe reads the rendered frame through
`gate//ui/lvprobe` (U02, docs/ui-lvprobe.md; "Frame facts" below, U05a). Its client is the explorer, `rigor ui-explore`
(U05, docs/ui-explore.md), which speaks this protocol exactly as written here. Selftest:
`selftest/ui.sh` on the toy app in `selftest/ui_product/`, and `selftest/ui_frame.sh` (called by it) on the frame toy in
`selftest/ui_frame_product/`.

## The interface (`ui/model/model.h`)

Gate-owned types only (`uim_t` is opaque and defined by the product; `uim_buf_t {data, cap, len}`;
`uim_input_t {kind, id, arg, text}`; `uim_result_t` = `UIM_ERROR | UIM_OK | UIM_REFUSED | UIM_MISSED`). Rules for every call, written in
the header: static storage (no allocation; the one model object comes from `uim_instance()`), determinism (only the
virtual clock and the seed of `uim_open` influence output), and:

* **A failure poisons the session.** A call that returns false (or `UIM_ERROR`) may have changed the model halfway
  (LVGL cannot be rolled back); the gate calls nothing but `uim_open` afterwards. The read-only `uim_env_inputs`,
  `uim_semantic` and `uim_identity` (U24) are the exceptions. `fail open` leaves the model closed.
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
| `uim_pointer_supported()`, `uim_pointer(m, x, y, down)` | the optional pointer entry (U05c, below): a constant of the build, and one pointer sample delivered exactly as the product's real input source would, the clock still, processed by the next `uim_settle`; false poisons |
| `uim_identity_supported()`, `uim_identity(m, out)` | the optional scene identity (U24, below): a constant of the build, and the state class and per-node element id, msgid and arguments of the current scene; read-only, false does not poison |

### The pointer entry (U05c)

A real kiosk handles a pointer event above LVGL first: its input hook queues the sample, posts an event (a `touch` that
restarts idle deadlines) and tracks the held state, and only its loop feeds LVGL's indev. A tap the probe injects at
LVGL's indev skips all of that, so it is not the production input path. A product therefore says whether it has a
pointer entry, and the probe then taps through it.

**An interface break.** Every model adapter must now define both functions (`uim_pointer_supported` and
`uim_pointer`), also one without a pointer entry: an adapter of before U05c no longer links with the probe main. The
selftest's adapters and the frame toy define the "no entry" pair below; a real product adds the same few lines.

**The mechanism: two required functions.** `bool uim_pointer_supported(void)` returns a constant of the build, and
`bool uim_pointer(uim_t *m, int32_t x, int32_t y, bool down)` must exist in every adapter and return false when it is not
supported (and whenever the sample could not be delivered). Both are ordinary required symbols: the probe main
references them, so an adapter without them does not link, and no weak symbol is needed in product code. Both carry the
`uim_` prefix, so the symbols gate confines them like the rest of the interface with no change to it (only the `model`
of a `c_ui_probe` may define or reference them; `gate/rigor_lib/facts_symbols.py` is unchanged). A constant function is
simpler than a capability record or a weak `uim_pointer`, which the symbols gate could not check (a weak undefined
reference links to NULL) and which the C rules exclude. The probe reads `uim_pointer_supported()` once, before its
greeting.

What a product adapter needs, in the build without an entry:

    bool uim_pointer_supported(void) { return false; }
    bool uim_pointer(uim_t *m, int32_t x, int32_t y, bool down) { (void)m; (void)x; (void)y; (void)down; return false; }

and with one (the host's input hook does the real work: here a queue the next `uim_settle` feeds to LVGL's indev):

    bool uim_pointer_supported(void) { return true; }
    bool uim_pointer(uim_t *m, int32_t x, int32_t y, bool down)
    {
        return m->open && host_pointer_sample(&m->host, x, y, down);   /* queue it, post `touch`, track the held state */
    }
    /* uim_settle: run the host loop at the current virtual time: it drains the queue into the pointer indev
     * (lv_indev_read) and then the work the click queued, as it does for any other queued input. */

### Scene identity (U24)

The semantic records say what is drawn, not what it IS. Three checks of the ui-scene judge need the latter
(docs/ui-judges.md): `required-element-missing` (the state class of each state and an element id per node: the splash
without its version line, F10; the report without its columns, F11; the pad without its echo, F2), `value-split` (which
nodes make one value: the locker number "82" drawn as two labels, F5) and `raw-text` (the msgid of a text: a raw msgid
on screen). The 14 semantic fields stay as they are, so every recorded transcript stays valid; identity is a call of
its own.

**The mechanism: two required functions, as U05c's pointer entry.** `bool uim_identity_supported(void)` returns a
constant of the build and `bool uim_identity(uim_t *m, uim_buf_t *out)` writes the records below. Both must exist in
every adapter (an interface break: an adapter of before U24 no longer links with the probe main), ordinary required
symbols of the `uim_` prefix that the symbols gate confines with no change to it (`rules/ui.bzl` and
`gate/rigor_lib/facts_symbols.py` are unchanged), no weak symbol in product code. A product without identity returns
false from both (the toys of `selftest/ui_product` and `selftest/ui_frame_product` do); the canary of the judges'
selftest reports it. The probe reads `uim_identity_supported()` before its greeting and again at every `identity`
command (a different answer is `err identity model-contract`). `uim_identity` is read-only like `uim_semantic`: it
never changes the model, is callable whenever `uim_semantic` is, and neither its failure (`fail identity`) nor a
breach of its grammar (`err identity model-contract`) poisons the session.

    bool uim_identity_supported(void) { return false; }                     /* a product without identity */
    bool uim_identity(uim_t *m, uim_buf_t *out) { (void)m; out->len = 0; return false; }

**The records** (one call, the record grammar's lines, escapes and printable bytes; unlike the other records NO empty
field, `-` is "none"; two record types told apart by their first field):

| Record | Fields | Meaning |
|---|---|---|
| `state` | `state`, class | exactly one, the FIRST line: the state class id of the screen shown: the product's name for that class of screen in its UI spec, a `[[state_class]]` id of the UI contract (lockers: `welcome`, `opened`, `dialog`, ...). Never `-` |
| `node` | `node`, key, element, msgid, n, then n arguments | one line per semantic node that has any identity, in any order, each key at most once and a key of the `uim_semantic` records of the same scene. `element`: the node's element id or `-`; `msgid`: the catalogue key its text was formatted from or `-`; `n`: decimal 0..16 (`UIM_IDENTITY_ARGS_MAX`), then exactly n fields, each `=` followed by the escaped bytes of one formatted argument (`=` alone is an empty argument: the `=` marker, as in the frame's `life` class field, lets an empty argument exist without an empty field) |

A `node` line whose element and msgid are both `-` (no identity), arguments without a msgid, a wrong argument count,
an argument without `=`, an empty field, a first line that is not the one `state` line, a second `state` line, or
(fix-up 1) a node key twice breaks the interface (`err identity model-contract`; the probe checks every line,
`probe_identity.c`). The explorer checks the same grammar (a violation of it read from a probe is a protocol error) and
then, as the model's breach (a probe error of kind `contract`, `probe-internal-error`): a key twice, a key no semantic
record of the step has, and (fix-up 1) a model that `identity` changed: after every `identity` it reads `next-due` and
`semantic` again and compares them with the step's observation, so read-only is verified, not only documented
(identity is read only under judging, and a model that changed on it would be graded on another behaviour).

**What each means, and what a product may not do.**
- The **state class** is the product's name for the class of screen shown, from its UI spec, the same for every state of
  that class (the language, a formatted value or a countdown do not change it). It is not the abstraction key: the
  explorer keys states as before, and the judges look the class up in the contract's `[[state_class]]` rows.
- An **element id** is a stable name of a node from the product's UI spec (the names the contract's `required` lists and
  `[[element]]` rows use: `screen_headline`, `numpad`, `countdown`, `lang_bg`, ...). A product may NOT derive it from the
  node's text, its position, its index or anything that changes with the language or the data; nodes that make one
  value (the digits of a locker number) carry the same element id.
- The **msgid** is the catalogue key the node's text was formatted from (gettext's msgid), byte for byte; the
  **arguments** are the values formatted into it, as formatted, in order. A text that is not catalogue text has no
  msgid (`-`); a product may NOT report a msgid for a text it did not format from the catalogue, nor the formatted text
  as the msgid.

The simplest mechanism the probe and the explorer can check exactly: one reply of two fixed record types, the counts
explicit, every field checked by the existing escape grammar. A 15th semantic field would have changed every
transcript and the 14-field grammar; a field per kind of identity (a separate `state` command) would have cost a
second round trip per step for no gain.

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

**The greeting.** `ui-probe/1 ready` followed by the capabilities, each a single space and a token, each at most once
and in this fixed order: `frame-facts`, `ink`, `hit-test`, `tap`, `apply-missed`, `crop` (a capability added later is
appended to the list). This probe announces those six, `pointer` (U05c) when the product has a pointer
entry (`uim_pointer_supported()`): `ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop pointer`, and
`identity` (U24) after it when the product reports its scene identity (`uim_identity_supported()`; the canary:
`ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop identity`).
A greeting with no capability is an older probe of the same protocol. The protocol name stays `ui-probe/1`: a capability
only adds commands or replies, it never changes an existing one. The explorer refuses an unknown, repeated or unordered
capability (a protocol finding) and a catalogue that needs one the probe does not announce (taps need `hit-test` and
`tap`).
`frame-facts`: `frame` carries the lvprobe records below; `ink`, `hit-test`, `tap`, `crop`: those commands;
`apply-missed`: `apply` can reply `ok apply missed`; `pointer`: `tap` goes through the product's pointer entry ("Hit
query and tap"), so a catalogue can require that its taps take the production input path; `identity`: the `identity`
command (below).

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
| `tap <x> <y>` | `ok tap <pressed> <clicked>` (node indexes or `none`) or `ok tap blocked`: a press and release through the production pointer path (the product's pointer entry with `pointer`, else LVGL's pointer indev), then `uim_settle` (so an intent the click queued runs at the tap's time: `trace`, `semantic` and `next-due` right after the tap show it), then refreshes to a quiet frame. An input: an `err` or `fail tap` (the settle failed) poisons, `blocked` does not |
| `crop <x> <y> <w> <h>` | `ok crop lines <h>`: one line per row, 8 lowercase hex digits (`rrggbbaa`) per pixel. The region must lie inside the display and `h x (8 w + 1) <= 65535` (160x51 fits, 160x52 does not); otherwise `bad-arguments`. Read-only |
| `semantic`, `patches`, `trace` | `ok <name> lines <n>` followed by exactly n record lines, verbatim; `fail <name>` (patches and trace poison) |
| `identity` (U24) | `ok identity lines <n>` and the n identity records ("Scene identity"), verbatim; needs `open`, no frame; `fail identity` (does not poison); `err identity unsupported` from a probe that did not announce `identity`; `err identity model-contract` (does not poison) for a breach of the grammar or a `uim_identity_supported()` that changed |
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
the probe; it poisons the session except after `env-inputs`, `semantic`, `identity` and `hit-test`), `unsupported`
(U24: `identity` from a probe that did not announce it), `internal` (a handler failed without an `err` line: never a partial `ok`).
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
| `taps` | 2 | written by the probe, in the first frame of a session only, third (after `frame`): `taps`, `entry`, `indev` or `probe` (U05c, "Hit query and tap") |
| `life` | 7 | written by the probe: `life`, seq (lvprobe's running number since `open`), `created` or `deleted`, late (`1`: found on a screen observed late), node, parent, `=` and the class |

`life`: node is the walk index of a deleted object in the **previous reported** frame's walk (-1 for a creation), parent
its parent's index there (or -1). An event drained after a walk this same `frame` command took and did not report (a
retried snapshot) would carry indexes of that unreported walk: it is written with node and parent -1. class is the
object's class name after the prefix `=`, escaped by the record grammar (a TAB is `\t`, a non-ASCII byte `\xHH`): an
empty name is `=` and a class named `-` is `=-`, so no name reads as a marker; a long or non-ASCII name is data (the line
takes at most 64 + 4 x its length bytes). A `life` line is in the first frame after its event only. The first frame after an `open` has no
`life` lines: lvprobe starts observing at that frame and logs what changes after it. `ink` and `noink` records (8 and 3
fields, docs/ui-lvprobe.md) come from the `ink` command only. A judge keys nodes through the scene, never through the
index (lvprobe, "Walk order and index").

**Statuses.** A per-node `unsupported` (walk) or an unmeasurable ink (`noink unstable`, `noink transformed`) is data.
`FULL` (a cap), `OVERFLOW` (lifecycle events lost) and a payload that cannot hold the lines are `err frame too-large`.
`model-contract`: `FORMAT` (not one full-size XRGB8888 buffer in DIRECT mode, no refresh timer, a rotated display),
`GONE` (the display was deleted), `LVGL` (LVGL refused something: normally the product's doing, such as its pool), a
display that never settles or keeps changing (`uim_settle` that still works after `PROBE_FRAME_TRIES` snapshots included),
a display with more pixels than the ink scratch, a display with more than one pointer indev, a `uim_settle` result other
than `UIM_OK`/`UIM_ERROR`, and a moved tick (below). A `uim_settle` that returns `UIM_ERROR` is `fail frame` or `fail
tap`, and poisons. The explorer receives every `err` of these as `probe-internal-error` kind `protocol`
(docs/ui-explore.md, "Deviations"). Anything else is
`err frame internal`. Each poisons the session. In `ink`, an unstable or unsettled node is settled and retried once
(lvprobe's rule); still unstable is `noink unstable`; a retry settle that flushed drops the frame (the checksum the last
`frame` reported would be older than the buffer `crop` reads), so the next `crop`, `tap` or `hit-test` needs a new frame.

**The tick is the gate's.** At the first frame after `open` the probe records `lv_tick_get() - (uint32_t)now` (the
virtual clock), and at every later check (before and after the snapshot of `frame`, the tap and its settle, `ink`,
`crop`) it requires the same offset. Only `uim_step` moves both together, so a product that drives LVGL's tick from a
real clock or a tick callback, or an `apply` or a settle that moves it, is caught at the next check whenever the clock
moved, not only when a millisecond boundary falls inside one command: `err <command> model-contract` (poisons, except
after the read-only `crop`). The frame toy has three fixtures: a tick callback that moves on every read, a settle that
moves the tick, and a clock that moves only between frames (which a before/after comparison would miss).

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

**A display the product deletes.** When lvprobe reports the display gone (`GONE`, from `hit-test`, `crop` or any
other call), the frame is dropped (`framed` false): no later command reads the display again until a `frame`, which
compares the model's display pointer with LVGL's list by address only and refuses it (`err frame model-contract`).

**Hit query and tap.** `hit-test` is `lvprobe_hit_test` (LVGL's `lv_indev_search_obj` over sys, top, active and bottom
roots): no input event is sent; only LVGL's own `LV_EVENT_HIT_TEST` reaches objects with `LV_OBJ_FLAG_ADV_HITTEST`.
`tap` takes one of two paths, fixed for the probe by `uim_pointer_supported()`; the reply grammar is the same.

* **Through the product's pointer entry** (capability `pointer`): `lvprobe_observe_begin` (the point, a current walk
  unless a press would be blocked now, the product's pointer indev; docs/ui-lvprobe.md "Observing a tap"), then
  `uim_pointer(x, y, true)`, `uim_pointer(x, y, false)`, then `uim_settle` (the product processes its samples and the
  work the click queues, at the tap's time), then `lvprobe_observe_end`, then refreshes to a quiet frame. The probe injects
  nothing and swaps no callback: pressed and clicked are OBSERVED from LVGL's own events on the product's indev
  (`LV_EVENT_PRESSED` and `LV_EVENT_CLICKED`, each mapped to its walk index when LVGL sends it). LVGL sends no
  `LV_EVENT_PRESSED` for a disabled object although it presses it; when none came, LVGL's own pointer search at the
  point (the one `hit-test` uses) names the pressed node if it is a live walked node in the disabled state, clicked
  `none`: the answer of the injected path (the toy's disabled button is `ok tap 3 none` on both builds).
  **Blocked** on this path: LVGL would not have processed a press when the tap began (no display, the indev disabled, a
  screen-load animation running, waiting for a release: the cases of the injected path; and a HELD indev, which LVGL
  left pressed after a release it did not process: its next press gets no `LV_EVENT_PRESSED`. `hit-test` says
  `blocked` in the same cases, so the two agree). A tap blocked when it began is `blocked` whatever happened during the
  settle (the walk was not checked then). It is also blocked when LVGL leaves the indev pressed after this tap. A
  failing `uim_pointer` or `uim_settle` is `fail tap` (poisons). `err tap model-contract` (poisons): a product that
  announces `pointer` with no pointer indev of its own at the session's first frame (`err frame model-contract` at that
  frame), a `uim_pointer_supported()` that differs from the greeting's (re-read at every tap), an indev deleted during
  the tap, the probe's listener removed, more than one press or click, and samples LVGL never read: an unblocked tap
  needs evidence that LVGL read the press (its `LV_EVENT_PRESSED`, or the advance of the indev's vector history that
  every processed press makes) and the release at the tap's point (the indev released, its point the tap's); a product
  that claims the entry and drops samples never reads as "pressed nothing".
  The probe does not reset the product's indev on this path, so LVGL's click streak persists between taps: a second
  tap at the same point within LVGL's double-click window also raises `LV_EVENT_DOUBLE_CLICKED` (`LV_EVENT_CLICKED` is
  still sent once per tap, and a tap is still one tap). "Clicked" means LVGL dispatched `LV_EVENT_CLICKED` to the
  indev; a product's own indev handler can stop the processing before the object sees it.
* **Injected at the pointer indev** (no `pointer`): `lvprobe_hit` (the product's handlers run, its read callback is
  replaced for the two reads, the indev reset first), then `uim_settle`, then refreshes to a quiet frame.

Which path taps take is a frame fact: the first frame of a session (the one that attaches lvprobe) carries one line
`taps<TAB><path>` after the `frame` line: `entry` (the product's pointer entry), `indev` (injected at the product's own
pointer indev: a product that has one but does not announce `pointer`) or `probe` (injected at the indev lvprobe
created: the display had none). The explorer records it in its summary (`taps`) and reports the info finding
`taps-injected` once per run for `indev` (docs/ui-explore.md).

The reply names the walk index of the pressed and of the clicked object; an object outside the walk is `err tap
internal`. The toy of `selftest/ui.sh` has both builds: `probe_pointer` (a queue above LVGL that the settle feeds to the
app's indev, and a press posts `touch`) and `probe` (no entry). The session `pointer.in` shows on the first the `touch`
and the click's `press` at the tap's instant, the scrim's tap posting `touch` only, a blocked tap with its `touch`
(delivered, then dropped by LVGL); on the second the same nodes and blocked tap without any `touch`
(`selftest/ui_product/pointer_check.py`). `pointer_bad.in` drives the path's failures on the first build: a failing
`uim_pointer` (`fail tap`, poisoned), a product that delivers a second whole tap (`err tap model-contract`, poisoned)
and every malformed `tap` (`err tap bad-arguments`, transcript `pointer_bad.out`).

## `c_ui_probe` (`rules/ui.bzl`)

`c_ui_probe(name, model)`: `model` is the `c_library` of the adapter. There is no `deps`: the adapter carries its own
dependencies, which every gate judges as for any library (`rigor buckfiles` refuses `deps` and `visibility`). It is a
`c_binary` (sealed C17 flags, the facts targets of every mode) of the adapter plus `gate//ui/model:probe`, built in the
modes of any `c_binary`; the grade uses release and san. A product BUCK file loads it with
`load("@gate//rules:ui.bzl", "c_ui_probe")` (next to the `c.bzl` load; `rigor buckfiles` accepts exactly these two loads)
and may name `gate//ui/model:model` (the header) in the `deps` of a library, binary or test; it can never name the probe
library, in any spelling.

## `c_ui_probe_session` (`rules/ui.bzl`, U05c)

`c_ui_probe_session(name, probe, session, expected)`: a test that runs a product's probe on a checked-in session and
compares the transcript, so the strongest evidence a product has about its own UI (frames, taps, hit-tests on the real
app) is enforced by `buck2 test` and needs no product script. `probe` is `":<name>"` of a `c_ui_probe` declared in the
same BUCK file; `session` (the commands, fed to stdin) and `expected` (the transcript) are two plain files of the
package (relative paths such as `tests/session.in`; no label, glob, `.`, `..` or absolute path). `rigor buckfiles`
accepts exactly these four keywords, all given, as string literals (`bad-argument` with why `keyword`, `missing`,
`value`, `probe` for a probe that is not a `c_ui_probe` of the same file, `file` for one file named twice), and
nothing may depend on the target (why `test-target`).

The test passes only if all four checks hold, in this order:
1. the session's last line is exactly `quit` (LF-terminated, nothing after it): a checked session is a clean one, so the
   exit status it implies is 0 (a session that ends otherwise would exit 1 with `err ? eof-without-quit`, and the strict
   protocol transcripts such as `bad.in` stay the selftest's own steps);
2. the probe exits 0 (killed by a signal is a failure);
3. it writes nothing on stderr (so any sanitizer report fails it);
4. its stdout is byte-identical to `expected`.

The report names every failed check; for stdout the first differing line with its number and both lines with their LF
(`stdout line 5 differs: got b'ok frame lines 26\n', want b'oK frame lines 26\n'`; a line longer than 512 bytes says
how much of it is shown). The probe runs once per mode with the session on stdin and an environment of the sealed
sanitizer variables of a `c_test` only (rules/ctest.bzl `sanitizer_env_lines`, the hermetic symbolizer, reports on stderr).

**How it is built and how it appears.** `c_ui_probe` also defines `<name>__ui_probe`, a mark that carries only the probe
binary (`UiProbeInfo`); the session rule accepts nothing else, so it can run no other binary and no product script. The
run is a cacheable build action of the gate-owned runner `gate//ui/model:probe_session.py` (stdlib Python, `python3 -I
-B`), compatible with the release and the san platform only: each mode is its own target configuration and its own
result. The target's default output is the result in the JSON Lines of `ctest` (docs/ctest.md; parsed by
`gate/rigor_lib/results_parse.py`), one record and the summary:

    {"asserts": 4, "id": "ui_probe_session/selftest.ui_product:session_test", "status": "pass"}
    {"summary": {"passed": 1, "total": 1}}

The id is `ui_probe_session/<package, "/" written ".">:<name>`; a failed run has `"status": "fail"` and the first failed
check as `reason`. Sub-targets `[report]` and `[verdict]`. `buck2 test` runs the target as one test (an external-runner
test labelled `c_ui_probe_session`, like a `c_fuzz` or `c_sim` verdict), listed under its label:
`✓ Pass: root//selftest/ui_product:session_test` with the report on its stdout, counted in `Pass N. Fail M.`. A later
expected-tests list holds the id above, one per target (the same id in release and san, as for a `c_test`). The id
spells `/` as `.`, so the packages `a/b` and `a.b` give the same id for a target of the same name: a product must not
have both (an id collision the tests gate would report as a duplicate).

**A SESSION IS ENFORCED BY `buck2 test` ONLY, NOT YET BY `rigor grade`.** The grade's `build` gate
(gate/rigor_lib/grade_build.py) collects only `kind(ctest_results, //...)` targets. The rule kind of every session is
the public name `ui_probe_session_run` (`kind(ui_probe_session_run, //...)` lists them; `selftest/ui.sh` queries it).
The follow-up, outside U05c: query that kind in `result_targets` too and copy each default output into the results
directory, so the tests gate sees the id `ui_probe_session/<pkg>:<name>` like any ctest id; and a selftest step in which
a failing session fails a grade.

Bounds: the runner reads stdout up to the expected length plus 64 KiB and stderr up to 64 KiB, and the run lasts at
most 600 s; past any of them the probe is killed and the session fails with that reason (a recorded failing verdict:
the build of the target succeeds and `buck2 test` fails, never a hang). A session whose replies contain an `err` exits 1
even when it ends in `quit`, so it cannot be a session test: such strict-protocol transcripts stay script steps.

`selftest/ui.sh` checks both toys' `session.in` and the taps session on both toy builds with session targets in
release and san (besides its own comparison steps), and shows at Buck2 level that one changed byte of `session.out`
leaves the build of the target green and makes `buck2 test` fail naming the first differing line (the file is
restored). A probe that writes to stderr, a session that does not end in `quit`, a probe that writes past its caps or
never ends each fail it (gate/tests/test_ui_probe_session.py drives the runner with fake probes for every check).

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
* U24: the identity grammar is driven by the probe's unit test (`//ui/model:probe_test`, every violation above), by the
  explorer's stub, and (fix-up 1) end to end by a toy build whose identity breaks the interface
  (`selftest/ui_product/identity_bad.c`, `:probe_identity_bad`): selftest/ui.sh sees a node line without identity and a
  key twice as `err identity model-contract`, a failing call as `fail identity`, and the next `identity` and `next-due`
  still answer (neither poisons). The plain toy drives `err identity unsupported`, the canary the supported path
  (`identity.in`, `identity.out`).
