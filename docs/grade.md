# `rigor grade`: the end-to-end grading pipeline (T005)

```
gate/rigor grade --product-repo R --base B --head H --task TASK.toml --product products/<p>/product.toml \
                 [--approvals DIR] [--sign-key KEY] [--uncached] [--allow-dirty-gate] --work DIR --out verdict.json
```
Exit 0 = overall PASS, 1 = FAIL, 2 = internal error (the verdict, if written, is FAIL). `--work` is
emptied (`src`, `tree`, `results`, `test-results`, `facts`, `mutants-reports`) at the start; `R` must be a local directory.
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
| `mutants` | mutation testing of every product module the policy puts at L2 or above (below). NOT_RUN unless `assemble`, `buckfiles`, `build` and both `tests-*` passed. |
| verdict | `rigor verdict` over `gate/order.txt`, plus `inputs`; with `--sign-key` (and a clean gate), `ssh-keygen -Y sign -n c-rigor-gate-verdict` writes `verdict.json.sig`. |

## Mutation testing in the pipeline (`mutants`, T008)
`gate/rigor_lib/grade_mutants.py`. What is mutated, and against which tests, is decided by the gate alone:
- **Levels.** `products/<p>/policy.toml` (gate-owned) has `level = "L1".."L5"` per module table. Every `c_library`
  and `c_binary` of the product needs one (`level-missing`); a `level` on a test is `level-on-test`. L1: not
  mutated. L2: mutated, survivors are info. L3, L4, L5: zero survivors (and the per-function rules of
  `docs/mutate.md`). A `c_binary` cannot be mutated: above L1 it is `unmutatable-module`. The `symbols` gates read
  the same file without the `level` keys (`grade_policy.py` writes that copy; every other key is still checked).
- **Nothing mutated is a failure.** No module at L2 or above is `no-mutated-modules`; a module whose sources
  produce no mutant at all is `no-mutants` (also inside `rigor mutants`); a module without tests is
  `module-without-tests`; a build that does not produce a report is `mutants-build-failed`.
- **Tests.** For a module, every product `c_test` that lists it directly in `deps`, found with `buck2 uquery` in
  the tree (the `test` attribute of the `ctest_results` targets, and the `deps` of libraries and tests). The
  product declares no `c_mutants`. The other libraries the tests link (the closure of their `deps` and the
  module's, without the module, dependents first) are passed as `deps`.
- **The generated package.** After the product was copied, the step writes `gate-mutants/BUCK` (one `c_mutants` call
  per module, target `m<NNN>_<module>`) and a root `PACKAGE` (`package(visibility = ["PUBLIC"], inherit = True)`;
  without it the product's test targets, which are package-private, are invisible to another package). Both are
  gate files: `buckfiles` ran before, the product may not carry a `PACKAGE`, and the step stops with exit 2 if
  either path already exists in the tree. A module that is not `visibility = ["PUBLIC"]` therefore fails to build
  its mutants (`mutants-build-failed`).
- **Build and judge.** `buck2 build` of the `c_mutants` targets in the release platform (`--no-remote-cache` with
  `--uncached`; the daemon is killed at the end), the reports are copied and `rigor mutants` runs in process over
  a policy the gate writes. Findings and the per-module summary (`total`, `verdicts`, `operators`, `survivors`)
  are reported with the product's module labels; metadata also has the executed/cached action counts and the
  sha256 of the generated `BUCK`.
- **Test names.** Inside a report a test is `<package>__<name>` (`rules/mutate.bzl`), so tests with the same name
  in two packages can both run against a module.
- **Unviable ratio (B11).** More than 25 % of a module's generated mutants unviable is `unviable-ratio`: an error
  at L3+, info at L2. Code written so that its mutants fail to compile (for example constants at the limit of
  their type, which trip `-Werror`) would otherwise escape.

## Layout coverage (B14)
`[layout].include` is an allow-list, so on its own a new product directory would be silently ungraded. The
`buckfiles` gate (`grade_checks.layout_findings`, rules in `product_layout.coverage_findings`) therefore reads every
entry of the product head (git tree, not the working directory) and fails closed. *Code* is: a file named `BUCK*`,
`TARGETS*` or `PACKAGE*`; a file with a C or header extension (`.c .h .inc .def`, and the C++, assembler and
linker-script spellings, in any letter case, trailing dots/spaces ignored); and any file a copied `BUCK` names in a
string literal (`srcs`, `headers`, ...) however it is called or wherever it lives (`../docs/x.txt`).

| Rule (all errors) | When |
|---|---|
| `ungraded-path` | code outside `layout.include`; or a submodule (gitlink) that is not the gate's own `gate` |
| `excluded-code` | a `layout.exclude` glob covers code. `exclude` may name non-code paths only (docs, plans, fixtures) |
| `ignored-code` | code inside a path the gate always excludes (`tools/`, `third_party/`, `toolchains/`, `prelude/`, `gate/`, `.git*`; matched in any letter case). A product's own `third_party/` copy would never be built, so it is refused instead of ignored |
| `stale-include` | an include glob that matches no file at the head (an empty module). A glob that itself names only gate-excluded paths (`.buckconfig`, `tools/**`) is inert, not stale |
| `case-collision` | two paths that differ only in letter case or Unicode normalisation |

Symlinks are judged by name like files (a symlink called `x.c` outside the include is `ungraded-path`; an included
one is `unsupported-entry` from `assemble`). `third_party/**` is always excluded (B12): a product's libraries come from
`gate//third_party`, and `rigor grade` now builds the `<label>_symbols` facts of every library in
`third_party/ALLOWED_LABELS` and `ALLOWED_TEST_LABELS` into the facts directory, so `symbols` can check
`third_party = [...]` policy entries. The check runs in `buckfiles` (not `assemble`) because `assemble`'s step lives in
`grade_steps.py`; moving it is a one-line follow-up.

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

## Verdict determinism and bound inputs (T021)
`core` holds the gate statuses (id, status, findings count, findings hash), `uncached`, and `inputs`.
Anything volatile (paths, seconds, action counts, stderr) is in `metadata`. Two runs of the same inputs give
the same `core_sha256`, whether the build was cold or fully cached; changing any single input below changes it.

`core.inputs` (all values are lowercase hex or booleans; `null` only where noted):

| Key | Is |
|---|---|
| `gate_sha`, `gate_clean` | commit of the gate checkout; `false` if tracked files differed (`--allow-dirty-gate`) |
| `head`, `base`, `merge_base` | commits as resolved in the clone by the `clone` gate |
| `product` | `name` from `product.toml` |
| `task_sha256`, `product_toml_sha256`, `policy_sha256`, `expected_tests_sha256` | sha256 of the exact bytes of `--task`, `product.toml`, `policy.toml`, `expected-tests.json` |
| `expected_tests_previous_sha256` | the same for `expected-tests.previous.json`; `null` if the file does not exist |
| `approvals_sha256` | digest of the approvals bundle (sorted name, kind, content hash of every entry); `null` without `--approvals` |
| `allowed_signers_sha256` | `gate/allowed_signers` as read at the start |
| `order_sha256` | the bytes of `gate/order.txt` the verdict was built from |
| `buckconfig_sha256` | the generated `.buckconfig` (from the `assemble` manifest) |
| `toolchain_buck_sha256`, `llvm_sha256`, `sysroot_sha256`, `buck2_sha256` | `toolchains/BUCK`, the LLVM and sysroot archive pins in it, and the Buck2 binary pin (`tools/buck2.version`), all from the assembled tree and checked against the manifest |
| `uncached` | the `--uncached` flag (also kept as `core.uncached`) |

"Read from what the grade used": the task, product, policy, expected-tests files and the approvals directory are
copied once into `<work>/inputs/` at the start and `args` are repointed at the copies, so the hash is of the bytes the
gates read and a later edit of the originals changes nothing. The commits, buckconfig and pins come from the gate
results the grade itself wrote. A missing optional file hashes as `null`; a required input that is `null` in a PASS is
an internal error (exit 2), and in a FAIL it is just `null`.

**Dirty gate.** Tracked files of the gate checkout that differ from `HEAD` make `rigor grade` exit 2. With
`--allow-dirty-gate` it grades, records `gate_clean = false`, never signs the verdict, and `rigor verify` rejects it.

## `rigor verify`: what a merge bot runs
```
gate/rigor verify --verdict verdict.json --allowed-signers SIGNERS \
    --expect-head <40-hex head> --expect-gate <40-hex gate commit> --expect-policy-sha <sha256 of policy.toml> \
    [--require-uncached] [--signature verdict.json.sig]
```
Exit 0 only for a trustworthy PASS; exit 1 prints every reason it was rejected (`REJECTED: ...`); exit 2 is an
internal error (unreadable file, no `ssh-keygen`). It checks, in order: the SSH signature over the exact file bytes
(`ssh-keygen -Y verify`, namespace `c-rigor-gate-verdict`; `SIGNERS` must allow that namespace, the approvals
`gate/allowed_signers` does not), then `core_sha256` recomputed from `core`, `overall == PASS`, every required input
present and well formed, `gate_clean == true`, `core.uncached == inputs.uncached`, and the `--expect-*` values.
`--expect-policy-sha` is the sha256 of the policy file the merge bot trusts (`sha256sum products/<p>/policy.toml`).
Trust is keyed on `core_sha256` only together with these expectations.

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

**Toolchain trees (T030).** `--no-remote-cache` would also re-unpack the 1.6 GB LLVM archive (about two minutes per
daemon). An uncached build instead first takes the tree from the action cache and verifies every byte of it,
uncached on a worker, against the gate-owned `toolchains/*.manifest`; a mismatch fails the build (a `build-failed`
finding with a `TOOLCHAIN VERIFICATION FAILED` stderr tail), never a silent re-fetch. See `docs/toolchain.md`.

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
