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
| `contract`, `suppressions` | the existing gates, in process, against the clone, `--task` and `--approvals`. `suppressions` also scans **every file the layout grades at H** (the same file set `assemble` copies; T054, R001 R5) with the same patterns, line by line, so a suppression committed before B (an ungraded ancestor, e.g. under a sanitizer macro) is found. A hit that is in the diff is reported once, as `forbidden-pattern`; any other hit is `forbidden-pattern-in-tree` (error, with path, line, pattern). Approvals use the same scope text and cover both. |
| `assemble` | builds `<work>/tree` from scratch (below). Findings: `bad-path`, `unsupported-entry` (symlink or gitlink that the layout would copy); info `ignored-by-gate` (a product path that matched `include` but is always excluded), info `product-manifest` (sha256 of the copied product files, so the verdict hash commits to them). An error here means no tree: `build` and `tests-*` are NOT_RUN. |
| `buckfiles` | `rigor buckfiles` over a copy of the product files of the tree only (never the gate's own `BUCK` files). |
| `semantic-suppressions`, `symbols` | one Buck2 build (release, `--no-remote-cache` with `--uncached`) of every `kind(c_facts, //...)` target, `gate//ctest:ctest_facts` and `toolchains//:libc_symbols`; then `rigor facts` logic with `products/<p>/policy.toml` (gate-owned, next to `product.toml`; trusted module is `gate//ctest:ctest`, and test targets need their own `[module]` entries). If the facts cannot be built (e.g. the product does not compile) both are NOT_RUN and `build` says why. Metadata has executed/cached action counts. |
| `build` | in the tree: `uquery 'kind(ctest_results, //...)'`, then `build --keep-going --build-report` of all of them in `release` and in `toolchains//:linux_san`. Findings: `build-failed` (target, mode), `missing-output`, `query-failed`, `no-results-targets`. Always ends with `buck2 kill` in the tree. Metadata: executed/cached action counts (from `buck2 log what-ran`, column 3 `cache` = hit), stderr tail. |
| `structure` | recursion and size/complexity limits (T011, B1, B2; `docs/structure.md`) from clang AST facts. `gate/rigor_lib/grade_structure.py` reads the modules with `uquery` over the `c_facts` and `mutsrc` targets (never from the product's words) and appends one `c_structure` call per module that has sources to the BUCK file of the module's package in the tree (a source can only be named from its own package; the original bytes come back when the step ends, and `buckfiles` has already read the product's files). Header-only modules get no target and are no dependency edge. Tests and fuzz targets have facts and are not graded. The policy is written by the gate from the built modules: the `level` of `products/<p>/policy.toml` (L1, L2, L3; the mutation levels L4 and L5 are L3, the strictest structure level) or none (L3, with a note). A module that does not build is `structure-build-failed`, a policy level for a module the tree does not have is `policy-module-without-facts`, no module at all is `no-structure-modules`; a malformed facts file is exit 2. Needs `assemble` and `build` to have passed (a product that does not compile has no facts), otherwise NOT_RUN. Release build, `--no-remote-cache` with `--uncached`, executed/cached counts in the metadata. |
| `mode-divergence` | `rigor facts --modes` (T023, B3; `docs/product-checks.md` "Modes") over the release facts of every `kind(c_facts, //...)` target and the `san` twins `kind(c_san_facts, //...)`, each with its `[calls]` output. A target without a twin (either way) is `missing-san-twin` / `missing-release-twin`, one that does not build is `modes-build-failed`; in both cases no comparison is made. Malformed or one-sided directories are exit 2. Same preconditions, caching and metadata as `structure`. Both gates sit right after `build` and before the tests: they only need a tree that compiles, they are cheap next to `mutants`, and a failing test does not hide them. |
| `tests-release`, `tests-san` | the `tests` gate over the results artifacts of that mode, with `products/<p>/expected-tests.json` and, if present, `expected-tests.previous.json` (both next to `product.toml`, gate-owned). NOT_RUN if the build of that mode was not clean. In role `test-author` (T041) only presence is judged (`tests --presence-only`: `missing-test`, `duplicate-test`, parse problems, `test-removed`, empty lists), not pass/fail or assertions: the head is the stub commit; metadata `statuses_judged: false`. |
| `tests-stub` | role `test-author` only (T041, P002 Q2; below): every new expected id fails on the stubs in both modes. Any other role: PASS with info `not-applicable`. |
| `mutants` | mutation testing of every product module the policy puts at L2 or above (below). NOT_RUN unless `assemble`, `buckfiles`, `build` and both `tests-*` passed. In role `test-author`: PASS with info `not-applicable` (mutating stubs only gives `baseline-red`). |
| `witness-tests`, `mutants-witness` | the witness gates (T039; `docs/witness.md`, P002), below. |
| verdict | `rigor verdict` over `gate/order.txt`, plus `inputs`; with `--sign-key` (and a clean gate), `ssh-keygen -Y sign -n c-rigor-gate-verdict` writes `verdict.json.sig`. |

## The witness gates (`witness-tests`, `mutants-witness`, T039)
`gate/rigor_lib/grade_witness.py`. They judge the tests against the gate-held witness (`--witness DIR`, bound as
`witness_sha256`; format, roles and procedure in `docs/witness.md`) for the modules W, computed from the head's layout
(`uquery`) and the paths changed in `merge_base..head` (`witness_scope.scope`, by the contract's `role`). They come
after `mutants`, so the head's mutants result exists for the identical-tree reuse. A bundle for another product or
with a file outside the policy's `impl` globs is exit 2 (checked in the `contract` step, before any build). In role
`test-author` the witness gates are required: W also holds the modules whose impl paths changed (the stubbed ones),
W = {} is `no-new-tests`, and a module of W without a bundle entry is `witness-missing` at every level.
- `impl = ["core/core.c"]` per module in `products/<p>/policy.toml` (globs; the paths an implementer may write and a
  witness replaces). An L2+ module without it is `impl-missing` (error at L3 and above, info at L2). The symbols and
  semantic-suppression readers accept the key and ignore it.
- **`witness-tests`** needs `assemble` and `buckfiles` PASS (not the head's tests). Info `witness-scope` (role, W, the
  modules with a bundle entry). A module of W without a bundle entry is `witness-missing` (error at L3 and above, info
  at L2); with an error so far nothing is built. Otherwise `<work>/tree-witness` is assembled exactly like the head
  tree (`grade_steps.assemble_tree`) except that the head files matching the impl globs of the judged modules are
  left out and the bundle's files written (info `witness-manifest`: sha256 of its product files), and built in both
  modes with its own daemon (`--no-remote-cache` with `--uncached`; findings `witness-build-failed` with the original
  rule as `kind`; compiler output is not kept). Every expected test is then judged in both modes: `witness-test-not-pass`
  (rename of `test-not-pass`), `no-assertions`, `missing-test`, `unexpected-failing-test`, each with its `mode`.
- **`mutants-witness`** needs `witness-tests` PASS. It plans the head's layout with the head's levels, keeps the modules
  of W with a bundle entry, and runs the same generator, tests and rules as `mutants` on the witness tree
  (`gate-mutants/` in `tree-witness`), judged with the approval kind `witness-equivalent-mutant`. `survived-mutant`
  is `witness-survived-mutant` (L3 and above) and the L2 info `survivor` is `witness-survivor`.
- **Not applicable** (PASS, info `witness-scope`): W = {} or no module of W with a bundle entry. A grade of a pure
  implementation change runs one `uquery`, no action.
- **Identical tree.** If the witness tree's product files are byte-identical to the head's (same manifest sha256) and
  the head built in both modes, `witness-tests` judges the head's results (info `witness-equals-head`, zero actions)
  and `mutants-witness` reuses the head's per-module `mutants` findings and summaries (also zero actions) unless the
  head result used an approval, whose kind is the implementer's.
- **No source text.** Mutant findings and survivor summaries lose `original` and `replacement`; full reports stay in
  `<work>/witness/mutants-reports/`.

## The stub check (`tests-stub`, T041)
`grade_steps.tests_stub_gate`, judged by `gate/rigor_lib/stub_judge.py` (`docs/witness.md`, "The stub judgement"). The
role is the task contract's `role` (`TASK.toml`, bound through `task_sha256`). A test-author head *is* the stub commit,
so the gate reads the head's results of both modes and builds nothing.
- **Inputs.** The new ids are `expected-tests.json` minus `expected-tests.previous.json` (next to `product.toml`; `{"ids": []}`
  for a new product). In role `test-author` the previous list is required: without it the grade is exit 2 in the
  `contract` step, before any build.
- **Findings.** `test-passes-on-stub` (id, mode, status: a new id that did not fail there; a pass in either mode is the
  finding), `missing-test` (id, mode), `no-new-tests` (no new id); info `stub-timeout` (id, mode). Any `fail` counts as
  failing on the stub (check failure, crash, sanitizer, timeout, no checks); metadata `fail_kinds` counts the kinds per
  mode, plus `new_ids` and `role`.
- **NOT_RUN** in role `test-author` unless both modes built clean. In the other roles it is PASS with info
  `not-applicable` whatever the build did. There is no approval kind for a test that passes on the stubs (owner
  decision 3): the stub is the test author's to change (return a sentinel such as `-12345`).
- **The rest of the role.** `tests-release`/`tests-san` judge presence only, head `mutants` is not applicable, and every
  status is judged on the witness tree instead (`witness-tests` runs every expected id), so a stubbed function's old
  tests may fail on the head (the A018 shape). A contract without `role` is `implementer`: a stubbed head graded so
  fails `test-not-pass`.

## Mutation testing in the pipeline (`mutants`, T008)
`gate/rigor_lib/grade_mutants.py`. What is mutated, and against which tests, is decided by the gate alone:
- **Levels.** `products/<p>/policy.toml` (gate-owned) has `level = "L1".."L5"` per module table. Every `c_library`
  and `c_binary` of the product needs one (`level-missing`); a `level` on a test is `level-on-test`. L1: not
  mutated. L2: mutated, survivors are info. L3, L4, L5: zero survivors (and the per-function rules of
  `docs/mutate.md`). A `c_binary` cannot be mutated: above L1 it is `unmutatable-module`. The `symbols` and
  `semantic-suppressions` gates read the same file whole (T055): the symbols gate uses the `level` to arm its
  `exports` check (an L3 module without an `exports` list is `exports-missing`, an error).
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

**Unused approvals (T068).** `core.unused_approvals` is a verdict-level list (hashed with the rest of `core`, so it cannot
be dropped silently; always present, `[]` without `--approvals`). After all gates ran, every *valid* approval (signed,
allowed signer, `repo_sha` an ancestor of the head) whose stem is in no gate's `approvals_used` becomes one finding
`{"rule": "unused-approval", "severity": "info", "kind", "stem", "scope", "reason"}`, sorted by stem. Typical cause: a
body edit changed a mutant id (T058), so an old `equivalent-mutant` approval names nothing. It grants nothing and does
not affect `overall`; it is housekeeping. Approvals that failed validation are reported by their gates
(`forged-approval`) and never appear here. `reason` is `not_used` when every gate in `order.txt` produced a result. If any
gate did not run (NOT_RUN) it is unknown whether that gate would have used the approval, so the report fails closed:
`reason = gate_not_run` for every unused approval (the grade is a FAIL then anyway). If the clone gate did not finish
there is no graded head, validity cannot be judged, and the list is empty.

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
- Self-test: `selftest/grade.sh` (property, witness and test-author steps, see below; RE farm). Unit tests: `selftest/gate.sh`.

`gate/tools/expected.py add --product P --results DIR...` merges test ids from result files into `products/<P>/expected-tests.json` (sorted, add-only; removal needs a signed `test-removal` approval and a manual edit).

## What `selftest/grade.sh` checks, and where its red cases went (T053)
`selftest/grade.sh` keeps the properties of the pipeline that need one product graded several ways: the cold run (a fresh
nonce, so every action executes), the warm run (nothing executes, same `core_sha256`, signature verifies under the
verdict namespace only), the hostile inherited environment (same `core_sha256`), `--uncached` (nothing cached, flag in the
verdict), the internal error (exit 2, FAIL verdict) and all action-count, daemon-leak and verdict-field assertions.
After the cold run, warm, hostile, uncached and internal-error run in parallel, each in its own work subdir with its own
Buck2 daemon, so the wall time is the cold run plus the slowest of them. The witness steps (T039) and the test-author
steps (T041) run in the same parallel wave.

**Test-author steps (T041).** Role `test-author`, a head that adds `core_pos` (1 if the value is positive, else 0) with a
stub and a strong new test `core/pos`, graded against a bundle with the correct `core_pos`, with a scratch copy of
`products/selftest` as the gate-owned inputs (new id added, the old list as `expected-tests.previous.json`, `core_pos`
exported). The new test also checks `core_pos(strcmp("a", "c"))`: -2 from the C library in release, -1 from the ASan
interceptor in san, so a stub that is wrong only at -1 (or -2) passes on the stub in release (or san) only, while the
correct body passes in both.

| Step | Head | Must give |
|---|---|---|
| `ta-green` | sentinel stub (`-12345`) | PASS; `mutants` not-applicable; witness judged, zero witness survivors |
| `ta-release-pass` | stub wrong only at -1 | `tests-stub`: exactly `test-passes-on-stub` (core/pos, release) |
| `ta-san-pass` | stub wrong only at -2 | `tests-stub`: exactly `test-passes-on-stub` (core/pos, san) |
| `ta-timeout` | stub that never returns | PASS, info `stub-timeout` in both modes, `fail_kinds` timeout |
| `ta-no-new` | the `ta-green` head, no new id in the expected list | `tests-stub`: `no-new-tests`; core/pos is info `unexpected-test` (status fail) in `tests-*` |
| `ta-a018` | sentinel stub, and `core_sign` stubbed too | PASS: core/sign fails on the head in both modes (checked in the results), the witness passes it |
| `ta-no-previous` | the `ta-green` head, no `expected-tests.previous.json` | exit 2, `contract` FAIL, `build` NOT_RUN |

**Export narrowing (T069).** `products/selftest/policy.toml` lists exactly what the clean module exports (`core_add`,
`core_sign`, `util_make_ramp`, `util_sum`); the red-case symbols live in the canaries' own policies. The step
`extra-export` (the clean module plus an exported `test_extra` in `core_test.c` that its `exports = ["main"]` does not list, graded with `bundle-base`; a function in `core.c` would also fail `mutants`) must fail `symbols` with
exactly `unexpected-export`, which pins that the list stays narrow. A step that needs an extra symbol grades against a
scratch copy of the product inputs (`ta_inputs`), never against a widened shared policy.

The canaries `stub-passes-test` (the stub is the correct body: `tests-stub: [test-passes-on-stub]` only) and
`stub-green` (control) cover the same gate with exact expectations in the pack (`docs/witness.md`).

Its 24 red cases were duplicated by canaries and ran cold every time. They are now only canaries, with exact expectations
(`docs/canaries.md`); `selftest/grade.sh` prints this table when it starts.

| grade.sh case | canary | notes |
|---|---|---|
| `outside-contract` | `outside-contract` | |
| `nolint` | `nolint` | |
| `buckconfig-hidden` | `buckconfig-hidden` | `contains`: `unused-variable` in `build.json` |
| `buckconfig-plain` | `buckconfig-plain` | |
| `product-buck2` | `product-buck2` | `absent`: the product's `tools/buck2` writes `ran` into the scratch dir; it must not exist |
| `failing-test` | `failing-test` | |
| `removed-test` | `removed-test` | |
| `deleted-target` | `deleted-target` | |
| `heap-overflow` | `heap-overflow` | also lists `no-assertions` (exact set) |
| `kills` | `kills` | |
| `spliced-optnone` | `spliced-optnone` | |
| `raw-rule` | `raw-rule` | |
| `weak-test` | `weak-test` | |
| `hollow-module` | `hollow-module` | |
| `unviable-shape` | `unviable-shape` | |
| `new-module` | `new-module` | |
| `long-function` | `structure-length` | also lists `statement-count` |
| `recursion` | `structure-recursion` | |
| `mode-divergent` | `mode-divergent` | |
| `ungraded-module` | `ungraded-module` (new, T053) | `extra/` as grade.sh had it; `ungraded-path` adds `http/` with a header |
| `excluded-code` | `excluded-code` | |
| `stale-include` | `stale-include` | |
| `third-party-copy` | `third-party-copy` | also `contract`: `outside-allowed` |
| `case-collision` | `case-collision` | |

## Audit grade of annas-c (T059)
An audit grades the whole product at one head with `products/annas-c/tasks/whole-repo.toml` (`allowed = ["**"]`).
The `contract` gate fails `submodule` for any gitlink in the diff, and annas-c's `gate` submodule pointer is bumped
from time to time. So the **base must be the last commit that changed the `gate` pointer** (the pointer is then equal
at base and head, and nothing under `gate` is in the diff): find it with `git log -1 --format=%h -- gate` in the
product repo at the head. It is `596f56b` (gate bump to `67c2230`) for annas-c main `81012ea` and `f990233`. The commit
that added the submodule (`ce5fb09`) is not usable once the pointer has been bumped. The other gates read the whole
tree at the head, whatever the base, and the in-diff gates only see changes after the base: for a first audit that
must also cover earlier changes use the product's root commit and expect the single `submodule` finding on `gate`.
```sh
gate/rigor grade --product-repo annas-c-clone --base $(git -C annas-c-clone log -1 --format=%h -- gate) --head HEAD \
    --task products/annas-c/tasks/whole-repo.toml --product products/annas-c/product.toml --work WORK --out verdict.json
```
