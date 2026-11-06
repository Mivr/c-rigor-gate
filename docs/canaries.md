# The canary pack (T018, backlog B6)

Self-tests check each component as its author imagined it. The canary pack is the standing, adversarial proof
that the **assembled** gate (`rigor grade`, real clone, Buck2 on RE) still says FAIL for every known cheat.
Every bypass found by a review, by R001 or by the red team becomes a canary.

```sh
selftest/canaries.sh                    # all canaries, 4 in parallel, one of them --uncached
selftest/canaries.sh --only nolint      # one canary (repeatable); --jobs N; --uncached ID; --keep
```
Exit 0 only if every non-pending canary behaved as declared. The output is a table
`canary | expected | got | ok`, the list of pending canaries, and the wall time.

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
