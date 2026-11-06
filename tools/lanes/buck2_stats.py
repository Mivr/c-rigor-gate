#!/usr/bin/env python3
"""Per-command build stats from Buck2 event logs (T022). Python stdlib only.

    python3 -I tools/lanes/buck2_stats.py <project-root> [--since <unix ts>] [--json] [--buck2 <path>]

Reads every Buck2 command event log under <project-root>/buck-out/*/log (all isolation dirs) and prints
one JSON row per command.  Decoding: the logs are `*_events.pb.zst` (protobuf + zstd); Python has no
zstd decoder, so each is streamed through the pinned client, `tools/buck2 log show <file>` (JSON lines).
Uncompressed `*.json-lines` logs are read directly.  See docs/lanes.md for the field reference and for
which fields this Buck2 build does not provide.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

ARGS_MAX = 200
TOP_N = 5
LOG_SUFFIXES = ("_events.pb.zst", ".json-lines")


def find_logs(root):
    """Command event-log files below root/buck-out/*/log, oldest first (names start with a timestamp)."""
    found = []
    for log_dir in glob.glob(os.path.join(root, "buck-out", "*", "log")):
        for name in os.listdir(log_dir):
            path = os.path.join(log_dir, name)
            if name.endswith(LOG_SUFFIXES) and os.path.isfile(path):
                found.append(path)
    return sorted(found, key=lambda p: (os.path.basename(p), p))


def default_buck2():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "buck2")


def decode(path, root, buck2):
    """Return the log's JSON records (list of dict). Raises RuntimeError if the client cannot decode it."""
    if path.endswith(".json-lines"):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        proc = subprocess.run([buck2, "log", "show", path], cwd=root, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError("buck2 log show failed ({}): {}".format(proc.returncode, proc.stderr.strip()[-200:]))
        text = proc.stdout
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def read_report(path, trace_id):
    """exit_code from <log dir>/<trace id>/command_report.json, or None when it is not there."""
    rep = os.path.join(os.path.dirname(path), trace_id or "-", "command_report.json")
    try:
        with open(rep, encoding="utf-8") as fh:
            code = json.load(fh).get("exit_code")
    except (OSError, ValueError):
        return None
    return code if isinstance(code, int) else None


def ts(pair):
    return pair[0] + pair[1] / 1e9


def command_of(report):
    """The deciding command of an action: the last one (earlier ones are cache probes / retries)."""
    cmds = report.get("commands") or []
    return cmds[-1] if cmds else None


def classify(cmd):
    """(kind, cache_type, details) for one command report. kind: cache_hit | remote | local | other."""
    if cmd is None:
        return "none", None, None
    kind = cmd["details"]["command_kind"]["command"]
    name = next(iter(kind), "")
    body = kind.get(name) or {}
    if name == "RemoteCommand":
        if body.get("cache_hit"):
            return "cache_hit", body.get("cache_hit_type"), body
        return "remote", None, body
    if name in ("LocalCommand", "WorkerCommand"):
        return "local", None, body
    return "other:" + name, None, body


def worker_fields(cmd, body):
    """Per-command timings in microseconds as the log carries them (None where absent)."""
    meta = cmd["details"].get("metadata") or cmd.get("metadata") or {}
    return {
        "wall": meta.get("wall_time_us"),
        "worker": meta.get("execution_time_us"),
        "queue": meta.get("queue_duration_us") if meta.get("queue_duration_us") is not None
        else (body or {}).get("queue_time_us"),
        "input_mat": meta.get("input_materialization_duration_us"),
    }


def label_of(key):
    owner = (key or {}).get("owner") or {}
    for variant in owner.values():
        lab = (variant or {}).get("label")
        if lab:
            return "{}:{}".format(lab.get("package"), lab.get("name"))
    return None


class Acc:
    """Accumulates one command's numbers."""

    def __init__(self):
        self.actions = 0
        self.by_exec = {"remote": 0, "local": 0, "cache_hit": 0, "none": 0, "other": 0}
        self.cache_types = {}
        self.dep_file_outcomes = {}
        self.failed_actions = 0
        self.test_runs = 0
        self.timed = []
        self.sums = {"wall": 0, "worker": 0, "queue": 0, "input_mat": 0}
        self.maxs = {"wall": 0, "worker": 0, "queue": 0, "input_mat": 0}
        self.cached_worker_us = 0
        self.output_bytes = 0
        self.reupload_bytes = 0
        self.reupload_digests = 0
        self.snapshots = []

    def add_command(self, report, category, ident, owner, is_test=False):
        self.actions += 1
        self.test_runs += 1 if is_test else 0
        self.failed_actions += 1 if report.get("failed") else 0
        cmd = command_of(report)
        kind, cache_type, body = classify(cmd)
        if kind in ("remote", "local"):
            self.output_bytes += report.get("output_size") or 0
        if kind.startswith("other:"):
            self.by_exec["other"] += 1
            return
        self.by_exec[kind] += 1
        if kind == "none":
            return
        times = worker_fields(cmd, body)
        if kind == "cache_hit":
            key = "cache_hit_type_{}".format(cache_type)
            self.cache_types[key] = self.cache_types.get(key, 0) + 1
            self.cached_worker_us += times["worker"] or 0
            return
        for name in self.sums:
            val = times[name] or 0
            self.sums[name] += val
            self.maxs[name] = max(self.maxs[name], val)
        self.timed.append((times["worker"] or 0, category, ident, owner, kind))


def top_actions(timed):
    ranked = sorted(timed, key=lambda t: (-t[0], str(t[1]), str(t[2])))[:TOP_N]
    return [{"worker_us": w, "category": c, "identifier": i, "target": o, "executor": k}
            for (w, c, i, o, k) in ranked]


def feed(acc, rec):
    """Fold one event record into acc; returns (first_ts, last_ts, command_duration_us) contributions."""
    ev = rec.get("Event")
    if not ev:
        return None, None, None
    when = ts(ev["timestamp"])
    data = ev["data"]
    dur = None
    if "SpanEnd" in data:
        end = data["SpanEnd"]
        name, body = next(iter(end["data"].items()))
        if name == "ActionExecution":
            nm = body.get("name") or {}
            acc.add_command(body, nm.get("category"), nm.get("identifier"), label_of(body.get("key")))
        elif name == "TestRun":
            suite = body.get("suite") or {}
            rep = body.get("command_report")
            acc.add_command({"commands": [rep] if rep else [], "failed": bool(rep and rep["details"].get("signed_exit_code") not in (0, None))}, "test", suite.get("suite_name"),
                            label_of({"owner": {"TargetLabel": {"label": (suite.get("target_label") or {}).get("label")}}}),
                            is_test=True)
        elif name == "ReUpload":
            acc.reupload_bytes += body.get("bytes_uploaded") or 0
            acc.reupload_digests += body.get("digests_uploaded") or 0
        elif name == "MatchDepFiles":
            key = "outcome_{}".format(body.get("outcome"))
            acc.dep_file_outcomes[key] = acc.dep_file_outcomes.get(key, 0) + 1
        elif name == "Command":
            dur = end.get("duration_us")
    elif "Instant" in data:
        inst = data["Instant"]["data"]
        if "Snapshot" in inst:
            acc.snapshots.append(inst["Snapshot"])
    return when, when, dur


def summarize(path, records, redact=ARGS_MAX):
    """One row from a decoded log."""
    header = records[0] if records and "command_line_args" in records[0] else {}
    trace = header.get("trace_id")
    acc = Acc()
    first, last, cmd_dur = None, None, None
    for rec in records:
        lo, hi, dur = feed(acc, rec)
        if lo is not None:
            first = lo if first is None else min(first, lo)
            last = hi if last is None else max(last, hi)
        cmd_dur = dur if dur is not None else cmd_dur
    start = ts(header["start_time"]) if header.get("start_time") else first
    # wall = client start (log header) to the last event; command = the daemon's Command span (no connect time).
    wall_us = int(round((last - start) * 1e6)) if start is not None and last is not None else None
    end = last
    argv = " ".join((header.get("command_line_args") or [])[1:])
    if len(argv) > redact:
        argv = argv[:redact - 3] + "..."
    snaps = acc.snapshots
    down = up = lookups = None
    if len(snaps) >= 2:
        # Snapshot counters are cumulative over the daemon's life: the per-command figure is last - first.
        down = snaps[-1].get("re_download_bytes", 0) - snaps[0].get("re_download_bytes", 0)
        up = snaps[-1].get("re_upload_bytes", 0) - snaps[0].get("re_upload_bytes", 0)
        lookups = snaps[-1].get("re_action_cache_started", 0) - snaps[0].get("re_action_cache_started", 0)
    return {
        "log": os.path.basename(path),
        "trace_id": trace,
        "start_unix": start,
        "end_unix": end,
        "args": argv,
        "exit_code": read_report(path, trace),
        "wall_ms": None if wall_us is None else wall_us // 1000,
        "command_ms": None if cmd_dur is None else cmd_dur // 1000,
        "actions_total": acc.actions,
        "test_runs": acc.test_runs,
        "failed_actions": acc.failed_actions,
        "executed_remote": acc.by_exec["remote"],
        "executed_local": acc.by_exec["local"],
        "cache_hits": acc.by_exec["cache_hit"],
        "cache_hits_by_type": acc.cache_types,
        "cache_misses": acc.by_exec["remote"],
        "re_action_cache_lookups": lookups,
        "dep_file_match_outcomes": acc.dep_file_outcomes,
        "actions_without_command": acc.by_exec["none"],
        "actions_other_executor": acc.by_exec["other"],
        "remote_worker_us_sum": acc.sums["worker"],
        "remote_worker_us_max": acc.maxs["worker"],
        "remote_queue_us_sum": acc.sums["queue"],
        "remote_queue_us_max": acc.maxs["queue"],
        "remote_wall_us_sum": acc.sums["wall"],
        "remote_wall_us_max": acc.maxs["wall"],
        "remote_input_materialization_us_sum": acc.sums["input_mat"],
        "remote_cpu_user_us": None,
        "remote_cpu_system_us": None,
        "cached_worker_us_sum": acc.cached_worker_us,
        "cas_uploaded_bytes": up,
        "cas_downloaded_bytes": down,
        "reupload_bytes": acc.reupload_bytes,
        "reupload_digests": acc.reupload_digests,
        "executed_output_bytes": acc.output_bytes,
        "materialized_bytes": None,
        "longest_actions": top_actions(acc.timed),
    }


def collect(root, since=None, buck2=None):
    """Rows for every log under root (oldest first). Undecodable logs yield an error row."""
    buck2 = buck2 or default_buck2()
    rows = []
    for path in find_logs(root):
        try:
            records = decode(path, root, buck2)
            row = summarize(path, records)
        except (RuntimeError, ValueError, KeyError, OSError) as err:
            row = {"log": os.path.basename(path), "error": str(err)[:300], "start_unix": None}
        if since is not None and (row.get("start_unix") is None or row["start_unix"] < since):
            continue
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", help="project root (the directory that holds buck-out/)")
    ap.add_argument("--since", type=float, default=None, help="only commands that started at or after this unix time")
    ap.add_argument("--json", action="store_true", help="one JSON object per line (default: human table)")
    ap.add_argument("--buck2", default=None, help="client used to decode .pb.zst logs (default: tools/buck2)")
    ns = ap.parse_args(argv)
    rows = collect(os.path.abspath(ns.root), ns.since, ns.buck2)
    for row in rows:
        if ns.json:
            print(json.dumps(row, sort_keys=True))
        else:
            print(render(row))
    return 0


def render(row):
    if "error" in row:
        return "{}  ERROR {}".format(row["log"], row["error"])
    return ("{log}  exit={exit_code} wall={wall_ms}ms actions={actions_total} remote={executed_remote} "
            "local={executed_local} hit={cache_hits} miss={cache_misses} worker_sum={remote_worker_us_sum}us "
            "up={cas_uploaded_bytes}B down={cas_downloaded_bytes}B  {args}").format(**row)


if __name__ == "__main__":
    sys.exit(main())
