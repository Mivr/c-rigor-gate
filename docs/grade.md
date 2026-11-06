# `rigor grade`: the end-to-end grading pipeline (T005)

```
gate/rigor grade --product-repo R --base B --head H --task TASK.toml --product products/<p>/product.toml \
                 [--approvals DIR] [--sign-key KEY] [--uncached] --work DIR --out verdict.json
```
Exit 0 = overall PASS, 1 = FAIL, 2 = internal error (the verdict, if written, is FAIL). `--work` is
emptied (`src`, `tree`, `results`, `test-results`) at the start; `R` must be a local directory.
A stale `verdict.json` and `.sig` are removed first, so a crash can never leave an old PASS.

## The gate list
`gate/rigor_lib/grade_pipeline.py` (`GATES`) is the only place gates are registered, in run order,
and `gate/order.txt` (fixed order for the verdict) must list the same ids in the same order (a unit
test checks). A step is `function(grading) -> GateResult | None`; `None` = did not run (NOT_RUN,
which fails the verdict). An exception inside a step is recorded as that gate's `internal-error`
FAIL, later gates do not run, the verdict is still written, and the exit code is 2.
A gate that fails by findings does not stop the others (except as noted for `build`/`tests-*`).

| Gate | What it does |
|---|---|
| `clone` | `git clone --no-local --no-hardlinks` of R into `<work>/src` with the hardened git environment of `gitrun` (no replace objects, grafts, fsmonitor, hooks, global config); resolves B and H **in the clone** (commit ids or refs the clone has, e.g. `origin/x`); detached checkout of H. Every later git gate reads the clone, never R. |
| `contract`, `suppressions` | the existing gates, in process, against the clone, `--task` and `--approvals`. |
| `assemble` | builds `<work>/tree` from scratch (below). Findings: `bad-path`, `unsupported-entry` (symlink or gitlink that the layout would copy); info `ignored-by-gate` (a product path that matched `include` but is always excluded), info `product-manifest` (sha256 of the copied product files, so the verdict hash commits to them). An error here means no tree: `build` and `tests-*` are NOT_RUN. |
| `buckfiles` | `rigor buckfiles` over a copy of the product files of the tree only (never the gate's own `BUCK` files). |
| `semantic-suppressions`, `symbols` | one Buck2 build (release, `--no-remote-cache` with `--uncached`) of every `kind(c_facts, //...)` target, `gate//ctest:ctest_facts` and `toolchains//:libc_symbols`; then `rigor facts` logic with `products/<p>/policy.toml` (gate-owned, next to `product.toml`; trusted module is `gate//ctest:ctest`, and test targets need their own `[module]` entries). If the facts cannot be built (e.g. the product does not compile) both are NOT_RUN and `build` says why. Metadata has executed/cached action counts. |
| `build` | in the tree: `uquery 'kind(ctest_results, //...)'`, then `build --keep-going --build-report` of all of them in `release` and in `toolchains//:linux_san`. Findings: `build-failed` (target, mode), `missing-output`, `query-failed`, `no-results-targets`. Always ends with `buck2 kill` in the tree. Metadata: executed/cached action counts (from `buck2 log what-ran`, column 3 `cache` = hit), stderr tail. |
| `tests-release`, `tests-san` | the `tests` gate over the results artifacts of that mode, with `products/<p>/expected-tests.json` and, if present, `expected-tests.previous.json` (both next to `product.toml`, gate-owned). NOT_RUN if the build of that mode was not clean. |
| verdict | `rigor verdict` over `gate/order.txt`; with `--sign-key`, `ssh-keygen -Y sign -n c-rigor-gate-verdict` writes `verdict.json.sig`. |

## The grading tree
`<work>/tree/` contains only:
- `gate/`: the gate repository at the commit `rigor` itself runs from (sha in `assemble` metadata),
  read as git blobs. `rigor grade` refuses (exit 2) if tracked files of the gate checkout differ from
  that commit. Its `.buckconfig` and `.buckroot` are not copied (it is a cell, not the root).
- product files, read as git blobs from the clone at H (so no attributes, filters or symlink tricks),
  only if they match `product.toml` `[layout] include` and none of `exclude` and none of
  `product_layout.ALWAYS_EXCLUDED` (`.buckconfig*`, `.buckroot`, `*.bzl`, `tools/**`, `toolchains/**`,
  `prelude/**`, `gate/**`, `.git*`). Always-excluded wins over anything the product says.
- a generated `.buckconfig`: cells `root = .`, `gate = gate`, `toolchains = gate/toolchains`, bundled
  prelude, `[buck2_re_client]` and `[http]` copied from the gate commit's own `.buckconfig`, the
  default platform `toolchains//:linux_release`; and an empty `.buckroot`.

`assemble` metadata has the `manifest`: `[path, sha256]` for every file in the tree (gate files,
generated files and product files).
Buck2 is the gate's pinned wrapper (`tree/gate/tools/buck2` checks the binary's sha256), so the
product's `tools/` is never consulted.

## Verdict determinism
`core` holds only gate id, status, findings count and the findings hash. Anything volatile (shas,
paths, seconds, action counts, stderr) is in `metadata`. Two runs of the same inputs give the same
`core_sha256`, whether the build was cold or fully cached.

## Sealed environment
`rigor grade` replaces its own environment, and gives Buck2, git and ssh-keygen only:
`HOME=<work>/home` (created empty, wiped at the start), `TMPDIR=<work>/tmp`,
`PATH=/usr/local/bin:/usr/bin:/bin`, `LANG=C.UTF-8`. No `BUCK*`, `XDG_*`, `PYTHON*`, `LD_*`, `SSH_*`,
proxy or `GIT_*` variable is inherited. Found by experiment: Buck2 reads `$HOME/.buckconfig.local` and
`$HOME/.buckconfig.d/*` (both applied on top of the project config); it does not read `~/.buckconfig` or
XDG paths. `/etc/buckconfig*` is not present on the grader host and is outside the gate's control.
`selftest/grade.sh` plants hostile config in an inherited HOME plus `BUCK2_*`, `LD_PRELOAD`, proxy and
`SSH_*` variables and requires the same `core_sha256` as the clean run.

## `--uncached`: merge-decisive grades
Test results are RE artifacts, and a cached grade trusts the shared action cache: anyone who can write it
could plant a forged `results.jsonl` for an action digest. `--uncached` passes `--no-remote-cache` to
every build, so no cache is read or written and every action runs on a worker. The verdict core records
`"uncached": true|false` (hashed), so a decisive verdict is distinguishable. **Merge-decisive grades use
`--uncached`** until the RE farm gives the grader a client-read-only action cache. (Buck2 notes the RE
service may still deduplicate identical in-flight actions; the selftest checks that an uncached grade
reports 0 cache hits.)

## Daemons
Every grading tree starts its own Buck2 daemon; the build gate kills it in a `finally`, and `rigor
grade` kills it again if anything escaped (and before reusing a work directory).

## Known limits
- The environment of Buck2 is the orchestrator's (including `HOME` and `BUCK2_BIN`); the binary is
  sha256-pinned, user-level Buck2 config files are not isolated.
- B and H must exist in what `git clone` copies (branches, tags); a ref that exists only in R's
  other namespaces is not found. Pass commit ids on a branch.
- The product's `BUCK` files are still the product's. They can define arbitrary rules in the root
  cell; restricting them to `load("@gate//rules:...")` is the BUCK guard of T004.
- `sign-key` must not need a passphrase.
- Self-test: `selftest/grade.sh` (about 2 minutes, RE farm). Unit tests: `selftest/gate.sh`.

`gate/tools/expected.py add --product P --results DIR...` merges test ids from result files into `products/<P>/expected-tests.json` (sorted, add-only; removal needs a signed `test-removal` approval and a manual edit).
