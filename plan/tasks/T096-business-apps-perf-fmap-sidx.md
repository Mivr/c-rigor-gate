# T096: gate-held perf targets for business-apps `fmap` and `sidx`

Repo: `Mivr/c-rigor-gate`. Branch `task/T096`. Read `AGENTS.md`, `docs/perf.md` (the whole file: harness API, policy
shape, thresholds, determinism), `docs/mutate.md` ("Perf kills", T090), `products/business-apps/` as T094 left it,
and the product's `lib/ds/fmap/fmap.h` and `lib/ds/sidx/sidx.h` (clone `/var/tmp/src/business-apps` read-only into
`/var/tmp/cache/T096/biz-clone`; grade the clone).

## Why
The T094 whole-repo grade leaves 11 `fmap` survivors (most in the hash/probe start: a weaker hash keeps the map
correct but makes it slow) and 8 `sidx` survivors (search and sort bounds that stay correct but cost more), plus a
`crash-kill-ratio` on `fmap` `home_of`. Their complexity is a promise of the design (`fmap`: O(1) expected per op;
`sidx`: seal O(n log n), find O(log n)). A perf target turns a mutant that breaks the promise into `killed-perf`.

## Build
In `products/business-apps/policy.toml`, per `docs/perf.md` "The policy shape" (sources as literal strings in the
policy, generator + driver on the `ctest/perf.h` API, no allocation: static storage sized for the largest size):
- `fmap.ops`: `perf_run` builds a map of the input's n distinct keys (fixed-width keys from the generator, seeded),
  then gets every key and some absent keys, deletes half, gets again. Class **O(n)** (n operations, O(1) each), sizes
  e.g. `[2000, 8000]` with slots sized for load <= 7/8. Choose keys that are adversarial to a weak hash only through
  the seed (the policy seed), not by knowing the implementation.
- `sidx.seal_find`: `perf_run` appends n records, seals, then finds every key and some absent ones. Class
  **O(n log n)**, sizes e.g. `[2000, 8000]`.
Run the whole-repo grade of the clone: the perf gate passes the honest modules (baselines inside their class) and the
mutants stage reports how many former survivors are now `killed-perf`. List every survivor that remains (id,
file:line, mutation) and every `crash-kill-ratio` finding; do not sign anything.

## Allowed paths
`products/business-apps/policy.toml` only (and `products/business-apps/tasks/**` if a grade task file is needed).

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the whole-repo grade summary (perf gate status, per-target baseline counts at both sizes, killed-perf counts per
module, remaining survivors).

## Rules
Use `TMPDIR=/var/tmp/cache/T096/tmp`; never write to `/tmp` (the harness scratchpad included). Build only with
`gate/tools/buck2`. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`,
`/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Kill only processes you started, by the pid
`tools/job` recorded (never by pattern). No sleep-poll loops (`tools/job`). Only one grade at a time. 2 CPUs and
8 GiB are shared and loaded; RE "No space left on device" or daemon errors are load: re-run.
