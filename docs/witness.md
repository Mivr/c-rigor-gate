# Witness grading

> **Not wired yet.** This is the library of P002 step 1 (T036). `rigor grade` does not read a witness, a
> role or an `impl` key yet: binding the bundle into the verdict is T037, the `witness-tests` and
> `mutants-witness` gates are T039, and `tests-stub` with the test-author role is T041. The design is
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

## impl paths, test surface and W

`gate/rigor_lib/witness_scope.py`:
- **impl paths**: `impl = ["core/core.c"]` per module in the gate-owned `policy.toml`, the paths an
  implementer task may write and a witness replaces. `impl_map(policy, levels)` returns them with an
  `impl-missing` finding for every L2+ module without them (error at L3 to L5, info at L2). A value that
  is not a non-empty list of distinct valid globs is exit 2.
- **test surface** of module m: every product path in m's package, and in the package of every `c_test`
  that lists m directly in `deps`, that is in no module's impl paths (the header, the BUCK file, the tests
  and the kits). The packages are the directories of the layout's targets; a path belongs to the deepest
  one that contains it, so a directory with a BUCK file but no library, binary or test counts toward the
  enclosing package (more modules in W, never fewer).
- **W** (`scope(role, changed_paths, layout, impl_map, levels)`), over the head's layout and the changed
  paths `merge_base..head`, sorted:
  - `implementer`: the L2+ modules whose test surface changed; a pure implementation change gives W = {};
  - `test-author`: those, plus every L2+ module whose impl paths changed (the stubbed ones);
  - `audit`: every L2+ module that has tests.

  W may be empty in every role. In role test-author an empty W must never pass; T041 turns it into
  `no-new-tests` or `witness-missing`.

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
1. Write the tests, the header, the BUCK file and failing stubs, and commit them (`role = "test-author"`).
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
