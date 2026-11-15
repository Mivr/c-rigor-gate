# The UI model interface and the probe (U03, P004 4.2, 6.2, 6.3)

The UI gate drives a product through one small, gate-owned interface, `ui/model/model.h`. A product implements it in a
model adapter (a `c_library`); `c_ui_probe` links the adapter with the gate's `main` (`ui/model/probe_main.c` and its
helpers) into a probe binary that speaks a line protocol on stdin and stdout. Later tasks add `lvprobe` (U02, joined at
the seam below) and the Python driver (U05). Selftest: `selftest/ui.sh` on the toy app in `selftest/ui_product/`.

## The interface (`ui/model/model.h`)

Gate-owned types only (`uim_t` is opaque and defined by the product; `uim_buf_t {data, cap, len}`;
`uim_input_t {kind, id, arg, text}`; `uim_result_t` = `UIM_ERROR | UIM_OK | UIM_REFUSED`). Rules for every call, written in
the header: static storage (no allocation; the one model object comes from `uim_instance()`), determinism (only the
virtual clock and the seed of `uim_open` influence output), and:

* **A failure poisons the session.** A call that returns false (or `UIM_ERROR`) may have changed the model halfway
  (LVGL cannot be rolled back); the gate calls nothing but `uim_open` afterwards. The read-only `uim_env_inputs` and
  `uim_semantic` are the exceptions. `fail open` leaves the model closed.
* **A refusal is not a failure.** `uim_apply` returns `UIM_REFUSED` for an input that is not enabled in this state; the
  model is unchanged and the session goes on.
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
| `uim_apply(m, in)` | deliver an env input, a wedge line or an intent; `UIM_OK`, `UIM_REFUSED` or `UIM_ERROR` |
| `uim_next_due(m)` | the next deadline or `UIM_NO_DEADLINE` (also before `open`), never earlier than now |
| `uim_step(m, ms)` | the time primitive above |
| `uim_frame(m, &disp)` | adopt and render the scene; `disp` must not be NULL |
| `uim_semantic`, `uim_patches`, `uim_trace` | text records (below); patches and trace clear their log |
| `uim_domain_count()`, `uim_domain_at(m, i)` | the optional view-domain sweep (the gate only asks for `i < count`) |

Deviations from P004's sketch: `uim_instance()` (the gate needs the one static model object and `uim_t` must not be a
product type in a gate header), `uim_frame` takes `struct _lv_display_t **` so the header includes no LVGL, and
`uim_advance` is gate code (the probe) over `uim_step`.

### Record grammar of `uim_semantic`, `uim_patches`, `uim_trace`

Gate-owned, line oriented. A buffer is zero or more records, one line each, LF terminated, printable ASCII and TAB
separators only; the fields of a record are separated by single TABs, in a fixed order and number, and may be empty.
Escaping: inside a field `\\` is a backslash, `\t` a TAB, `\n` an LF, `\xHH` (lowercase hex) any other byte outside
`0x20..0x7e`; any other backslash sequence or byte is a violation. The probe checks every line.

| Call | Fields |
|---|---|
| `uim_semantic` (14, one line per node, tree order, P004 4.2 "a11y+") | `key`, `role`, `label`, `x`, `y`, `w`, `h` (signed decimal), `enabled` (0 or 1), `intent:arg` (`-` if none), `flags`, `style`, `importance`, `input_policy`, `wrap_policy` |
| `uim_patches` (5, one line per scene patch since the last call) | `op`, `key`, `field`, `old`, `new` |
| `uim_trace` (3, one line per emitted event since the last call) | `seq` (from 0 at `open`), `type`, `mono_ms` (unsigned decimal) |

## The probe protocol `ui-probe/1`

One command per line on stdin; one reply per command on stdout, flushed after each. A command line is printable ASCII
(`0x20..0x7e`), single-space separated tokens, no leading, trailing or doubled space, at most 640 bytes, at most 8 tokens
and ended by LF; any other byte (TAB, CR, NUL, anything above `0x7e`) makes it malformed. Numbers are decimal, no
leading zeros, no overflow; `arg` may carry a `-` (never `-0`) and must fit `int32`; `id` must fit `uint32`. Text is `-`
(empty) or lowercase hex of 1 to 256 bytes, none of them `00`. The first line the probe writes is the greeting
`ui-probe/1 ready`.

| Command | Reply |
|---|---|
| `open <origin_ms> <seed>` | `ok open` or `fail open` (clears "open") |
| `env-inputs` | `ok env-inputs <n> <kind>:<id>:<arg>:<hex\|->...` (one line) |
| `apply <kind 1..3> <id> <arg> <hex\|->` | `ok apply`, `ok apply refused` or `fail apply` (poisons) |
| `next-due` | `ok next-due <ms>` or `ok next-due none` |
| `advance <to_ms>` | `ok advance <now_ms>` or `fail advance` (poisons); `to_ms` before now, more than 600000 ms ahead or past 2^52 is `err advance bad-arguments` |
| `frame` | `ok frame lines <n>` and n lines (the lvprobe seam; none today) or `fail frame` (poisons) |
| `semantic`, `patches`, `trace` | `ok <name> lines <n>` followed by exactly n record lines, verbatim; `fail <name>` (patches and trace poison) |
| `domain-count` | `ok domain-count <n>` (allowed before `open`) |
| `domain-at <i>` | `ok domain-at` or `fail domain-at` (poisons); `i >= count` is `err domain-at bad-arguments` |
| `quit` | `ok quit`; the probe then reads to EOF and any further non-empty line is `err ? after-quit` (once) and counted |

Replies: `ok ...` success; `fail <command>` the model returned false (an ordinary reply that poisons the session: every
later command but `open`, `domain-count` and `quit` is `err <command> not-open` until a successful `open`); `err
<command|?> <why>` a protocol error, counted. Whys: `malformed`, `unknown-command`, `bad-arguments` (also a wrong
argument count), `not-open`, `line-too-long`, `eof-without-quit`, `model-contract` (the model broke the interface:
`n > UIM_ENV_MAX`, `len > cap`, a record that breaks the grammar, a NULL display from `uim_frame`, an env input that is
not kind env, a `uim_next_due` in the past), `internal` (a handler failed without an `err` line: never a partial `ok`).
A last line without LF is `err ? malformed` followed by `err ? eof-without-quit`. Exit status 0 when no protocol error
occurred and `quit` ended the session, 1 otherwise, 2 if stdout cannot be written. Static memory only.

**Seam for U05.** `seam_frame_lines` in `probe_main.c` is called with the display after `uim_frame`; U05 writes the
`lvprobe` facts of the frame there, as printable lines, and they become the lines of the `frame` reply.

## `c_ui_probe` (`rules/ui.bzl`)

`c_ui_probe(name, model, deps = [])`: `model` is the `c_library` of the adapter. It is a `c_binary` (sealed C17 flags, the
facts targets of every mode) of the adapter plus `gate//ui/model:probe`, built in the modes of any `c_binary`; the grade
uses release and san. No flag argument. A product BUCK file loads it with `load("@gate//rules:ui.bzl", "c_ui_probe")`
(next to the `c.bzl` load; `rigor buckfiles` accepts exactly these two loads) and may name `gate//ui/model:model` (the
header) in the `deps` of a library, binary or test; it can never name the probe library.

## Confinement of the `uim_` symbols (P004 6.3)

The `symbols` gate reserves the prefix itself (`ui-model-symbol`, `gate/rigor_lib/facts_symbols.py`), whatever the
product's policy file says and with no policy entry of any kind: a product module that **defines or references** any
symbol starting with `uim_` is a finding (`use` = `defined` or `referenced`), except (a) the model adapters, that is
the dependencies of a probe binary (a target that depends on `gate//ui/model:probe`, which only `c_ui_probe` adds)
other than the gate's own two UI libraries, and (b) the gate's probe library. The set is derived from the prefix, not from
a list of names, and from the build graph, not from hand-written labels. A library that depends on the adapter and calls
it is flagged; so is a module that defines and calls its own `uim_` name, and the header library if it ever defined one.
The probe library's undeclared references to the adapter's symbols are accepted; its other symbols are judged as before.

A product policy still needs ordinary entries for the gate libraries in the product's facts: in a product cell the keys
are `gate//ui/model:model` and `gate//ui/model:probe` (`//ui/model:...` when the gate is the root cell, as in the
selftest), the probe library with `allow` = the stdio and string functions it calls, `allow_mutable_data = true` and its
`exports` (`main` and the `probe_*` helpers; see `selftest/ui.sh` for the working text).

## Known gaps

* `tools/validate.sh` learned the `ui` name (one case and the lane order) so that a selected `ui` runs.
