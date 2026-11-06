# P002: grading against the gate-held witness and the stubs (backlog B27, R003 G1)

> Orchestrator note: task numbers renumbered at merge (the doc's T035-T040 are T036-T041; T035 is the G2/G3 generator task).

Design only. It answers the six questions of `plan/tasks/P002-witness-grading-design.md` and ends in a task split
(T036 to T041) and the decisions the owner has to make. Read against main `3c0ee72`. T021 (verdict inputs), T030
(toolchain reuse), T032 (structure and mode-divergence wiring), T033 (exports) and T034 (header-only kits,
deterministic mutants) are unmerged and in flight; the split below waits for whichever of them owns a file it needs.
No farm run was made. The cost figures are R004's measured annas numbers, plus estimates from file counts that are
marked as estimates.

## Summary

| # | Question | Recommendation |
|---|---|---|
| 1 | Where the witness lives | A **witness bundle**: a directory with `witness.toml` and `files/<product path>`, kept in a private repo named `c-rigor-hidden` (the trajectory rule `read-hidden-repo` already blocks any `*-hidden` path). `rigor grade --witness DIR` snapshots it into `<work>/inputs/witness/`, the same way T021 snapshots approvals, and binds `witness_sha256` into `core.inputs`; `rigor verify --expect-witness-sha` checks it. There is no signature: it is bound like `policy.toml` is. Each module's implementation paths are a gate-owned `impl = [...]` list in `policy.toml`. |
| 2 | `test-passes-on-stub` | Checked at the **test-author grade**, whose head *is* the stub commit, so it costs no extra builds. A task contract with `role = "test-author"` makes the new gate `tests-stub` require every **new** expected id (`expected` − `expected-tests.previous.json`) to fail in release **and** san. Any `fail` counts (check failure, crash, sanitizer, timeout, no checks); the kind is recorded in metadata. Nothing is checked at the implementer grade, and there is no approval for a test that passes on the stubs. |
| 3 | `witness-survived-mutant` | A **separate gate**, `mutants-witness`. It is not a union with the implementer's mutants, because a different party fixes it. It uses the same tests and the same rules, at the same levels (error at L3 and above, info at L2). It runs only for modules whose **test surface** changed in the graded diff, so an implementer grade normally runs nothing extra. Approvals use a distinct kind, `witness-equivalent-mutant`. |
| 4 | Off-spec tests (S7b) | Witness grading cannot see a divergence that the tests and the witness share, and it cannot see code the witness itself left out. Both need **hidden tests** (B7) run against the witness *and* the head. The interface is fixed here: a second bundle (`--hidden`, bound as `hidden_sha256`), a gate-written `gate-hidden/` package, a fail-on-stub / pass-on-witness / pass-on-head rule, and redacted findings. Owner option: an independent witness author for L3 modules. |
| 5 | Cost | An annas-size test-author grade gains one witness mutation run (about 900 compile and 10,000 run actions, about 17 min uncached; R004) and one witness-tree build (about 1,000 actions, estimate). The implementer grade gains nothing. A witness byte-identical to the head reuses the head's results (zero actions). Decisive grades stay `--uncached` in full. T030 is a prerequisite: without it each witness build command re-unpacks LLVM (about 120 s). |
| 6 | Tasks | T036 (pure library, can start now), T037 (verdict binding, after T021), T038 (build and mutants steps take a tree, after T030), T039 (witness gates, after T032, T033, T034, T037, T038), T040 (canaries, stacked on T039 and merged with it), T041 (`tests-stub` and the test-author role). |

## What changes in the two-context flow

**Today:**
- The test author commits the header, BUCK, tests and failing stubs, and writes a witness in `/var/tmp/cache/A<NNN>/`.
- The orchestrator checks by hand that the stubs fail and the witness passes, in release and san, then moves the
  witness out of reach.
- `rigor grade` cannot pass a test-author commit at all: `test-not-pass` on the stubs makes `mutants` NOT_RUN (R003
  S7a). Test-author merges therefore carry no PASS verdict.
- The implementer grade judges the tests only against the implementer's code (G1).

**After this design:**
- The test-author commit gets a real PASS verdict. It requires all of these:
  - every new test fails on the stubs (`tests-stub`);
  - every expected test passes on the witness (`witness-tests`);
  - the witness has zero survivors (`mutants-witness`).
- The implementer grade is unchanged. It needs nothing new because zero witness survivors means the tests pin every
  mutant-observable behaviour of the witness. An implementer who omits code the witness has now fails a test, so G1
  moves from "whatever the implementer chose to write" to "whatever the witness contains" (see Q4 for that residue).

## Terms

- **role**: a new optional key in the task contract (`TASK.toml`), bound into the verdict by `task_sha256`:
  - `"implementer"` is the default and the behaviour today;
  - `"test-author"` means a stubbed head;
  - `"audit"` means a periodic or bootstrap grade of all modules.
  A contract without the key behaves as today, which fails closed: a stubbed head graded as implementer fails
  `test-not-pass`.
- **impl paths**: `impl = ["annas/src/**"]` per module in the gate-owned `policy.toml`. These are the paths an
  implementer task may write, and the paths a witness replaces. In annas-c they are `<m>/src/**`. In the canary and
  selftest products they are single files (`core/core.c`), so this cannot be a naming convention.
  - An L2+ module without `impl` is a finding `impl-missing` (error at L3, info at L2). The symbols copy of the
    policy drops the key, exactly as it drops `level` today (`grade_policy.py`).
- **test surface** of module `m`: every product file in `m`'s package, and in the package of every `c_test` that
  lists `m` directly in `deps` (the same test set `grade_mutants.plan` uses), that is not in any module's impl paths.
  That is the header, the BUCK file, the tests and the kits.
- **witness scope W**: the modules the witness gates judge. It is computed from the head's layout (`uquery`, as
  `grade_mutants.read_layout` does) and the changed paths `merge_base..head`:
  - `implementer`: the L2+ modules whose test surface changed. A pure implementation change gives W = {}.
  - `test-author`: those, plus every L2+ module whose impl paths changed (the stubbed ones). W must not be empty.
  - `audit`: every L2+ module that has tests.
- **witness tree**: `<work>/tree-witness`. It is assembled exactly like `<work>/tree` (gate files, generated
  `.buckconfig`, product files read as blobs from the clone at H), except that for every module in W that has a
  bundle entry, the head files matching its impl paths are left out and the bundle's files are written instead.

## Q1: where the witness lives and how it is bound

| Option | Integrity | Secrecy | Bound into the verdict | Verdict |
|---|---|---|---|---|
| A. In the gate repo (`products/<p>/witness/`) | git | **none**: the gate repo is public and a submodule of every product | as a product file | rejected |
| B. The orchestrator's quarantine directory (today) | none: same uid, anyone can edit | detection only | no | status quo, the gap |
| C. A bundle directory, kept in a private `c-rigor-hidden` repo; `rigor grade --witness DIR` snapshots and hashes it | git history in the hidden repo, plus `witness_sha256` in the signed core | detection in phase 1 (the trajectory rules `read-hidden-repo` and `read-other-cache`); enforced once contributors run in orca-dev sandboxes that do not mount it (B5) | yes | **recommended** |
| D. C plus an SSH signature on the bundle | as C | as C | yes | not needed: the merge bot already pins the expected sha, as it does for the policy. A signature adds key handling and no new trust root |

### Bundle format (gate-owned input: any defect is exit 2, like a malformed `expected-tests.json`)
```
<bundle>/witness.toml
<bundle>/files/annas/src/api.c            # product-relative paths, under files/
```
```toml
product = "annas-c"                      # must equal product.toml's name
[module."//annas:annas"]
origin = "A012"                          # the task that wrote it (information)
written_against = "<40-hex>"             # the test-author head it was calibrated on (information)
```

Validation:
- no symlinks, special files, unsafe paths or empty directories;
- every file under `files/` matches the impl paths of exactly one listed module;
- a listed module with no files is an error;
- impl paths are checked against the policy when the grade starts, so a path outside them is exit 2 before any build.

Digest: `witness_sha256` is the sha256 of `canonical_dumps([["witness.toml", sha], [path, sha], ...])` over the
snapshot. It is independent of where the bundle was stored.

### Binding
T021's pattern applies:
- The bundle is copied once into `<work>/inputs/witness/`, and every later step reads the copy.
- `core.inputs.witness_sha256` is optional: null without `--witness`.
- `witness-tests` also writes an info finding `witness-manifest` with the sha256 of the witness tree's product files,
  so the verdict hash commits to exactly what was built, like `product-manifest`.
- `rigor verify --expect-witness-sha S` rejects any other bundle, and a null one.
- Decisive grades of a product with L3 modules always pass the product's current bundle, even when W is empty. The
  merge bot always passes `--expect-witness-sha`.

### Who may read it, and how a test author produces it unseen
1. The test author writes the bundle in its own `/var/tmp/cache/A<NNN>/witness/` and never commits it. Its own
   acceptance is a cached `rigor grade --witness /var/tmp/cache/A<NNN>/witness` against a scratch copy of
   `products/<p>` that has its new ids added with `expected.py add`, and the old list as
   `expected-tests.previous.json`.
2. At validation the orchestrator does all of the following:
   - commits the bundle to `c-rigor-hidden/<product>/witness/`, replacing that module's files;
   - deletes the cache copy;
   - updates the gate-owned expected lists;
   - runs the decisive grade with a work directory under a `*-hidden` path. The work directory holds witness copies in
     `inputs/` and `tree-witness/`, and naming it so puts it under the same trajectory rule.
3. Readers allowed: the orchestrator, the gate process, and the test-author lane that wrote it, during its own task
   and in its own fix tasks (the orchestrator hands the bundle back into that task's cache).
   - Never an implementer.
   - Never a later test author: a strengthening task starts from main's `src/`, which it can read anyway.
4. **Leak through verdicts.** `mutants-witness` findings carry `file:line`, the function and the operator, but no
   `original` or `replacement` text. The full reports stay in `<work>/witness/mutants-reports/`.
   - An implementer grade with W = {} contains no witness output at all.
   - The orchestrator never forwards a test-author verdict to an implementer.
5. **Bootstrap.** Existing annas-c modules have no witness that passes today's tests: A003's witness predates
   A025/A032. `gate/tools/witness.py from-commit` builds a bundle from the impl paths of a commit (main), which the
   orchestrator commits as the first bundle. Such a witness equals the head, so it gives no G1 gain for the existing
   modules (see owner decision 6). It does make every later strengthening task gradeable, and it costs nothing
   through the identical-tree reuse (Q5).

## Q2: `test-passes-on-stub`

### Where it is checked
| Option | Cost | Problem |
|---|---|---|
| **At the test-author grade: its head is the stub commit** | 0 extra actions (the head is built in both modes anyway) | none; **recommended** |
| At the implementer grade, by building `base` | one extra full results build in both modes | `base` is main, not the stubs, once anything else has merged; and strengthening tasks have no stubs at all |
| At the implementer grade, on a named stub commit | as above | redundant once test-author verdicts are decisive; the implementer's contract keeps the tests fixed |

### Semantics with `role = "test-author"`
- **New ids** are `expected-tests.json` minus `expected-tests.previous.json`.
  - In this role the previous file is required (`{"ids": []}` for a new product); without it the grade is exit 2.
  - The orchestrator moves the old list to `previous` and adds the new ids before grading, as `expected.py` already
    supports.
- **`tests-stub` gate** (new; it reads the head's results of both modes, with no new build):
  - `test-passes-on-stub` (id, mode): a new id with status `pass` in release **or** san;
  - `missing-test` (id, mode): a new id absent from the head's results;
  - `no-new-tests`: the new-id set is empty (a test-author grade that judges nothing must not pass);
  - NOT_RUN if the head's build was not clean. In the other roles it is PASS with info `not-applicable` (role).
- **What "fail" means.** Any `status: fail` counts:
  - a check failure (`N of M checks failed`);
  - a crash, a signal, or a sanitizer exit (`exited with status ...`);
  - `timeout after 10 s`;
  - `no checks executed`.

  The point of the rule is that the test can tell the stub from the witness. `witness-tests` separately proves that
  the test passes on the witness with at least one assertion, so a crash on a NULL-returning stub is a fine way to
  fail. The kinds are counted in metadata per mode. A timeout is info `stub-timeout`, because each one costs 10 s of
  farm time per mode: stubs should return at once.
- **Both modes.** A pass in either mode is the finding: the implementer is graded in both, and passing on the stubs
  in san alone means the test only checks something under the sanitizer.
- **`tests-release` / `tests-san` in this role** still check presence, duplicates and parse problems of every
  expected id, but **not pass/fail status**. A stubbed function fails its old tests too (A018-style rework). All
  statuses are judged on the witness tree instead (`witness-tests` runs every expected id).
- **Head `mutants` in this role** is PASS with info `not-applicable`: mutating stubs only gives `baseline-red`. The
  modules outside W have unchanged code and tests, so skipping them loses nothing.
- **No approval kind.** A stub is the test author's to choose. A test that passes on *every* stub tests nothing about
  the module. One that passes on the shipped stub only needs a different stub (return a sentinel such as `-12345`).
  If a real exception appears, adding a `stub-pass` approval kind is an owner decision (decision 3), not part of this
  design.
- **Process rule for the orchestrator.** A test-author task either stubs every function its new tests exercise
  (`role = "test-author"`), or adds tests that pass on the current implementation (default role, like A032), where
  the witness gates do the judging. A mixed head fits neither.

## Q3: `witness-survived-mutant`

- **Gate `mutants-witness`.** The same `c_mutants` generation as `mutants` (`grade_mutants.plan` over the witness
  tree's layout, the same direct tests and link deps) runs over the witness tree, for the modules in W that have a
  bundle entry and are at L2 or above. It is judged by `mutants_gate.run` with the witness approval kind.
  - It needs `witness-tests` PASS (else NOT_RUN).
  - It is PASS with info `witness-scope` (an empty list) when W = {}.
- **Rules.** Every `rigor mutants` rule applies under this gate id:
  - `crash-only-function`, `no-assert-kill-function`, `unviable-ratio`, `unmutated-function`, `macro-hidden-code`
    (T028) and `no-mutants`. A witness has to be mutable code too.
  - Two are renamed, so that triage never confuses them with the implementer's: `survived-mutant` becomes
    **`witness-survived-mutant`** (error at L3, L4 and L5), and the L2 info `survivor` becomes `witness-survivor`.
  - `witness-tests` likewise says `witness-test-not-pass` instead of `test-not-pass`.
- **Not a union with the implementer's mutants.** The two sets are about different code, so a survivor in one and a
  kill in the other compare nothing. They also have different owners: a witness survivor is a test-author fix task,
  an implementer survivor is an implementer fix (or, when the witness had no survivor there, a hint that the
  implementer wrote behaviour the witness lacks, see Q4). Separate gates keep both visible in one verdict. Both apply
  in an `audit` grade.
- **When it runs.** In practice at the test-author grade and in strengthening and audit grades. It does not run at a
  plain implementer grade: the implementer's contract protects the test surface, so a witness result graded when that
  surface was merged stays valid.
  - The invariant is: every merged change to a module's test surface was witness-graded. It holds because W is
    computed from the diff, not taken on trust from the role.
  - Known limit: a later change to a *dependency* module could in principle change what the tests kill. A periodic
    `audit` grade re-checks that.
- **Approvals.** Approvals are allowed, under a **distinct kind `witness-equivalent-mutant`**, signed like any
  loosening (owner decision 4).
  - The mutant id (`docs/mutate.md`, Ids) has no context in it. An `equivalent-mutant` approval written for the
    witness could therefore also cover an identical-looking mutant of the implementer's code, in a context where it
    is not equivalent (the B18 drift risk). A separate kind keeps the two sets apart.
  - The guidance for the orchestrator: prefer rewriting the witness, which the test author owns. Approve only
    spec-required defensive code.

## Q4: what remains for hidden tests (B7), and the interface they need

Witness grading proves that the visible tests pin the witness. It does not prove that the witness follows the spec.
What remains:
1. **S7b**: tests and witness share a misreading of the spec. Today the spec-correct implementer is the one that
   fails (S7b-c).
2. **The minimal witness** (G1 one level up): a test author who writes weak tests *and* a witness without the
   untested code passes `mutants-witness`, as W4 would. This is the main residual risk of this design.
3. Header looseness that no code reveals (R003 pattern 6, for example "`*out` unspecified on error"), quadratic
   paths (B13), and overfitting to the visible inputs.
4. A useful mechanical hint that comes free: an implementer survivor at a line where the witness had no survivor
   means the implementer wrote behaviour the witness lacks. Either the code is extra, or the witness and tests are
   incomplete; the orchestrator triages.

**Interface for B7** (designed here so that T036 to T039 build the right seams; the hidden tests themselves are a
later task):
- **Bundle:** `--hidden DIR`, with the same snapshot and digest code as the witness, bound as `hidden_sha256`.
  - It contains `hidden.toml` (`[module."//annas:annas"] tests = [...]`), `files/<n>/*_test.c` and
    `hidden-expected.json`.
  - It is written by a different context (Opus, from the spec) and stored in the same `c-rigor-hidden` repo.
- **Package:** the gate copies the files to `gate-hidden/<n>/` in each tree it judges and writes
  `gate-hidden/<n>/BUCK` itself: one `c_test` per entry, with `deps` equal to the module plus its link closure, loaded
  from `@gate//rules:c.bzl`.
  - This is the same mechanism as `gate-mutants/`. T039 extracts the gate-package writer (including the root
    `PACKAGE`) into a shared helper.
  - Hidden tests include only the module's public header and `ctest/ctest.h`. Suite names are `hidden_<x>`.
- **Rules:** fail on the stub head (role test-author), pass on the witness tree, pass on the head (every grade whose
  W or impl change touches the module). Release and san.
- **Redaction:** findings carry only `hidden_id` (the first 12 hex digits of the sha256 of the id), the mode and the
  tree. Reasons and ids stay in `<work>/hidden/`, which only the orchestrator reads. Hidden tests never take part in
  mutation: visible-test adequacy stays a property of the visible tests.
- **Owner option** that closes items 1 and 2 without waiting for B7: an **independent witness author** (decision 1).
  - The test author writes tests and stubs only; a third context writes the witness from the spec, without seeing
    the tests' reasoning.
  - Off-spec tests then fail on the witness (`witness-test-not-pass`), and a minimal witness can no longer be
    shaped to fit weak tests.
  - The cost is one more implementation-sized agent run per module.

## Q5: cost and caching

| Grade (annas-size module, `--uncached`) | Today | With this design |
|---|---|---|
| Test-author (stub head) | head facts and build; tests fail; `mutants` NOT_RUN; verdict FAIL; witness calibrated by hand | head facts and build (unchanged), `tests-stub` 0 extra, witness-tree build about 1,000 actions (estimate: 168 C files, 105 `c_test`s, plus mbedTLS, both modes), witness mutants about 900 compile and 10,000 run actions, about 17 min wall (R004's annas run); `http` would be about 13,000 |
| Implementer | head build and head mutants (about 10,900 actions) | **unchanged**: W = {}, so the witness gates cost one `uquery` (seconds) |
| Strengthening (A032 shape, default role) | head build and head mutants | witness byte-identical to head (bootstrap): **0 extra**, results reused; otherwise plus one witness build and one witness mutation run |
| Audit (bootstrap, periodic) | (not defined) | head mutants of all modules; witness gates reuse the head's results wherever the witness equals the head |

- **Reuse across trees (cached grades).** Action keys use project-relative paths and the same generated
  `.buckconfig`, so every action of the witness tree whose inputs equal the head tree's is an action-cache hit. The
  canary pack relies on the same effect across canary trees. Only the overlaid modules' compiles, the relinks and
  runs of tests that link them, and the witness mutants execute.
- **Identical-tree reuse (all modes, including uncached).** If the overlay leaves every product file byte-identical
  to the head, the witness tree *is* the head tree. `witness-tests` then reuses the head's results and
  `mutants-witness` reuses the head's per-module mutants result for the modules in W (info `witness-equals-head`),
  with zero actions. This is sound because T034 makes mutant results a deterministic function of their inputs, so
  T039 waits for T034.
- **Same-daemon reuse was considered and rejected.** Swapping the witness files into `<work>/tree` after the head's
  gates would let the live daemon skip unchanged actions even when uncached. But it would mutate a tree whose
  manifest is already in the verdict, and couple two gates through daemon state. Each tree keeps its own daemon:
  `witness-tests` and `mutants-witness` share one, killed at the end of `mutants-witness` and again by `rigor grade`'s
  `finally`.
- **Only the witness's direct tests?** Building only `rdeps(W)` targets would skip unaffected targets (mbedTLS and
  `tls_stream` when W = {annas}). It needs an id-to-target map so that unbuilt ids are not reported missing. Left out
  of the first version: the full build is about 10 % of the witness mutation cost, and every expected id judged on the
  witness keeps role test-author simple.
- **`--uncached`** applies to the witness builds exactly as to the head's. A decisive verdict has no cached action
  anywhere: forged witness results could hide survivors (B4), the same threat in the other direction.
  `core.uncached` covers both trees.
- **T030** removes the 120 s LLVM unpack from each fresh uncached build command (it runs a verify action instead). The
  witness tree adds two build commands per decisive grade, so without T030 that is about 4 extra minutes on the
  critical path. T038 and T039 come after T030.

## The gate list and the verdict after this design

`gate/order.txt`, on top of T032's list:
```
clone contract suppressions assemble buckfiles semantic-suppressions symbols build structure mode-divergence
tests-release tests-san tests-stub mutants witness-tests mutants-witness
```
- `tests-stub` comes right after the head's tests (it reads only their results).
- The witness gates come after `mutants`, so that the head's mutants result exists for the identical-tree reuse.
- `witness-tests` needs `assemble` and `buckfiles` PASS (a trustworthy layout), not the head's tests: in role
  test-author those are red by design.

| Gate | Findings (errors unless noted) | NOT_RUN when | Not applicable (PASS, info) |
|---|---|---|---|
| `tests-stub` | `test-passes-on-stub`, `missing-test`, `no-new-tests`; info `stub-timeout` | head build not clean | role is not test-author |
| `witness-tests` | `witness-missing` (L3; info at L2), `impl-missing` (L3; info at L2), `witness-build-failed` (mode, target), `witness-test-not-pass`, `no-assertions`, `missing-test`, `unexpected-failing-test`; info `witness-scope`, `witness-manifest`, `witness-equals-head` | `assemble` or `buckfiles` not PASS | W = {} |
| `mutants-witness` | as `mutants`, with `witness-survived-mutant` (L3+) and info `witness-survivor` (L2) | `witness-tests` not PASS | W has no module at L2+ with a bundle entry |

`core.inputs` gains `witness_sha256` (optional). The role is already bound through `task_sha256`.

## Q6: the task split

Every task follows `AGENTS.md`. Every acceptance includes `selftest/gate.sh`, plus `trajectory_real.sh` where the
orchestrator audits.
- File ownership while T021, T030, T032, T033 and T034 are in flight:
  - T021: `grade.py`, `grade_context.py`, `verdict*`, `approvals.py`;
  - T030: `grade_build.py`, `toolchains/**`;
  - T032: `grade_steps.py`, `grade_pipeline.py`, `grade_checks.py`, `grade_tree.py`, `grade_policy.py`,
    `gate/order.txt`, `selftest/grade.sh`, `selftest/grade_product/**`, `docs/grade.md`;
  - T033: `facts_*`, `products/annas-c/**`;
  - T034: `rules/mutate.bzl`, `mutate/**` except `gen.py`, `selftest/mutate.sh`.
- Dependency order: T036 now; T037 after T021 and T036; T038 after T030 (parallel with T036 and T037); T039 after
  T032, T033, T034, T037 and T038; T040 stacked on `task/T039` and merged in the same merge; T041 after T039 and T040.

### T036: witness bundle, impl paths, scope and stub judge, as a pure library (Sonnet; can start now)
- **Allowed:**
  - new `gate/rigor_lib/witness_bundle.py`, `gate/rigor_lib/witness_scope.py` and `gate/rigor_lib/stub_judge.py`;
  - `gate/rigor_lib/contract.py` (the `role` key only);
  - new `gate/tools/witness.py`;
  - new `gate/tests/test_witness_bundle.py`, `test_witness_scope.py`, `test_stub_judge.py`, `gate/tests/fixtures/witness/**`;
  - `gate/tests/test_contract*.py` (role cases);
  - new `docs/witness.md`.
- **Requirements:**
  1. `witness_bundle`:
     - `load(dir) -> Bundle`: the format above, every defect an `InternalError`, symlinks and special files refused;
     - `digest(bundle)`;
     - `check(bundle, product_name, impl_map)`: each file under exactly one listed module's impl globs, no listed
       module without files;
     - `overlay(head_paths, bundle, modules) -> (kept head paths, witness files)`: a pure function over path lists.
  2. `witness_scope`:
     - `impl_map(policy_table, levels)`: `{label: [globs]}`, with `impl-missing` findings (error at L3, info at L2);
       non-list or empty values are `InternalError`;
     - `test_surface(layout, impl_map, paths)`, taking `grade_mutants.Layout`, which it imports and does not change;
     - `scope(role, changed_paths, layout, impl_map, levels) -> sorted W`, following "Terms".
     - Tests cover:
       - a header-only change;
       - a change only to a test in another package (`util/util_core_test.c` tests `//core:core`);
       - a pure impl change (W = {});
       - role test-author with a stubbed module whose test surface is unchanged;
       - role audit;
       - a new module.
  3. `stub_judge.judge(expected, previous, parsed_by_mode)`: the `tests-stub` findings and metadata above (kinds per
     mode parsed from `reason`). Tests: one case per rule, per fail kind, a pass in san only, and an id missing in one
     mode.
  4. `contract.py`: `role` is one of `implementer` (default when absent), `test-author` or `audit`; anything else is
     `InternalError`; exposed as `Contract.role`.
  5. `gate/tools/witness.py`:
     - `from-commit --repo R --commit C --module LABEL --paths GLOB... [--module ...] --product NAME --out DIR`
       (reads blobs as `grade_tree` does, through `gitrun`);
     - `digest DIR`;
     - `check DIR --product NAME --impl LABEL=GLOB...`.
  6. `docs/witness.md`: the bundle format, the roles, W, and the test-author and orchestrator procedure of Q1, marked
     "not wired yet".
- **Acceptance:** `selftest/gate.sh`. Then, on a scratch git repo of `canaries/_base/product` in
  `/var/tmp/cache/T036`:
  - `witness.py from-commit` for `//core:core` with `core/core.c`;
  - `witness.py digest` twice, identical;
  - `witness.py check` passes, and fails with exit 2 after `ln -s` of a file into `files/`.

### T037: bind the bundle into the verdict (Sonnet; after T021 and T036)
- **Allowed:** `gate/rigor_lib/verdict_inputs.py`, `grade.py`, `grade_context.py`, `approvals.py` (a new kind),
  `gate/tests/test_verdict*.py`, `test_grade_verdict*.py`, `test_approvals*.py`, `docs/witness.md` (the binding
  section).
- **Requirements:**
  1. `rigor grade --witness DIR`:
     - made absolute;
     - snapshotted into `<work>/inputs/witness/` with T021's snapshot rules (copy once, hash the copy, refuse
       symlinks);
     - `g.witness = witness_bundle.load(copy)`, or `None`;
     - a load error is exit 2 before `clone`.
  2. `witness_sha256` is in `INPUT_KEYS` and `OPTIONAL_KEYS` (null without `--witness`). There is a per-input change
     test as T021 has for the others, and a determinism test: the same bundle under two paths gives the same core.
  3. `rigor verify --expect-witness-sha S`: rejects a mismatch and rejects null.
  4. `approvals.KIND_WITNESS_EQUIVALENT_MUTANT = "witness-equivalent-mutant"`, added to `KINDS`.
  5. `prepare_work` also clears `tree-witness` and `witness` (and kills that tree's daemon first).
- **Acceptance:** `selftest/gate.sh`, `selftest/grade.sh` (unchanged steps still green; the grade without `--witness`
  has `witness_sha256: null`).

### T038: the build and mutants steps run on a given tree (Sonnet; refactor only; after T030)
- **Allowed:** `gate/rigor_lib/grade_build.py`, `grade_mutants.py`, `mutants_gate.py` (only an `approval_kind`
  argument, defaulting to `equivalent-mutant`), `gate/tests/test_grade_build*.py`, `test_grade_mutants*.py`,
  `test_mutants*.py` (only for the new argument).
- **Requirements:**
  1. A `TreeRun` (tree, work subdirectory, results dir, test-results dir, mutants-reports dir, report-file prefix,
     `built` dict) replaces the direct use of `g.tree`, `g.work`, `g.test_results` and `g.built` in `build_mode`,
     `build_gate`'s core, `read_layout`, `write_package`, `build_reports` and `judge`. The existing gates construct
     the head `TreeRun`.
  2. `judge` takes the approval kind and a rule rename map (empty for the head).
  3. No behaviour change: same file names, findings and metadata keys.
- **Acceptance:** `selftest/gate.sh`; `selftest/grade.sh`, reporting that `core.gates` of every step is identical
  before and after (compare `gates` rather than `core_sha256`, which contains `gate_sha`).

### T039: the witness gates (Sonnet, Opus line review; after T032, T033, T034, T037, T038)
- **Allowed:**
  - new `gate/rigor_lib/grade_witness.py`;
  - `grade_pipeline.py`, `gate/order.txt` (only `witness-tests` and `mutants-witness`, after `mutants`);
  - `grade_tree.py` (assembly with an overlay: the product-file source becomes a parameter);
  - `grade_steps.py` (`assemble_gate` calls the shared assembly);
  - `grade_policy.py` (load `impl`, drop it from the symbols copy);
  - `grade_mutants.py` (extract the gate-package writer for reuse by `gate-hidden`);
  - `products/selftest/policy.toml` and `products/annas-c/policy.toml` (`impl` keys only);
  - `selftest/grade.sh`, `selftest/grade_product/**` (a witness bundle fixture);
  - `gate/tests/test_grade*.py`;
  - `docs/grade.md`, `docs/witness.md`;
  - `plan/backlog.md` (B27: witness half).
- **Requirements:**
  1. `witness-tests` and `mutants-witness` exactly as in "The gate list", for roles implementer and audit. Role
     test-author is not accepted yet: a grade with it is exit 2 "role test-author needs T041", so it can never pass
     early.
  2. W from `witness_scope.scope` over the head layout and `git diff --name-only merge_base head` in the clone.
  3. The witness tree is assembled from the clone at H plus the bundle **snapshot**. It gets its own manifest
     (`witness-manifest` info) and its own daemon. Both builds and the mutants build pass `--no-remote-cache` under
     `--uncached`.
  4. Identical-tree reuse as in Q5, with info `witness-equals-head`.
  5. Findings carry no source text from the witness (Q1, point 4).
  6. Head behaviour is unchanged when W = {}: report the executed and cached action counts of an implementer-shaped
     selftest step with and without `--witness`.
  7. `selftest/grade.sh` steps:
     - red: a witness that fails a test;
     - red: a witness survivor (the R003 W4 shape);
     - red: W non-empty without a bundle entry;
     - green: a test-surface change with a strong witness;
     - green: a pure impl change with a bundle, where the witness gates are not applicable;
     - green: a witness identical to the head (0 witness actions, cold and warm counts reported).
  8. Report the annas-c effect (information only, scratch clone in `/var/tmp/cache/T039`): an audit grade of annas-c
     main with a bootstrap bundle from `witness.py from-commit`. Report W and the actions executed.
- **Acceptance:** `selftest/gate.sh`, `selftest/grade.sh`, and `selftest/canaries.sh` **from `task/T040`** (the pack
  is only green with T040 on top).

### T040: the witness canaries (Sonnet; branch from `task/T039`; merged together with T039)
- **Allowed:**
  - `canaries/runner.py` (`--witness`: `canaries/<id>/witness/` if present, else `canaries/_base/witness/`);
  - new `canaries/_base/witness/**` (core and util, equal to the base sources);
  - new `canaries/witness-survivor/`, `canaries/witness-test-fails/`, `canaries/witness-missing/`,
    `canaries/witness-green/`;
  - every `canaries/*/policy.toml` (adding `impl` only, mechanically);
  - `canaries/*/expect.json` (only `fail` and `not_run` entries caused by the two new gates, each listed in the
    report with the reason);
  - `gate/tests/test_canaries_runner.py`, `docs/canaries.md`.
- **Canaries** (R003's two names and two more):
  - `witness-survivor`:
    - head: `core_test.c` loses the positive `core_sign` checks, and head `core.c` drops the `> 0` branch;
    - witness: base `core.c`;
    - expected: `mutants-witness: [witness-survived-mutant]` and nothing else (head `mutants` PASS proves G1 was
      open).
  - `witness-test-fails`:
    - head: adds a strong `core_add(1, 1) == 2` check;
    - witness: `core_add` returns `a + b + 1`;
    - expected: `witness-tests: [witness-test-not-pass]`, `not_run: [mutants-witness]`.
  - `witness-missing`: a core test-surface change with a canary bundle that lacks `//core:core`. Expected:
    `witness-tests: [witness-missing]`, `not_run: [mutants-witness]`.
  - `witness-green`: `"control": true`, a strong new core test plus the base witness. It must PASS, which proves
    that the gates can pass.
- **Acceptance:**
  - `selftest/canaries.sh`: 0 live misses, every gate in `order.txt` the expected failing gate of some live canary;
  - the wall-time change of the pack reported;
  - each changed `expect.json` justified line by line.

### T041: the stub check and the test-author role (Sonnet; after T039 and T040)
- **Allowed:**
  - `grade_pipeline.py`, `gate/order.txt` (`tests-stub` after `tests-san`);
  - `grade_steps.py` (`tests_gate_for` takes the role);
  - `tests_gate.py` (an option that leaves statuses unjudged: presence, duplicates and parse problems are still
    checked);
  - `grade_mutants.py` (role test-author: not applicable);
  - `grade_witness.py` (W for role test-author; `no-new-tests`);
  - `selftest/grade.sh`, `selftest/grade_product/**`, `gate/tests/test_grade*.py`, `gate/tests/test_tests*.py`;
  - new `canaries/stub-passes-test/` and `canaries/stub-green/`;
  - `canaries/runner.py` (only if the previous list needs plumbing);
  - `docs/grade.md`, `docs/witness.md`;
  - `plan/backlog.md` (close B27).
- **Requirements:**
  1. `tests-stub` as in Q2. Role test-author without `expected-tests.previous.json` is exit 2. The "needs T041" refusal
     from T039 is removed.
  2. In role test-author:
     - `tests-release` and `tests-san` judge presence, but not status;
     - head `mutants` is not applicable;
     - W also contains the modules whose impl changed;
     - the witness gates are required (W = {} there is `no-new-tests` or `witness-missing`, never a PASS).
  3. `selftest/grade.sh` steps:
     - green: a stub head with a correct witness;
     - red: a new test that passes on the stub in release;
     - red: a new test that passes in san only;
     - green: a timeout stub (the test still fails on the stub; info `stub-timeout`);
     - red: no new ids;
     - green: old tests failing on a stubbed function, with a witness that passes them (the A018 shape).
- **Canaries:**
  - `stub-passes-test`:
    - role test-author; new function `core_pos`;
    - the shipped stub *is* the correct body, the new test is strong, and the witness is the same body;
    - expected: `tests-stub: [test-passes-on-stub]` only.
  - `stub-green`: `"control": true`, role test-author, a sentinel stub, a strong test, a correct witness.
- **Acceptance:** `selftest/gate.sh`, `selftest/grade.sh`, `selftest/canaries.sh`.

### Orchestrator steps (not contributor work)
1. After T039 and T040 merge:
   - create `c-rigor-hidden` (local, private), with `annas-c/witness/` produced by `gate/tools/witness.py from-commit`
     at annas-c main for every L2+ module, using the `impl` keys T039 put in `products/annas-c/policy.toml`;
   - grade annas-c main once with `role = "audit"`, uncached, and record the cost.
2. From then on, every decisive annas-c grade passes `--witness`, and the merge bot passes `--expect-witness-sha`.
3. After T041, change the annas-c test-author task template (`A<NNN>-*-tests`) to:
   - `role = "test-author"` in the contract;
   - the witness in bundle layout in `/var/tmp/cache/A<NNN>/witness/`;
   - acceptance by a cached `rigor grade --witness` against a scratch products copy (Q1, point 1);
   - the report lists the new ids, the stub fail kinds and the witness verdict, and never the witness code.
4. Strengthening tasks (A032 shape) keep the default role. Their witness is the bundle entry, kept equal to main's
   `src/` when nothing better exists; the identical-tree reuse makes that free.

## Decisions that need the owner

1. **Who writes the witness for L3 modules.**
   - The test author (phase-1 default, no extra runs): leaves S7b and the minimal witness to B7.
   - An independent third context: closes both now, at about one implementation-sized run per module.
   - Recommendation: the test author by default; independent witnesses for `annas` and `http` (secrets, files,
     hostile input) and for any new L3 module.
2. **Hidden-repo infrastructure.** A local private `c-rigor-hidden` now (no network). Whether it becomes a private
   GitHub repository, and that orca-dev sandboxes must never mount it (B5), are owner and infra calls.
3. **No `stub-pass` approval kind.** Recommended; confirm. Adding one later is a loosening.
4. **The `witness-equivalent-mutant` approval kind** (a new loosening kind, signed by the same key). Confirm that it
   exists and is separate from `equivalent-mutant`.
5. **Cost.** A decisive test-author grade of an annas-size module costs about one extra mutation run (about 17 min,
   about 11,000 actions) on the shared farm, uncached. The recommendation is to keep it uncached while B4 is open.
   The alternative is a cached test-author grade, with only implementer grades decisive; that is weaker, because a
   forged cache could hide witness survivors.
6. **The bootstrap witnesses for existing annas-c modules** come from main's `src/`, so there is no G1 gain for
   them. The alternative is to commission independent witnesses for the already-merged L3 modules (`core`, `json`,
   `url`, `fsname`) as well. Recommendation: bootstrap now, and commission only where decision 1 applies.

## Known limits of this design
- The witness proves the tests pin the witness, not the spec (Q4, items 1 to 3). B7 and decision 1 are the answers.
- Dependency drift after a witness grade is re-checked only by `audit` grades (Q3).
- In phase 1, secrecy is by detection (trajectory rules); enforcement needs B5.
- The witness tree is built from the whole product in both modes. The `rdeps(W)` narrowing is deferred (Q5).
- Mutants run in release only, for the witness as for the head (`docs/mutate.md`). Out-of-bounds survivors in the
  witness (R004 `name.c:61` class) stay invisible until a san mutant pass exists.
