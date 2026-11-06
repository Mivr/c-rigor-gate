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
        {"rc": N, "timed_out": B, "results": the normalised JSON Lines text or null}. A failed link is an
        error (never a verdict). What is stored is a deterministic function of the verdict: see `normalise_*`.
    tool.py collect --manifest M --out F
        Merge the per-mutant files named by the manifest into one report. A mutant whose -O2 object equals
        the baseline's or an earlier mutant's also carries `compile.o0`, the result of compiling it again
        at -O0 (the compile command is the same with `-O0` appended); every source carries `baseline_o0`.
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
# `rigor mutants` calls a failed test "killed by an assert" when its reason starts like this (the counts and the
# detail after it come from the program under test, and from garbage when a mutant reads uninitialised memory).
CHECK_FAILURE = re.compile(r"[0-9]+ of [0-9]+ checks failed; first: ")
NORMAL_CHECK_FAILURE = "0 of 0 checks failed; first: "
NUMBER = re.compile(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)")
UNPARSABLE_LINE = "!"


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


def normalise_reason(reason):
    """A reason that depends only on the kind of failure and on the check that failed, never on values.

    A failed check ("N of M checks failed; first: file:line: CHECK_X(a, b): got != want") keeps the place and
    the text of the check and loses the counts and the observed values; the prefix stays in a form the verdict
    code still recognises. Every other reason ("killed by signal 11", "timeout after 10 s", ...) keeps its
    words and loses its numbers. No reason is ever turned into, or out of, a check failure."""
    found = CHECK_FAILURE.match(reason)
    if found is None:
        return NUMBER.sub("#", reason)
    detail = reason[found.end():]
    cut = detail.find("): ")
    if cut >= 0:
        detail = detail[:cut + 1]
    return NORMAL_CHECK_FAILURE + detail


def normalise_results(text):
    """The ctest JSON Lines of one mutant run without anything that comes from uninitialised memory:
    status and the test id are kept, `asserts` becomes 0 or 1 (the verdict code only asks for at least one),
    the reason is normalised. A line that is not one JSON object stays a line that does not parse."""
    lines = []
    for raw in text.split("\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            lines.append(UNPARSABLE_LINE)
            continue
        if isinstance(obj, dict) and "id" in obj and isinstance(obj.get("asserts"), int) \
                and not isinstance(obj["asserts"], bool):
            obj["asserts"] = min(obj["asserts"], 1) if obj["asserts"] >= 0 else obj["asserts"]
            if isinstance(obj.get("reason"), str):
                obj["reason"] = normalise_reason(obj["reason"])
        lines.append(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return "".join(line + "\n" for line in lines)


def normalise_rc(rc, timed_out):
    """The exit status as far as it decides a verdict: 0 or 1 from the test binary, the timeout kill, or
    -1 for any other way of dying (which signal or status can depend on garbage)."""
    if timed_out:
        return -signal.SIGKILL
    return rc if rc in (0, 1) else -1


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
        write_json(args.out, {"rc": normalise_rc(rc, timed_out), "timed_out": timed_out,
                              "results": None if text is None else normalise_results(text)})


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
                        "baseline": read_json(entry["baseline"]),
                        "baseline_o0": read_json(entry["baseline_o0"]), "original": read_json(entry["original"])})
        extra = manifest["mutants"].get(entry["rel"], {})
        for mutant in gen["mutants"]:
            item = dict(mutant)
            item["compile"] = read_json(extra[mutant["id"]]["info"])
            if "o0" in extra[mutant["id"]]:  # only a candidate for equivalent / duplicate has one (B15)
                low = read_json(extra[mutant["id"]]["o0"])
                item["compile"]["o0"] = {"status": low["status"], "hash": low["hash"]}
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
