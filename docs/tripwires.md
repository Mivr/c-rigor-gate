# The tripwire pack (T086, backlog B6, second half)

A canary ([docs/canaries.md](canaries.md)) is a **cheat** that must be red. A tripwire is the opposite: an **honest**
product, nothing in it cheats, carrying an **obligation that no code can meet**. The only way it goes green is a
blind checker: a gate that stopped looking, a cached verdict reused for inputs it does not cover, a forged
action-cache entry (backlog B4). Canaries prove the gate catches known cheats; tripwires prove it still *looks*.

```sh
selftest/tripwires.sh                    # every tripwire, one of them --uncached; exit 0 = all red as declared
selftest/tripwires.sh --only equivalent-mutant   # one (repeatable); --jobs N; --uncached ID; --keep
```
Same runner as the canary pack (`canaries/runner.py --root tripwires`), same table and same exact-match rule: the
failing gates, their error rules and the NOT_RUN gates must be exactly those of `expect.json`. A tripwire that grades
PASS fails the pack with `tripwire <id> is green: <gate> is blind`. Layout of `tripwires/<id>/` is the canary layout
(`product.toml`, `policy.toml`, `expected-tests.json`, `task.toml`, `expect.json`, `edit.sh` on the shared
`canaries/_base/product`, optional `witness/`); the coverage-of-every-gate check is a canary-pack rule and does not apply.

**Uncached lane.** Every tripwire is graded cached on every run; exactly one is also graded `--uncached` (no remote
cache, the toolchain verified), chosen by day: the sorted ids, index `days since the epoch (UTC) mod count`. Over a
week every tripwire takes the uncached path, so a blind spot that exists only in the cached or only in the uncached
path shows within days. `--uncached ID` overrides.

## The tripwires

| id | gate | impossible obligation | why it is impossible |
|---|---|---|---|
| `equivalent-mutant` | `mutants` (and `mutants-witness`, which reuses the head's verdict: the witness is the head's file) | `core_clamp0` (`if (v < 0) return 0; return v;`) and no approval | the mutants `<` to `<=` and `0` to `1` in the condition differ from the original only at `v == 0`, where both return 0: provably equivalent (proof in the code comment), so no test kills them and no approval is offered |
| `stub-is-the-answer` | `tests-stub` | role test-author: a new test that fails on the stub of `core_zero` | `core_zero` is specified to return 0, so the only correct body is the stub; whatever the test asserts, it passes on the stub |
| `witness-disagrees` | `witness-tests` | the head's expected test `core/neg` must pass on the gate-held witness | the head is correct (`-v`), the witness returns `1 - v`; the witness is gate-owned and the contributor cannot change it, so the test cannot pass against it |
| `witness-equivalent-mutant` | `mutants-witness` | every mutant of the witness must die under the head's tests | the witness spells `v + 1 + 0`; the last `+` to `-` is equivalent; the head has no such code, so no test of the head can kill it |
| `unproducible-test-id` | `tests-release`, `tests-san` | the expected list names `core/Add` | ctest accepts only `[a-z0-9_]+` names, so no product can emit an id with a capital; both modes must report `missing-test` (one tripwire for both gates: each is judged exactly, so a blind one changes the failing set) |

### Gates without a tripwire
The other gates of `gate/order.txt` judge the shape of the diff or the build, and everything they reject can be avoided
by writing different code, so they have no obligation that is impossible for every product (a refusal that code can avoid
is a canary):
- `clone`: judges the repository and refs, not code; a bad ref is a cheat or an error, never an obligation.
- `contract`: judges paths against the task's `allowed` list; the task can always be met inside it, or is not a product obligation.
- `suppressions`: forbidden text is avoidable by not writing it.
- `assemble`: a bad path or symlink is avoidable.
- `toolchain`: judges the grader, not the product; proven failing by the last step of `selftest/grade.sh`.
- `buckfiles`: only the permitted rules and attributes exist, and every product can use only those.
- `semantic-suppressions`, `symbols`: denied calls, attributes and exports are avoidable; policy exports are met by listing them.
- `build`: a product that cannot compile cannot be demanded to; a compile error is a code defect, not an obligation.
- `structure`: size and recursion limits are met by splitting and iterating; any algorithm has a bounded, non-recursive form.
- `layering`: the architecture contract is met by depending only on what the contract allows; a forbidden edge is avoidable by not adding it.
- `perf`: a complexity class is met by choosing the algorithm (a product that cannot is a defect, `perf-class-exceeded` has a canary).
- `fuzz`: a crash within a fixed seed and a fixed budget is a defect of the code, a required target is written by the product (`fuzz-crash`, `fuzz-missing`, `fuzz-vacuous-harness` and `fuzz-regression-dropped` are canaries).
- `mode-divergence`: release and san twins are generated by the same macros; divergence is a code choice (`ifdef`), avoidable.

## Adding one
1. Copy the four gate files from `canaries/_base`, write `edit.sh` (or a `product/`), keep the code honest: no
   suppression, no special case, no weakened test.
2. Prove the impossibility in a comment next to the code or in the table above.
3. `expect.json`: `fail` (gate to rules), `not_run`, `description`; `contains` for text that proves the right reason.
4. Run `selftest/tripwires.sh --only <id>`; then show the one change that turns it green and run that variant once in
   scratch (never commit it).

## Green variants (checked 2026-11-07)
Each tripwire was also run with one change and went green (`PASS exit 0`, message `tripwire <id> is green`):
`equivalent-mutant` without the function and its test; `stub-is-the-answer` with the stub `return -12345`;
`witness-disagrees` with the witness `-v`; `witness-equivalent-mutant` with the witness `v + 1`; `unproducible-test-id`
without `core/Add` in the list.

## Measured wall time
`selftest/tripwires.sh` (five tripwires, `--jobs 8`, one uncached, shared farm and two CPUs):
283 s wall (final run, `witness-equivalent-mutant` uncached; 193 s and 203 s at `--jobs 3` on earlier runs). The uncached tripwire is the longest lane; the cached ones take 20 to 210 s each while other lanes share the farm.
