# Per-run Buck2 stats (T022)

`tools/lanes/buck2_stats.py <project-root> [--since <unix ts>] [--json] [--buck2 <client>]` turns the event logs
Buck2 writes for every command into one row per command, so the orchestrator can see what a lane really cost on
the RE farm (a process sampler sees only the client and the daemon). Python 3 stdlib only.

```sh
python3 -I tools/lanes/buck2_stats.py . --json          # one JSON object per line, oldest command first
python3 -I tools/lanes/buck2_stats.py . --since 1793974400   # human table, only commands started after that time
```

## Where the data comes from

- Logs: `<root>/buck-out/*/log/*_events.pb.zst` (every isolation dir; this repo allows only `v2`) and `*.json-lines`.
- Decoder: **the pinned client's own**, `tools/buck2 log show <file>`, which streams the log as JSON lines. Python
  has no zstd decoder, so `.pb.zst` is never parsed directly. `*.json-lines` (uncompressed) is read directly (the
  test fixtures are in that form). A log the client cannot decode becomes a row `{"log", "error"}`; the rest go on.
- Exit code: `<log dir>/<trace id>/command_report.json` (`exit_code`), which Buck2 writes next to the log.
  `null` if that file is gone. (`Command.is_success` in the log is not usable: a passing `buck2 test //examples/...`
  has `is_success: false`.)
- `--buck2` defaults to `tools/buck2` beside the script. For another root (a clone of a product) pass that
  tree's own pinned wrapper, e.g. `--buck2 <tree>/gate/tools/buck2`.

**Logs are pruned by Buck2.** After about a dozen commands the oldest `*_events.pb.zst` files disappear
(observed: the first two logs of a session were gone after ~12 later commands) while the small
`<trace id>/command_report.json` directories stay. Run the tool right after the work you want to measure (or
use `--since`), not days later.

## Row fields

All times are microseconds (`_us`) or milliseconds (`_ms`) as named; bytes are bytes. Anything the log does
not carry is `null`, never `0`.

| Field | Meaning and source |
|---|---|
| `log`, `trace_id` | file name; trace id from the log header |
| `start_unix`, `end_unix` | client start (header `start_time`) and the timestamp of the last event |
| `args` | command line without the binary path, truncated to 200 chars (`...` marks truncation) |
| `exit_code` | from `command_report.json` (see above) |
| `wall_ms` | `end_unix - start_unix`: what the caller waited, including daemon connect/start |
| `command_ms` | the daemon's `Command` span (without client start and connect), `null` if absent |
| `actions_total` | `ActionExecution` spans plus `TestRun` spans (a test execution is a remote action) |
| `test_runs` | the `TestRun` spans among them |
| `failed_actions` | actions with `failed: true`, plus test runs with non-zero exit |
| `executed_remote` / `executed_local` | the action's deciding (last) command is a `RemoteCommand` that was not a cache hit / a `LocalCommand` or `WorkerCommand` |
| `cache_hits`, `cache_hits_by_type` | `RemoteCommand.cache_hit == true`; keyed by raw `cache_hit_type` (`cache_hit_type_0` is the action cache; see "Unverified" below) |
| `cache_misses` | remote executions (a miss is an action cache lookup that ended in an execution) |
| `re_action_cache_lookups` | `Snapshot.re_action_cache_started`, last minus first snapshot of the command |
| `dep_file_match_outcomes` | counts of `MatchDepFiles` spans per raw `outcome` code (local dep-file matching) |
| `actions_without_command` | actions that ran no command (`write`, `download_file`, symlink trees, ...) |
| `actions_other_executor` | actions whose command is neither remote nor local (none seen) |
| `remote_worker_us_sum` / `_max` | `metadata.execution_time_us` of executed actions (time on the worker) |
| `remote_queue_us_sum` / `_max` | `metadata.queue_duration_us` (else `RemoteCommand.queue_time_us`) |
| `remote_wall_us_sum` / `_max` | `metadata.wall_time_us`: client-observed, includes queue, upload, download |
| `remote_input_materialization_us_sum` | `metadata.input_materialization_duration_us` |
| `cached_worker_us_sum` | the `execution_time_us` recorded for cache hits: the **original** worker time the cache saved, not time spent now |
| `cas_uploaded_bytes` / `cas_downloaded_bytes` | `Snapshot.re_upload_bytes` / `re_download_bytes`, last minus first snapshot of the command |
| `reupload_bytes`, `reupload_digests` | sum over `ReUpload` spans (bytes of inputs the command uploaded) |
| `executed_output_bytes` | `output_size` of executed (not cache-hit) actions |
| `longest_actions` | top 5 executed actions by worker time: `worker_us`, `category`, `identifier`, `target`, `executor` |

Sums and maxima cover executed actions only: a cache hit costs no worker time now. Test runs are included with
category `test`.

## What this Buck2 build does not provide (checked on real logs)

- **Remote CPU time (user / system): not provided.** `execution_stats.cpu_instructions_user`,
  `cpu_instructions_kernel`, `userspace_events` and `kernel_events` are `null` for RE commands, and
  `memory_peak` is `0`. `remote_cpu_user_us` and `remote_cpu_system_us` are always `null`. The best proxy is
  `remote_worker_us_*` (worker wall time); the platform asks for `cpu_count=1`, so on this farm worker time is also
  an upper bound of one core's use per action.
- **Materialized bytes: not provided.** There are no per-artifact materialization byte events in this build: a
  build that materializes an output has only a `FinalMaterialization` span (no size), `buck2 log what-materialized`
  prints nothing, and `buck2 log summary` shows `Total materialized: 0B`. `materialized_bytes` is always `null`.
  `executed_output_bytes` is the closest figure (bytes the executed actions produced), not what was copied locally.
- **Per-command CAS bytes are a difference of daemon counters.** `Snapshot` counters are cumulative for the
  daemon's life. `buck2 log summary` prints the absolute last value (an empty command shows `Total downloaded:
  411KiB`), so its figure is not per-command. We use last minus first snapshot, which is exact up to the
  few snapshots at command start. `null` when a log has fewer than two snapshots. Commands that overlap in one
  daemon would share the counters, and the deltas would then overlap too (not checked).
- `Total uploaded` of the summary is the same counter; `reupload_bytes` is a separate, narrower measure.
- No per-action CPU, no worker hostname (`hostname` is `null` or a container id), no queue time for cache hits.
- Cache hits report the original worker time (`cached_worker_us_sum`); there is no "time saved" accounting beyond it.

## Unverified mappings

`cache_hit_type` is reported raw. In the logs seen, `0` is always an action cache hit and a non-hit carries `2`.
The Buck2 value for a remote dep-file cache hit is believed to be `1` but **was never observed**, so it is not
labelled. Likewise `MatchDepFiles.outcome` is only ever seen as `1`. The `ActionExecution.execution_kind` enum is
not used (classification uses the command kind instead).

## Tests

`gate/tests/test_lanes.py`: trimmed real logs (`tools/lanes/fixtures/log`, recorded 2026-11-06 from a passing
`test`, an all-cache-hit `build`, and a `build` whose compile failed with exit 3) and synthetic records for the
shapes this farm has not produced yet (local and worker commands, dep-file cache hits, failed test runs). The
fixture logs keep every executed action and two command-less ones, so their counts are smaller than the live
logs they were cut from.

# Waiting on long jobs (T042)

Agents are Claude Code subagents. A subagent is not re-invoked when its background shell finishes: ending its turn
ends the task. So it must wait with a **blocking** call, and that call must return before the harness takes it away.
`tools/job` (Python 3 stdlib, Linux) starts a long command detached and lets the agent wait on it with one blocking
call per ~2-3 minutes, instead of `sleep`/`until` loops, `tail` peeks or a watcher that can die.

```sh
TMPDIR=/var/tmp/cache/T042/tmp tools/job run --deadline 1800 gate -- selftest/gate.sh
TMPDIR=/var/tmp/cache/T042/tmp tools/job wait gate              # Bash default timeout: blocks up to 110 s
TMPDIR=/var/tmp/cache/T042/tmp tools/job wait gate --max 170    # only with the Bash tool's timeout: 600000
TMPDIR=/var/tmp/cache/T042/tmp tools/job status gate            # never blocks (same as wait --max 0)
TMPDIR=/var/tmp/cache/T042/tmp tools/job list
```

## Harness measurements (2026-11-06, from a contributor subagent session on sb-ws)

| Call | What happened |
|---|---|
| foreground Bash, `timeout: 600000`, a 420 s command | moved to the background **after 180 s** ("Command was moved to the background ... after running for 180s"); R007 confirmed |
| foreground Bash, no `timeout` (default 120 s), a 150 s command | moved to the background **after 120 s** ("did not complete within its 120s timeout and was moved to the background"), not killed |
| foreground Bash, `timeout: 600000`, `tools/job wait --max 170` | stayed in the foreground and returned after 170 s (`running 173s`, exit 124) |

So a foreground call blocks at most **min(timeout, 180 s)**. What happens to an auto-backgrounded call: the command
keeps running to the end (the 420 s and 150 s loops both finished: 42 and 15 ticks, exit 0), its output goes only to
a harness file under the session's `tasks/` directory (nothing reaches the agent unless it reads that file), and a
"completed" notification arrives later as a system event while the agent is still working. A subagent that has
ended its turn by then is never re-invoked (not measurable from inside one: ending the turn ends the task). An
agent that misses this ends up polling the output file, which is what R006/R007 saw.

**The limit chosen:** `wait` defaults to `--max 110` (the 120 s default Bash timeout minus a 10 s margin), so a
plain `tools/job wait NAME` never gets backgrounded. With `timeout: 600000` on the Bash call, `--max 170` (the 180 s
cut-off minus 10 s) is allowed; anything above 170 is refused, because the harness would background the call.

## Behaviour

- `run [--deadline SECONDS] [--dir DIR] NAME -- CMD [ARG...]`: CMD is executed as an argv, never through a shell
  (write `sh -c '...'` yourself), in a new session, stdin `/dev/null`, stdout and stderr appended to `DIR/NAME/log`,
  with the caller's cwd and environment unchanged. `run` prints one line (name, pid, deadline, log path, the argv
  shell-quoted) and returns at once. A detached runner records `DIR/NAME/job.json` (argv, cwd, start, pid,
  runner pid, deadline) and on exit `DIR/NAME/exit.json` (code, end, killed, signal). At the deadline (default
  3600 s) the runner sends SIGTERM to the job's whole process group, then SIGKILL after 3 s, and records `killed`.
  A NAME whose job is still running is refused; a finished NAME is replaced.
- `wait NAME [--max SECONDS]`: blocks in `flock` on `DIR/NAME/lock`, which the runner holds for the job's whole life,
  so it wakes as soon as the job ends (no polling). While running it prints exactly one line, `running 312s`, and
  exits 124. When done it prints `exit N after S s` (with `(signal N)` if a signal ended it) or
  `KILLED after S s (deadline Ds, exit N)`, then the last 30 lines of the log with ANSI escapes removed (a line
  redrawn with `\r` shows its last state; a line is cut at 400 characters), and exits with the job's code (128+N for
  a signal). A job whose runner died without recording an exit is `LOST ...` (exit 2), never "running forever".
- `status NAME`: `wait --max 0`. `list`: one line per job (name, state, argv).
- `DIR` is `--dir`, else `$TMPDIR/jobs`; without either it refuses. The absolute, normalized DIR must be inside
  `/var/tmp/cache/` and resolve to itself (no symlink anywhere in it); so must `DIR/NAME`. Exit 2 on every tool error.
- Known limit: with a C/POSIX locale (no `LANG`/`LC_ALL`/`LC_CTYPE`), Python's PEP 538 locale coercion sets
  `LC_CTYPE=C.UTF-8` in the tool's own environment, and the job inherits it. Lanes run with `LANG` set, where
  nothing is added.

Tests: `gate/tests/test_job.py` (the real executable as a subprocess, in a fresh directory under `$TMPDIR` when that is
inside `/var/tmp/cache/`, else under `/var/tmp/cache/`) and `gate/tests/test_trajectory_job.py` (the audit side, see
docs/trajectory.md).

## Backlog (T047)

`plan/backlog.md` is generated. Each row is one fragment, `plan/backlog.d/B<N>.md` (header lines `found_by:` and
`fix:`, a blank line, then the one-line gap text; `_header.md` holds the title and table header). Edit a fragment,
then run `python3 -I tools/backlog_fold.py` to rewrite the table; `--check` (also run by `selftest/gate.sh` through
`gate/tests/test_backlog_fold.py`) fails if the table is stale. Two tasks therefore never edit the same file.
**Row ids are assigned by the orchestrator in the task spec**; a task never picks its own next `B<N>`.
