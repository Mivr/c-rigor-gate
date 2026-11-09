#!/usr/bin/env python3
"""Run actions of the schema mutation engine (T124): the `reach` and `kill` modes of a linked test binary. stdlib only.

    schema_run.py reach --tool TOOL.PY --binary BIN --out F
        Run `BIN --seed 1 --out RESULTS --rigor-mode reach --rigor-reach REACH` once (no mutant active) and write
        {"record": {"rc", "timed_out", "results"}, "reached": [index, ...]}. The record is the one `tool.py linkrun`
        writes for an unmutated run (same normalisation), so it can be compared with the baseline's.
    schema_run.py kill --tool TOOL.PY --binary BIN --mutants F --out F
        F is a JSON list of {"index", "id"}. The binary runs every mutant in a forked child (schema_rt.c) and the
        action writes {"records": {id: {"rc", "timed_out", "results"}}}, one record per mutant, normalised exactly as
        `tool.py linkrun` normalises a run of a relinked mutant.

`TOOL.PY` is mutate/tool.py: its `normalise_*` functions are the single definition of what a stored record is.
"""

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile

RUN_TIMEOUT_SECONDS = 180  # the reach run is the unmutated baseline: the same cap as v1's baseline runs


def load_tool(path):
    spec = importlib.util.spec_from_file_location("mutate_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, obj):
    with open(path, "wb") as handle:
        handle.write((json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode())


def record_of(tool, rc, timed_out, results_path):
    """The record `tool.link_and_run` would store for a run with this exit status and results file."""
    text = None
    if os.path.isfile(results_path):
        with open(results_path, "rb") as handle:
            text = handle.read().decode("utf-8", "replace")
    return {"rc": tool.normalise_rc(rc, timed_out), "timed_out": timed_out,
            "results": None if text is None else tool.normalise_results(text)}


def run_group(command, limit):
    """Run COMMAND in its own session; (rc, timed_out). The whole group is killed at the limit."""
    process = subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return process.wait(timeout=limit), False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return -signal.SIGKILL, True


def cmd_reach(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("tool", "binary", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    tool = load_tool(args.tool)
    with tempfile.TemporaryDirectory(prefix="reach-") as scratch:
        results, reach = os.path.join(scratch, "results.jsonl"), os.path.join(scratch, "reach.txt")
        rc, timed_out = run_group([args.binary, "--seed", "1", "--out", results, "--rigor-mode", "reach",
                                   "--rigor-reach", reach], RUN_TIMEOUT_SECONDS)
        reached = []
        if rc in (0, 1) and not timed_out and not os.path.isfile(reach):
            sys.exit("schema_run.py: the binary finished but wrote no reach file (is it linked with the runtime?)")
        if os.path.isfile(reach):
            with open(reach, encoding="ascii") as handle:
                reached = sorted(int(line) for line in handle.read().split())
        record = record_of(tool, rc, timed_out, results)
    write_json(args.out, {"record": record, "reached": reached})


def read_status(path):
    with open(path, encoding="ascii") as handle:
        rc, timed_out = handle.read().split()
    return int(rc), timed_out == "1"


def cmd_kill(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("tool", "binary", "mutants", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    tool = load_tool(args.tool)
    with open(args.mutants, "rb") as handle:
        mutants = json.loads(handle.read())
    with tempfile.TemporaryDirectory(prefix="kill-") as scratch:
        listing = os.path.join(scratch, "list.txt")
        with open(listing, "w", encoding="ascii") as handle:
            handle.write("".join("%d %s\n" % (m["index"], m["id"]) for m in mutants))
        # The binary kills a mutant at its own adaptive limit; this cap only bounds a binary that stopped working.
        cap = RUN_TIMEOUT_SECONDS * (len(mutants) + 2)
        rc, timed_out = run_group([args.binary, "--seed", "1", "--rigor-mode", "kill", "--rigor-list", listing,
                                   "--rigor-dir", scratch], cap)
        if rc != 0 or timed_out:
            sys.exit("schema_run.py: the kill run failed (rc %d, timed out %s)" % (rc, timed_out))
        records = {}
        for mutant in mutants:
            status = os.path.join(scratch, mutant["id"] + ".st")
            if not os.path.isfile(status):
                sys.exit("schema_run.py: no status for mutant %s: the runtime lost it" % mutant["id"])
            mrc, mtimed = read_status(status)
            records[mutant["id"]] = record_of(tool, mrc, mtimed, os.path.join(scratch, mutant["id"] + ".res"))
    write_json(args.out, {"records": records})


COMMANDS = {"reach": cmd_reach, "kill": cmd_kill}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("usage: schema_run.py {%s} ..." % "|".join(COMMANDS))
    COMMANDS[sys.argv[1]](sys.argv[2:])
