# T117: G7 (P001): Linux X11 system library from the pinned sysroot, and `c_embed(nul = True)`

Repo: `Mivr/c-rigor-gate`. Branch `task/T117` from main. Read `AGENTS.md`, `toolchains/BUCK` (the Chromium sysroot
pin and its member list / `sysroot.manifest`), `rules/c.bzl` (`_SYSTEM_LIBS`, how `c_library`/`c_binary` link system
libraries, around the `pthread` entry), `rules/` for `c_embed` (T112), `docs/grade.md` (c_embed text), the symbols and
policy docs (`docs/*.md`: how a product allows a system library and its symbols), and `selftest/`.

## Why
business-apps P001 plans gate item **G7**: "Linux X11/xcb sysroot members, plus ... the Mozilla CA bundle as ... embed
data". The lockers Linux shell (`apps/lockers/lkapp/shell_linux`, L1) draws the LVGL buffer into an X11 window and reads
X11 key and pointer events; the e2e harness drives it on Xvfb with XTest. Today the sysroot has no X11 headers or libs
and `_SYSTEM_LIBS` allows only `pthread` (business-apps probe P290 found this). Separately, business-apps posixio wants
the CA bundle PEM as a NUL-terminated slice, and `c_embed` adds no terminator.

## Do
1. **X11 members.** Find whether the pinned Chromium sysroot archive (same sha as today) contains libX11 and what it
   needs at link time (libxcb, libXau, libXdmcp, and whatever else `ldd`-style inspection of the archive shows), plus
   the headers (`X11/Xlib.h`, `X11/Xutil.h`, `X11/keysym.h`, `X11/XKBlib.h` if present). Add exactly those members to
   the sysroot member list / manifest (the same mechanism the existing members use; `gen_manifests.sh` or whatever the
   repo uses, run twice gives an empty diff). If the archive lacks them, STOP and report what is missing and the
   smallest alternative (do not fetch another archive in this task).
2. **System library `X11`.** Add `"X11"` to the allowed system libraries so a product target can declare it
   (`system_libs = ["X11"]` or the repo's existing spelling), linking libX11 and its link-time deps, in `linux_release`
   and `linux_san` (and say what happens in the other platforms: refused, or not applicable). It must stay opt-in per
   target: no target gets X11 unless it says so. Document it in the policy docs: the product must still list the X
   symbols it calls in its policy (`allow`), and libX11 allocates internally (product rules S2 apply to product code only;
   say so).
3. **`c_embed(nul = True)`.** An option that appends one NUL byte after the embedded data, so the exposed length
   includes it (or excludes it: pick one, document it, and test both the default and the option). Default unchanged.
4. **Selftests.** A throwaway-free selftest fixture: a `c_library(system_libs = ["X11"])` that calls `XOpenDisplay(NULL)`
   and `XCloseDisplay` behind a function a test calls only to prove it LINKS (the test must not need a display: e.g.
   call `XOpenDisplay` with a display name that cannot exist, `":99999"`, and assert NULL), in both modes. A `c_embed`
   selftest for `nul`. The existing system-lib canaries still pass, plus a canary that a target WITHOUT `system_libs`
   that calls an X symbol fails to link (or is refused by the symbols check; say which).

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
selftest/toolchain.sh
```
plus the new selftests in both modes. Report the members added (with their sizes), the link line for the fixture, the
`c_embed` change, and the outputs.

## Allowed paths
`toolchains/**`, `rules/**`, `selftest/**` (add fixtures; do not weaken existing ones), `gate/tests/**`, `docs/**`,
`tools/affected.toml`. NOT `products/**` (T116 is editing it).

## Rules
Use `TMPDIR=/var/tmp/cache/T117/tmp`; never write `/tmp`. Build only with `tools/buck2` / `gate/tools/buck2` as the docs
say. Redirect every output to a file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never `rm`
(`cp -f`, or `mv` into your cache dir). No stash, merge or push. **Never use the Agent tool.** Never read
`/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs; never
search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid (`pgrep -f '^buck2d\['`
plus `readlink /proc/<pid>/cwd`); never `pgrep -f buck2d`, `buck2 kill` or `pkill`. One buck2 build at a time (8 GiB
shared). No network except Buck2's pinned downloads. No display is available; never start an X server.
