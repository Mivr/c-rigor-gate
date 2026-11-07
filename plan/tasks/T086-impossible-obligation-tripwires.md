# T086: impossible-obligation tripwires (backlog B6, second half)

Repo: `Mivr/c-rigor-gate`. Branch `task/T086`. Read `AGENTS.md`, `README.md` (the `tripwires/` row), `docs/canaries.md`,
`canaries/runner.py`, `gate/order.txt`, and `docs/grade.md`.

## Why
A canary is a **cheat** that must be red. A tripwire is an **honest** product with an obligation that **cannot be met**:
nothing in it cheats, so the only way it goes green is a blind checker (a gate that stopped looking, a cached verdict
reused for inputs it does not cover, a forged action-cache entry: backlog B4). `README.md` already lists `tripwires/`;
it does not exist yet.

## What to build
1. `tripwires/<id>/`, the same format as `canaries/<id>/` (`product.toml`, `policy.toml`, `expected-tests.json`,
   `task.toml`, `expect.json`, `product/` or `edit.sh` on the shared `canaries/_base/product`). Reuse the canary runner:
   give `canaries/runner.py` a `--root DIR` (default `canaries`), and add `selftest/tripwires.sh` (like
   `selftest/canaries.sh`, with `--root tripwires`). Do not edit or remove any existing canary.
2. One tripwire for **every gate in `gate/order.txt` that judges the product and can carry an impossible obligation**.
   For each other gate, one line in `docs/tripwires.md` saying why no impossible obligation exists for it. Candidates
   (design your own if one is better; each must be honest code, no cheat):
   - `mutants`: a truly equivalent mutant (prove it in a comment) with no approval. Must FAIL as a survivor.
   - `tests-stub`: a function whose correct implementation equals its stub, so no correct test can tell them apart.
   - `witness-tests` / `mutants-witness`: an obligation the witness cannot meet (for example a task test asserting
     behaviour the witness does not have), if the runner can stage a witness; otherwise explain.
   - `tests-release` / `tests-san`: an expected test id listed in `expected-tests.json` that the product cannot produce
     (say why it cannot).
3. **Each tripwire is red, and also red `--uncached`.** The selftest grades every tripwire once cached and the pack runs
   one of them `--uncached` per run (rotate deterministically by day, like the canary uncached lane, or pick the slowest;
   say which). A tripwire that goes green fails the selftest with the message `tripwire <id> is green: <gate> is blind`.
4. Wire it into `tools/validate.sh` and `tools/affected.py` exactly like `canaries` (same trigger paths plus
   `tripwires/**`), as its own step `tripwires`.
5. `docs/tripwires.md`: what a tripwire is, the table `id | gate | impossible obligation | why it is impossible`, how
   to add one, and the measured wall time of `selftest/tripwires.sh`. Link it from `docs/canaries.md` and `README.md`.

## Allowed paths
`tripwires/**`, `canaries/runner.py` (the `--root` option and the green-tripwire message only), `selftest/tripwires.sh`,
`tools/validate.sh`, `tools/affected.py`, `docs/tripwires.md`, `docs/canaries.md` (one link line), `README.md` (one
link), new unit tests `gate/tests/test_*tripwire*.py` if you add runner logic worth testing.

## Acceptance
```sh
selftest/tripwires.sh                 # every tripwire red as declared; exit 0
selftest/canaries.sh --only control --only failing-test   # the runner change breaks no canary
python3 -I -B gate/tests/run_parallel.py
python3 -I tools/affected.py main HEAD   # must list tripwires
```
Then, to prove each tripwire is not red for the wrong reason, for each one show the single change that turns it green
legitimately (an approval left unsigned in the scratch, the obligation removed from `expected-tests.json`, ...): run that
variant once in your cache dir only (never commit it) and paste the green verdict. Report the table, the outputs, the
wall time, and every deviation.

## Rules
Use `TMPDIR=/var/tmp/cache/T086/tmp`; never write to `/tmp`. Build only with the gate's Buck2 (`gate/tools/buck2`, which
the runner uses), never host compilers. No `git stash`, no merge of `main`, no push. Never read `/var/tmp/.config`,
`/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache dirs. Never kill processes you did not
start; never `buck2 kill` outside your own scratch. No sleep-poll loops (`tools/job`). 2 CPUs and 8 GiB are shared.
