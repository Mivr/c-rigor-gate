# T025: canary pack wall time from ~10 min to <= 3 min, same verdicts (lane speed)

Repo: `Mivr/c-rigor-gate`. Branch `task/T025`. Read `AGENTS.md`, `docs/canaries.md`, `canaries/runner.py`,
`docs/grade.md`, `docs/lanes.md` and `tools/lanes/buck2_stats.py` (T022: per-command Buck2 stats from event logs).
**T013, T021, T023 and T024 run in parallel**: don't touch `gate/rigor_lib/**`, `rules/**`, `selftest/grade.sh`,
`selftest/product_checks*`, `tools/lanes/**`, or any `canaries/<id>/` content.

## Why
Every gate merge runs `selftest/canaries.sh`. It now takes 605 s wall at `--jobs 4` (47 canaries; `weak-test
[uncached]` 313 s, `inline-asm` 138 s, `generator-attribute` 109 s, `pragma-plain` 86 s). It is the long pole of
task-to-merge. A canary must still be a real `rigor grade` of a real clone: speed may not come from skipping gates,
mocking Buck2, trusting a cache the grade itself refuses, or loosening the expected verdicts.

## Allowed paths
`canaries/runner.py`, new `canaries/*.py` helpers, `canaries/_base/**` (only if a shared base speeds it up without
changing any verdict), `selftest/canaries.sh`, `docs/canaries.md`, new `gate/tests/test_canaries*.py`.

## Requirements
1. **Measure first.** Per canary, record wall and, from its Buck2 logs via `tools/lanes/buck2_stats.py`, actions
   executed vs cached, worker time, queue time, CAS bytes, and the longest actions. Put the table (before) in
   `docs/canaries.md`. Say where the time goes: RE work, queueing, toolchain fetch/unpack, daemon start-up,
   clone/assemble, Python, serial steps.
2. **Then cut it**, for example: a sensible default `--jobs` for this farm (measure 4/6/8/12), longest-first
   scheduling, one assembled base reused read-only, sharing the warm action cache between canaries that run cached,
   avoiding a cold toolchain unpack per canary, starting daemons once. Each change measured, kept only if it helps.
   The one `--uncached` canary stays uncached (it proves the uncached path); find why it is 313 s and say what
   would make it faster even if out of scope.
3. **Same verdicts.** The runner prints the same per-canary verdict lines (expected, got, ok) as before, and every
   canary is still graded by `rigor grade` with its own clone. Add a check that compares a run's verdict set to the
   expectations exactly as today; a canary that errors is a miss, never a skip.
4. **Report the resources** of a whole pack run, before and after: wall, sum of worker time, peak local RSS and
   local CPU seconds (`/usr/bin/time -v` or `/proc`), disk used by scratch at peak.

## Acceptance
```sh
selftest/canaries.sh            # 0 live misses, wall <= 180 s on this farm (state the measured number)
selftest/canaries.sh            # second run, warm
selftest/gate.sh
```
