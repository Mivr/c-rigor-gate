# T125: `msan` and `tsan` build modes (P003 W5 part 1, P001 G12; landed, not wired)

Repo: `Mivr/c-rigor-gate`. Branch `task/T125` from main. Read P003 §7.1, `docs/toolchain.md`, `toolchains/BUCK`
(`RUNTIMES`, the platforms), `rules/c.bzl` (`_COMPILE_BY_MODE`, `_LINK_BY_MODE`, the `_ONLY_*` lists),
`rules/ctest.bzl` (`ctest_results`, `sanitizer_env_lines`), `rules/third_party.bzl` (`_SAN`, `_FUZZ`).

## Why
The verdict builds two modes, `release` and `san` (ASan + UBSan + LSan). Nothing looks for reads of uninitialised
memory or for data races, and business-apps has four threads (`lib/rt/mbox`, `lib/io/osal`, `lkapp/wire`). In C one
more build mode is cheap. This task lands the two modes and proves them on fixtures. Wiring them into `rigor grade`
(`MODES`, the gates `tests-msan` and `tests-tsan`, `mode-divergence`) is the next task; do not do it here.

## Do
1. **Toolchain.** Platforms `toolchains//:linux_msan` and `toolchains//:linux_tsan` next to the existing ones (follow
   the existing names exactly). Add the MemorySanitizer and ThreadSanitizer runtime members of the **pinned LLVM
   19.1.7 archive** to `RUNTIMES`, and to the manifest if the manifest lists them. If a runtime is not in the pinned
   archive, stop on that mode and report it: fetch nothing else.
2. **Flags** (sealed, in `rules/c.bzl`; products pass none):
   - msan: `-O1 -g -fsanitize=memory -fsanitize-memory-track-origins=2 -fno-sanitize-recover=all -fno-omit-frame-pointer`
   - tsan: `-O1 -g -fsanitize=thread -fno-sanitize-recover=all -fno-omit-frame-pointer`
   The same in `rules/third_party.bzl` for gate-owned third-party code, so a test that links mbedTLS is instrumented
   throughout.
3. **Results targets.** In the msan and tsan platforms `<name>_results` runs the test exactly as in `san`: the sealed
   environment, `halt_on_error`, a non-zero exit on any report, the hermetic symbolizer, `file:line function` in the
   failure `reason`. `ctest` forks one process per test: make that work under both sanitizers and say what you had to
   set. Edit `ctest/**` only if there is no other way, and report it.
4. **Which tests.** `c_test` gets a boolean attribute `threads` (default `False`). A tsan results target exists only
   for `threads = True`. An msan results target exists for every `c_test` whose link closure has no system library
   beyond libc and pthread (MSan needs every linked object instrumented); for the others it does not exist. List in
   your report how the macro decides.
5. **Selftest** `selftest/sanmodes.sh` with fixtures under `selftest/sanmodes/`:
   - a read of an uninitialised struct field that decides a branch: the msan results FAIL with a symbolized
     MemorySanitizer report naming the line; the fixed twin passes; the same bug passes in `release` and `san` (state
     this in the output: it is the reason the mode exists);
   - two pthreads writing one variable without a lock, `threads = True`: the tsan results FAIL with a symbolized
     report; the mutex twin passes;
   - a `threads = False` test has no tsan target; a test linking X11 has no msan target;
   - every case twice with identical verdicts; the script ends with `elapsed <S>s` and `ALL CHECKS PASSED (n)`.
6. `docs/toolchain.md` (the two modes, their flags, what they cannot see), `docs/ctest.md` if `ctest` behaviour
   changed, `tools/affected.toml` rules for the new files.

## Not in this task
`gate/rigor_lib/**`, `gate/order.txt`, `products/**`, the hardened release profile, any change to the `release`,
`san`, `cov` or `fuzz` modes.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/toolchain.sh`; `selftest/ctest.sh`; `selftest/third_party.sh`;
`selftest/sanmodes.sh` twice in a row; `python3 -I tools/affected.py --check`. The orchestrator runs the full
`tools/validate.sh` (a change under `rules/**` selects every selftest), so keep the existing modes byte-identical.

## Allowed paths
`toolchains/**`, `rules/c.bzl`, `rules/ctest.bzl`, `rules/third_party.bzl`, `selftest/sanmodes.sh`,
`selftest/sanmodes/**`, `docs/toolchain.md`, `docs/ctest.md`, `tools/affected.toml`; `ctest/**` only as item 3 allows.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T125`. `TMPDIR=/var/tmp/cache/T125/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Commit on `task/T125`; your last message is the report (what works, what does not, every deviation).
