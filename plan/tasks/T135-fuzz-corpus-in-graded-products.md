# T135: a graded product can give its fuzz targets a corpus and a budget (P003 W6 part 3)

Repo: `Mivr/c-rigor-gate`. Branch `task/T135` from main (T129 merged: the `fuzz` gate). Read `docs/fuzz.md`,
`docs/grade.md` ("Fuzz in the pipeline", "The grading tree", "Layout coverage"), `rules/fuzz.bzl`, `rules/c.bzl`
(`c_fuzz`), `gate/rigor_lib/buckfiles.py`, `product_layout.py`, `grade_tree.py`, `grade_fuzz.py`, `fuzz_gate.py`,
`suppressions.py` and `patterns.py`, and the canary `fuzz-regression-dropped`.

## Why
T129 reported it: `buckfiles` accepts only `name`, `srcs`, `headers`, `deps` and `visibility` on `c_fuzz`, so a
graded product cannot pass `corpus` or `runs`. Every graded fuzz target therefore starts from an empty corpus, and
the regression list (`fuzz-regressions.json`) can only ever report an input as missing. The point of that list is the
opposite: an input that once crashed stays in the corpus and is replayed forever.

## Do
1. **`buckfiles`.** On `c_fuzz` accept `corpus` and `runs`. `corpus` follows exactly the rule `srcs` follows today
   (which forms are allowed, where the files may live); `runs` is an integer literal. Anything else stays an error.
   The parser never executes the file; keep it that way.
2. **The grading tree.** Corpus files must reach the tree the grade builds: say which layout rule covers them and add
   one if none does (a corpus directory that the layout does not name must be `ungraded-path`, as any other
   directory is). A corpus file is data, not code: check what `suppressions` (the added-lines pattern scan, which
   forces files to text), `binary-artifact`, `structure`, the symbol and semantic facts and the mutation generator do
   with it, and report each. Change one only where it makes a corpus unusable, and then in the narrowest way: the
   exemption must be tied to the file being listed in a `c_fuzz` `corpus` and in no `srcs` or `headers`.
3. **Budget.** A product may set `runs` on a target; the judge still demands the policy's budget (`fuzz-short`). Show
   it: a target with `runs` below the policy budget is red.
4. **End to end through `rigor grade`.** In the selftest and as canaries (follow `docs/canaries.md`; every new
   expectation lists the gates that are NOT_RUN, including `fuzz` where it applies):
   - a product whose target has a corpus that contains the listed regression input: PASS, and the metadata shows it
     replayed;
   - `fuzz-regression-dropped` reworked: the same product with that corpus file removed is red on `fuzz` with
     `fuzz-regression-missing`;
   - `fuzz-regression-crashes`: the corpus holds an input that makes the current code crash: red with `fuzz-crash`,
     phase `replay`;
   - `fuzz-budget-lowered`: `runs` below the policy budget: red with `fuzz-short`.
5. **Docs.** `docs/fuzz.md` and `docs/grade.md`: remove the gap note, describe where a corpus lives and how an input
   gets onto the regression list.

## Not in this task
`rules/**` (the macro already takes both arguments; if a rule change is needed, stop and report), `products/**`, a
nightly campaign, anything about how the regression list is written (a later task; today the gate owner edits it).

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/grade.sh`; `selftest/fuzz.sh`; `selftest/product_checks.sh`;
`selftest/canaries.sh --jobs 8`; `selftest/tripwires.sh --jobs 5`; `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/buckfiles.py`, `gate/rigor_lib/product_layout.py`, `gate/rigor_lib/grade_tree.py`,
`gate/rigor_lib/grade_fuzz.py`, `gate/rigor_lib/fuzz_gate.py`, `gate/rigor_lib/suppressions.py` (only as item 2
allows), `gate/tests/**`, `canaries/fuzz-*/**`, `canaries/_fuzz/**` and the canary catalogue files,
`selftest/grade.sh`, `selftest/fuzz.sh`, `selftest/fuzz_product/**`, `docs/fuzz.md`, `docs/grade.md`,
`docs/canaries.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T135`. `TMPDIR=/var/tmp/cache/T135/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. If you need a throwaway script, write it with the Write tool or a heredoc so its text is in your transcript.
`rigor grade` and the canary runner refuse a dirty checkout: commit before you run them. Commit on `task/T135`; your
last message is the report (what works, what does not, what each checker does with a corpus file, every deviation).
