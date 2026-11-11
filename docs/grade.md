# `rigor grade`: the end-to-end grading pipeline (T005)

```
gate/rigor grade --product-repo R --base B --head H --task TASK.toml --product products/<p>/product.toml \
                 [--approvals DIR] [--sign-key KEY] [--tier merge|nightly] [--uncached] [--allow-dirty-gate] --work DIR --out verdict.json
```
Exit 0 = overall PASS, 1 = FAIL, 2 = internal error (the verdict, if written, is FAIL). `--work` is
emptied (`src`, `tree`, `results`, `test-results`, `facts`, `mutants-reports`, `mutants-perf`) at the start, so re-grading into the same `--work` never reads or collides with a previous run's files; `R` must be a local directory.
A stale `verdict.json` and `.sig` are removed first, so a crash can never leave an old PASS.

## The gate list
`gate/rigor_lib/grade_pipeline.py` (`GATES`) is the only place gates are registered, in run order,
and `gate/order.txt` (fixed order for the verdict) must list the same ids in the same order (a unit
test checks). A step is `function(grading) -> GateResult | None`; `None` = did not run (NOT_RUN,
which fails the verdict). An exception inside a step is recorded as that gate's `internal-error`
FAIL, later gates do not run, the verdict is still written, and the exit code is 2.
A gate that fails by findings does not stop the others (except as noted for `build`/`tests-*`, and for
`toolchain`: every gate that compiles needs it).

| Gate | What it does |
|---|---|
| `clone` | `git clone --no-local --no-hardlinks` of R into `<work>/src` with the hardened git environment of `gitrun` (no replace objects, grafts, fsmonitor, hooks, global config); resolves B and H **in the clone** (commit ids or refs the clone has, e.g. `origin/x`); detached checkout of H. Every later git gate reads the clone, never R. |
| `contract`, `suppressions` | the existing gates, in process, against the clone, `--task` and `--approvals`. `suppressions` also scans **every file the layout grades at H** (the same file set `assemble` copies; T054, R001 R5) with the same patterns, line by line, so a suppression committed before B (an ungraded ancestor, e.g. under a sanitizer macro) is found. A hit that is in the diff is reported once, as `forbidden-pattern`; any other hit is `forbidden-pattern-in-tree` (error, with path, line, pattern). Approvals use the same scope text and cover both. |
| `assemble` | builds `<work>/tree` from scratch (below). Findings: `bad-path`, `unsupported-entry` (symlink or gitlink that the layout would copy); info `ignored-by-gate` (a product path that matched `include` but is always excluded), info `product-manifest` (sha256 of the copied product files, so the verdict hash commits to them). An error here means no tree: `build` and `tests-*` are NOT_RUN. |
| `toolchain` | grader integrity (T073, B33 a; below): is the toolchain the one `toolchains/*.manifest` pins? In an `--uncached` grade it verifies the cached LLVM and sysroot trees once, before anything compiles: PASS with info `toolchain-verified` (`manifests`: path and sha256 of each manifest), or FAIL with error `toolchain-mismatch`. A cached grade: PASS with info `toolchain-not-verified` (`reason: cached grade`). NOT_RUN in an uncached grade without a tree (`assemble` failed). Unless it passed, the gates that compile (`semantic-suppressions`, `symbols`, `build`, `structure`, `mode-divergence`, `fuzz`, `mutants`, `witness-tests`, `mutants-witness`) are NOT_RUN (the log names the reason: `<gate> not run: gate toolchain is FAIL`). |
| `buckfiles` | `rigor buckfiles` over a copy of the product files of the tree only (never the gate's own `BUCK` files). A macro keyword is a string or a list of strings; `c_embed` (T112, below) has keywords of its own too (`src`, `symbol` strings, `max_bytes` one int literal, `nul` one `True`/`False` literal, no `srcs`, `headers` or `deps`); `c_catalog` (T105, below) has keywords of its own (no `srcs` or `headers`, but `deps` as usual) and takes one dict, `po`, of language -> list of strings; its `runtime` is one string checked like a `deps` entry (same-cell label, or `bad-argument` why `dep`; a test or a test-derived target is `test-target`); the only computed value (T102) is a package-local source glob, in `srcs` or `headers` of `c_library`, `c_binary` and `c_test`: (1) `glob(["<pat>", ...])`, or (2) one literal non-empty string list and one such glob joined by a single `+`, in either order (`["fp.h"] + glob(["src/*.h"])`). A pattern is `src/<stem>.c` or `src/<stem>.h` (the headers use `.h`), where the stem is a plain name or has exactly one `*` (`src/*.c`, `src/a.c`); no `..`, no leading `/`, no `**`, no other subdirectory. `glob` takes one list and nothing else (no `exclude`, no keyword). Everything else (a glob in `deps`, `tests/**`, `glob + glob`, a variable, a comprehension, any other `+`) stays `bad-argument` (why `value`). The layout check (below) needs nothing: a glob matches only `.c`/`.h` files, which are code by extension and so already covered, and a pattern is not a named file. |
| `semantic-suppressions`, `symbols` | one Buck2 build (release, `--no-remote-cache` with `--uncached`) of every `kind(c_facts, //...)` target, `gate//ctest:ctest_facts` and `toolchains//:libc_symbols`; then `rigor facts` logic with `products/<p>/policy.toml` (gate-owned, next to `product.toml`; trusted module is `gate//ctest:ctest`, and test targets need their own `[module]` entries). If the facts cannot be built (e.g. the product does not compile) both are NOT_RUN and `build` says why. Metadata has executed/cached action counts. T138: `symbols` also owns the `threads` declaration of every `c_test` (the test facts are its): `threads-undeclared` (error: the test's own objects, or any library in its link closure, reference `pthread_create` or `thrd_create` without `threads = True`, so it has no tsan result; `via` names the modules) and `threads-vacuous` (error: `threads = True` and nothing in the closure references one). A test that links a threading library without starting a thread is treated as threaded on purpose (the facts say what the closure can do, not what a run does); the declaration is read from the `threads` attribute of the test's `ctest_results` target (one `uquery`, only when the product has a test). |
| `layering` | the architecture contract (T087, `docs/layering.md`): the facts of the `symbols` gate against `products/<p>/architecture.toml`. No such file: PASS with info `no-architecture`. Otherwise it runs only after `toolchain` and `assemble` passed. |
| `decoupling` | the decoupling rules under a baseline ratchet ([decoupling.md](decoupling.md); why: [lessons-decoupling.md](lessons-decoupling.md)): the `BUCK` files and `#include` lines of the tree plus the facts of the `symbols` gate (no build of its own), against `products/<p>/decoupling.toml` (module kinds and test packages) and `products/<p>/decoupling-baseline.toml` (the violations still tolerated). No `decoupling.toml`: PASS with info `not-applicable`, nothing read. Otherwise NOT_RUN unless `toolchain`, `assemble` and `buckfiles` passed and the facts built. Errors: `unused-dep`, `missing-export`, `needless-export`, `unit-test-links-component`, `unleveled-test`, `library-in-test-package`, `contract-has-behaviour` (each only for a violation the baseline does not list; `entry` is the baseline key), `stale-baseline` (a listed violation that is gone: the fix lands with a gate whose list dropped it) and `interface-changed` (a frozen header of the merge base lost or changed a declaration at the head; never baselined). Info: `interface-extended`, `decoupling-inputs` (sha256 of the two files, so the verdict commits to them). Metadata: per rule `violations`/`new`/`stale`, tests per level, the frozen modules, the fan-out report. |
| `build` | in the tree: `uquery 'kind(ctest_results, //...)'`, then `build --keep-going --build-report` of all of them in `release` and in `toolchains//:linux_san`. Findings: `build-failed` (target, mode), `missing-output`, `query-failed`, `no-results-targets`. Always ends with `buck2 kill` in the tree. Metadata: executed/cached action counts (from `buck2 log what-ran`, column 3 `cache` = hit), stderr tail. |
| `structure` | recursion and size/complexity limits (T011, B1, B2; `docs/structure.md`) from clang AST facts. `gate/rigor_lib/grade_structure.py` reads the modules with `uquery` over the `c_facts` and `mutsrc` targets (never from the product's words) and appends one `c_structure` call per module that has sources to the BUCK file of the module's package in the tree (a source can only be named from its own package; the original bytes come back when the step ends, and `buckfiles` has already read the product's files). Header-only modules get no target and are no dependency edge. Tests and fuzz targets have facts and are not graded. The policy is written by the gate from the built modules: the `level` of `products/<p>/policy.toml` (L1, L2, L3; the mutation levels L4 and L5 are L3, the strictest structure level) or none (L3, with a note). A module that does not build is `structure-build-failed`, a policy level for a module the tree does not have is `policy-module-without-facts`, no module at all is `no-structure-modules`; a malformed facts file is exit 2. Needs `assemble` and `build` to have passed (a product that does not compile has no facts), otherwise NOT_RUN. Release build, `--no-remote-cache` with `--uncached`, executed/cached counts in the metadata. |
| `mode-divergence` | `rigor facts --modes` (T023, B3; `docs/product-checks.md` "Modes") over the release facts of every `kind(c_facts, //...)` target and the `san`, `msan` and `tsan` twins (`kind(c_san_facts, //...)`, `c_msan_facts`, `c_tsan_facts`; T138), each with its `[calls]` output, release against each mode in turn (`only_in` names the mode). A target without a twin (either way) is `missing-san-twin` / `missing-msan-twin` / `missing-tsan-twin` / `missing-release-twin`, except a target with a sysroot library beyond libc and pthread in its closure, which has no msan twin and is left out of the msan comparison; one that does not build is `modes-build-failed`; in both cases no comparison is made. Malformed or one-sided directories are exit 2. Same preconditions, caching and metadata as `structure`. Both gates sit right after `build` and before the tests: they only need a tree that compiles, they are cheap next to `mutants`, and a failing test does not hide them. |
| `tests-release`, `tests-san` | the `tests` gate over the results artifacts of that mode, with `products/<p>/expected-tests.json` and, if present, `expected-tests.previous.json` (both next to `product.toml`, gate-owned). NOT_RUN if the build of that mode was not clean. In role `test-author` (T041) only presence is judged (`tests --presence-only`: `missing-test`, `duplicate-test`, parse problems, `test-removed`, empty lists), not pass/fail or assertions: the head is the stub commit; metadata `statuses_judged: false`. |
| `tests-msan`, `tests-tsan` | (T138, P003 §7.1; `grade_sanmodes.py`, below) the `tests` rules over the results of the msan and tsan modes. Each builds the results targets its mode has, in one Buck2 build of the head tree (`--no-remote-cache` with `--uncached`), NOT_RUN under the conditions of `tests-san` (no clean release and san results; the release results say which ids each target holds) and, like every gate that compiles, until `toolchain` passed. `tests-msan` expects every expected id except those of a test whose link closure has a sysroot library beyond libc and pthread (no msan results target): info `msan-not-applicable` (`target`, `library`) for each; anything else missing is `missing-test`. `tests-tsan` expects exactly the ids of the tests declared `threads = True`; a product with none passes with info `no-threaded-tests`. Results that the farm could not produce because the sanitizer runtime died at start-up are the one error `sanitizer-startup` (`mode`, `prerequisite`: the RE worker must allow `personality(ADDR_NO_RANDOMIZE)`), never a list of missing tests, and never retried. Other build failures are `build-failed` (`mode`, `target`). In role `test-author` they judge presence only, as `tests-san` does. Both tiers run both gates. |
| `tests-stub` | role `test-author` only (T041, P002 Q2; below): every new expected id fails on the stubs in both modes. Any other role: PASS with info `not-applicable`. |
| `fuzz` | the fuzz runs of every `c_fuzz` target of the product, judged by `rigor fuzz` in process (T129, P003 §7.2; "Fuzz in the pipeline" below, `docs/fuzz.md`). Findings of the judge (`fuzz-crash`, `fuzz-missing`, `fuzz-harness-no-call`, `fuzz-not-run`, `fuzz-short`, `fuzz-regression-missing`) and `fuzz-build-failed` (a target that did not build or lacks an output). A product without a `c_fuzz` target and without a module that must be fuzzed passes with info `no-fuzz-targets`, role `test-author` with `not-applicable`. NOT_RUN unless `assemble`, `buckfiles`, `build` and both `tests-*` passed (and the facts built). |
| `perf` | the cost counts of the perf targets of the policy and of the perf bundle, judged against their complexity classes (T090, `docs/perf.md` "Judging"). Findings `perf-class-exceeded`, `perf-counter-unavailable`, `perf-record-bad`, `perf-build-failed`; a product without perf targets passes with info `no-perf-targets`, role `test-author` with `not-applicable`. NOT_RUN unless `assemble`, `buckfiles`, `build` and both `tests-*` passed. It writes `gate-perf/` into the tree, builds the `<name>_perf` targets in the release platform and removes the package again. |
| `mutants` | mutation testing of every product module the policy puts at L2 or above (below). NOT_RUN unless `assemble`, `buckfiles`, `build` and both `tests-*` passed. In role `test-author`: PASS with info `not-applicable` (mutating stubs only gives `baseline-red`). |
| `witness-tests`, `mutants-witness` | the witness gates (T039; `docs/witness.md`, P002), below. |
| verdict | `rigor verdict` over `gate/order.txt`, plus `inputs`; with `--sign-key` (and a clean gate), `ssh-keygen -Y sign -n c-rigor-gate-verdict` writes `verdict.json.sig`. |

## Fuzz in the pipeline (T129, P003 §7.2, G23)
The `fuzz` gate runs after `tests-stub` and before `perf`. It needs `assemble`, `buckfiles`, `build` and both `tests-*` to have
passed and the facts to exist, otherwise NOT_RUN; it runs only after `toolchain` passed like every gate that compiles
(`grade_fuzz.py`).

1. **Targets.** `uquery 'kind(fuzz_run, //...)'` in the grading tree lists every product `c_fuzz` target (never the product's
   words about them). One `build --target-platforms toolchains//:linux_fuzz --keep-going --build-report` builds the five outputs of
   all of them (`[verdict]`, `[report]`, `[crash]`, `[stats]`, `[replayed]`). A transport failure of Buck2 (the text of
   `grade_build.transport_failure`) that leaves a target unbuilt is retried once, as the mutants build does; nothing else is
   retried. A target that does not build, or builds without one of its outputs, is `fuzz-build-failed` (error, `target`).
2. **Judging.** The outputs are copied into `<work>/fuzz/` in the layout `rigor fuzz` reads (`index.json` and `t<N>.*` per target)
   and judged in process with the policy and the facts of the `symbols` gate and, if present, `fuzz-regressions.json`.
3. **What must be fuzzed** (gate-owned, `products/<p>/policy.toml`): a module with `fuzz = true`, or whose `profile` list
   contains `parser` (T127), needs a `c_fuzz` target that lists it in `deps` (`fuzz-missing` otherwise); `fuzz_runs` is its budget
   (default 200000, at most 2000000). Every reader of the policy accepts `fuzz`, `fuzz_runs` and `profile` (a unit test loads one
   policy with the three keys through each of them).
4. **Regression inputs.** `products/<p>/fuzz-regressions.json` (`{"<target label>": ["<sha256>", ...]}`, optional, next to
   `expected-tests.json`) is snapshotted into `<work>/inputs/product` and bound into the verdict as `inputs.fuzz_regressions_sha256`
   (null without the file), like the other gate-owned inputs.
5. **Cache.** The run is deterministic (fixed seed, a number of runs, never a time), so the action cache answers a repeat grade:
   `executed_actions` is 0 the second time. `--uncached` adds `--no-remote-cache` as for every build. Metadata: `executed_actions`,
   `cached_actions`, `exit_code`, `required_modules` and per target `runs_done`, `corpus_files`, `replayed`, `phase`.
6. **Roles.** `test-author`: PASS with info `not-applicable` (the stubs are not fuzzed), as for `mutants`.

A graded `c_fuzz` may name a `corpus` and a `runs` (T135): `buckfiles` accepts `corpus` (a list of string literals, the form `srcs`
has on a `c_fuzz`; no `glob`) and `runs` (an integer literal) on `c_fuzz` only. The corpus files are product files: the layout
must include them (a copied `BUCK` that names one makes it a named file, so outside `layout.include` it is `ungraded-path`, see
"Layout coverage"), and the replay and the budget run as in `docs/fuzz.md`. The policy's budget still wins: `runs` below it is
`fuzz-short`. An input that once crashed is committed into the corpus and its sha256 into the gate-owned `fuzz-regressions.json`
(beside `policy.toml`, bound into `core.inputs.fuzz_regressions_sha256`); the gate's metadata shows it under `replayed`. The
canaries `fuzz-crash`, `fuzz-missing`, `fuzz-vacuous-harness`, `fuzz-regression-dropped` (the corpus without the input),
`fuzz-regression-crashes` (replay crash) and `fuzz-budget-lowered` and the controls `fuzz-green` and `fuzz-corpus-replayed` are red
or green on this gate only; `selftest/grade.sh` grades a product with a clean target (gate PASS), the same head again (0 fuzz actions)
and the four corpus and budget cases above.
Because the libFuzzer binary of a `c_fuzz` (`<name>__bin`) is a `cxx_binary`, the mutants gate's layout query leaves out the
binaries that a `fuzz_run` target names in its `binary` attribute (otherwise it would ask for a `level`).

## `c_catalog`: translations as a const C catalog (T105, G9)
```
c_catalog(name = "catalog", pots = ["lockers.pot", "kit.pot"], po = {"bg": ["lockers.bg.po", "kit.bg.po"]},
          langs = ["bg", "en"], source_lang = "en", symbol = "lk_catalog", runtime = "//lib/fmt/i18n:i18n",
          deps = ["//lib/base/core:core", "//lib/fmt/fmt:fmt"], names = {"codes unavailable": "CODES_UNAVAILABLE_INLINE"},
          visibility = ["PUBLIC"])
```
`pots`: ordered `.pot` files of the package; `po`: language -> `.po` files, one per pot, same order, for every language of `langs`
but `source_lang` (whose text is the msgid itself); `langs`: ordered codes, the index is the runtime `lang`; `symbol`: the C
identifier of the generated `const i18n_catalog_t`; `runtime`: the i18n library, a `//package:name` label whose header is derived as
`<package>/<name>.h` (there is no separate header attribute); `deps` (optional): the libraries that runtime header includes from, because the
generated header includes it and a library's `deps` are not exported (the business-apps `i18n.h` includes `core` and `fmt`). The macro makes a `c_library` `name` with the header
`<package>/<name>.h` (the symbol, `typedef enum {...} <symbol>_msg_t` of msgids, `<SYMBOL>_<WORDS>` constants and `<SYMBOL>__COUNT`) and
one generated `.c` (buck-out only, never checked in), plus `<name>__gen`, the rule `rules/catalog.bzl` that runs
`gate/rigor_lib/po2c.py` (stdlib only, byte-identical output for identical inputs). The `.pot` and `.po` files are named in the
`BUCK`, so the layout check requires them to be in `layout.include` (`ungraded-path` otherwise).
- **Build errors, each naming file, line and msgid** (first one stops): PO subset only (`msgid`/`msgstr` and continuation lines;
  escapes `\\ \" \n \t`; `msgctxt`, `msgid_plural`, `msgstr[n]`, `#, fuzzy`, other escapes, invalid UTF-8, a header charset other than
  UTF-8, a msgid twice in one file, a `.po` msgid not in its `.pot`); an empty or missing `msgstr` in any non-source language;
  a template that breaks the `i18n.h` grammar (`{0}`..`{9}`, `{{`, `}}`); source placeholder indices that are not exactly `0..n-1`
  (`n_args` = their number); a translation using another set of indices. Count rule: an index the source uses once is used
  exactly once by every translation, an index the source repeats is used at least once. A msgid in two pots is one id if
  all its translations are byte-identical, otherwise an error.
- **Enum names**: `<UPPER symbol>_<WORDS>`; WORDS is the msgid with every run of non-`[A-Za-z0-9]` bytes (of the UTF-8) turned into one
  `_`, upper-cased, outer `_` dropped, cut to 48 characters (outer `_` dropped again after the cut), `N` before a leading digit. Two
  different msgids with one name, or a msgid with no letter or digit, fail the build; there is no suffix or override.
- **`names` (optional): a narrow enum-name override.** `{msgid: WORDS}`, a literal dict of strings in the `BUCK` (anything else is
  `bad-argument`). It exists for msgids that differ only in case or punctuation (`Codes unavailable` / `codes unavailable`), where renaming a
  msgid would split the C catalog from the Rust translation files that Bulgarian proofreading shares. `{"codes unavailable":
  "CODES_UNAVAILABLE_INLINE"}` gives `LK_CATALOG_CODES_UNAVAILABLE_INLINE`. Build errors: `names: unknown msgid` (not a msgid of the merged pots);
  a value that is not `[A-Z0-9_]+`, starts with a digit or is over 48 characters; `names: entry not needed` (the msgid's derived name
  is shared with no other msgid, so the table cannot become a free-form rename list); an override that collides with another
  name or with `<SYMBOL>__COUNT`. Either side of a collision may be overridden, or both.
- **Why `deps`.** The generated header includes the runtime header, and a library's `deps` are not exported to its dependents' compiles,
  so what that header itself includes (the business-apps `i18n.h` includes `lib/base/core/buf.h`, `str.h` and `lib/fmt/fmt/fmt.h`) must
  be named again here: `deps = ["//lib/base/core:core", "//lib/fmt/fmt:fmt"]`. Without it the catalog does not compile
  (`'lib/base/core/buf.h' file not found`).
- **C text**: strings are literals with every byte outside printable ASCII, and `"` `\` `?` (trigraphs), as a 3-digit octal escape;
  `str` is `n_msgs * n_langs` row-major, `n_args` a `static const uint8_t` array, nothing mutable, `_Static_assert` on the counts.
- **How the other gate steps see it.** The `.c` is a generated source, so `c_facts` gets it in a new `generated` attribute (counted
  against the compiled units, scanned and symbol-checked like any source: `cv_catalog` is a defined, exported, read-only symbol;
  `rules/facts.bzl`). `rigor structure` reads the `srcs` attribute only: the catalog has none, so like a header-only module it gets
  no `c_structure` target and no dependency edge (generated tables have no function to limit; a file-length limit would be
  meaningless on them). `mutsrc` is empty, so a catalog needs `level = "L1"` in the policy (`exports = ["<symbol>"]`); at L2 or above it is
  `no-mutants`. No test is needed at L1. A package that uses the catalog lists the runtime in its own `deps`
  (`deps` is not exported, as for `c_library`). Canaries: `docs/canaries.md`, "T105".

## `c_embed`: a binary file as a const C byte array (T112)
```
c_embed(name = "font", src = "NotoSans-Regular.ttf", symbol = "ui_font_ttf", max_bytes = 524288, visibility = ["PUBLIC"])
```
`src`: one checked-in file of the package (a plain relative path: no label, glob, `..`, or absolute path); `symbol`: a C identifier
(`[A-Za-z][A-Za-z0-9_]*`, at most 63 characters, not a C keyword or `bool`/`true`/`false`/`NULL`); `max_bytes` (optional, default 1048576):
an int from 1 to 16777216 (16 MiB); `nul` (optional, default `False`, a `True`/`False` literal): see below. The macro makes a `c_library` `name`, usable in `deps` of `c_library`, `c_test` and `c_binary`
like any library, with the public header `<package>/<name>.h` (`#include "<package>/<name>.h"`, e.g. `"ui/fonts/font.h"`), which declares
```
extern const unsigned char ui_font_ttf[];
extern const size_t ui_font_ttf_len;
```
and one generated `.c` that defines both as `const` objects (read-only data). `ui_font_ttf` holds exactly the bytes of the file, no terminator;
`ui_font_ttf_len` is the file size. **`nul = True` (T117)** appends one 0x00 byte after the data inside the same array: `ui_font_ttf` then has
`ui_font_ttf_len + 1` bytes and `ui_font_ttf[ui_font_ttf_len] == 0`, so it is a C string (a PEM bundle, for example). The length constant still
EXCLUDES the terminator (the file size; `max_bytes` applies to the file, not to the extra byte); the header is the same either way. The default is unchanged. Both are generated at build time by `<name>__gen`, the rule `rules/embed.bzl`, which runs
`gate/rigor_lib/bin2c.py` (`python3 -I -B`, stdlib only, no network; the output is a pure function of the file). Nothing generated is
checked in. `rigor buckfiles` accepts `c_embed` with literal arguments only (`src` and `symbol` strings, `max_bytes` an int literal, `nul` a `True`/`False` literal, `name`,
`visibility`; no `srcs`, `headers`, `deps` or flags).
- **Refusals (named in the message):** `symbol` not a C identifier or a keyword, `src` not one plain file, `max_bytes` out of 1..16 MiB
  (analysis errors of the BUCK file); a missing file or a directory (analysis); an empty file, a file over `max_bytes`, a non-regular file
  (the `bin2c` action, `bin2c: error: ...`).
- **How the other gate steps see it.** Exactly as a `c_catalog` (above): the generated `.c` is compiled with the sealed warnings and, per mode,
  the sanitizers, and `c_facts` scans it through the `generated` attribute (one const object pair, no function). The shape checks that are about
  hand-written code (lines per file, line length, function limits) do not apply, because `rigor structure` reads the `srcs` attribute only and a
  `c_embed` has none, so it has no `c_structure` target (a 400 KB array is no hand-written code). Facts, sanitizers and warnings do apply.
  A `c_embed` is a leaf library of its package for architecture and layering (no `deps`; its facts list none). `mutsrc` is empty, so its policy
  entry needs `level = "L1"` (`exports = ["<symbol>", "<symbol>_len"]` at L3 and above lists both); at L2 or above it is `no-mutants`.
- **Platforms:** built and tested in `linux_release` and `linux_san` (`selftest/embed.sh`, `selftest/product_checks.sh`); the other modes use
  the same `c_library` build and were not run.
- **Licensing.** An embedded asset (a font, an image) needs its license file next to it in the package (for an OFL font, `OFL.txt` beside
  the `.ttf`). The gate does not check the license text; the file is named nowhere, so it is the reviewer's check.
- **Use with LVGL.** `lv_tiny_ttf_create_data(ui_font_ttf, ui_font_ttf_len, size)`: file support is off in the gate's `lv_conf`, fonts come from memory.

## The perf bundle (`--perf DIR`, B13)
`rigor grade --perf DIR` snapshots a hidden perf bundle (`docs/perf.md`, "The perf bundle") into `<work>/inputs/perf`
before any gate runs, loads and checks it once (format, the product name, every target's module in the policy at
level L3 or above; any defect or a bundle for another product is exit 2 before `clone`) and binds its digest as
`core.inputs.perf_sha256` (`null` without `--perf`). Only the snapshot is read. No gate judges it yet: the grade runs
exactly the gates it runs without the flag. `rigor verify --expect-perf-sha SHA` accepts only that bundle; `none`
accepts only a grade without `--perf`.

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
- **Identical module** (owner decision 2026-11-11). Otherwise `mutants-witness` leaves out every module of W whose
  witness is the head's code **and** that the head's `mutants` gate judged in this grade: info
  `witness-module-equals-head` (module, level, `judged_by = "mutants"`) per module and metadata `equal_to_head` (the
  list); it is neither mutated nor judged a second time and needs no `witness-equivalent-mutant` approval for a mutant
  the head gate already judged with `equivalent-mutant`. "The head's code" (`grade_witness.modules_equal_to_head`): the
  files under the module's impl paths are the same paths with the same sha256 in the head tree and in the witness tree,
  nothing missing and nothing extra. "Judged in this grade": the head `mutants` gate ran and its result has a summary
  for the module. So the skip never leaves a module unjudged: in role `test-author` head `mutants` is not applicable
  and **nothing is skipped** (a test author who weakens the tests of a module he did not touch is still caught by the
  copy's survivors: canary `witness-copy-weak-tests`); a module whose head mutants did not build is not skipped
  either. `witness-tests` and `witness-missing` are unchanged: the whole witness tree is built and every expected test
  must pass on it, and every module of W needs its bundle entry. The modules that differ are judged as before.
  A module that is the head's code and is **not** skipped is mutated and judged here, and its survivors may be covered
  by an `equivalent-mutant` approval as well as a `witness-equivalent-mutant` one (metadata `head_approvals_accepted`,
  `approvals_used_by_kind`; `mutants_gate.run(..., extra_kinds)`): the mutant id is bound to the function body, so for
  identical code it is the mutant the head approval names. Why that is sound, and why a survivor of weakened tests
  still fails: `docs/witness.md`, "A module whose witness is the head's code".
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

## Grade tiers: `--tier merge|nightly` (T137, P003 §9, D2)
`rigor grade --tier merge|nightly`, default `nightly`. **`nightly` is the whole grade, exactly what `rigor grade` was
before tiers.** `merge` is the grade a merge bot can afford: it differs in one place today, the mutation of the modules
whose mutation can only report (below). The tier is bound into the verdict (`inputs.tier`, in the hashed `core`), so a
merge PASS and a nightly PASS of the same inputs have different `core_sha256` and cannot be confused; `rigor verify`
prints the tier and `--require-tier TIER` refuses a verdict of the other one.

| gate | `nightly` | `merge` |
|---|---|---|
| every gate but the two below | runs | runs, unchanged |
| `tests-msan`, `tests-tsan` (T138) | run | run, unchanged (both tiers run both gates) |
| `mutants` | every module at L2 or above is built, run and judged | the modules that can only report are **deferred** (not built, not run); the others as in `nightly` |
| `mutants-witness` | every module of the witness scope | the same deferral rule |

**No other gate changes with the tier.** Later tasks add a row to this table for what they move; they do not invent a
second mechanism (the tier is one string, `grade_tier.tier_of`, read from `args.tier`).

**The deferral rule** (`gate/rigor_lib/grade_tier.py`). A module is deferred at tier `merge` when no finding of its
mutation can be an error:
- a module whose policy table declares no `profile`: level L2 (a surviving mutant is an info finding there). L3, L4 and L5
  are mutated, judged as today;
- a module that declares `profile` is judged by the technique matrix (`profiles.required`, P003 §4.1): it is deferred
  unless `mutation_zero_survivors` is a `gate` for its profiles at its level (`pure` and `parser` gate from L3, `safety`
  at every level; `adapter` and `concurrent` only report; `wiring` and `ui` have no mutation cell; with several
  profiles one gating profile is enough). A profiled `adapter` at L3 is therefore deferred at merge even though a module
  without a profile at L3 is not. An unknown profile or level is never deferred (the `policy-check` gate reports it).

Each deferred module is an info finding `mutation-deferred` (`module`, `level`, `reason`) of the gate; the gate metadata
has `tier` and `deferred` (the count). The metadata of a nightly grade has neither, and its findings are what they were.
If every module is deferred the gate passes with the infos; `no-mutated-modules` still means the product has no module at
L2 or above at all, in either tier. Findings that come from the plan, before a module is deferred (`level-missing`,
`module-without-tests`, `unresolved-link-dep`, `unmutatable-module`, ...), are raised in both tiers.

**What a deferred module can no longer raise at merge** (the nightly tier still raises all of them): `no-mutants` (an
error at every level: a source with functions but no mutants), `all-unviable`, `mutants-build-failed` and
`perf-build-failed` for it (nothing is built), the missing or malformed run reports of its mutants, and, for a profiled
module at L3 or above whose profile only reports mutation, `survived-mutant`, `unviable-ratio`, `unmutated-function` and
the other level-dependent errors (`rigor mutants` still judges every level L3 and above strictly, and the nightly grade
does so as before). At L2 `unviable-ratio`, `unmutated-function` and survivors were info findings already; what is lost
there is the report itself. A merge PASS is thus no evidence about these, which is why `rigor verify --require-tier
nightly` exists for a bot that needs the whole grade.

## Mutation testing in the pipeline (`mutants`, T008)
`gate/rigor_lib/grade_mutants.py`. What is mutated, and against which tests, is decided by the gate alone:
- **Levels.** `products/<p>/policy.toml` (gate-owned) has `level = "L1".."L5"` per module table. Every `c_library`
  and `c_binary` of the product needs one (`level-missing`); a `level` on a test is `level-on-test`. L1: not
  mutated. L2: mutated, survivors are info. L3, L4, L5: zero survivors (and the per-function rules of
  `docs/mutate.md`). A `c_binary` cannot be mutated: above L1 it is `unmutatable-module`. The `symbols` and
  `semantic-suppressions` gates read the same file whole (T055): the symbols gate uses the `level` to arm its
  `exports` check (an L3 module without an `exports` list is `exports-missing`, an error).
- **Nothing mutated is a failure.** No module at L2 or above is `no-mutated-modules`; a module whose sources
  produce no mutant at all is `no-mutants` (also inside `rigor mutants`); a module that no test of its own package
  lists directly is `module-without-tests` (an error at every mutated level, L2 included; it is not mutated, so it can
  never pass by having nothing judged; the field `foreign_tests` counts the tests of other packages that list it, which
  do not count: see "Tests"); a build that does not produce a report is `mutants-build-failed`.
  Perf kills (T090): a module with perf targets in the policy gets `c_mutants(..., perf = [...])` (the targets' binaries'
  libraries are linked in too, `gate//ctest:perf` never), its `[perf]` output is copied to `<work>/mutants-perf/` and judged with
  the reports; `killed-perf` is a separate verdict that counts as killed (`docs/mutate.md`, "Perf kills"). A perf target the
  layout does not know is `perf-target-unknown`; `perf-build-failed` if the evidence did not build.
- **Tests: the module's own package only** (owner decision 2026-11-11). For a module, the product `c_test`s **of the
  module's own package** (same cell, same package: `//lib/fmt/jw:jw` and `//lib/fmt/jw:jw_test`, not a parent, child
  or sibling package) that list it directly in `deps` (`grade_mutants.own_tests`; `rules/mutate.bzl` `_own_package` is
  the same notion), found with `buck2 uquery` in the tree (the `test` attribute of the `ctest_results` targets, and the
  `deps` of libraries and tests). The product declares no `c_mutants`. The other libraries those tests link (the
  closure of their `deps` and the module's, without the module, dependents first) are passed as `deps`. See "Link
  dependencies of the mutants (T070)". A test of another package never runs against the module's mutants and cannot
  kill one, however directly it lists the module: a mutant that only such a test would kill is a survivor
  (`survived-mutant` at L3 and above), and a module with no own-package test that lists it is `module-without-tests`.
  The tests of a package the product declares an integration or simulation package (`decoupling.toml` `[tests]`,
  [decoupling.md](decoupling.md)) are never a module's own tests, even if a library sits in that package.
  Why: a module's `mutant_run` actions are keyed on every archive its tests link. When every test that lists a module
  counted, a composition test made each module's mutants depend on nearly every other module, and a one-line edit
  anywhere re-ran them all (business-apps: 92 % of the module/test pairs were another package's, about 21,000 mutant
  actions and 71 minutes for one edit, and 3 % of the live mutants were killed only by such a test). Now an edit in
  module A re-runs the mutants of module B only if a test in B's own package links A. The same selection serves
  `mutants-witness` and `tools/mutants` (they call `grade_mutants.plan`). The witness scope W follows the same rule: a
  module's test surface is its own package plus the kits its own-package tests link (`docs/witness.md`, "impl paths,
  test surface and W").
- **The generated package.** After the product was copied, the step writes `gate-mutants/BUCK` (one `c_mutants` call
  per module, target `m_<module>_<sha8 of the label>`, never a position: T121) and a root `PACKAGE` (`package(visibility = ["PUBLIC"], inherit = True)`;
  without it the product's test targets, which are package-private, are invisible to another package). Both are
  gate files: `buckfiles` ran before, the product may not carry a `PACKAGE`, and the step stops with exit 2 if
  either path already exists in the tree. A module that is not `visibility = ["PUBLIC"]` therefore fails to build
  its mutants (`mutants-build-failed`).
- **Build and judge.** `buck2 build` of the `c_mutants` targets in the release platform, in **chunks** of
  `MUTANTS_CHUNK` (12) modules, `MUTANTS_INFLIGHT` (3) chunk builds at a time in the one daemon (T121; they ran one after
  the other and the RE farm idled while each chunk waited for its slowest module; `--uncached` keeps them one at a
  time, because the toolchain re-priming around an uncached build reads "the last command"). Memory: 3 x 12 modules is
  about 12k actions in the daemon at once, a third of the 42k-action single build that died and three times one chunk;
  `MUTANTS_INFLIGHT` is the knob to lower. Each chunk counts its own actions from its own `--event-log`, and the
  outcome is assembled in chunk order, so it never depends on who finishes first. One build per chunk with its own `build-report-mutants-<NNN>.json` and the chunk's
  `[perf]` outputs (T115; one build of about 112 modules died of an h2 `BrokenPipe` and failed every pending target).
  The daemon stays up between chunks (its cache is warm) and is killed at the end. A chunk whose build exits non-zero,
  leaves a target without SUCCESS and whose stderr matches `grade_build.transport_failure` (`h2 protocol error`,
  `broken pipe`, `connection reset`, ...) is retried once; a real compile or test failure is never retried. A chunk
  that still fails gives `mutants-build-failed` for its missing modules only. Report names keep the global module
  index; metadata sums the action counts over every attempt, `exit_code` is the first non-zero chunk exit, and
  `chunks`, `retried` (chunk indexes) and `stderr_tail` (last failing chunk) are added. `--no-remote-cache` with
  `--uncached`.
  **Stop at the first kill (T121).** A mutant's tests run in a fixed order (the tests of the module's own package, then the
  others, each sorted by label; a grade hands a module its own package's tests only, the others exist for a `c_mutants`
  target written by hand) and its runs stop at the first test that fails a check; the rest are recorded as skipped
  (`killed_by`), never as passes (`rigor mutants`: `bad-skip` unless an earlier run of that mutant fails a check). A crash
  does not stop the runs: the verdict is killed-assert if any test fails a check, so every verdict stays what it was. See
  `docs/mutate.md`.
  **Reuse (T121).** Each `mutant_run` is a Buck2 action: for a module whose sources, tests, link deps, operator set,
  toolchain and gate rules are unchanged its key is the same in every grade, so the RE action cache answers and a repeat
  grade executes none. The key holds no work dir, time or nonce; the one per-grade thing that was in it, the target
  name's position (`m<NNN>_`, part of every output path), is gone. The verdict is read from the cached action output; no
  verdict is stored anywhere else. A module whose link deps changed re-runs (tests link every library the module's
  own-package tests link, and nothing else: a library that only another package's test links is no input).
  `selftest/mutants_cache.sh` (a step of `selftest/grade.sh`) proves it, step (d) for the last point. The reports are copied and `rigor mutants` runs in process over
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
| `tier` | `merge` or `nightly` (`--tier`, T137); a verdict of one tier never has the `core_sha256` of the other |

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

**Signers and order from the snapshot (T071).** `gate/allowed_signers` and `gate/order.txt` are copied to
`<work>/inputs/allowed_signers` and `<work>/inputs/order.txt` with the other inputs, before any gate runs, and hashed
from the copies (`allowed_signers_sha256`, `order_sha256`; the keys and their meaning are unchanged). `args.allowed_signers`
and `args.order_file` point at the copies: every step that loads approvals (suppressions, tests, mutants, witness),
the unused-approval report and the verdict's gate order read only those. A file that cannot be copied is an internal
error (exit 2) before `clone`. `verdict.metadata.order_file` is now the snapshot path. Standalone `rigor approvals`,
`tests`, `mutants`, `suppressions` and `verify` still read `gate/allowed_signers` (or `--allowed-signers`) directly.

**Dirty gate.** Tracked files of the gate checkout that differ from `HEAD` make `rigor grade` exit 2. With
`--allow-dirty-gate` it grades, records `gate_clean = false`, never signs the verdict, and `rigor verify` rejects it.

## `rigor verify`: what a merge bot runs
```
gate/rigor verify --verdict verdict.json --allowed-signers SIGNERS \
    --expect-head <40-hex head> --expect-gate <40-hex gate commit> --expect-policy-sha <sha256 of policy.toml> \
    [--require-uncached] [--require-tier merge|nightly] [--signature verdict.json.sig]
```
Exit 0 only for a trustworthy PASS; exit 1 prints every reason it was rejected (`REJECTED: ...`); exit 2 is an
internal error (unreadable file, no `ssh-keygen`). It checks, in order: the SSH signature over the exact file bytes
(`ssh-keygen -Y verify`, namespace `c-rigor-gate-verdict`; `SIGNERS` must allow that namespace, the approvals
`gate/allowed_signers` does not), then `core_sha256` recomputed from `core`, `overall == PASS`, every required input
present and well formed, `gate_clean == true`, `core.uncached == inputs.uncached`, and the `--expect-*` values.
`--require-tier TIER` rejects a verdict graded at another tier (`tier is merge, expected nightly`); the tier of the verdict is
printed on every run (`rigor verify: tier merge`), also when it is rejected.
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

**Toolchain trees (T030, T073).** `--no-remote-cache` would also re-unpack the 1.6 GB LLVM archive (about two minutes per
daemon). An uncached grade instead takes the tree from the action cache and verifies every byte of it, uncached on a
worker, against the gate-owned `toolchains/*.manifest`, never a silent re-fetch. See `docs/toolchain.md`.
- **The `toolchain` gate** does that once, right after `assemble`, in the head tree's daemon (which the facts gates and
  `build` then reuse without re-executing anything). A mismatch is the gate's FAIL `toolchain-mismatch`:
  `manifest` (`toolchains/llvm.manifest` or `toolchains/sysroot.manifest`, `null` if the failing step is not the
  verify action), `first_difference` (the first `missing`/`extra`/`changed` path the verifier printed, or `null`),
  `step` (`fetch`, `verify`, `what-ran`, `verify-served-from-cache`), `exit_code` (of that buck2 command) and
  `verifier_exit_code` (of the verify action, as buck2 reports it, or `null`); metadata `stderr_tail`. The gates
  that compile are then NOT_RUN, so a grader-integrity failure is never reported as the product's `build-failed`.
- **Later daemons.** `build` and `structure`, `mode-divergence`, `mutants` and the witness tree each end by killing
  their daemon, so a later gate's uncached `buck2 build` starts a fresh one. `grade_build.run_buck` re-primes it with
  the same two commands (cached fetch, uncached verify) before the build: the verify action executes once per daemon,
  as before T073, and the alternative (no priming) would re-unpack the archive per daemon. "Once per grade" in
  the T073 spec means this (orchestrator ruling): the gate verifies once, and a daemon verifies at most once. If that re-check fails
  after `toolchain` passed, the toolchain changed during the grade: an internal error (exit 2, the step's
  `internal-error` FAIL), never a product finding.
- **Canaries.** No product can make `toolchain` fail, so no canary expects it to: `canaries/runner.py`
  `GRADER_INTEGRITY_GATES` exempts it from the coverage pre-check. The proof that it fails is the last step of
  `selftest/grade.sh` (a scratch gate copy with one `llvm.manifest` sha256 flipped, graded `--uncached`).
- **Exit code: 1.** A `toolchain` FAIL is a failed gate like any other: overall FAIL, exit 1. It is a
  grader-integrity failure, not a product failure, and the verdict says so where it is hashed (`core` has gate
  `toolchain` FAIL, finding `toolchain-mismatch`, every compiling gate NOT_RUN). Exit 2 stays what it is: the grader
  stopped (an exception) and later gates have no result. Here the grade ran to the end fail-closed with a
  well-defined result, so a consumer tells the two failures apart by the verdict, not by the exit code. (On the
  client-writable action cache of B4 the planted tree may come from the graded party itself; it is a recorded FAIL
  of that grade either way.)

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

## Link dependencies of the mutants (T070)
The generated `c_mutants(deps = ...)` of a module lists every library its tests link in a normal build, in a static
link order (a library before the ones it depends on), without the module itself (its mutant objects replace it):
- **Every cell.** The closure follows `deps` and `exported_deps` through the product's libraries and through the
  libraries of other cells (`gate//third_party/mbedtls:mbedtls`, `gate//ctest:ctest`, ...). The other-cell libraries
  are found by `uquery` of the labels the product's targets name, round by round, until nothing new appears
  (`deps(//...)` is no use: it also follows the toolchain's hidden deps). Nothing is named by hand, and nothing is
  linked that the tests do not reach. A library named twice (`ctest` is a dep of every `c_test` and of `c_mutants`
  itself) is linked once.
- **Fail closed.** A label the closure reaches that is no library (`cxx_library`, `prebuilt_cxx_library`) of the layout
  is the error `unresolved-link-dep` (fields `module`, `dep`); the module is not mutated and the step fails. Before T070
  such deps were dropped, the baseline link failed on undefined symbols, and the whole module was `mutants-build-failed`.
- `Layout.deps` still holds the product's own cell only (the witness scope reads it); `Layout.links` holds the
  complete link graph.
- Canary `third-party-link` (control, must PASS): `//core:tpm`'s test links `//core:tpw`, which depends on mbedtls.
  Its mutants must have real verdicts (`core/tpm.c:5` survives on purpose); on the pre-T070 gate it is
  `mutants-build-failed`.
