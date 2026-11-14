# Validating a branch: the affected-selftest map (T044)

The orchestrator used to pick selftests by hand. `tools/affected.py` and `tools/validate.sh` do it from a checked-in map.

## The map: `tools/affected.toml`

Ordered rules `{glob, selftests}`. The **first** rule whose glob matches a changed path decides that path; the selected
set is the union over all changed paths, plus `gate` (the unit tests), which is always selected. Selftest names:
`gate grade mutate structure product_checks profiles require sanmodes sim toolchain ctest fuzz third_party canaries trajectory_real`; `all` stands for
every one of them.

Fail closed:
* A changed path that no rule matches selects **everything**.
* `rules/**`, `toolchains/**`, `prelude/**`, `.buckconfig`, `.buckroot`, `tools/buck2*`, `gate/rigor_lib/grade*` and
  `gate/rigor` select everything and come first.
* Renames count as a delete plus an add, so both paths are looked at.

Globs match the whole repo-relative path: `*` and `?` stay inside one path segment, `**` crosses segments.

When you add a file, add or extend a rule. `python3 -I tools/affected.py --check` (also a unit test) exits 1 and lists
every tracked file that is matched by no rule or only by a catch-all rule (glob `**`), so the map cannot rot silently.
A rule that is too narrow is the dangerous direction: when unsure, list more selftests.

## `tools/affected.py`

```sh
python3 -I tools/affected.py BASE HEAD          # selftests to run, one per line, stable order
python3 -I tools/affected.py --why BASE HEAD    # name<TAB>the first path and rule that selected it
python3 -I tools/affected.py --check            # every tracked file matches a specific rule
```

Stable order: gate, grade, mutate, structure, product_checks, toolchain, ctest, fuzz, third_party, canaries,
trajectory_real. Exit 2 on a usage or git error, 1 only for `--check` failures.

## `tools/validate.sh [--dry-run] BRANCH`

Run it in the val worktree (already merged with main). It takes the merge base of `main` and BRANCH, selects the
selftests, runs them, and prints one table: selftest, exit, seconds, last line. Logs are
`$TMPDIR/validate/<selftest>.log`. `--dry-run` prints the plan and runs nothing. It never merges, pushes, fetches or
reads agent output. Exit 0 only if every selected selftest exited 0.

Parallelism: `gate`, `grade`, `canaries` (with `--jobs 8`) and `trajectory_real` each get a lane of their own, because
they do not build in this project root. The selftests that do (`product_checks profiles require ctest toolchain fuzz sim sanmodes structure mutate
third_party`) share one Buck2 daemon and read `buck2 log what-ran`, which names the last command of the root, so they
run one after another in a single lane. `trajectory_real` needs `TRAJECTORY_REAL_DIR`; unset, it skips (exit 0) and the
table's last line says so.

## Timing

Every selftest script now prints a line `elapsed <S>s` to **stdout, immediately before** its final result line, so the
existing last line (`ALL CHECKS PASSED (n)`, `selftest/<x>.sh: all ...`) is still the last human-readable line the
orchestrator greps. `canaries.sh` already prints `exit N after Ns` as its last line, and `gate.sh` and `grade.sh`
are covered by other tasks.
