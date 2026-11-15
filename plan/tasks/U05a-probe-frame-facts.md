# U05a: rendered-tree facts in the probe: the frame seam, taps, the hit query, the `missed` outcome

Repo `Mivr/c-rigor-gate`, branch `task/U05a`. Read first: `plan/tasks/U00-ui-gate-rules.md`; `docs/ui-model.md`,
`ui/model/model.h`, `ui/model/probe*.c`, `ui/model/probe.h` in full; `docs/ui-lvprobe.md` and `ui/lvprobe/lvprobe.h`
in full (sections "Calls and the seam", "Configuration and storage", "Text format", "What the probe changes in the
product", "Limits"); P004 §2.1, §3.3, §3.4, §4.2, §16 (H6); `selftest/ui.sh` and `selftest/ui_product/`.

## Why
The probe binary speaks the model interface but reports nothing about what LVGL actually drew, and it can only send
an input by scene key. The judges need the rendered tree per frame, a way to tap a point through the production
hit-test, a way to ask what a point would hit without changing anything, and an honest outcome when a press did
not produce the intent it was aimed at (the "overlay swallows the tap" class of defect).

## Do
1. **Frame facts.** In `ui/model/probe_frame.c` (split into more files as it grows; no file over 500 lines) the
   `frame` command, after `uim_frame`, runs `lvprobe` on the returned display: life (every frame), settle, walk, and
   emits the encoder's records as framed lines using the streaming entry points (never one buffer for the whole
   tree), followed by the frame checksum and the lifecycle events since the previous frame. Errors follow the
   lvprobe doc: "settle and retry" errors are retried a bounded number of times; fatal ones are `err frame
   model-contract` or `err frame internal` as fits, and poison the session; a per-node `unsupported` is data, not an
   error. The probe owns the lvprobe storage statically; caps are constants in the header with a documented
   per-frame byte budget against the payload limit. lvprobe is closed before a new `open` and before exit, in the
   order its doc requires. The product's own pointer indev is used when the display has one.
2. **Ink on request.** `ink` (all nodes of the current walk that can be inked) and `ink <node>`: the ink records as
   framed lines. Ink is expensive (the measurement report says 96% of the cost) and is never run implicitly.
3. **Hit query.** `hit-test <x> <y>`: the node LVGL's own search would give the press, firing no handler; replies
   the node index, or `none`, or the blocked error as a normal typed reply.
4. **Tap.** `tap <x> <y>`: a press and release at a point through the production pointer path (lvprobe's injection),
   then the model is stepped to stable the way an `apply` is; replies what received the press, what received the
   click, or that the tap was blocked. A tap is an input: it follows the same poisoning rules as `apply`.
5. **`missed`.** `model.h` gains a fourth apply outcome, `UIM_MISSED`: the input was delivered through the production
   path but the product did not produce the intent it was aimed at; the model may have changed. Reply `ok apply
   missed`. It is not an error and does not poison. Update the toy adapter so one toy input can produce it (a toy
   button covered by a transparent clickable overlay: the F3b canary).
6. **Capabilities.** The greeting line announces a space-separated capability list after the protocol name
   (`frame-facts`, `ink`, `hit-test`, `tap`, `apply-missed`), so a driver can refuse a catalogue that needs a
   capability a probe lacks. Document the greeting grammar; keep the protocol name `ui-probe/1`.
7. **Pixels for evidence.** `crop <x> <y> <w> <h>`: RGBA of a region of the current frame as framed lines of
   lowercase hex, bounded by the payload limit (a larger region is `err crop bad-arguments`).
8. `selftest/ui.sh` runs the lvprobe tests (`tools/buck2 test //ui/lvprobe/...`, release and san) as a step, so the
   `ui` selftest covers them. Put this task's other new steps in `selftest/ui_frame.sh`, called from `ui.sh` by one
   line at the end, with its fixtures under `selftest/ui_frame_product/` (another task is editing `ui.sh` and
   `ui_product/` at the same time; touch `ui_product/` only for item 5 and the transcripts that change with it).
9. Update `docs/ui-model.md` (protocol, capabilities, new commands and replies, the `missed` outcome, budgets) and
   add the judge-facing description of every frame record type by reference to `docs/ui-lvprobe.md`.

## Not in this task
The Python driver (U05 is in flight; a later small task teaches it the new replies); judges; anything in a product.

## Acceptance
`selftest/ui.sh` green twice in a row, including: the toy's frame facts match a checked-in transcript in release
and san (node records with exact coords, the label text of the toy's button and notice with Cyrillic text in one of
them, the fit facts, checksum); two identical sessions give byte-identical frame facts; a label made too small is
reported `clipped` and the same label with room is not; `hit-test` at the covered toy button names the overlay and
fires nothing (the trace stays empty); `tap` there gives the overlay as receiver and `apply` of the button's intent
gives `ok apply missed`; with the overlay not clickable the same `apply` is `ok apply` and the tap reaches the
button; `ink` gives ink 0 for a hidden label; a frame that exceeds the documented budget is a typed error, not a
truncation; `crop` round-trips known pixels; every new malformed command form is in the strict-protocol transcript.
`python3 -I -B gate/tests/run_parallel.py` at baseline; `python3 -I tools/affected.py --check`. Each new check seen
failing once against a deliberately broken build (say how).

## Allowed paths
`ui/model/**`, `rules/ui.bzl` (only if the probe library needs the lvprobe dependency declared there),
`selftest/ui.sh` (the lvprobe step and the one line calling `ui_frame.sh`), `selftest/ui_frame.sh`,
`selftest/ui_frame_product/**`, `selftest/ui_product/**` (item 5 and the transcripts it changes only),
`docs/ui-model.md`, `tools/affected.toml` (new paths only), `gate/rigor_lib/facts_symbols.py`,
`gate/rigor_lib/buckfiles.py` and their tests only if the probe library's new dependency on `gate//ui/lvprobe`
requires it (explain). `ui/lvprobe/**` is not yours: if lvprobe lacks something, say so in the report.
