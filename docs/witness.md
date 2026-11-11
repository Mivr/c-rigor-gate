# Witness grading

> **Wired for every role** (T039, T041): `rigor grade --witness DIR` binds the bundle (T037), the gates `witness-tests`
> and `mutants-witness` judge it (`docs/grade.md`, "The witness gates"), and in role `test-author` the gate
> `tests-stub` judges the new tests on the stubs (`docs/grade.md`, "The stub check"). The design is
> `plan/P002-witness-grading.md`.

A **witness** is an implementation of a module that the gate holds and the implementer never sees. The
test-author grade judges the tests against it: every new test fails on the stubs, every expected test
passes on the witness, and the witness has zero surviving mutants. So the tests pin whatever the witness
does, not only whatever the implementer chose to write (R003 G1).

## Bundle format

A bundle is a directory with exactly two entries:
```
<bundle>/witness.toml
<bundle>/files/<product path>       # product-relative paths, e.g. files/core/core.c
```
```toml
product = "annas-c"                 # must equal product.toml's name
[module."//annas:annas"]
origin = "A012"                     # the task that wrote it (information)
written_against = "<40-hex>"        # the test-author head it was calibrated on (information)
```

It is gate-owned input: every defect is exit 2 (`InternalError`), like a malformed `expected-tests.json`.
`gate/rigor_lib/witness_bundle.py` checks:
- the top level holds exactly `witness.toml` (a regular file) and `files/` (a directory), and the bundle
  directory itself is not a symlink;
- under `files/`: no symlinks (to files or directories), no special files (FIFOs, sockets, devices), no
  empty directories, no names that are not UTF-8, no unsafe paths;
- `witness.toml` is UTF-8 TOML with exactly the keys `product` (non-empty string) and `[module]` (at least
  one table); each module label is `//pkg:name` and has exactly `origin` (non-empty string) and
  `written_against` (40 lowercase hex digits);
- against the policy (`check`): the product name matches; every listed module has `impl` paths; every
  file matches the `impl` paths of exactly one module of the policy, and the bundle lists that module;
  every listed module has at least one file.

Files are read once, without following symlinks, and kept in memory; file modes are not part of a bundle
(witness files are written `0644`).

**Digest.** `witness_sha256` is the sha256 of `canonical_dumps(entries)`, where `entries` is
`[["witness.toml", sha256 of witness.toml], ["files/<path>", sha256 of the file], ...]`: the manifest
first, then every file by its bundle path, sorted by path. It does not depend on where the bundle is
stored.

**Overlay.** `overlay(head_paths, bundle, modules)` is the witness tree's product file list. `modules` maps
each module in W to its `impl` globs. For each one the bundle lists, the head paths matching its globs are
left out and the bundle files matching them are added; a module in W that the bundle does not list keeps
its head files (the gate reports `witness-missing`). A path that would be both a file and a directory is
exit 2.

## Binding (T037)

The bundle is bound like `policy.toml` (T021's rules: copy once, hash the copy), with no signature.
- `rigor grade --witness DIR`: DIR is made absolute and copied once into `<work>/inputs/witness/`.
  The copy refuses symlinks (the bundle directory itself, files, directories, `witness.toml`) and
  special files. The copy is then loaded once with `witness_bundle.load`; that one load is both the
  grade's `g.witness` and what `witness_sha256` is computed from (`digest`, above), so nothing is
  hashed from one read and used from another, and the original can change afterwards without effect.
- Any defect (missing or unreadable DIR, symlink, special file, any format defect of the loader) is
  exit 2 before `clone`: no gate runs and no verdict is written.
- `core.inputs.witness_sha256` is the digest, or `null` without `--witness`. The same bundle stored under
  two paths gives the same core.
- `rigor verify --expect-witness-sha S` rejects a verdict whose `witness_sha256` is any other value, and
  one graded without a witness (`null`). Without the option any well-formed value, or `null`, is
  accepted. The merge bot passes it for every decisive grade of a product with L3 modules.
- `rigor grade` clears `<work>/tree-witness/` and `<work>/witness/` before a run (stopping the witness
  tree's Buck2 daemon first), and stops that daemon again on exit, as it does for `<work>/tree/`. The witness
  gates (T039) fill them.
- **Approvals** (owner decision 4, not yet confirmed): an equivalent mutant of the witness is approved
  with the separate kind `witness-equivalent-mutant` (`rigor approve --kind witness-equivalent-mutant
  --scope <mutant id> ...`), never with `equivalent-mutant`, so a witness approval cannot cover a same-id
  mutant of the implementer's code. `mutants-witness` (T039) judges its survivors with it. Prefer rewriting the
  witness; approve only spec-required defensive code.

## A module whose witness is the head's code (owner decision 2026-11-11)

A bundle often carries a real re-implementation for the few modules a task changes and `from-commit` copies for the
rest of W (each needs an entry, else `witness-missing`). A copy is the head's code, and in the roles `implementer`
and `audit` the head's `mutants` gate judges that same code against the same tests in the same grade, with the
`equivalent-mutant` approvals. So `mutants-witness` leaves such a module out (info `witness-module-equals-head` per
module, metadata `equal_to_head`): its survivors are the head gate's findings, not a second set that would need a
second approval of another kind.

- **Equal** means, per module: the files under its impl paths are the same paths with the same bytes (sha256) in the
  head tree and in the witness tree; a missing file, an extra file or one differing byte makes it a different module,
  which is mutated and judged as always.
- **Only when the head gate judged it in this grade**: head `mutants` ran and its result has a summary for the module.
  In role `test-author` head `mutants` is not applicable (the head is the stub commit), so there **every module of W
  is still mutated in `mutants-witness`, copies included**. That is deliberate: it is the only gate of a test-author
  grade that judges the tests of a module the author did not stub, and without it a test author could weaken them
  unseen (canary `witness-copy-weak-tests`). A copy's unkillable mutants therefore still need
  `witness-equivalent-mutant` approvals in a test-author grade.
- `witness-tests`, `witness-missing` and the whole-tree reuse ("Bootstrap", below) are unchanged.

| canary | what | fails |
|---|---|---|
| `witness-copy-skipped` | role implementer; a bundle with a rewritten `core` and a copy of the head's `util` (L3 here), which has unkillable mutants | `mutants`: survived-mutant (the head's own, once). `mutants-witness` passes: `core` judged, `util` reported as `witness-module-equals-head` |
| `witness-copy-weak-tests` | role test-author; `util` is stubbed and has a real witness, `core` is a copy, and the author dropped the positive `core_sign` checks | `mutants-witness`: witness-survived-mutant (the copy is still judged) |

## Roles

`role` is an optional key of the task contract (`TASK.toml`), read by `contract.load_contract` as
`Contract.role`:

| Role | Meaning |
|---|---|
| `implementer` | the default (no key): an implementation against fixed tests; the behaviour of today |
| `test-author` | a stubbed head: new tests plus stubs that fail them |
| `audit` | a periodic or bootstrap grade of every module |

Any other value, or a value that is not a string, is exit 2. A contract without the key fails closed: a
stubbed head graded as implementer fails `test-not-pass`.

What role `test-author` changes in `rigor grade` (T041):
- `expected-tests.previous.json` is required next to `product.toml` (exit 2 in the `contract` step otherwise);
- `tests-release` and `tests-san` judge presence, duplicates and parse problems of every expected id, not
  pass/fail or assertions;
- `tests-stub` requires every new id to fail on the stubs in both modes;
- head `mutants` is PASS with info `not-applicable`;
- the witness gates are required: W = {} is `no-new-tests` (in `witness-tests`), and a module of W without a
  bundle entry is `witness-missing` as an error at every level, so the grade can never pass unjudged.

## impl paths, test surface and W

`gate/rigor_lib/witness_scope.py`:
- **impl paths**: `impl = ["core/core.c"]` per module in the gate-owned `policy.toml`, the paths an
  implementer task may write and a witness replaces. `impl_map(policy, levels)` returns them with an
  `impl-missing` finding for every L2+ module without them (error at L3 to L5, info at L2). A value that
  is not a non-empty list of distinct valid globs is exit 2.
  A product's BUCK files are test surface and are not replaced, so a witness that chooses its own file names
  (`src/dump.c` where the head has `src/scene_dump.c`) would be built against an explicit `srcs` list naming files
  that do not exist. That is why `buckfiles` accepts the package-local source glob (`srcs = glob(["src/*.c"])`,
  `headers = ["fp.h"] + glob(["src/*.h"])`, exact forms in `docs/grade.md`): the BUCK file stays
  witness-agnostic, and the impl globs of `policy.toml` cover whatever the witness writes under `src/`. The
  structure, mutants and witness steps read sources with `uquery` (which expands the glob), not from BUCK text.
- **test surface** of module m: every product path in m's package, and in the package of every `c_test`
  that lists m directly in `deps` (of any package: wider than the tests that run against m's mutants, which are
  its own package's only, `docs/grade.md` "Tests"), that is in no module's impl paths (the header, the BUCK file, the
  tests and the kits). The packages are the directories of the layout's targets; a path belongs to the deepest
  one that contains it, so a directory with a BUCK file but no library, binary or test counts toward the
  enclosing package (more modules in W, never fewer).
- **W** (`scope(role, changed_paths, layout, impl_map, levels)`), over the head's layout and the changed
  paths `merge_base..head`, sorted:
  - `implementer`: the L2+ modules whose test surface changed; a pure implementation change gives W = {};
  - `test-author`: those, plus every L2+ module whose impl paths changed (the stubbed ones);
  - `audit`: every L2+ module that has tests.

  W may be empty in the roles implementer and audit (the witness gates are then not applicable). In role
  test-author an empty W is the error `no-new-tests`, and a module of W without a bundle entry is the error
  `witness-missing` at every level (T041).

Example, `canaries/_base/product`: `util/util_core_test.c` is `//util:core_test`, which lists `//core:core`
directly, so a change to it alone gives W = {`//core:core`, `//util:util`}.

## The stub judgement (`tests-stub`)

`gate/rigor_lib/stub_judge.py`, `judge(expected, previous, parsed_by_mode)`: the new ids are `expected` minus
`previous` (`expected-tests.previous.json`, required in role test-author; `None` is exit 2). The results
are those of the head, release and san (`parse_directory` per mode).

| Finding | When |
|---|---|
| `test-passes-on-stub` (id, mode, status) | a new id did not fail in that mode (`pass`, or `skip`, which is not a fail either) |
| `missing-test` (id, mode) | a new id is absent from that mode's results |
| `no-new-tests` | there are no new ids |
| info `stub-timeout` (id, mode) | a new id failed by timeout: stubs should return at once |

Any `status: fail` counts as failing on the stub. Its kind is read from the ctest `reason` and counted in
metadata `fail_kinds` per mode: `check` (`N of M checks failed`), `crash` (a signal, an exit status, a
sanitizer report, no or an invalid report), `timeout`, `no-checks`, and `other` (any other reason).

**Wiring (T041).** The gate `tests-stub` (`grade_steps.tests_stub_gate`) runs right after `tests-san`. In role
test-author it is NOT_RUN unless both modes built clean; in the other roles it is PASS with info
`not-applicable`. There is no approval kind for a test that passes on the stubs.

| canary | what | fails |
|---|---|---|
| `stub-passes-test` | role test-author; new `core_pos`, whose shipped stub is its correct body (the witness's, byte for byte); a strong new test | `tests-stub`: test-passes-on-stub |
| `stub-green` (control) | role test-author; a sentinel stub (`-12345`), a strong new test, a correct witness | none: PASS |

Both carry `expected-tests.previous.json` (the base list) and their own one-module bundle in `witness/`.

## `gate/tools/witness.py`

```sh
gate/tools/witness.py from-commit --repo R --commit C --module //core:core --paths core/core.c \
    [--module LABEL --paths GLOB... ...] --product NAME --out DIR
gate/tools/witness.py digest DIR
gate/tools/witness.py check DIR --product NAME --impl //core:core=core/core.c [LABEL=GLOB ...]
```
- `from-commit` reads the commit's blobs (`ls-tree` and `cat-file`, as the grading tree does; never a
  working directory) into a new bundle at DIR, which must not exist. A symlink, a gitlink, or a path
  matched by two modules is exit 2, as is a module with no files. The bundle is written next to DIR,
  loaded and checked, and only then renamed into place. `origin` is `from-commit` and `written_against`
  is the commit. It prints the digest.
- `digest` prints `witness_sha256`.
- `check` loads the bundle and checks it against the product name and the impl globs; it prints `ok`
  and the digest.

Exit 0 when done, 2 on any defect.

## Procedure (P002, Q1)

**Test author.**
1. Write the tests, the header, the BUCK file and failing stubs, and commit them (`role = "test-author"`). Stub
   every function the new tests exercise, with a sentinel (`-12345`) rather than a plausible value; a stub that
   never returns works, but costs 10 s per mode (info `stub-timeout`).
2. Write the witness as a bundle in your own `/var/tmp/cache/A<NNN>/witness/`. Never commit it.
3. Acceptance is a cached `rigor grade --witness /var/tmp/cache/A<NNN>/witness` against a scratch copy of
   `products/<p>` with the new ids added by `expected.py add` and the old list as
   `expected-tests.previous.json`.
4. The report lists the new ids, the stub fail kinds and the witness verdict, never the witness code.

**Orchestrator, at validation.**
1. Commit the bundle to the private `c-rigor-hidden/<product>/witness/`, replacing that module's files.
2. Delete the cache copy.
3. Update the gate-owned expected lists.
4. Run the decisive grade with a work directory under a `*-hidden` path (it holds witness copies in
   `inputs/` and `tree-witness/`, and the trajectory rule `read-hidden-repo` covers it).

**Who may read a bundle:** the orchestrator, the gate process, and the test-author lane that wrote it,
during its own task and its fix tasks. Never an implementer, never a later test author. The orchestrator
never forwards a test-author verdict to an implementer.

**Bootstrap.** For modules that already exist, `witness.py from-commit` at main builds a bundle from their
impl paths. Such a witness equals the head, so it adds no G1 strength for them, but it makes every later
strengthening task gradeable and costs nothing through the identical-tree reuse.
