# The UI model interface and the probe (U03, P004 4.2, 6.2, 6.3)

The UI gate drives a product through one small, gate-owned interface, `ui/model/model.h`. A product implements it in a
model adapter (a `c_library`); `c_ui_probe` links the adapter with the gate's `main` (`ui/model/probe_main.c`) into a
probe binary that speaks a line protocol on stdin and stdout. Later tasks add `lvprobe` (U02, joined at the seam below) and
the Python driver (U05). Selftest: `selftest/ui.sh` on the toy app in `selftest/ui_product/`.

## The interface (`ui/model/model.h`)

Gate-owned types only (`uim_t` is opaque and defined by the product; buffers are `uim_buf_t {data, cap, len}`; inputs are
`uim_input_t {kind, id, arg, text}`). Rules for every call, written in the header: static storage (no allocation, the one
model object comes from `uim_instance()`), determinism (only the virtual clock and the seed from `uim_open` influence
output), failure is a `false` return and leaves the model unchanged, a too-small buffer is a failure.

| Call | Meaning |
|---|---|
| `uim_open(m, origin_ms, seed)` | cold boot to the first stable scene (nothing pending before the next reported deadline, LVGL has drawn once); callable again to restart |
| `uim_env_inputs(m, out, cap)` | the enabled environment and fault inputs, fixed order, at most `UIM_ENV_MAX` (64) |
| `uim_apply(m, in)` | deliver an env input, a wedge line or an intent at the current time, run to the next stable scene without moving the clock |
| `uim_next_due(m)` | virtual time of the next deadline or `UIM_NO_DEADLINE` |
| `uim_advance(m, to_ms)` | move the clock in 16 ms frames, running the LVGL timer handler each frame and ending a frame exactly at every deadline passed; never one long jump |
| `uim_frame(m, &disp)` | adopt and render the scene, return the LVGL display |
| `uim_semantic`, `uim_patches`, `uim_trace` | text lines into a `uim_buf_t` (the scene projection; the scene patches and the emitted events since the last call, then cleared) |
| `uim_domain_count()`, `uim_domain_at(m, i)` | the optional view-domain sweep: how many classes, and move to the i-th |

Deviation from P004's sketch: `uim_instance()` is added (the gate needs the one static model object and `uim_t` must not
be a product type in a gate header), and `uim_frame` takes `struct _lv_display_t **` so the header includes no LVGL.

## The probe protocol `ui-probe/1`

One command per line on stdin, exactly one reply line per command on stdout, flushed after each. A line is printable ASCII
(0x20 to 0x7e), single-space separated tokens, no leading, trailing or doubled space, at most 512 bytes. Numbers are
decimal without sign (`apply`'s `arg` may carry `-`), no leading zeros, no overflow. Text is `-` (empty) or lowercase hex of
printable ASCII bytes, at most 48 bytes. The first line the probe writes is the greeting `ui-probe/1 ready`.

| Command | Reply |
|---|---|
| `open <origin_ms> <seed>` | `ok open` or `fail open` |
| `env-inputs` | `ok env-inputs <n> <kind>:<id>:<arg>:<hex\|->...` |
| `apply <kind 1..3> <id> <arg> <hex\|->` | `ok apply` or `fail apply` |
| `next-due` | `ok next-due <ms>` or `ok next-due none` |
| `advance <to_ms>` | `ok advance` or `fail advance` |
| `frame` | `ok frame <0\|1>` (1: a display came back) |
| `semantic`, `patches`, `trace` | `ok <name> <len> <hex of the bytes>` or `fail <name>` |
| `domain-count` | `ok domain-count <n>` (allowed before `open`) |
| `domain-at <i>` | `ok domain-at` or `fail domain-at` |
| `quit` | `ok quit`, then exit |

Replies: `ok ...` the model call succeeded; `fail <command>` the model returned false (an ordinary reply, the session
continues, the exit status is unaffected); `err <command|?> <why>` a protocol error, counted. Whys: `malformed`,
`unknown-command`, `bad-arguments` (also a wrong number of arguments), `not-open` (any command but `open`, `domain-count`,
`quit` before a successful `open`), `line-too-long`, `eof-without-quit`. Exit status 0 when no protocol error occurred and
`quit` ended the session, 1 otherwise, 2 if stdout cannot be written. Static memory only.

**Seam for U05.** `seam_frame_facts` in `probe_main.c` is called with the display after `uim_frame`; U05 appends the
`lvprobe` facts of the frame to the `frame` reply there. It adds nothing today.

## `c_ui_probe` (`rules/ui.bzl`)

`c_ui_probe(name, model, deps = [])`: `model` is the `c_library` of the adapter. It is a `c_binary` (sealed C17 flags,
the facts targets of every mode) of the adapter plus `gate//ui/model:probe`, so it builds in the same modes as every
`c_binary`; the grade uses release and san. No flag argument.

## Confinement of the `uim_*` symbols (P004 6.3)

No new gate code: the symbols policy already expresses it, and `selftest/ui.sh` pins it.

* **References.** Every `uim_*` name is on the policy's `[global] deny` list. The only module with `deny_exempt` for them
  is `//ui/model:probe` (the gate's main). A product library that calls one gets `denied-symbol`, even when it depends on the
  model adapter (which would otherwise satisfy `undeclared-symbol`). The adapter itself defines them, so it needs no
  exemption; if it spreads the calls over two libraries, the second one needs `deny_exempt`, in the open, in the policy.
* **Definitions.** The adapter lists the `uim_*` names in its `exports`; any other module with an `exports` key that defines
  one gets `unexpected-export`.

Contract wording: the finding the contract calls `symbol-not-allowed` is `denied-symbol` (references) and
`unexpected-export` (definitions); no finding of that name exists in the gate.

Policy lines a product needs (see `selftest/ui.sh` for the working text): the twelve names in `[global] deny`, a module
entry for `//ui/model:model` (`allow = []`, `exports = []`), one for `//ui/model:probe` (`allow` = the stdio and string
functions it calls, `deny_exempt` = the twelve names, `allow_mutable_data = true`, `exports = ["main"]`), and the entries
of the adapter and of the `c_ui_probe` binary.

## Known gaps (for the orchestrator)

* `rigor buckfiles` accepts macros only from `@gate//rules:c.bzl` (`gate/rigor_lib/buckfiles.py`, `LOAD_PATH`, `MACROS`).
  A product BUCK that loads `c_ui_probe` from `@gate//rules:ui.bzl` is refused until that file learns the macro; it is
  outside U03's paths.
* `tools/affected.py` has no `ui` selftest name; `tools/affected.toml` maps the new paths to `third_party` meanwhile.
