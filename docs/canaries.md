# The canary pack (T018, backlog B6)

Self-tests check each component as its author imagined it. The canary pack is the standing, adversarial proof
that the **assembled** gate (`rigor grade`, real clone, Buck2 on RE) still says FAIL for every known cheat.
Every bypass found by a review, by R001 or by the red team becomes a canary.
The opposite pack, honest code with an impossible obligation, is [docs/tripwires.md](tripwires.md).

```sh
selftest/canaries.sh                    # all canaries, 8 at a time, one of them --uncached
selftest/canaries.sh --only nolint      # one canary (repeatable); --jobs N; --uncached ID; --keep
```
Exit 0 only if every non-pending canary behaved as declared. The output is a table
`canary | expected | got | ok`, the list of pending canaries, and the wall time.

## Where the time goes (T025)
Measured 2026-11-06 on the shared farm (four other lanes running; numbers move with their load). Resources of a whole
pack run come from `python3 -I -B canaries/measure.py [--keep] -- python3 -I -B canaries/runner.py ...` (wall, local CPU of
every process including detached Buck2 daemons, peak summed RSS, peak scratch disk); worker time and queue time come from
`tools/lanes/buck2_stats.py` over the kept trees.

| Run | wall | local CPU | peak RSS | peak scratch | pack verdicts |
|---|---|---|---|---|---|
| before: `--jobs 4`, control alone first, scratch kept to the end | 551 s | 96 s | 1380 MiB | 1284 MiB | 0 live misses |
| after: `--jobs 4`, longest-first, uncached lane at t=0, trees removed when judged | 378 s | 96 s | 1536 MiB | 110 MiB | 0 live misses |
| after: `--jobs 8` (new default) | 301 s | 102 s | 2916 MiB | 220 MiB | 0 live misses |
| after: `--jobs 12` | 310 s | 131 s | 4257 MiB | 329 MiB | 0 live misses |

Per canary (before, `--jobs 4`, farm busy): the 41 cached canaries took 15 to 44 s each, `control` 21 s, `weak-test [uncached]` 265 s.
Alone on the same farm a cached canary takes about 8 s (`inline-asm`: 8 s wall, 3.6 s local CPU), so the 15 to 44 s
is queueing behind the other lanes and the four daemons, not work. For a cached canary (`inline-asm`, `control`):
8 to 9 Buck2 commands, 0 actions executed, 24+9+16+102 action-cache hits, 0 worker time, 0 queue time, about 230 KiB
downloaded per build command, 4 to 7 s of the wall in `uquery`/daemon start and prelude analysis (about 2 s per fresh
daemon), the rest in clone, assemble (copy of the gate tree) and Python. Nothing is fetched or unpacked on a cached run.

`weak-test` (`--uncached`, `--no-remote-cache`): 79+15+68+191 actions, 24+9+16+102 executed, 337 s of worker time, queue
under 2 s, 308 KiB uploaded in the large build, 280 KiB downloaded. Its longest actions: `fetched_tree llvm` 113 to 125 s worker
time (it runs twice, once in the facts build and once in the mutants build, because with the action cache off the 2 GB
`tar -xJf` of the LLVM release is redone on a worker each time), then two waves of `mutant_compile`/`mutant_run` actions
of about 35 s wall each but about 1 s of worker time: they wait for input materialisation of the unpacked toolchain on the
worker (sum 31 s) and the `core` wave depends on the `util` wave. Critical path: llvm unpack (about 118 s) + util wave
(about 33 s) + core wave (about 38 s) + the other gates (about 55 s). That floor is about 250 s on this farm and it
cannot be cut from the runner. What would make it faster, out of scope here (`toolchains/**`, `rules/**`): store the LLVM
subset as a smaller, zstd-compressed (or pre-split per member group) archive so the uncached unpack is a few seconds
rather than a 2 GB xz decompress; run the `core` and `util` mutants in one wave; and let the toolchain's `fetched_tree` be
resolved from the CAS even under `--no-remote-cache` (it is a pure download, so the "uncached" proof does not need it).

### What was changed, and what each change gave
- Scratch: each canary's work tree (its `buck-out`, the bulk of the disk) is removed as soon as it is judged unless `--keep`:
  peak scratch 1284 to 110 MiB, no effect on wall.
- Scheduling: the uncached canary starts at t=0 on its own lane (it shares nothing with the rest) and the control runs
  beside it instead of the pack waiting for the control first; the rest start longest-first (canaries that are expected to
  run more gates go first). 551 s to 378 s at `--jobs 4`. `--jobs` counts the uncached canary as one.
- Default `--jobs` 8: 301 s (4: 378 s, 12: 310 s with 4.2 GiB RSS and 131 s CPU). 8 is the knee on this farm.
- Not done, measured against: sharing one `buck-out` or daemon between canaries would change what a "real clone" proves
  (`rigor grade` seals HOME and builds one tree per grade), so every canary keeps its own clone, tree and daemon.

The wall is now `weak-test`'s: with it the pack takes 300 to 380 s here and the 180 s target of T025 is not reachable
while it stays uncached. The other 42 canaries finish in well under 180 s at `--jobs 8`.

## The rule
**No bypass fix merges without its canary.** A change that closes a hole in the gate adds
`canaries/<id>/` in the same commit, and the canary must be red for the reason the fix is about.
A canary is never edited to make it pass (AGENTS.md rule 2); a change to `expect.json` needs the same review as a
change to the gate.

## What passes
A canary passes only if **all** hold, and anything else is a miss (a fixture that fails for the wrong reason
hides a disarmed check):
- the set of FAIL gates equals `expect.json` `fail`'s keys, and for each, the set of **error** finding rules
  equals the listed rules (info findings are ignored);
- the set of NOT_RUN gates equals `not_run` (default none); every other gate is PASS;
- the exit code is `exit` (default 1; 2 is an internal error);
- every `contains` entry (`{"build": "unused-variable"}`) occurs in that gate's result file;
- no file named in `absent` exists in the canary's scratch dir (code that must never run, did not).

Several gates may legitimately fire for one bypass (a defence in depth: the text scan and the semantic scan, the
buckfiles check and the macro's own `fail()`); list them all. If a second defence disappears, that is a change
and the canary says so.

`control` (the unmodified base) must PASS; it proves the shared fixtures are sound and it warms the cache.
The pack also fails if some gate in `gate/order.txt` is not the expected failing gate of any live canary.

## Layout of `canaries/<id>/`
| File | Meaning |
|---|---|
| `expect.json` | `description`, `bypass` (class), `fail` (`{gate: [rules]}`), optional `not_run`, `exit`, `contains`, `absent`, `pending` |
| `product.toml`, `policy.toml`, `expected-tests.json`, `task.toml` | the gate-owned inputs of `rigor grade` (`expected-tests.previous.json` if the canary needs one); `task.toml` is the task contract |
| `edit.sh` | bash, run inside the product repo on top of the base commit; whatever it changes is the head commit |
| `history.sh` | instead of `edit.sh`, for git tricks (graft, replace, unresolvable refs): full control of the repo, env `BASE`, `CANARY_DIR`, `CANARY_SCRATCH`; its last line prints `<base> <head>`. It must check that the trick is armed (see `git-graft`) |
| `product/` | optional full product tree; default is the shared `canaries/_base/product` |

The product repository and its history are generated at run time under `$TMPDIR` and never committed
(no nested repos). `canaries/_base/` holds the shared tree and defaults; copy its four gate files into a new
canary and change only what the bypass needs, so unchanged targets are cache hits.

## Adding a canary
1. Write the smallest `edit.sh` that performs the cheat. Do not use a spelling that a *different* check catches
   first unless that is the point (the spliced `#pra\<newline>gma` canary exists because the plain one is caught
   by the text scan).
2. Put code in a library whose policy level does not add unrelated findings (`util` is L2: its survivors are
   info; `core` is L3, so an untested new function there adds `survived-mutant`).
3. `expect.json`: the gate and rule(s) the cheat must hit. Run `selftest/canaries.sh --only <id>`; if it goes red
   for a *different* reason, fix the fixture; if the gate is silent, you found a gate bug: report it, fix the gate
   in its own task.
4. For a check that is still in flight on another branch, add `"pending": "<task id>"`. Pending canaries run and
   print their verdict but do not fail the pack. When the task merges, the orchestrator removes `pending`
   (and fixes the guessed rule ids in `expect.json`) in the merge.
5. Record the bypass class in `bypass` and, if it came from an audit, the id in `description`.

## Canaries mirroring `selftest/grade.sh` red cases (T046)
These seven were the red cases only `grade.sh` had (R006 #1, step 1). Each `edit.sh` is the grade.sh `edit_*` function verbatim,
with the same `product.toml` variant. The expectation is exact (grade.sh only checks that one rule is present).

| canary | grade.sh step | fails | NOT_RUN |
|---|---|---|---|
| `deleted-target` | `deleted-target` | `tests-release`/`tests-san`: missing-test, `symbols`: policy-module-without-facts | mutants |
| `kills` | `kills` | `symbols`: denied-symbol, `mutants`: survived-mutant | none |
| `spliced-optnone` | `spliced-optnone` | `semantic-suppressions`: forbidden-attribute + line-directive | none |
| `excluded-code` (`product.toml` excludes `core/docs/**`) | `excluded-code` | `buckfiles`: excluded-code | mutants |
| `stale-include` (`product.toml` includes `gone/**`) | `stale-include` | `buckfiles`: stale-include | mutants |
| `third-party-copy` | `third-party-copy` | `buckfiles`: ignored-code, `contract`: outside-allowed (third_party/ is not an allowed path) | mutants |
| `case-collision` | `case-collision` | `buckfiles`: case-collision | mutants |

The runner also ports grade.sh's leaked-daemon check (`find_daemons`): after each canary, a process whose working
directory is under the canary's scratch dir makes that canary a miss.

## Canary added by T055
| canary | bypass | fails | NOT_RUN |
|---|---|---|---|
| `exports-missing-l3` | a new L3 module whose policy table has no `exports` list | `symbols`: exports-missing | none |

Its `policy.toml` is the `_base` policy plus L3 tables for `//core:extra` (no `exports`) and `//core:extra_test`.
## Canary added by T106
| canary | bypass | expected |
|---|---|---|
| `structure-third-party-callback-cycle` (`tpcallback`, step "T106" of `selftest/structure.sh`) | a callback registered with a gate-owned vendored library (`mbedtls_ssl_set_bio(.., bio_send, ..)`) calls back into the library (`mbedtls_ssl_write`) | `structure`: `indirect-cycle-possible` (the only finding) |
| `structure-third-party-callback-green` (`tpgreen`, same step) | the mbedTLS shape: registered callbacks that never call into the library, the registrar behind an ops table | no finding |

Both are real Buck2 modules that depend on `gate//third_party/mbedtls:mbedtls` (the scanner marks the calls into it).
They live in `selftest/structure_product` and are run by `selftest/structure.sh`, which is what the `structure` gate's
canaries are (`callbackcycle` and `fpcycle`, the libc and pointer cases, stay red in the same script).
Unit coverage: `gate/tests/test_structure_vendor.py`.

## Canaries replacing the rest of `selftest/grade.sh`'s red cases (T053)
All 24 remaining red cases of `selftest/grade.sh` are canaries; the table is in `docs/grade.md`. Only one was missing:
`ungraded-module` (the `extra/` directory the layout does not list, `buckfiles`: `ungraded-path`, NOT_RUN mutants).
grade.sh's two extra checks are the `contains` (`unused-variable` in `buckconfig-hidden`) and `absent` (`product-buck2`) hooks the runner already has.

## Witness canaries (T040)
The runner grades every canary with `--witness`: `canaries/<id>/witness/` if present, else the shared
`canaries/_base/witness/` (the base `core.c` and `util.c`, `written_against` is a placeholder). Every `policy.toml`
carries `impl` for its L2+ modules (T039's `impl-missing`). The red witness cases of `selftest/grade.sh` live here.

| canary | bypass | fails | NOT_RUN |
|---|---|---|---|
| `witness-survivor` | head drops the positive `core_sign` checks and the `> 0` branch (its own mutants die); the base witness keeps the branch | `mutants-witness`: witness-survived-mutant | none |
| `witness-test-fails` | a strong new `core_add(1, 1) == 2`; the witness `core_add` returns `a + b + 1` | `witness-tests`: witness-test-not-pass | mutants-witness |
| `witness-missing` | a core test change; the canary's bundle lists only `//util:util` | `witness-tests`: witness-missing | mutants-witness |
| `witness-green` (control) | a strong new core test and the base witness | none: PASS | none |

## Canaries added by T095
| canary | bypass | fails | NOT_RUN |
|---|---|---|---|
| `system-lib-not-allowed` | a new L3 library declares `system_libs = ["pthread"]`, its policy entry does not list it | `symbols`: system-lib-not-allowed; `witness-tests`: witness-missing | mutants-witness |
| `system-lib-not-declared` | the policy entry lists `system_libs = ["pthread"]`, the library declares none | `symbols`: system-lib-not-declared; `witness-tests`: witness-missing | mutants-witness |

Both are the `exports-missing-l3` shape (a new `//core:extra`, whose `witness-missing` is the same as there) with an `exports` list, so the
`system_libs` cross-check is the only symbols finding.

## Canaries not in the tables above (T079)
Added by their own tasks and never listed here. `bypass` is the `expect.json` field; each fail list is the exact set of
FAIL gates with their error rules, and `N later gates` means a gate the bypass stops before (see the canary's `expect.json`).
`crash-oracle` and `crash-oracle-green` came with T078 (`crash-kill-ratio`), `third-party-link` with T070.

| canary | bypass | fails | NOT_RUN |
|---|---|---|---|
| `ancestor-suppression` | suppression committed before the graded base (R001 R5) | `suppressions`: forbidden-pattern-in-tree | none |
| `approval-in-repo` | approval planted in the repo | `contract`: approval-in-repo; `suppressions`: approval-in-repo | none |
| `attr-noinline-backdoor` | attribute hides a function from the mutator | `mutants`: survived-mutant | none |
| `attribute-paste` | attribute behind a macro | `mutants`: survived-mutant; `semantic-suppressions`: forbidden-attribute | none |
| `bad-ref` | unresolvable head | `clone`: internal-error | 15 later gates |
| `binary-artifact` | binary artifact | `suppressions`: binary-artifact | none |
| `bool-function` (control) | R002 F3: a tested `bool` function is mutated, not skipped as macro-made | none: PASS | none |
| `buck-assign` | BUCK assignment | `buckfiles`: bad-statement | mutants, witness-tests, mutants-witness |
| `buck-concat` | BUCK concatenation | `buckfiles`: bad-argument | mutants, witness-tests, mutants-witness |
| `buck-glob-bad` | glob beyond the accepted forms (`**`, `..`, `exclude`, glob in deps, a test glob, glob + glob) | `buckfiles`: bad-argument; `build`: query-failed | 9 later gates |
| `buck-glob-ok` (control) | T102: the two accepted `src/` glob forms (`srcs = glob(["src/*.c"])`, `headers = ["core.h"] + glob(["src/*.h"])`) | none: PASS | none |
| `buck-v2` | hidden build file | `buckfiles`: forbidden-file; `build`: build-failed | 9 later gates |
| `buckconfig-nested` | hidden .buckconfig | `build`: build-failed | 7 later gates |
| `buckconfig-plain` | hidden .buckconfig | `build`: build-failed; `suppressions`: forbidden-pattern | 7 later gates |
| `builtin-alloca` | compiler builtin aliasing a denied capability | `build`: build-failed | 7 later gates |
| `bzl-load` | hidden build file | `buckfiles`: bad-load, extra-load; `build`: query-failed | 9 later gates |
| `crash-oracle` | oracle that only checks for crashes | `mutants`: crash-kill-ratio; `mutants-witness`: crash-kill-ratio | none |
| `crash-oracle-green` (control) | T078: the `crash-oracle` module with real assertions; `crash-kill-ratio` stays quiet | none: PASS | none |
| `cross-cell-dep` | cross-cell dep | `buckfiles`: bad-argument; `symbols`: missing-dep-facts | mutants, witness-tests, mutants-witness |
| `denied-fnptr` | function pointer to a denied symbol | `symbols`: denied-symbol | none |
| `denied-libc` | denied libc symbol | `symbols`: denied-symbol | none |
| `extra-hook` | extra exported writable hook | `symbols`: mutable-global-export, unexpected-export | none |
| `failing-test` | failing test | `tests-release`: test-not-pass; `tests-san`: test-not-pass | mutants |
| `generator-attribute` | function lost by the mutant generator | `mutants`: survived-mutant | none |
| `git-replace` | git replace | `contract`: outside-allowed | none |
| `header-only-kit` (control) | a module whose tests use a header-only test kit is mutation graded at L3 | none: PASS | none |
| `heap-overflow` | heap overflow seen only in san | `tests-san`: no-assertions, test-not-pass | mutants |
| `hollow-module` | logic hidden from the mutator | `mutants`: no-mutants, unmutated-function; `witness-tests`: witness-build-failed | mutants-witness |
| `line-plain` | #line spoofing | `semantic-suppressions`: line-directive; `suppressions`: forbidden-pattern | none |
| `line-splice` | #line spoofing (spliced) | `semantic-suppressions`: line-directive | none |
| `macro-backdoor` | logic hidden from the mutator in a macro | `mutants`: macro-hidden-code | none |
| `mode-divergent` | sanitizer-only code | `mode-divergence`: mode-divergent-code | none |
| `new-module` | module missing from the policy | `mutants`: level-missing; `symbols`: module-not-in-policy | none |
| `nolint` | NOLINT suppression | `suppressions`: forbidden-pattern | none |
| `null-guard` | weak test on a NULL-tolerant accessor | `mutants`: survived-mutant; `witness-tests`: witness-build-failed | mutants-witness |
| `o2-folded-mutant` | equivalent mutant hidden by the optimiser | `mutants`: survived-mutant; `witness-tests`: witness-build-failed | mutants-witness |
| `outside-contract` | files outside the contract | `contract`: outside-allowed | none |
| `per-file-flags` | per-file flags in srcs | `buckfiles`: bad-argument; `build`: query-failed | 9 later gates |
| `pragma-plain` | pragma suppression | `semantic-suppressions`: pragma; `suppressions`: forbidden-pattern | none |
| `pragma-splice` | pragma behind a line splice | `semantic-suppressions`: pragma | none |
| `raw-rule` | raw rule in BUCK | `buckfiles`: bad-call | mutants, witness-tests, mutants-witness |
| `removed-test` | removed expected test | `tests-release`: missing-test; `tests-san`: missing-test; `witness-tests`: missing-test | mutants, mutants-witness |
| `reserved-mbedtls` | reserved mbedtls_ definition | `symbols`: symbol-collision | none |
| `results-fd` | test inherits the results fd | `tests-release`: test-not-pass; `tests-san`: test-not-pass; `witness-tests`: witness-test-not-pass | mutants, mutants-witness |
| `sanitize-guard` | sanitizer-only code | `suppressions`: forbidden-pattern | none |
| `skipped-test` | skipped test | `tests-release`: no-assertions, test-not-pass; `tests-san`: no-assertions, test-not-pass; `witness-tests`: no-assertions, witness-test-not-pass | mutants, mutants-witness |
| `struct-return-untested` | a struct-returning function that is only called, never checked | `mutants`: survived-mutant; `witness-tests`: witness-build-failed | mutants-witness |
| `structure-length` | function too long | `structure`: function-length, statement-count | none |
| `structure-recursion` | recursion | `structure`: recursion | none |
| `structure-typed-cycle-cast` | recursion through a function pointer, hidden by a function-pointer cast | `structure`: indirect-cycle-possible; `witness-tests`: witness-build-failed | mutants-witness |
| `stub-green` (control) | T041: role `test-author`, sentinel stub, strong new test, correct witness | none: PASS | none |
| `stub-passes-test` | a test-author test that passes on the stub (P002 Q2, test-passes-on-stub) | `tests-stub`: test-passes-on-stub | none |
| `symlink` | symlink | `assemble`: unsupported-entry; `contract`: symlink | 11 later gates |
| `test-peer-in-library` | test peer in a library | `buckfiles`: bad-argument; `build`: build-failed | 9 later gates |
| `test-removal` | removed expected test (list edited) | `tests-release`: test-removed; `tests-san`: test-removed | mutants |
| `third-party-link` (control) | T070: an under-tested L2 module whose test links a library that depends on `gate//third_party/mbedtls`; its mutants are still graded (`contains` `core/tpm.c:5`) | none: PASS | none |
| `unviable-shape` | unviable-ratio | `mutants`: unviable-ratio; `witness-tests`: witness-build-failed | mutants-witness |
| `weak-error-code` | tests check failure, not which failure | `mutants`: survived-mutant; `witness-tests`: witness-build-failed | mutants-witness |
| `weak-string` | tests check non-NULL, not the text | `mutants`: survived-mutant; `witness-tests`: witness-build-failed | mutants-witness |
| `weak-symbol` | weak symbol | `semantic-suppressions`: forbidden-attribute; `symbols`: weak-symbol | none |

## Canaries added by T105 (`c_catalog`)
| canary | bypass | fails | NOT_RUN |
|---|---|---|---|
| `catalog-ok` (control) | two pots with one shared msgid, one needed `names` override (`Hello` / `hello!`), bg and en, a `c_test` formatting three ids in both languages; the catalog is an L1 module | none: PASS | none |
| `catalog-empty-bg` | an untranslated phrase in the default language (empty `msgstr`) | `build`: build-failed (`no bg translation`) | semantic-suppressions, symbols, structure, mode-divergence, tests-release, tests-san, mutants |
| `catalog-extra-msgid` | a `.po` msgid that its `.pot` does not have | `build`: build-failed (`not in cat/a.pot`) | same |
| `catalog-placeholder` | a translation that drops the source's `{0}` | `build`: build-failed (`bg uses placeholders []`) | same |
| `catalog-names-unneeded` | a `names` entry for a msgid whose name collides with nothing | `build`: build-failed (`names: entry not needed`) | same |
| `catalog-name-collision` | two msgids (`Hello`, `hello`) naming one enum constant | `build`: build-failed (`also the name of msgid`) | same |

All five share `canaries/_catalog/files/` (a canary-local `i18n` runtime with the layout of the business-apps one, a two-pot
`cat` package and its test), copied in by each `edit.sh`; the red ones then break one thing with a few lines. The product
here is `i18n/`, `cat/` next to `core/`, `util/`. `expect.json` `contains` pins the exact `po2c` message in `build.json`, so a
canary that fails for another reason is a miss.

## Canaries added by T129 (the `fuzz` gate)
| canary | bypass | fails | NOT_RUN |
|---|---|---|---|
| `fuzz-crash` | a parser (profile `parser`) whose `parse_run` reads `buf[data[4] % 8]` from a 4-byte buffer behind the magic `PA`; the fixed seed and budget of the `c_fuzz` run reach it | `fuzz`: fuzz-crash | none |
| `fuzz-missing` | the policy gives `//parse:parse` the `parser` profile and the product has the library and no `c_fuzz` target | `fuzz`: fuzz-missing | none |
| `fuzz-vacuous-harness` | the `c_fuzz` target lists the parser in `deps`, runs clean, and its harness never calls it | `fuzz`: fuzz-harness-no-call | none |
| `fuzz-regression-dropped` | `fuzz-regressions.json` (gate-owned, beside `policy.toml`) names the sha256 of an input that once crashed `//parse:fz`; it is not among the replayed corpus files (a graded `c_fuzz` cannot name a corpus yet, so none) | `fuzz`: fuzz-regression-missing | none |
| `fuzz-green` (control) | the same shape with the fixed parser and a harness that calls it | none: PASS | none |

They share `canaries/_fuzz/files/` (the parser in two variants, the two harnesses, the BUCK files), copied in by each `edit.sh`; the
policy of each adds an L1 `//parse:parse` (`profile = ["parser"]`, `allow = ["malloc", "free"]`) and, where there is a target, a
`//parse:fz` entry that exports `LLVMFuzzerTestOneInput`. `fuzz` is also a NOT_RUN gate wherever `mutants` is (they need the same
gates to have passed): every `not_run` list that named `mutants` names `fuzz` now, in the canaries and the tripwires.

## Not covered here
`rigor trajectory` (T015) audits an agent transcript, not a graded repository, so it has no canary until it is
part of `rigor grade`. The environment-hostility and signature checks stay in `selftest/grade.sh`.
