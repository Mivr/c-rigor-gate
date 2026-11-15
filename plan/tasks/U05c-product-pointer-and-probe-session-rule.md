# U05c: taps through the product's own pointer entry, and a test rule for probe sessions

Repo `Mivr/c-rigor-gate`, branch `task/U05c`. Read first: `plan/tasks/U00-ui-gate-rules.md`; `docs/ui-model.md` and
`ui/model/model.h` in full; `ui/model/probe_*.c`; `docs/ui-lvprobe.md` ("Calls and the seam", the hit and hit-test
sections, "What the probe changes in the product"); `docs/ui-explore.md` ("Taps"); `rules/ui.bzl`, `rules/c.bzl`
(how `c_test` and `c_embed` are built and what a product BUCK may load), `gate/rigor_lib/buckfiles.py` and
`docs/product-checks.md`; `selftest/ui.sh`, `selftest/ui_frame.sh` and both toy products;
`/home/user/business-apps/docs/lockers/ui-model.md` sections "The frame-facts probe" and what it says about `touch`
(read only), and `/home/user/business-apps/apps/lockers/lkapp/uimodel/tests/probe_session.py` (read only: the
script a product had to write because no rule exists).

## Why
Two gaps found by running the probe against the real kiosk.
1. The probe's `tap` injects at LVGL's pointer indev. A real kiosk handles a pointer event above LVGL first (its
   input hook queues the sample, posts a `touch` event that restarts idle deadlines, tracks the held state), so a
   probe tap is not the production input path: on the real app it enters a digit without the `touch` a real tap
   posts. A tap must enter where a real pointer event enters.
2. A product can check a probe session transcript only with a hand-run script: the gate's rules give a product no
   test that runs the built probe on an input file and compares the output. So the strongest evidence a product has
   about its own UI (frames, taps, hit-tests on the real app) is enforced by nothing.

## Do
### A. The product's pointer entry
1. `ui/model/model.h` gains an OPTIONAL model call, `bool uim_pointer(uim_t *m, int32_t x, int32_t y, bool down)`:
   "deliver one pointer sample exactly as the product's real input source would; the clock does not move; the sample
   is processed by the following `uim_settle`". A product declares whether it provides it through a documented,
   link-time-safe mechanism that needs no weak symbols in product code (for example a required
   `uim_pointer_supported()` returning a constant, with `uim_pointer` required to exist and to return false when
   unsupported). Choose the simplest mechanism that the symbols gate can check; say why.
2. `tap x y`: when the product supports `uim_pointer`, the probe delivers press then release through it, then
   `uim_settle`, then the LVGL settle. What was pressed and what was clicked are OBSERVED from LVGL's own events on
   the pointer indev (pressed / clicked / press lost), not produced by the probe swapping the indev's read
   callback. When the product does not support it, the tap is injected at the indev as today. The reply grammar is
   unchanged; the greeting gains a capability (`pointer`) that says which path taps take, so a catalogue can
   require it. A blocked tap (LVGL would not process it) is still reported as blocked; say how that is detected on
   the new path.
3. `hit-test` is unchanged (LVGL's own search, no events).
4. lvprobe: if observing pressed/clicked from indev events needs a small addition to `ui/lvprobe` (an observe-only
   mode that registers event callbacks on the product's indev and reports what LVGL pressed and clicked for
   samples it did not inject), add it with its own tests, the same rules as the rest of lvprobe (no leftover state,
   callbacks removed at close, liveness by traversal), and document it. Do not change the existing injection path's
   behaviour.
5. Both toys implement the new call. One toy keeps a queue above LVGL (as a real host does) and posts a `touch`
   only from its pointer entry, so the selftest shows: a `tap` through the product entry produces the `touch` and
   the click's work at the tap's instant; the same toy built WITHOUT the entry (the unsupported path) produces the
   click without the `touch` — and the explorer catalogue that requires `pointer` refuses that build.
6. Explorer: the capability `pointer` is known (strict greeting order documented); `requires` accepts it; nothing
   else changes.

### B. A test rule for probe sessions
7. `rules/ui.bzl`: `c_ui_probe_session(name, probe, session, expected)` — a test target a product BUCK may declare
   (extend `gate/rigor_lib/buckfiles.py` with strict argument checks, as for `c_ui_probe`): it runs the probe built
   by a `c_ui_probe` target with `session` (a checked-in command file) on stdin, in the modes the gate grades
   (release and san), and passes only if stdout is byte-identical to `expected`, stderr is empty and the exit
   status is the one the session's last line implies (0 after `quit`). The runner is gate-owned (stdlib Python or
   the gate's existing test runner; a product supplies data files only, never a script). The failure message shows
   the first differing line with its number. It is a hermetic Buck2 test like `c_test` (same result reporting, so
   the gate's test accounting sees it; say exactly how it appears in the test results and what a later
   expected-tests list must contain).
8. Use it in the selftest: both toys' transcripts are checked by `c_ui_probe_session` targets under `buck2 test`,
   in addition to the existing script steps (keep those).
9. Docs: `docs/ui-model.md` (the pointer entry, the capability, the tap paths, the session rule), `docs/ui-lvprobe.md`
   (the observe mode), `docs/product-checks.md` (the new macro).

## Not in this task
Any product; the judges; changing what `hit-test`, `ink`, `crop` or `frame` do.

## Acceptance
`selftest/ui.sh` (all steps) green twice in a row, including: the queue toy's tap through the product entry (the
`touch` and the click's event at the tap's instant in the trace, pressed and clicked nodes named); the same tap on
the build without the entry (no `touch`; capability absent; a catalogue requiring `pointer` is refused with the
house message); a tap blocked on the new path; the F3b overlay canary still `intent-missed` / `tap-misrouted` on the
new path; `c_ui_probe_session` targets pass under `buck2 test` in release and san, and fail (seen once, then
reverted) when one byte of the expected file is changed, when the probe writes to stderr, and when the session
does not end in `quit`; `rigor buckfiles` accepts the macro with exactly its arguments and refuses anything else.
`tools/buck2 test //ui/lvprobe/...` release and san twice if lvprobe changed. `python3 -I -B
gate/tests/run_parallel.py` at the host baseline; `python3 -I tools/affected.py --check`. Each new check seen
failing once against a deliberately broken build (say how). No probe or stub process left; never kill by name.

## Allowed paths
`ui/model/**`, `ui/lvprobe/**` (item 4 only), `rules/ui.bzl`, `gate/rigor_lib/buckfiles.py`,
`gate/rigor_lib/facts_symbols.py` (only if the new model call needs it) and their tests, `gate/rigor_lib/ui_explore*.py`
and tests (item 6 only), `gate/tools/**` or `ui/model/**` for the gate-owned session runner, `selftest/ui.sh`,
`selftest/ui_frame.sh`, `selftest/ui_product/**`, `selftest/ui_frame_product/**`, `docs/ui-model.md`,
`docs/ui-lvprobe.md`, `docs/ui-explore.md`, `docs/product-checks.md`, `tools/affected.toml` (new paths only).
Another task is adding one line to `selftest/ui.sh` (a call to `ui_judges.sh`) and a new directory
`selftest/ui_canary_product/` at the same time: do not touch those.
