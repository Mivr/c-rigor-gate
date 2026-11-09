# T126: the fuzz judge: corpus replay, a fixed run budget, required targets (P003 W6, P001 G23; landed, not wired)

Repo: `Mivr/c-rigor-gate`. Branch `task/T126` from main. Read P003 §7.2, `rules/c.bzl` (`c_fuzz`), `rules/ctest.bzl`
(`fuzz_run`), `selftest/fuzz.sh`, `selftest/fuzz_product/`, and how `rigor mutants` and `rigor tests` are built
(`gate/rigor_lib/cli.py`, `mutants_gate.py`, `tests_gate.py`, `findings.py`).

## Why
`c_fuzz` exists and runs `-seed=1 -runs=200000` with no corpus, and no gate reads its result. business-apps has eight
hand-written parsers and zero fuzz targets. This task makes the fuzz run useful and adds the judge. Wiring it into
`rigor grade` (`GATES`, `gate/order.txt`) and its canaries is the next task; do not do it here.

## Do
1. **`c_fuzz` with a corpus.** `c_fuzz(name, srcs, deps, corpus = [...], runs = N)`: `corpus` is a list of files of the
   product (a `glob` in the product's BUCK; default empty), `runs` an optional budget with a sealed default and a
   sealed maximum in the rules. The run action, in this order:
   1. **replay**: every corpus file once (`-runs=0` over the files); a crash here is a regression;
   2. **budget**: `-seed=1 -runs=N` seeded with the corpus.
   The budget is a number of runs, never a time, so the action stays deterministic and cacheable; a wall-clock limit
   is only the timeout that fails it. Outputs: `verdict` (as today, written after the target exited), `report`,
   `crash` (the reproducer), and a new `stats.json` with exactly: `runs_done`, `corpus_files`, `replayed`, `phase`
   (`replay` or `budget`, where it stopped), `reproducer_sha256` (empty on a pass). Nothing volatile in it. Move
   `fuzz_run` into a new file `rules/fuzz.bzl` if that keeps `rules/ctest.bzl` simpler.
2. **`rigor fuzz --results DIR --policy P.toml --facts DIR [--regressions R.json] [--out F]`** in
   `gate/rigor_lib/fuzz_gate.py`, fail closed like the other judges (unknown key, stray file, malformed input: exit 2).
   Policy: `[module."//pkg:name"] fuzz = true` means the module must be fuzzed. Findings (errors unless noted):
   - `fuzz-missing`: a module with `fuzz = true` that no `c_fuzz` target lists in `deps`;
   - `fuzz-harness-no-call`: a fuzz target that references no exported symbol of the module it claims to fuzz (from
     the symbol facts the `symbols` gate already reads): a harness that never calls the code is not a harness;
   - `fuzz-crash`: target, phase, reproducer sha256, the symbolized top frame;
   - `fuzz-not-run`: a required target without results; `fuzz-short`: fewer runs done than the budget without a crash;
   - `fuzz-regression-missing`: an input listed in `R.json` (gate-owned: `{"<target label>": ["<sha256>", ...]}`) that
     is not among the replayed corpus files. This is what stops a crashing input from being deleted;
   - info `fuzz-empty-corpus`.
   Findings are sorted and byte-identical on rerun; counts and timings go to `metadata` only.
3. **Selftest.** Extend `selftest/fuzz.sh` and `selftest/fuzz_product/`: a parser with an out-of-bounds read that the
   budget reaches (`fuzz-crash`, phase `budget`); the same bug with its reproducer in the corpus (phase `replay`); the
   fixed parser (PASS); a harness that returns at once (`fuzz-harness-no-call`); a module with `fuzz = true` and no
   target (`fuzz-missing`); a regression list naming an absent input (`fuzz-regression-missing`). Each run twice with
   identical results.
4. Unit tests `gate/tests/test_fuzz_gate*.py`; `docs/fuzz.md` (the rule, the judge, the findings, the limits: a
   fixed seed and budget find shallow bugs only, long campaigns are a later nightly task); `tools/affected.toml`.

## Not in this task
`gate/rigor_lib/grade*.py`, `gate/order.txt`, canaries, `products/**`, a nightly campaign, the other build modes.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/fuzz.sh` twice in a row; `selftest/ctest.sh`;
`python3 -I tools/affected.py --check`. The orchestrator runs the full `tools/validate.sh` (a change under `rules/**`
selects every selftest), so every existing `c_fuzz` use must keep working with no `corpus` argument.

## Allowed paths
`rules/fuzz.bzl`, `rules/c.bzl` (the `c_fuzz` macro only), `rules/ctest.bzl` (`fuzz_run` only),
`gate/rigor_lib/fuzz_gate.py`, `gate/rigor_lib/cli.py` (registering the subcommand only), `gate/tests/test_fuzz_gate*.py`,
`selftest/fuzz.sh`, `selftest/fuzz_product/**`, `docs/fuzz.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T126`. `TMPDIR=/var/tmp/cache/T126/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Commit on `task/T126`; your last message is the report (what works, what does not, every deviation).
