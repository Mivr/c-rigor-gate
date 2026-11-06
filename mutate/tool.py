#!/usr/bin/env python3
"""Build-action helpers for `c_mutants` (rules/mutate.bzl). Python 3 stdlib only.

    tool.py compile --spec SPEC --src SRC --src-out F --obj F --info F -- <compiler command>
        Write SRC with the spec's replacement applied to F, compile it (`-c F -o OBJ` appended) and
        write INFO = {"status": "ok", "hash": sha256 of the object} or {"status": "unviable", ...}
        when the compiler rejects it. A compiler crash or a spec that does not match SRC is an error.
    tool.py hash --obj OBJ --out F
        INFO for an object compiled elsewhere.
    tool.py linkrun --out F -- <link command>
        Link (`-o BIN` appended), run `BIN --seed 1 --out RESULTS`, write
        {"rc": N, "results": the JSON Lines text or null}. A failed link is an error (never a verdict).
    tool.py collect --manifest M --out F
        Merge the per-mutant files named by the manifest into one report.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile

RUN_TIMEOUT_SECONDS = 180  # the whole test binary; ctest itself kills one test after 10 s
DETAIL_CHARACTERS = 600
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def write_json(path, obj):
    with open(path, "wb") as handle:
        handle.write(canonical(obj))


def read_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read())


def sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def split_command(argv):
    if "--" not in argv:
        sys.exit("tool.py: missing `--` and a command")
    index = argv.index("--")
    return argv[:index], argv[index + 1:]


def cmd_compile(argv):
    argv, command = split_command(argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("spec", "src", "src-out", "obj", "info"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--strict", dest="strict", action="store_true")
    parser.add_argument("--lenient", dest="strict", action="store_false")
    args = parser.parse_args(argv)
    spec = read_json(args.spec)
    with open(args.src, "rb") as handle:
        data = handle.read()
    begin, end = spec["begin"], spec["end"]
    if data[begin:end] != spec["original"].encode("latin-1"):
        sys.exit("tool.py: the source no longer matches the mutant list at [%d, %d)" % (begin, end))
    mutated = data[:begin] + spec["replacement"].encode("latin-1") + data[end:]
    with open(args.src_out, "wb") as handle:
        handle.write(mutated)
    done = subprocess.run(command + ["-c", args.src_out, "-o", args.obj],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode == 0:
        write_json(args.info, {"status": "ok", "hash": sha256_file(args.obj)})
        return
    if done.returncode < 0 or done.returncode > 1 or args.strict:
        sys.stderr.buffer.write(done.stderr)
        sys.exit("tool.py: the compiler failed with status %d" % done.returncode)
    with open(args.obj, "wb"):
        pass  # a declared output must exist
    detail = ANSI.sub("", done.stderr.decode("utf-8", "replace"))[:DETAIL_CHARACTERS]
    write_json(args.info, {"status": "unviable", "hash": "", "detail": detail})


def cmd_hash(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--obj", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    write_json(args.out, {"status": "ok", "hash": sha256_file(args.obj)})


def run_binary(binary, results):
    """Run a ctest binary in its own process group; (rc, timed_out)."""
    process = subprocess.Popen([binary, "--seed", "1", "--out", results], start_new_session=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        return process.wait(timeout=RUN_TIMEOUT_SECONDS), False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return -signal.SIGKILL, True


def cmd_linkrun(argv):
    argv, command = split_command(argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="mutant-") as scratch:
        binary = os.path.join(scratch, "bin")
        done = subprocess.run(command + ["-o", binary], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            sys.stderr.buffer.write(done.stderr)
            sys.exit("tool.py: linking failed with status %d" % done.returncode)
        results = os.path.join(scratch, "results.jsonl")
        rc, timed_out = run_binary(binary, results)
        text = None
        if os.path.isfile(results):
            with open(results, "rb") as handle:
                text = handle.read().decode("utf-8", "replace")
        write_json(args.out, {"rc": rc, "timed_out": timed_out, "results": text})


def cmd_collect(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    manifest = read_json(args.manifest)
    sources = []
    mutants = []
    for entry in manifest["sources"]:
        gen = read_json(entry["gen"])
        sources.append({"file": gen["file"], "sha256": gen["sha256"],
                        "definitions": gen["definitions"], "functions": gen["functions"],
                        "skipped": gen["skipped"], "hidden": gen["hidden"],
                        "baseline": read_json(entry["baseline"]), "original": read_json(entry["original"])})
        extra = manifest["mutants"].get(entry["rel"], {})
        for mutant in gen["mutants"]:
            item = dict(mutant)
            item["compile"] = read_json(extra[mutant["id"]]["info"])
            item["runs"] = {test: read_json(path) for test, path in extra[mutant["id"]]["runs"].items()}
            mutants.append(item)
    baseline = {test: read_json(path) for test, path in manifest["baseline_runs"].items()}
    write_json(args.out, {"schema": 1, "label": manifest["label"], "tests": manifest["tests"],
                          "sources": sources, "baseline_runs": baseline, "mutants": mutants})


COMMANDS = {"compile": cmd_compile, "hash": cmd_hash, "linkrun": cmd_linkrun, "collect": cmd_collect}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("usage: tool.py {%s} ..." % "|".join(COMMANDS))
    COMMANDS[sys.argv[1]](sys.argv[2:])
