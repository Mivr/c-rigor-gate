# T102: `buckfiles` accepts the one package-local source glob form (witness-friendly BUCK files)

Repo: `Mivr/c-rigor-gate`. Branch `task/T102`. Read `AGENTS.md`, `docs/grade.md` (the `buckfiles` row and "The
witness gates"), `docs/witness.md` ("impl paths"), `docs/canaries.md` (`buck-concat`, `per-file-flags`,
`test-peer-in-library`, `cross-cell-dep`), `gate/rigor_lib/buckfiles.py` and its tests.

## Why
The business-apps grade (T101) fails `buckfiles` `bad-argument` (why `value`) on every new library whose BUCK file
says:
```python
c_library(
    name = "fp",
    srcs = glob(["src/*.c"]),
    headers = ["fp.h"] + glob(["src/*.h"]),
    ...
)
```
That form is deliberate. In the witness gates, the head's impl files are removed and the hidden witness's files are
written in their place. The witness was written from the header alone, so it chooses its own file names (for
example `src/dump.c` where the head has `src/scene_dump.c`). An explicit `srcs` list in the BUCK file, which is test
surface and is not replaced, then names files that do not exist, and the witness build fails. A product cannot carry
witness-agnostic BUCK files today.

## Build
Accept exactly these two forms, only as the value of `srcs` or `headers` in `c_library` and `c_binary` (and in
`c_test` only if the existing code already allows lists there; say what you found):
1. `glob(["<pat>", ...])`, a literal list of one or more string patterns, each matching `src/*.c`, `src/*.h` or
   `src/<name>.c` / `.h`: relative to the package, no `..`, no leading `/`, no `**`, and only a `src/` subdirectory with
   a single `*` in the basename. No `exclude=`, and no other keyword or argument.
2. `[<literal strings>] + glob([...])` or `glob([...]) + [<literal strings>]`: exactly one literal list of strings and
   one glob as above, joined by a single `+`. The strings are package-relative paths that the existing rules already
   accept.

Everything else stays `bad-argument`: concatenation of anything else, a glob in `deps`, a glob of `tests/**`,
`glob(...) + glob(...)`, variables, comprehensions, a glob with `exclude`, and patterns outside the rules above. The
existing canaries (`buck-concat` in particular) must stay red with their exact rules. Add canaries `buck-glob-bad`
(several bad forms: `**`, `..`, `exclude`, glob in deps, a test glob) and a control `buck-glob-ok` (the two accepted
forms, PASS). Make sure any part of the gate that reads `srcs` from BUCK text instead of from Buck queries (search
for it) handles the glob, or prove that none does. The structure, mutants and witness steps use `uquery`, so check
that they need nothing. Document the accepted forms in `docs/grade.md` (`buckfiles` row) and `docs/witness.md` (why).

## Acceptance (the orchestrator re-runs it)
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
plus `rigor buckfiles` over a business-apps clone (`git clone /var/tmp/src/business-apps /var/tmp/cache/T102/biz`, no
submodule needed for this one command) showing no `bad-argument` on the glob BUCK files (`lib/fmt/fp`, `lib/io/osal`,
`lib/io/posix_net`, `lib/rt/rtprio`, `lib/rt/rx`, `lib/ui/scene`, `lib/sim/simhost`).

## Rules
Edit only `gate/**`, `docs/**`, `selftest/**`, `canaries/**`. Use `TMPDIR=/var/tmp/cache/T102/tmp`, and never write to
`/tmp`. Build only with `tools/buck2`. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`,
`/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs, and never search from `/`. Do
not print the environment. Kill only processes you started, by the pid `tools/job` recorded. Never `rm` outside your
cache dir. No sleep-poll loops. 2 CPUs and 8 GiB, shared and loaded. No network.
