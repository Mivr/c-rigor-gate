# R003: does the gate's mutation testing catch weak unit tests?

## What I measured
- **Gate:** `/var/tmp/cache/R003/gate` at main `ca91e2a`, after a `git pull`. I added one local commit, `977746d`, with
  `products/r003/` (`product.toml`, `policy.toml` with `//sat:sat` at L3, `expected-tests.json`, `tasks/author.toml`
  allowing `sat/**`). It was never pushed. T028 (macro-hidden code, `bool`) is **not** merged on this main.
- **Product:** `/var/tmp/cache/R003/product`, one L3 module `sat`:
  - `sat_parse_u16`: decimal to `uint16_t` with an enum status;
  - `sat_add`: saturating add;
  - `sat_count_digits`;
  - `sat_status_name`: a `switch` that returns string literals;
  - `sat_span`: returns a struct;
  - plus a static `is_digit`.

  Each suite is a branch off base `fd07ea0` (which holds only `sat/README.md`). Unless a row says otherwise, the
  implementation is the correct one (`suites/impl_correct.c`). Inputs are in `/var/tmp/cache/R003/suites/`.
- **Commands:** `mk.sh` builds a branch and `grade.sh <branch> <label>` runs a cached `gate/rigor grade`, capped by
  `timeout 900`. Verdicts are in `runs/<label>.json`, results in `work/<label>/results/`, and
  `python3 summary.py <label>` prints the survivors per function. Every grade took 15 to 226 s. Nothing was uncached;
  no cache forgery is involved, so cached verdicts answer the question.

## Per-suite results
| # | suite / pattern | commit | verdict | flagged by (gate: rule) | right? |
|---|---|---|---|---|---|
| S0 | strong control (tagged struct, `struct sat_span` prototype) | `4e79b9c35c68` | PASS (58 mutants: 46 assert, 1 crash, 1 equivalent, 9 duplicate, 1 unviable) | none | yes |
| S0' | same tests, `typedef struct {..} sat_span_t` return | `9bfd0331c0f7` | FAIL | mutants: `no-assert-kill-function` on `sat_span` | **no** (false positive, G5) |
| S0'' | same, `typedef struct sat_span {..} sat_span_t` return | `6cb3f9edc406` | FAIL | mutants: `no-assert-kill-function` on `sat_span` | **no** (G5) |
| S1 | 1: only "no crash", non-NULL or in-range checks | `07db361c8982` | FAIL | mutants: `survived-mutant` x39 | yes overall; but `sat_status_name` has **0** survivors with only `!= NULL` checks (G3), and `sat_span` has no mutants (G4) |
| S1s | 1 on a struct return: S0, but `sat_span` only called (`CHECK(t, 1)`) | `3d0f747bca8b` | **PASS** | none | **no** (G4) |
| S1s-w | S1s plus a *wrong* `sat_span` (`ptr = s + len`) | `04f67df6f51a` | **PASS** | none | **no** (G4) |
| S2 | 2: oracle is the code itself (same call twice, expectation computed by the function) | `eb441a6b0196` | FAIL | mutants: `survived-mutant` x47 (all live mutants) | yes |
| S3 | 3: exact values, mid-range inputs only | `a788b6dea381` | FAIL | mutants: `survived-mutant` x13 | yes |
| S3n | 3 on NULL: S0 without the `out == NULL` cases | `c06ee4e74bd9` | **PASS** | none | **no** (G2) |
| S3n-w | S3n plus an implementation that **drops** `out == NULL` | `876f01e9c54f` | **PASS** | none | **no** (G2, G1) |
| S4 | 4: only one side of each decision (happy paths) | `b18d2b7b8724` | FAIL | mutants: `survived-mutant` x15 | yes |
| W4 | S4 tests plus a witness without any error handling or saturation | `26c62c20c679` | **PASS** (14 mutants, all assert-killed) | none | **no** (G1) |
| S5a | 5: every value checked by a NULL-deref crash, one `CHECK(t, 1)` per test | `782b8b3b4292` | FAIL | mutants: `crash-only-function` x5 | yes |
| S5b | 5a plus one real CHECK per function inside the same tests | `dde484b0189e` | FAIL | mutants: `crash-only-function` x5 | yes, though by accident: a later crash in the same forked test hides the failed CHECK (note under G6) |
| S5c | 5a plus one *separate* test with one real CHECK per function | `6ff98da47c2a` | **PASS** (28 of 47 live mutants killed only by crash) | none | debatable; low (G6) |
| S6a | 6: header adds `extern int (*sat_skip_hook)(char)`, honest impl honours it, tests never set it | `135e2678c6a3` | **PASS** | none | **no** (G7, G2) |
| S6b | 6: header loosened to "OK versus not OK" and "non-NULL name"; tests pin only that; impl follows the spec | `cd4b66d832f3` | **PASS** | none | **no** (G3) |
| S6c | 6: header defines `sat_add` as `static inline` | `0ee74359671e` | FAIL | mutants: `unmutated-function` (`sat_add`) | yes |
| S7a | 7: test-author commit with stubs, 3 of 8 tests pass on the stubs | `bf94403cc876` | FAIL | tests-release/tests-san: `test-not-pass` x5; mutants NOT_RUN | yes for the commit, but the 3 tests that pass on stubs show up only as info `unexpected-test`; there is no fail-on-stub rule (G1) |
| S7b-c | 7: tests follow a witness that differs from the spec (`"99999x"` gives DIGIT, length > 5 gives RANGE); correct impl | `560cff4169e0` | FAIL | tests-release/tests-san: `test-not-pass` (`sat/parse`) | wrong party: the spec-correct implementer fails |
| S7b-w | the same tests with the off-spec witness | `2821e417349d` | **PASS** | none | **no** (spec divergence is invisible, G1) |

On level: a test author cannot lower a module's level. `policy.toml` is owned by the gate, and a new
`c_library` without a level is `level-missing` (`grade_mutants.py:142`). I did not grade this; it is reasoned
from the code. Moving code into the header is caught (S6c, and the live `hollow-module` canary).

## Patterns the gate does not flag

### G1 (HIGH): mutation testing rates the tests only against code the implementer chose to write
A weak suite is flagged only when the graded implementation contains the code the tests don't pin. If the
implementation leaves that code out, nothing survives:
- **Repro:**
  - S4's happy-path tests FAIL with the correct implementation (15 survivors), but the witness without any
    error handling or saturation PASSES (W4 `26c62c20c679`).
  - The same holds for NULL (S3n-w `876f01e9c54f`).
  - Off-spec tests PASS their off-spec witness while the spec-correct implementation FAILS (S7b-w and S7b-c).
- **Effect:** an implementer facing weak tests is rewarded for deleting spec-required code, not for reporting
  the tests.
- **Stubs:** nothing checks that tests fail on the stubs. In S7a three tests pass on stubs and show up only as
  info `unexpected-test`; once they are in `expected-tests.json`, they are silent.
- **Fix sketch** (gate task "grade the tests against a gate-held witness and the stubs"):
  - At implementer grading, the gate also runs the mutants step with `src/` replaced by the orchestrator's
    witness (kept out of reach, like hidden tests). Any survivor there is `witness-survived-mutant`: the visible
    tests are weak no matter what the implementer wrote.
  - At test-author grading, every expected test must fail on the committed stubs (`test-passes-on-stub`).
  - **Limit:** spec divergence that the witness shares with the tests (S7b) still needs spec-derived hidden
    tests (B7).
  - **Allowed paths:** `gate/rigor_lib/grade_pipeline.py`, `grade_steps.py`, `grade_tree.py`,
    `grade_mutants.py`, new `gate/rigor_lib/grade_witness.py`, `gate/order.txt`, `gate/tests/test_grade*.py`,
    `selftest/grade.sh`, `canaries/runner.py` (a `witness/` dir per canary), `docs/grade.md`, `plan/backlog.md`.
  - **Canaries:**
    - `witness-survivor`: the witness's `core_sign` has a `> 0` branch that the head's tests never reach.
      Expected: `mutants-witness: witness-survived-mutant`.
    - `stub-passes-test`: the stub `core_sign` returns `1`, and a test checks only `core_sign(9) == 1`.
      Expected: `tests-stub: test-passes-on-stub`.

### G2 (HIGH, not covered by T028): a `NULL` in a condition hides the whole condition from mutation
- **Cause:** `gen.py` drops every node whose range touches a macro expansion. `NULL` is a macro, so
  `if (s == NULL || out == NULL)` gets no `relational`, `logical` or `condition` mutant. Only the `return` inside
  is mutated (S0 report: line 7 has none, line 8 has one `return-value` mutant). One NULL test kills that mutant.
- **Repro:**
  - S3n (`c06ee4e74bd9`): `out == NULL` never tested, PASS.
  - S3n-w (`876f01e9c54f`): the `out == NULL` check deleted from the code, PASS.
  - The same effect hides the `sat_skip_hook != NULL && ...` operators in S6a.
- **Scope:** T028 explicitly exempts system macros (`NULL`, `true`, `INT32_MAX`, ...) from its new
  `macro-hidden-code` finding, so this stays open after T028. Exposure in annas-c: 249 `== NULL` / `!= NULL` in
  43 `src` files, 181 of them in `if` / `while` conditions.
- **Fix:**
  - In `annotate`, treat a location whose `spellingLoc` is under a `--system-root` and whose `expansionLoc` is a
    main-file token of an object-like macro as plain. Use the expansion's offset and `tokLen`, so `s == NULL`
    has a main-file span.
  - Mutants still only rewrite main-file bytes around the macro token, never inside it.
  - Product-defined macros stay skipped (T028's finding).
- **Allowed paths:** `mutate/gen.py`, `gate/tests/test_mutate_gen.py`, `gate/tests/fixtures/mutate/**`
  (a new `null_guard.c` with its AST), `docs/mutate.md`, new `canaries/null-guard/`.
- **Canary `null-guard`:** `edit.sh` adds `int core_pick(const int *a, const int *b)` with
  `if (a == NULL || b == NULL) { return -1; } return *a;`, tested only with `a == NULL` and a valid pair.
  Expected: `mutants: survived-mutant`.

### G3 (MED-HIGH): enum constants and string literals are never mutated, so "it failed" / "non-NULL" checks pass L3
- **Cause:** the only mutants of `return SAT_ERR_RANGE;` and `return "range";` are `(T)0`, meaning `SAT_OK` or
  NULL. A test that checks `!= SAT_OK` or `!= NULL` kills them. An enumerator is never swapped for another, and
  a string literal is never changed.
- **Repro:**
  - S6b (`cd4b66d832f3`) PASS, with no test pinning which error or which name.
  - In S1 (`07db361c8982`), `sat_status_name` had 0 survivors with only `!= NULL` checks.
- **Pattern 6:** this is the mechanical half of pattern 6 (a header looser than the spec). The other half,
  "`*out` unspecified on error", is review or hidden-test work (B7).
- **Fix** (new operators in `gen.py`, listed in docs/mutate.md):
  - `enum-constant`: a `DeclRefExpr` to an `EnumConstantDecl` (return, assignment, argument) becomes the next
    enumerator of the same `EnumDecl`, found in the AST. Skip it under `case` labels, as now.
  - `string-literal`: `"x"` becomes `""`, and `""` becomes `"?"`.
  - `char-literal`: `'c'` becomes `'c' + 1`.
- **Allowed paths:** `mutate/gen.py`, `gate/tests/test_mutate_gen.py`, `gate/tests/fixtures/mutate/**`,
  `docs/mutate.md`, new canaries.
- **Canaries** (both `mutants: survived-mutant`):
  - `weak-error-code`: `enum core_kind { CORE_ZERO = 1, CORE_OTHER = 2 }`, returned from a `switch`, and a test
    that checks only `!= 0`.
  - `weak-string`: `const char *core_sign_name(int)` returns literals from a `switch`, and a test that checks
    only non-NULL.

### G4 (MED): a function that returns a struct and has no operators can be untested, or wrong, and pass L3
- **Cause:** struct and union returns get no `function-body` and no `return-value` mutant. A body of plain
  assignments has nothing else to mutate. The function is reported only as info `no-mutable-token`.
  Pointer `+` and `-` are not mutated either (`pointerish`).
- **Repro:**
  - S1s (`3d0f747bca8b`): `sat_span` only called, PASS.
  - S1s-w (`04f67df6f51a`): a wrong `span.ptr = s + len`, PASS.
- **Fix:**
  - For struct and union returns, `function-body` becomes `{ (void)p; ... return (T){0}; }` and `return-value`
    becomes `((void)(e), (T){0})`. T is the return type text from the declaration; this also fixes G5.
  - At L3, `no-mutable-token` becomes an error for any function that returns a value or takes a non-const
    pointer.
- **Allowed paths:** `mutate/gen.py`, `gate/rigor_lib/mutants_verdict.py`, `gate/rigor_lib/mutants_gate.py`,
  `gate/tests/test_mutate*.py`, `gate/tests/test_mutants*.py`, `gate/tests/fixtures/mutate/**`, `docs/mutate.md`.
- **Canary `struct-return-untested`:** `struct core_pair core_pair(int a, int b)`, a test that only calls it.
  Expected: `mutants: survived-mutant`.

### G5 (LOW-MED, fails closed, a gate false positive): a typedef'd struct return gets mutants that cannot compile
- **Cause:** `return_class` reads the function type as written (`sat_span_t (const char *, size_t)`), so it
  emits `function-body ... return 0;`, which is unviable.
  - For an anonymous `typedef struct {..}`, it also emits `return-value (sat_span_t)0`, also unviable.
  - When these are the function's only mutants, the strongly tested function gets `no-assert-kill-function`.
- **Repro:** S0' `9bfd0331c0f7` and S0'' `6cb3f9edc406`, identical strong tests, both FAIL. The only honest
  way out is to spell `struct sat_span` in the header prototype (S0).
- **Side effects:** these unviable mutants also count toward `unviable-ratio`. annas-c returns typedef'd
  structs (for example `core_str_t`).
- **Fix:** resolve typedefs through the AST's `TypedefDecl` nodes in `return_class` and `returned`. Better,
  make it part of G4.
- **Allowed paths:** as G4.
- **Canary:** a green fixture in `selftest/mutate.sh`: `typedef struct { int a; } core_box_t;
  core_box_t core_box(int a)` with a strong test, and no `no-assert-kill-function`.

### G6 (LOW): one assert-kill per function hides a suite whose oracle is mostly crashes
- **Cause:** `crash-only-function` fires only when a function has no assert-kill and no survivor.
- **Repro:** S5c (`6ff98da47c2a`) checks every value by dereferencing NULL, plus one separate test with one
  CHECK per function. It PASSES with 28 of 47 live mutants killed only by crash; S0 has 1 of 47.
- **Why low:** a crash on mismatch is still an oracle. But crash kills that come from out-of-bounds access in
  release mode depend on memory layout, and the diagnostics are lost.
- **Note:** a failed CHECK followed by a crash in the same test is classified as a crash (S5b). That is correct
  behaviour of `outcome_of_run`, but it means a suite that mixes checks and crash helpers in one test reads as
  crash-only.
- **Fix:** a `crash-kill-ratio` finding at L3 when more than 50 % of a function's live mutants (not equivalent,
  not duplicate, not unviable) are killed only by crash. The threshold must be calibrated on annas-c first.
- **Allowed paths:** `gate/rigor_lib/mutants_gate.py`, `gate/tests/test_mutants*.py`, `docs/mutate.md`.
- **Canary `crash-oracle`:** `core_test.c` checks `core_sign` with `if (core_sign(-5) != -1) { *(volatile int *)0 = 1; }`,
  plus one separate CHECK test. Expected: `mutants: crash-kill-ratio`.

### G7 (MED): a header can add an unpinned global hook and still pass L3
- **Cause:** S6a declares `extern int (*sat_skip_hook)(char)` and the honest implementation honours it.
  - The only mutant on the hook line is the whole-condition flip, and the default path kills it.
  - `!= NULL` and `&&` are unmutated (G2).
  - No rule covers a writable object with external linkage.
- **Effect:** any linked code can redirect parsing, and no test pins what the hook does.
- **Repro:** S6a (`135e2678c6a3`) PASS.
- **Fix:**
  - A gate-owned export list per module in `policy.toml` (`exports = ["sat_parse_u16", ...]`, written by the
    orchestrator from the spec). The symbols gate checks it against the facts' defined global symbols:
    `unexpected-export`, error at L3.
  - Also `mutable-global-export` for a writable data symbol with external linkage at L3.
  - G2's fix then also exposes the hook's untested operators.
- **Allowed paths:** `gate/rigor_lib/facts_symbols.py`, `gate/rigor_lib/facts_policy.py`,
  `gate/rigor_lib/grade_policy.py`, `gate/tests/test_facts*.py`, `docs/` (symbols section),
  `products/*/policy.toml` (orchestrator only), new `canaries/extra-hook/`.
- **Canary `extra-hook`:** `edit.sh` adds `int (*core_hook)(int) = 0;` to `core.c` and the extern to `core.h`,
  and uses it in `core_sign`. Expected: `symbols: unexpected-export`.

## What worked
- **Plain weak assertions:** "no crash" (S1), self-comparison oracles (S2), missing boundaries (S3) and one
  branch only (S4) are all caught by `survived-mutant` when the implementation has the code. The survivor list
  names each untested line exactly (`summary.py`).
- **Crash-only oracles** (S5a) are caught by `crash-only-function` on every function.
- **Logic in the header** (S6c) is caught by `unmutated-function`, and `hollow-module` is live. The level cannot
  be lowered by the test author: the policy is gate-owned and a new library is `level-missing`.
- **Stubs:** a stub commit fails `test-not-pass` and later gates are NOT_RUN (S7a). The pipeline fails closed.
- **Equivalence:** TCE handled the only semantically equivalent mutant in S0. Duplicates and unviable mutants
  stayed low (9 and 1 of 58), so a carefully written honest module reaches zero survivors without approvals.
- **Caching:** every re-grade after a test-only change re-ran only the live mutants (32 to 110 s).
