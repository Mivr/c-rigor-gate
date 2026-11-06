# T022: per-run build stats from Buck2 event logs (remote CPU, cache hits, bytes over the wire)

Repo: `Mivr/c-rigor-gate`. Branch `task/T022`. Read `AGENTS.md`, `docs/toolchain.md`, `docs/grade.md`, `tools/buck2` (the pinned
client), and how `selftest/*.sh` and `rigor grade` invoke Buck2. **In parallel:** T011, T013, T021, and annas-c A028. Touch none of
their files.

## Why
The orchestrator tracks every lane's cost (goal: agents fast and cheap). A local process sampler sees only the Buck2 client and
daemon; the real work runs on the NativeLink RE farm. Every Buck2 command already writes an event log under
`buck-out/log/` (for example `buck2 log what-ran`, `buck2 log summary` or the raw `.pb.zst`/`.json-lines`, whichever this pinned build
supports). Turn those logs into numbers.

## Allowed paths
`tools/lanes/**` (new), `docs/lanes.md` (new), `gate/tests/test_lanes*.py` (new).

## Requirements
1. `tools/lanes/buck2_stats.py <project-root> [--since <unix ts>] [--json]`, Python stdlib only. It reads every Buck2 command log in
   that root's `buck-out/log` (and any isolation dirs) and prints one JSON row per command: start and end time, the command line
   (arguments only, redacted to 200 chars), exit code, wall time, actions total, executed remote, executed local, cache hits
   (action cache and remote dep-file), cache misses, the sum and max of remote execution wall and CPU time per action (whatever the
   log carries: queue, worker wall, user and system time), bytes uploaded to and downloaded from the CAS, materialized bytes, and the
   longest actions (top 5 by worker time, with their category and identifier).
2. Use the pinned client's own decoder (`tools/buck2 log ... --format json` or similar) if it exists. Otherwise decode the event
   log yourself, stdlib only (zstd: if no stdlib decoder exists, use `tools/buck2 log show` to stream JSON). Document which.
3. Work on real data: run it over this worktree after a couple of `selftest/` runs, over a copy of a grade work dir, and over the
   annas-c worktree `/var/tmp/src/annas-c` (read-only: point it at a fresh clone in `/var/tmp/cache/T022/` and build there first).
   Report the numbers.
4. Unit tests over small recorded fixtures (a short real log, trimmed), covering every field and a log of a failed command.

## Acceptance
```sh
python3 -I tools/lanes/buck2_stats.py . --json | head
selftest/gate.sh
```
Report the fields available in this Buck2 build, the fields missing, and example rows from the three real sources.
