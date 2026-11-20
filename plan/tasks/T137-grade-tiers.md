# T137: grade tiers: report-only mutation runs in the nightly tier, not at merge (P003 §9, W10 part 1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T137` from main. Read P003 §5.6, §8 and §9, `docs/grade.md` ("Mutation testing in
the pipeline", "Verdict determinism and bound inputs", "`rigor verify`", "`--uncached`"), `gate/rigor_lib/grade.py`,
`grade_mutants.py`, `grade_witness.py`, `mutants_gate.py`, `verdict_inputs.py`, `verdict.py`, `profiles.py`
(`required`), and `plan/metrics/schema-engine-proto-2026-11.md`.

## Why
Mutation is the largest machine cost of a grade, and part of it cannot change a verdict: at L2 a surviving mutant is
an info finding. In the T124 measurement one L2 adapter (`lib/io/posix_fs`) cost about ten times each of the four
other modules (3,828 s of execution against 92 to 456 s). The owner accepted a scoped merge grade with a blocking
nightly grade (P003 D2). This task adds the two tiers and moves report-only mutation to the nightly one. The default
stays today's behaviour, so nothing changes for an existing caller.

## Do
1. **`rigor grade --tier merge|nightly`**, default `nightly`. `nightly` is exactly today's grade.
2. **In tier `merge` the `mutants` gate defers the modules whose mutation can only report.** A module is deferred when
   no finding of its mutation can be an error: level L2 today; and, when its policy table declares `profile`, when
   `profiles.required(profiles, level)` does not make `mutation_zero_survivors` a `gate` (a module with profiles is
   judged by the matrix; a module without profiles by its level, exactly as today). A deferred module is not built
   and not run. The gate result lists each one as info `mutation-deferred` (module, reason) and the metadata counts
   them. Every other module is mutated and judged as today, with the same findings.
   - State in the docs which module-level errors a deferred module can no longer raise at merge (for example
     `no-mutants`, `unviable-ratio` as an error) and that the nightly tier still raises them.
   - `mutants-witness` follows the same rule.
   - If, at tier `merge`, every module is deferred, the gate passes with the infos (today's `no-mutated-modules`
     error stays for a product that has no module at L2 or above at all).
3. **The verdict says which tier it is.** Bind `tier` into `core.inputs`, so a merge-tier PASS and a nightly PASS
   have different `core_sha256` and cannot be confused. `rigor verify` gets `--require-tier TIER` (exit 1 with a clear
   message when the verdict's tier differs) and prints the tier always.
4. **No other gate changes with the tier** in this task. Say so in `docs/grade.md`, with a table of what each tier
   runs, so later tasks add rows instead of inventing a second mechanism.
5. **Tests, selftest, canaries.**
   - Unit tests: the deferral rule for every level with and without profiles (each profile of P003 §4.1 at L2, L3,
     L4); the tier in the verdict inputs; `--require-tier`.
   - `selftest/grade.sh`: a step that grades the selftest product at tier `merge` with one L2 and one L3 module: the
     L3 module is mutated, the L2 one is `mutation-deferred`, fewer mutant actions execute than at `nightly`, and the
     nightly grade of the same tree reports exactly what it reported before this task.
   - Canaries: every existing canary that is red on `mutants` at an L3 or L4 module must be red at tier `merge` too:
     run the canary pack once at tier `merge` (a runner flag or a second pass; your choice, documented) and require
     the same red gates for those. One new canary `tier-forged`: a verdict produced at tier `merge` and presented to
     `rigor verify --require-tier nightly` is refused.
6. **Docs.** `docs/grade.md` (tiers, the table, deferral), `docs/mutate.md` (what deferral means for the findings).

## Not in this task
Any change to which mutants exist or how they are judged; sampling of mutants; the action cache or `--uncached`;
other gates' behaviour per tier; `products/**`; `mutate/**`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/grade.sh`; `selftest/mutate.sh`; `selftest/canaries.sh --jobs 8`
(and the tier `merge` pass of item 5); `selftest/tripwires.sh --jobs 5`; `python3 -I tools/affected.py --check`.
`selftest/perf.sh` is known to flake (backlog B35, another lane): ignore it.

## Allowed paths
`gate/rigor_lib/grade*.py`, `gate/rigor_lib/mutants_gate.py`, `gate/rigor_lib/verdict*.py`, `gate/rigor_lib/cli.py`
(only if `verify` is registered there), `gate/tests/**`, `canaries/tier-forged/**` and the canary catalogue and
runner files, `selftest/grade.sh`, `selftest/grade_product/**`, `selftest/canaries.sh`, `docs/grade.md`,
`docs/mutate.md`, `docs/canaries.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T137`. `TMPDIR=/var/tmp/cache/T137/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. If you need a throwaway script, write the whole file with the Write tool or a heredoc so its text is in your
transcript. `rigor grade` and the canary runner refuse a dirty checkout: commit before you run them. Commit on
`task/T137`; your last message is the report (what works, what does not, the action counts of the two tiers, every
deviation).
