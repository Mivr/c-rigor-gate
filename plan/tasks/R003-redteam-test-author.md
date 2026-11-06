# R003: test-adequacy audit of the gate (does it catch weak tests?) (Opus)

Repo: `Mivr/c-rigor-gate` (read-only for you; findings go in your report). Scratch and your sample product live under
`/var/tmp/cache/R003/`. Read `AGENTS.md`, `docs/grade.md`, `docs/mutate.md`, `docs/canaries.md`, the annas-c
`plan/phase1.md` (the two-context rule: a test author writes header, BUCK, tests, stubs and a witness; an implementer
writes `src/` only), and `/var/tmp/cache/R003/R002-redteam.md` for the method used on the implementer side.

## Question
The gate's guarantee rests on the visible tests being strong. Mutation testing is meant to catch weak tests. Measure
how well it does: for a small L3 sample module with a correct implementation, write test suites with known
weaknesses and grade each one with `rigor grade` on a local product, as R002 did.

## Weak-test patterns to measure (one suite each, same correct implementation)
1. Assertions that only check "returns without crashing" or a non-null result.
2. Assertions that compare the function's output with itself, or with a value computed by the same code.
3. Boundary values missing (only mid-range inputs; no 0, max, overflow, empty, off-by-one).
4. Only one branch of each decision exercised.
5. Tests that kill mutants only through a crash or a timeout rather than an assertion.
6. A header contract looser than the spec (an extra hook or a lower level than the spec asks) that the tests don't pin.
7. A stub that already passes some tests; a witness that differs from the spec but agrees with the tests.

## Report
For each suite: the commit, the verdict, which gate and rule flagged it (or none), and whether that is the right
outcome. For each pattern the gate does not flag: severity, a minimal repro, and a fix sketch (allowed paths, the rule,
a canary). Also list what worked. Write it to `/var/tmp/cache/R003/redteam.md`. Stay on the farm and in your cache.
