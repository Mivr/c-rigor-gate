# T095: policy-gated system libraries for `c_library` (libpthread for business-apps `osal`)

Repo: `Mivr/c-rigor-gate`. Branch `task/T095`. Read `AGENTS.md`, `rules/c.bzl`, `rules/mutate.bzl`, `toolchains/`
(the pinned sysroot, glibc 2.31), `docs/products.md`, `docs/grade.md`, the policy docs (allows, `deny_exempt`), the
facts and semantic-suppressions code under `gate/rigor_lib/` (a `#pragma comment(lib, ...)` is a `pragma`
finding, correctly), and `docs/canaries.md`.

## Why
business-apps `lib/io/osal` is the only module allowed to call pthread (design S7). With the pinned glibc 2.31
sysroot, `pthread_create`, `pthread_join` and the attr functions live in libpthread, so a product binary or test that
links `osal` fails to link: `rules/c.bzl` gives products no way to name a system library, and a pragma is a
suppression. Products need one narrow, auditable way to link a sysroot library.

## Build
- `c_library(..., system_libs = [...])`: a list of bare sysroot library names (`"pthread"`, nothing else is
  accepted until a product needs it: an allow-list in the rules, `pthread` only). It becomes an exported linker flag
  (`-lpthread` from the sysroot, never a host path) so every binary, test and mutant binary that links the
  library gets it; `c_mutants` must link it too (`rules/mutate.bzl`).
- Policy gate: the facts record `system_libs` per module; a product policy must allow it per module (for example
  `system_libs = ["pthread"]` in that module's policy entry). A module that declares a system lib without the policy
  allow, or a policy allow without the declaration, is an error finding (name the rule, add it to the docs and to
  the canary table with a canary that proves each direction).
- Do not change any product config in this task except a fixture/canary product; business-apps policy gets the
  allow in a later config refresh.
- Docs: `docs/products.md` (how a product declares a system lib), the rule table.

## Allowed paths
`rules/**`, `toolchains/**` (only if the sysroot needs a link-path tweak), `gate/rigor_lib/**`, `gate/tests/**`,
`docs/**`, `canaries/**`, `selftest/**`, fixture products under `products/` used by selftests. Not
`products/business-apps/**` or `products/annas-c/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/toolchain.sh
```
plus a fixture module that starts a real pthread in a c_test linking with `system_libs = ["pthread"]`, passing in
release and san, and its c_mutants run linking.

## Rules
Use `TMPDIR=/var/tmp/cache/T095/tmp`; never write to `/tmp` (the harness scratchpad included). Build only with
`gate/tools/buck2`, never host compilers. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`,
`/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill processes you did
not start; never `buck2 kill` outside your scratch. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared
and the machine is loaded.
