#!/usr/bin/env python3
"""Build-action helpers for `c_mutants` (rules/mutate.bzl). Python 3 stdlib only.

    tool.py compile --spec SPEC --src SRC --src-out F --obj F --info F -- <compiler command>
        Write SRC with the spec's replacement applied to F, compile it (`-c F -o OBJ` appended) and
        write INFO = {"status": "ok", "hash": sha256 of the object} or {"status": "unviable", ...}
        when the compiler rejects it. A compiler crash or a spec that does not match SRC is an error.
    tool.py compile-batch --specs SPECS [--item SRC ID OBJ INFO]... --strict|--lenient -- <compiler command>
        The same for a batch of mutants (T064; of one or more sources): SPECS = {"mutants": [{"id", "begin", "end",
        "original", "replacement"}, ...]}; each `--item` names the source and a mutant of it and where its object
        and INFO go.
        Every mutant is compiled on its own, in its own scratch directory, and a mutant the compiler rejects is
        `unviable` without touching the others. A compiler crash, or a spec that does not match SRC, fails the batch.
    tool.py hash --obj OBJ --out F
        INFO for an object compiled elsewhere.
    tool.py linkrun --out F -- <link command>
        Link (`-o BIN` appended), run `BIN --seed 1 --out RESULTS`, write
        {"rc": N, "timed_out": B, "results": the normalised JSON Lines text or null}. A failed link is an
        error (never a verdict). What is stored is a deterministic function of the verdict: see `normalise_*`.
    tool.py linkrun-batch [--stop-on assert|never] --test NAME N TOBJ1..TOBJN [--test ...]...
                          [--item N OUT OBJ1..OBJN [--prior F]]... -- <link command containing @TEST_OBJECTS@ and @MUTANT_OBJECTS@>
        The same for a batch of mutants (T064) and a group of tests (T121): for each item and each test, in the
        order of the `--test` options, the command is run with `@TEST_OBJECTS@` replaced by the test's objects and
        `@MUTANT_OBJECTS@` by the N objects OBJ1..OBJN (the objects of the mutant's link, in link order). OUT gets
        {"runs": {test: record}}, the record being the one `linkrun` writes. One fresh process and one scratch
        directory per run, one after another; a crash or timeout of one run is only its own record. A failed link
        fails the batch.
        Stop at the first kill (T121): once a run of the mutant failed a check (`stop_kill`: rc 1 and a failed-check
        line; with `--stop-on never` nothing counts) its later runs are not made: they get {"killed_by": TEST} with
        the first killing test. A mutant whose `--prior` file (the group before, same mutant) already holds a kill
        gets {"killed_by": ...} for every test of this group, naming the same test. A skipped run is never a pass:
        `rigor mutants` accepts it only after a run of that very mutant that it judges a failed check itself.
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
NORMAL_CHECK_FAILURE = "0 of 0 checks failed; first: (not stored)"
NUMBER = re.compile(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)")
UNPARSABLE_LINE = "!"
OBJECT_SLOT = "@MUTANT_OBJECTS@"  # where `linkrun-batch` puts the objects of the mutant it runs
TEST_SLOT = "@TEST_OBJECTS@"      # ... and those of the test


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


def compile_mutant(spec, data, command, src_out, obj, info, strict):
    """Write the mutated copy of the source to SRC_OUT, compile it to OBJ and write INFO."""
    begin, end = spec["begin"], spec["end"]
    if data[begin:end] != spec["original"].encode("latin-1"):
        sys.exit("tool.py: the source no longer matches the mutant list at [%d, %d)" % (begin, end))
    mutated = data[:begin] + spec["replacement"].encode("latin-1") + data[end:]
    with open(src_out, "wb") as handle:
        handle.write(mutated)
    done = subprocess.run(command + ["-c", src_out, "-o", obj], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode == 0:
        write_json(info, {"status": "ok", "hash": sha256_file(obj)})
        return
    if done.returncode < 0 or done.returncode > 1 or strict:
        sys.stderr.buffer.write(done.stderr)
        sys.exit("tool.py: the compiler failed with status %d" % done.returncode)
    with open(obj, "wb"):
        pass  # a declared output must exist
    detail = ANSI.sub("", done.stderr.decode("utf-8", "replace"))
    detail = detail.replace(os.path.dirname(src_out) + os.sep, "")[:DETAIL_CHARACTERS]  # no scratch path in a record
    write_json(info, {"status": "unviable", "hash": "", "detail": detail})


def cmd_compile(argv):
    argv, command = split_command(argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("spec", "src", "src-out", "obj", "info"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--strict", dest="strict", action="store_true")
    parser.add_argument("--lenient", dest="strict", action="store_false")
    args = parser.parse_args(argv)
    with open(args.src, "rb") as handle:
        data = handle.read()
    compile_mutant(read_json(args.spec), data, command, args.src_out, args.obj, args.info, args.strict)


def cmd_compile_batch(argv):
    argv, command = split_command(argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--specs", required=True)
    parser.add_argument("--item", nargs=4, action="append", default=[], metavar=("SRC", "ID", "OBJ", "INFO"))
    parser.add_argument("--strict", dest="strict", action="store_true")
    parser.add_argument("--lenient", dest="strict", action="store_false")
    args = parser.parse_args(argv)
    specs = {spec["id"]: spec for spec in read_json(args.specs)["mutants"]}
    for src, mid, obj, info in args.item:
        if mid not in specs:
            sys.exit("tool.py: mutant %s is not in the batch specs" % mid)
        with open(src, "rb") as handle:
            data = handle.read()
        with tempfile.TemporaryDirectory(prefix="mutant-") as scratch:
            compile_mutant(specs[mid], data, command, os.path.join(scratch, os.path.basename(src)), obj, info,
                           args.strict)


def cmd_hash(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--obj", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    write_json(args.out, {"status": "ok", "hash": sha256_file(args.obj)})


def normalise_reason(reason):
    """A reason that depends only on the kind of failure and on the check that failed, never on values.

    A failed check ("N of M checks failed; first: file:line: CHECK_X(a, b): got != want") becomes the constant
    NORMAL_CHECK_FAILURE: the verdict code only asks whether the reason starts like a failed check. Which check
    failed first is not kept either, because when a mutant reads uninitialised memory it depends on the garbage
    (T067). Every other reason ("killed by signal 11", "timeout after 10 s", ...) keeps its words and loses its
    numbers. No reason is ever turned into, or out of, a check failure."""
    if CHECK_FAILURE.match(reason) is None:
        return NUMBER.sub("#", reason)
    return NORMAL_CHECK_FAILURE


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


def link_and_run(command, out):
    """Link COMMAND (`-o BIN` appended) in a fresh scratch directory, run it, write the record to OUT."""
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
        write_json(out, {"rc": normalise_rc(rc, timed_out), "timed_out": timed_out,
                         "results": None if text is None else normalise_results(text)})


def cmd_linkrun(argv):
    argv, command = split_command(argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    link_and_run(command, args.out)


def stop_kill(record):
    """Does this run record kill its mutant for good: the binary exited 1 and a result line is a failed check?
    (`rigor mutants` makes the same call from the stored text, and only a run it calls a failed check justifies a
    skipped one. A crash is not final: the verdict is killed-assert when any test fails a check, so a crash stays
    open to a later check failure.)"""
    if record["rc"] != 1 or record["timed_out"] or not record["results"]:
        return False
    for raw in record["results"].split("\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("status") != "pass" and isinstance(obj.get("reason"), str) \
                and CHECK_FAILURE.match(obj["reason"]):
            return True
    return False


def prior_killer(path):
    """The test that killed the mutant in an earlier group's record file (`--prior`), or None."""
    runs = read_json(path)["runs"]
    for name, record in runs.items():
        if "killed_by" in record:
            return record["killed_by"]
        if stop_kill(record):
            return name
    return None


def parse_group_args(argv):
    """(stop-on, [(test, [objects])], [(objects, out, prior or None)]) of the arguments before `--`."""
    stop, tests, items, index = "assert", [], [], 0
    while index < len(argv):
        flag = argv[index]
        try:
            if flag == "--stop-on":
                stop = argv[index + 1]
                index += 2
            elif flag == "--test":
                count = int(argv[index + 2])
                objects = argv[index + 3:index + 3 + count]
                if count < 0 or len(objects) != count:
                    raise ValueError
                tests.append((argv[index + 1], objects))
                index += 3 + count
            elif flag == "--item":
                count = int(argv[index + 1])
                item = argv[index + 2:index + 3 + count]
                if count < 1 or len(item) != count + 1:
                    raise ValueError
                items.append([item[1:], item[0], None])
                index += 3 + count
            elif flag == "--prior" and items and items[-1][2] is None:
                items[-1][2] = argv[index + 1]
                index += 2
            else:
                sys.exit("tool.py: unexpected argument %r" % flag)
        except (IndexError, ValueError):
            sys.exit("tool.py: bad %s arguments" % flag)
    if stop not in ("assert", "never") or not tests or len({name for name, _ in tests}) != len(tests):
        sys.exit("tool.py: --stop-on assert|never and distinct --test names are needed")
    return stop, tests, [tuple(item) for item in items]


def link_and_record(command):
    """link_and_run's record for COMMAND, as a dict (no file)."""
    with tempfile.TemporaryDirectory(prefix="mutant-") as scratch:
        out = os.path.join(scratch, "record.json")
        link_and_run(command, out)
        return read_json(out)


def cmd_linkrun_batch(argv):
    argv, command = split_command(argv)
    stop, tests, items = parse_group_args(argv)
    for slot in (OBJECT_SLOT, TEST_SLOT):
        if command.count(slot) != 1:
            sys.exit("tool.py: the link command must contain %s exactly once" % slot)
    for objects, out, prior in items:
        killer = None if prior is None or stop == "never" else prior_killer(prior)
        runs = {}
        for name, test_objects in tests:
            if killer is not None:
                runs[name] = {"killed_by": killer}
                continue
            line = []
            for word in command:
                line.extend(test_objects if word == TEST_SLOT else objects if word == OBJECT_SLOT else [word])
            runs[name] = link_and_record(line)
            if stop == "assert" and stop_kill(runs[name]):
                killer = name
        write_json(out, {"runs": runs})


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
            item["runs"] = {}
            for path in extra[mutant["id"]]["runs"]:   # one file per group of tests, in the order of the groups
                item["runs"].update(read_json(path)["runs"])
            mutants.append(item)
    baseline = {test: read_json(path) for test, path in manifest["baseline_runs"].items()}
    write_json(args.out, {"schema": 1, "label": manifest["label"], "tests": manifest["tests"],
                          "sources": sources, "baseline_runs": baseline, "mutants": mutants})


COMMANDS = {"compile": cmd_compile, "compile-batch": cmd_compile_batch, "hash": cmd_hash, "linkrun": cmd_linkrun,
            "linkrun-batch": cmd_linkrun_batch, "collect": cmd_collect}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("usage: tool.py {%s} ..." % "|".join(COMMANDS))
    COMMANDS[sys.argv[1]](sys.argv[2:])
