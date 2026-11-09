#!/usr/bin/env python3
"""Numbers of one Buck2 build from its event log (T124 measurements). Python 3 stdlib only.

    schema_measure.py --buck TOOLS_BUCK2 --cwd DIR LOG.pb.zst...

For each log: executed actions (a command ran, no cache hit; actions of the `toolchains` cell, the fetched
compiler and sysroot, are left out), the sum of their wall time and of their execution time on the worker (the RE
workers here have one CPU, so execution time is the nearest thing to CPU seconds the event log has: it carries no
instruction counts), and the same per action category.
"""

import json
import subprocess
import sys


def stats(buck, cwd, log):
    text = subprocess.run([buck, "log", "show", log], cwd=cwd, capture_output=True, text=True, check=True).stdout
    total = {"actions": 0, "wall_s": 0.0, "exec_s": 0.0}
    cats = {}
    for line in text.splitlines():
        if '"ActionExecution"' not in line or '"SpanEnd"' not in line:
            continue
        end = json.loads(line)["Event"]["data"]["SpanEnd"]
        act = end["data"]["ActionExecution"]
        owner = json.dumps(act["key"]["owner"])
        if "toolchains//" in owner and "biz//" not in owner or not act.get("commands"):
            continue
        ran = [c for c in act["commands"] if not c["details"]["command_kind"]["command"].get("RemoteCommand", {}).get("cache_hit")]
        if not ran or act.get("execution_kind") in (None, 0):
            continue
        cat = act["name"]["category"]
        wall = act.get("wall_time_us", 0) / 1e6
        exe = sum(c["details"]["metadata"].get("execution_time_us") or 0 for c in ran) / 1e6
        row = cats.setdefault(cat, {"actions": 0, "wall_s": 0.0, "exec_s": 0.0})
        for r in (row, total):
            r["actions"] += 1
            r["wall_s"] += wall
            r["exec_s"] += exe
    return {"total": total, "by_category": cats}


if __name__ == "__main__":
    args = sys.argv[1:]
    buck, cwd, logs = args[args.index("--buck") + 1], args[args.index("--cwd") + 1], args[args.index("--cwd") + 2:]
    for log in logs:
        print(json.dumps({log: stats(buck, cwd, log)}, sort_keys=True))
