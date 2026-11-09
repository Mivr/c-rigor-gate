# T124: schema mutation engine, prototype and measurement (P003 W1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T124` from main (`plan/P003-gate-v2.md` is on main). Read P003 §5 in full, then
`docs/mutate.md` ("Pipeline", "Batched actions", "Verdicts"), `mutate/gen.py`, `mutate/tool.py`, `rules/mutate.bzl`.

## Why (measured, `business-apps/plan/metrics/lead-time-2026-11-09.md`)
Mutation testing is 49% of agent wall time and waiting on gate jobs 23%. Step 4 `mutant_run` relinks every test with
every mutated object and runs it in a fresh process. P003 §5 proposes: one **schema object** per source with every
mutant switchable at run time, each test linked **once**, one `fork()` per mutant, and only for the tests that
**reach** the mutant. This task builds that run stage as a prototype **beside** the v1 engine and measures both. It
decides whether P003 W2 is built. Nothing here changes a verdict or `rigor grade`.

## Do
1. **Schema generator** (`mutate/schema.py`, stdlib only). Input: a source file and the mutant list `mutate/gen.py`
   already writes for it (same mutants, same content-bound ids; do not fork or reorder `gen.py`'s list). Output: one
   schema source plus a table `index -> mutant id`.
   - Expression mutants: `(rigor_hit(N) ? (mutated) : (original))`. Statement deletion: `if (!rigor_hit(N)) { ... }`.
     Function-body mutants: `if (rigor_hit(N)) { return <default>; }` at the start of the body.
   - `rigor_hit(N)` records that mutant N's site was executed (the reach bitmap) and returns whether N is active.
   - **Eligibility** comes from the AST parent, never from text. Not eligible, with a reason code each: a mutation in
     a constant-expression context (case label, array bound, `_Static_assert`, static or file-scope initializer), a
     string literal initialising an array, a mutant whose replacement changes the expression's type so that the
     conditional does not compile, and two mutants whose byte ranges overlap partially. For nested ranges, wrap the
     inner one inside the outer one's `original` arm. If a whole schema source does not compile, find the offending
     mutants by bisection, mark them `schema-unviable`, and say how many.
   - Only mutants that v1 would run (viable, not `equivalent`, not `duplicate`) go into the schema.
2. **Runtime** (`mutate/schema_rt.c`, `mutate/schema_rt.h`; C17, no allocation, compiled with the sealed flags).
   `rigor_hit`, the active id, the reach bitmap, and a `main` wrapper (`-Wl,--wrap=main`; do **not** edit `ctest/`):
   - mode `reach`: run the real `main` once with no mutant active; write the results file and the reach set;
   - mode `kill`: for each mutant id in a list file, `fork()`, activate it in the child, run the real `main` with its
     own results file, and wait in the parent under the adaptive limit of T122 (`clamp(20 x baseline, 5 s, 180 s)`) and
     the ctest resource limits. One record per (mutant, test binary): the same fields v1's `linkrun` records.
3. **Buck2 rule** `c_mutants_schema` in a **new** file `rules/mutate_schema.bzl`. Per source: one schema compile with
   the module's exact compile command. Per test: one link against the schema objects and the runtime, one `reach`
   action, one `kill` action over the mutants that test reached. A mutant no test reaches is recorded `unreached` and
   not run. No cross-test "stop at first kill" in this prototype; report what it would have saved. If you need a
   private helper of `rules/mutate.bzl`, export it there by **appending** a public name; change nothing else in it.
4. **Comparison** (`mutate/schema_compare.py`). From a v1 `report.json` and the schema results of the same module:
   for every schema-eligible mutant the v1 class (`killed-assert`, `killed-crash`, `survived`) against the schema
   class. Every disagreement is listed with file, line, operator and both records.
5. **Measure** and write `plan/metrics/schema-engine-proto-2026-11.md`:
   - on the mutate selftest modules, and on five business-apps modules in the product clone the orchestrator prepared
     at `/var/tmp/cache/T124/ba` (`lib/ds/fmap`, `lib/fmt/jpull`, `apps/lockers/relay/frame`, `apps/lockers/lk/audit`,
     `lib/io/posix_fs`). That clone is scratch: you may write generated `BUCK` packages into it; never commit there.
     Its `gate/` directory is a clone of this repo: bring it to your branch with
     `git -C /var/tmp/cache/T124/ba/gate fetch -q /var/tmp/wt/c-rigor-gate/T124 task/T124 && git -C /var/tmp/cache/T124/ba/gate checkout -q --detach FETCH_HEAD`
     (commit first). Build from `/var/tmp/cache/T124/ba` with `gate/tools/buck2`.
   - per module, v1 against schema, both with `--no-remote-cache`: executed actions, summed action wall and CPU
     seconds (from the event log or `buck2 log what-ran`), build wall time; mutants total, eligible, not eligible by
     reason, `schema-unviable`, `unreached`; class disagreements.
   - one paragraph: go or no-go for P003 W2, and which numbers decide it.
6. Unit tests (`gate/tests/test_mutate_schema*.py`) for eligibility, nesting, bisection and the comparison; a selftest
   `selftest/mutate_schema.sh` that builds the schema engine for the mutate selftest modules twice and requires
   byte-identical results and **zero unexplained class disagreements** with v1 on them. Add its `tools/affected.toml`
   rules. Document the design and its limits in `docs/mutate-schema.md`.

## Not in this task
Wiring into `rigor grade` or `rigor mutants`; the confirm pass, the sanitizer pass, `equivalent-proved`; any change to
`mutate/gen.py`, `mutate/tool.py`, `ctest/**`, `gate/rigor_lib/**` or `products/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/mutate.sh` (unchanged, still passes); `selftest/mutate_schema.sh`
twice in a row; `python3 -I tools/affected.py --check`; the metrics file with real numbers. A disagreement on a
business-apps module does not fail the task: list it and explain it.

## Allowed paths
`mutate/schema*`, `rules/mutate_schema.bzl`, `rules/mutate.bzl` (appended exports only), `selftest/mutate_schema.sh`,
`selftest/mutate_schema/**`, `gate/tests/test_mutate_schema*.py`, `docs/mutate-schema.md`,
`plan/metrics/schema-engine-proto-2026-11.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T124`. `TMPDIR=/var/tmp/cache/T124/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs (your own `/var/tmp/cache/T124` is yours); never search from `/` or `/var/tmp`. Do not print the
environment. Kill only your own buck2d by pid. One buck2 build at a time. The RE farm is shared: measure each module
once, not in a loop. Never end your turn while a job you started is running. Commit on `task/T124`; your last message
is the report (what you built, the table, every deviation, and anything you could not do).
