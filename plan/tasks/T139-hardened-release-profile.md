# T139: hardened release profile: measure, then adopt or reject by the stated rule (P003 §6, D5)

Repo: `Mivr/c-rigor-gate`. Branch `task/T139` from main. Read P003 §6 ("Hardened release profile") and D5,
`docs/toolchain.md` (the sealed flags, the modes), `rules/c.bzl` (`_COMPILE_BY_MODE`, `_LINK_BY_MODE`, the sealed
lists), `rules/third_party.bzl`, `docs/perf.md`, `selftest/perf.sh`, `selftest/toolchain.sh`, `selftest/mutate.sh`.

## Why
The shipped binary is the `release` build, and the sanitizers only run in other modes. Flags that the pinned LLVM
19.1.7 already has can make part of that protection permanent in the shipped code: fixed-size array accesses trap
when out of bounds, automatic variables start zeroed, the stack is protected, libc calls are checked against known
object sizes. The codebase this gate grades keeps most of its state in fixed arrays inside static structs, so the
first of these covers a lot. The owner's rule (P003 D5): adopt if the declared perf targets move by under 3% in
instructions; otherwise keep the flags out of `release`.

## Do
1. **The candidate set**, for the `release` mode only (the other modes are untouched):
   `-ftrivial-auto-var-init=zero`, `-fsanitize=bounds -fsanitize-trap=bounds`, `-fstack-protector-strong`,
   `-D_FORTIFY_SOURCE=3`, `-fstrict-flex-arrays=3`. Check that each exists and does what is claimed with the pinned
   compiler and sysroot (a flag the toolchain ignores or rejects is reported and dropped, not worked around). Product
   code only: gate-owned third-party code keeps its own flags unless a flag must match across objects to link; say
   which did.
2. **Measure before changing the sealed profile.** For every `c_perf` target the gate's selftests have, and for a
   small set of fixtures you add that stress what the flags touch (a loop indexing a fixed array inside a struct, a
   function with a large automatic buffer, a `memcpy`-heavy path), report instructions without the flags, with each
   flag alone, and with all of them: the table goes in `docs/toolchain.md`. Use the perf harness and its agreement
   rule (docs/perf.md): compare counts only between records of the same CPU model.
3. **Decide by the rule.** If every declared perf target moves by under 3% with the whole set: adopt the whole set.
   If not: adopt the largest subset that stays under 3% on every target, and name the flags left out with their
   cost. Do not tune the threshold.
4. **Show what it buys** with selftest cases that run the `release` binary: an out-of-bounds index into a fixed array
   inside a struct ends in a trap (today it reads or writes a neighbour); a read of an uninitialised automatic
   variable yields zero; an overflowing `memcpy` into a sized object is stopped. State plainly what the set does
   **not** cover (a pointer plus a separate length is not bounds-checked; heap objects do not exist here; uninitialised
   static data is already zero).
5. **Effects on the rest of the gate.** With the adopted flags: the mutation selftest still passes (a mutant that now
   traps in `release` is a crash kill; report whether any verdict class changes in the selftest modules); the
   `mode-divergence` gate does not start reporting the new flags' effects as product differences; `-Wframe-larger-than`
   still holds with the stack protector; the RAM budget facts change by how much.
6. **Docs.** `docs/toolchain.md`: the adopted flags, the table, what they cover and do not cover, and that
   `-fbounds-safety` (which would check pointer-plus-length pairs) is not complete in upstream Clang yet.

## Not in this task
The `san`, `msan`, `tsan`, `cov` and `fuzz` modes; `products/**`; `gate/rigor_lib/grade*.py`; any change to warnings.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/toolchain.sh`; `selftest/ctest.sh`; `selftest/perf.sh`;
`selftest/mutate.sh`; `selftest/product_checks.sh`; `selftest/third_party.sh`; `selftest/grade.sh`;
`python3 -I tools/affected.py --check`. The orchestrator runs the full `tools/validate.sh` (a change under `rules/**`
selects every selftest, canaries included).

## Allowed paths
`rules/c.bzl`, `rules/third_party.bzl` (only as item 1 allows), `selftest/toolchain.sh`, `selftest/toolchain/**`,
`selftest/perf.sh`, `selftest/perf*/**`, `gate/tests/**` (tests of what you change), `docs/toolchain.md`,
`docs/perf.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T139`. `TMPDIR=/var/tmp/cache/T139/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. If you need a throwaway script, write the whole file with the Write tool or a heredoc so its text is in your
transcript. `rigor grade` and the canary runner refuse a dirty checkout: commit before you run them. Commit on
`task/T139`; your last message is the report (the table, the decision by the rule, what changed, every deviation).
