# The canary pack (T018, backlog B6)

Self-tests check each component as its author imagined it. The canary pack is the standing, adversarial proof
that the **assembled** gate (`rigor grade`, real clone, Buck2 on RE) still says FAIL for every known cheat.
Every bypass found by a review, by R001 or by the red team becomes a canary.

```sh
selftest/canaries.sh                    # all canaries, 8 at a time, one of them --uncached
selftest/canaries.sh --only nolint      # one canary (repeatable); --jobs N; --uncached ID; --keep
```
Exit 0 only if every non-pending canary behaved as declared. The output is a table
`canary | expected | got | ok`, the list of pending canaries, and the wall time.

## Where the time goes (T025)
Measured 2026-11-06 on the shared farm (four other lanes running; numbers move with their load). Resources of a whole
pack run come from `python3 -I -B canaries/measure.py [--keep] -- python3 -I -B canaries/runner.py ...` (wall, local CPU of
every process including detached Buck2 daemons, peak summed RSS, peak scratch disk); worker time and queue time come from
`tools/lanes/buck2_stats.py` over the kept trees.

| Run | wall | local CPU | peak RSS | peak scratch | pack verdicts |
|---|---|---|---|---|---|
| before: `--jobs 4`, control alone first, scratch kept to the end | 551 s | 96 s | 1380 MiB | 1284 MiB | 0 live misses |
| after: `--jobs 4`, longest-first, uncached lane at t=0, trees removed when judged | 378 s | 96 s | 1536 MiB | 110 MiB | 0 live misses |
| after: `--jobs 8` (new default) | 301 s | 102 s | 2916 MiB | 220 MiB | 0 live misses |
| after: `--jobs 12` | 310 s | 131 s | 4257 MiB | 329 MiB | 0 live misses |

Per canary (before, `--jobs 4`, farm busy): the 41 cached canaries took 15 to 44 s each, `control` 21 s, `weak-test [uncached]` 265 s.
Alone on the same farm a cached canary takes about 8 s (`inline-asm`: 8 s wall, 3.6 s local CPU), so the 15 to 44 s
is queueing behind the other lanes and the four daemons, not work. For a cached canary (`inline-asm`, `control`):
8 to 9 Buck2 commands, 0 actions executed, 24+9+16+102 action-cache hits, 0 worker time, 0 queue time, about 230 KiB
downloaded per build command, 4 to 7 s of the wall in `uquery`/daemon start and prelude analysis (about 2 s per fresh
daemon), the rest in clone, assemble (copy of the gate tree) and Python. Nothing is fetched or unpacked on a cached run.

`weak-test` (`--uncached`, `--no-remote-cache`): 79+15+68+191 actions, 24+9+16+102 executed, 337 s of worker time, queue
under 2 s, 308 KiB uploaded in the large build, 280 KiB downloaded. Its longest actions: `fetched_tree llvm` 113 to 125 s worker
time (it runs twice, once in the facts build and once in the mutants build, because with the action cache off the 2 GB
`tar -xJf` of the LLVM release is redone on a worker each time), then two waves of `mutant_compile`/`mutant_run` actions
of about 35 s wall each but about 1 s of worker time: they wait for input materialisation of the unpacked toolchain on the
worker (sum 31 s) and the `core` wave depends on the `util` wave. Critical path: llvm unpack (about 118 s) + util wave
(about 33 s) + core wave (about 38 s) + the other gates (about 55 s). That floor is about 250 s on this farm and it
cannot be cut from the runner. What would make it faster, out of scope here (`toolchains/**`, `rules/**`): store the LLVM
subset as a smaller, zstd-compressed (or pre-split per member group) archive so the uncached unpack is a few seconds
rather than a 2 GB xz decompress; run the `core` and `util` mutants in one wave; and let the toolchain's `fetched_tree` be
resolved from the CAS even under `--no-remote-cache` (it is a pure download, so the "uncached" proof does not need it).

### What was changed, and what each change gave
- Scratch: each canary's work tree (its `buck-out`, the bulk of the disk) is removed as soon as it is judged unless `--keep`:
  peak scratch 1284 to 110 MiB, no effect on wall.
- Scheduling: the uncached canary starts at t=0 on its own lane (it shares nothing with the rest) and the control runs
  beside it instead of the pack waiting for the control first; the rest start longest-first (canaries that are expected to
  run more gates go first). 551 s to 378 s at `--jobs 4`. `--jobs` counts the uncached canary as one.
- Default `--jobs` 8: 301 s (4: 378 s, 12: 310 s with 4.2 GiB RSS and 131 s CPU). 8 is the knee on this farm.
- Not done, measured against: sharing one `buck-out` or daemon between canaries would change what a "real clone" proves
  (`rigor grade` seals HOME and builds one tree per grade), so every canary keeps its own clone, tree and daemon.

The wall is now `weak-test`'s: with it the pack takes 300 to 380 s here and the 180 s target of T025 is not reachable
while it stays uncached. The other 42 canaries finish in well under 180 s at `--jobs 8`.

## The rule
**No bypass fix merges without its canary.** A change that closes a hole in the gate adds
`canaries/<id>/` in the same commit, and the canary must be red for the reason the fix is about.
A canary is never edited to make it pass (AGENTS.md rule 2); a change to `expect.json` needs the same review as a
change to the gate.

## What passes
A canary passes only if **all** hold, and anything else is a miss (a fixture that fails for the wrong reason
hides a disarmed check):
- the set of FAIL gates equals `expect.json` `fail`'s keys, and for each, the set of **error** finding rules
  equals the listed rules (info findings are ignored);
- the set of NOT_RUN gates equals `not_run` (default none); every other gate is PASS;
- the exit code is `exit` (default 1; 2 is an internal error);
- every `contains` entry (`{"build": "unused-variable"}`) occurs in that gate's result file;
- no file named in `absent` exists in the canary's scratch dir (code that must never run, did not).

Several gates may legitimately fire for one bypass (a defence in depth: the text scan and the semantic scan, the
buckfiles check and the macro's own `fail()`); list them all. If a second defence disappears, that is a change
and the canary says so.

`control` (the unmodified base) must PASS; it proves the shared fixtures are sound and it warms the cache.
The pack also fails if some gate in `gate/order.txt` is not the expected failing gate of any live canary.

## Layout of `canaries/<id>/`
| File | Meaning |
|---|---|
| `expect.json` | `description`, `bypass` (class), `fail` (`{gate: [rules]}`), optional `not_run`, `exit`, `contains`, `absent`, `pending` |
| `product.toml`, `policy.toml`, `expected-tests.json`, `task.toml` | the gate-owned inputs of `rigor grade` (`expected-tests.previous.json` if the canary needs one); `task.toml` is the task contract |
| `edit.sh` | bash, run inside the product repo on top of the base commit; whatever it changes is the head commit |
| `history.sh` | instead of `edit.sh`, for git tricks (graft, replace, unresolvable refs): full control of the repo, env `BASE`, `CANARY_DIR`, `CANARY_SCRATCH`; its last line prints `<base> <head>`. It must check that the trick is armed (see `git-graft`) |
| `product/` | optional full product tree; default is the shared `canaries/_base/product` |

The product repository and its history are generated at run time under `$TMPDIR` and never committed
(no nested repos). `canaries/_base/` holds the shared tree and defaults; copy its four gate files into a new
canary and change only what the bypass needs, so unchanged targets are cache hits.

## Adding a canary
1. Write the smallest `edit.sh` that performs the cheat. Do not use a spelling that a *different* check catches
   first unless that is the point (the spliced `#pra\<newline>gma` canary exists because the plain one is caught
   by the text scan).
2. Put code in a library whose policy level does not add unrelated findings (`util` is L2: its survivors are
   info; `core` is L3, so an untested new function there adds `survived-mutant`).
3. `expect.json`: the gate and rule(s) the cheat must hit. Run `selftest/canaries.sh --only <id>`; if it goes red
   for a *different* reason, fix the fixture; if the gate is silent, you found a gate bug: report it, fix the gate
   in its own task.
4. For a check that is still in flight on another branch, add `"pending": "<task id>"`. Pending canaries run and
   print their verdict but do not fail the pack. When the task merges, the orchestrator removes `pending`
   (and fixes the guessed rule ids in `expect.json`) in the merge.
5. Record the bypass class in `bypass` and, if it came from an audit, the id in `description`.

## Not covered here
`rigor trajectory` (T015) audits an agent transcript, not a graded repository, so it has no canary until it is
part of `rigor grade`. The environment-hostility and signature checks stay in `selftest/grade.sh`.
