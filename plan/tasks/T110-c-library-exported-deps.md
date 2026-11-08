# T110: `c_library(exported_deps = [...])` so includers of a public header need not repeat its deps

Repo: `Mivr/c-rigor-gate`. Branch `task/T110` from main. Read `AGENTS.md`, `rules/c.bzl` (`c_library`, `_facts`,
`c_catalog`'s note that "`deps` of a library are not exported"), `rules/facts.bzl`, the layering/architecture checks that
read the dependency graph (`gate/rigor_lib/` facts and grade code that use deps; find them), `rigor buckfiles` (the
allowed BUCK statement and keyword set), `docs/product-checks.md`, `docs/rules.md` or wherever `c_library` is documented,
and their tests and selftests.

## Why
In business-apps, `lkrx/fold_status/fold_status.h` now includes `lk/codeset/codeset.h`. Because a `c_library`'s deps
are private, EVERY target that includes `fold_status.h` (notice, visit, boot, shift, view, and all their tests and kits)
must list `lk/codeset` and `lib/ds/sidx` itself, or it fails with "file not found". One header change caused a
build break on a branch that merged main, and three lanes had to edit BUCK files. A public header's includes are part
of its interface: they should travel with it.

## Change
- `c_library` gains `exported_deps = []` (a list of labels). They are passed to the underlying cxx library as exported
  deps (so their headers and link inputs reach every dependent transitively) AND they count as deps of this library for
  every gate check: facts, layering/architecture edges, the reverse-dependency and fan-out counts, and the mutants
  package. A label may not be in both `deps` and `exported_deps` (analysis error with a clear message).
- The layering rule does not change: an exported dep is an edge FROM this library, so it must be allowed for this
  library exactly as a plain dep is. A dependent does NOT gain an allowed edge to the exported library by inheriting its
  headers; if the dependent's own sources include the exported library's header directly, the existing include/dep
  checks must still demand a direct dep (state what the gate does today for a transitively visible header, and keep it).
- `rigor buckfiles` accepts the new keyword (literal list only, like `deps`).
- Docs: `c_library`'s parameters, and a short "when to export" rule: export exactly the libraries whose headers the
  library's PUBLIC headers include; never export for convenience.
- Tests: unit tests for the rule/facts changes; a selftest product fixture with A -> B where `b.h` includes `c.h` and B
  has `exported_deps = [C]`: A builds without listing C, and the facts/layering see the edge B -> C, not A -> C. Red
  cases: a label in both lists; an exported dep the architecture forbids for B; A's own source including `c.h` without
  a direct dep (whatever the gate reports today for that, unchanged).

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/structure.sh        # if it exists and covers deps/layering
selftest/canaries.sh
```
Report the change, the outputs, and every deviation.

## Allowed paths
`rules/*.bzl`, `gate/rigor_lib/**`, `gate/tests/**`, `selftest/**` (add fixtures; do not weaken existing ones), `docs/**`.

## Rules
Use `TMPDIR=/var/tmp/cache/T110/tmp`; never write `/tmp`. Build only with `tools/buck2` / `gate/tools/buck2` as the docs
say. Redirect every output to a file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never `rm`
(`cp -f`). No stash, merge or push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`,
other worktrees or other cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your
own buck2d by pid (`readlink /proc/<pid>/cwd`); never `buck2 kill`. 2 CPUs shared. No network except Buck2's pinned
downloads.
