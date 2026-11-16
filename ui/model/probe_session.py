"""The runner of `c_ui_probe_session` (rules/ui.bzl, docs/ui-model.md "`c_ui_probe_session`"). Gate-owned, stdlib only.

    python3 -I -B probe_session.py --probe BIN --session IN --expected OUT --id ID --label LABEL
                                   --out RESULTS --report REPORT --verdict VERDICT

Runs the probe binary BIN (built by a `c_ui_probe`) once with the bytes of IN on stdin and an environment of the
sanitizer variables only (rules/ui.bzl sets them, as for a `c_test`). The session passes when all hold:

* IN ends with the line `quit` (so the probe's exit status must be 0: no protocol error, `quit` ended the session);
* the probe exits with status 0 (a death by signal is a failure, never an error of the runner);
* the probe writes nothing on stderr;
* its stdout is byte-identical to OUT.

Reads are bounded: stdout up to len(OUT) + 64 KiB, stderr up to 64 KiB, the whole run up to 600 s; past any of them the
probe is killed and the session FAILS with the reason (a recorded failing verdict, never a hang or an unbounded read).

Writes RESULTS in the JSON Lines of the `ctest` framework (one record `{"id": ID, "status": "pass"|"fail", "asserts": 4,
"reason": ...}` and the summary; gate/rigor_lib/results_parse.py), REPORT (what a person reads: every failed check, and
for a stdout difference the first differing line with its number) and VERDICT (`pass` or `fail`). Exit status 0 when
the three files are written, whatever the verdict; 2 on a usage or I/O error of the runner (the build action fails).
"""

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time

TIMEOUT_S = 600
STDOUT_SLACK = 65536      # stdout may exceed the expected transcript by this much before the probe is killed
STDERR_CAP = 65536        # likewise stderr (which must be empty anyway)
SHOW_BYTES = 512          # a line in the report: at most this many bytes of it, and the report says so
CHECKS = 4                # ends-in-quit, exit status, stderr, stdout
ID = re.compile(r"[A-Za-z0-9_.+:-]+/[A-Za-z0-9_.+:-]+")
SAN_VARS = ("ASAN_OPTIONS", "UBSAN_OPTIONS", "LSAN_OPTIONS", "ASAN_SYMBOLIZER_PATH", "LLVM_SYMBOLIZER_PATH")


class Usage(Exception):
    pass


def shown(data):
    """`data` (bytes) for the report: its repr, and how much of it is left out when it is longer than SHOW_BYTES."""
    if len(data) <= SHOW_BYTES:
        return repr(data)
    return "%r (the first %d of %d bytes)" % (data[:SHOW_BYTES], SHOW_BYTES, len(data))


def ends_in_quit(session):
    """The session's last line is exactly `quit`, LF-terminated (nothing, not even an empty line, after it)."""
    return session == b"quit\n" or session.endswith(b"\nquit\n")


def lines(data):
    """The lines of `data` with their LF (a last line without one is kept as it is, so a missing LF shows)."""
    parts = [part + b"\n" for part in data.split(b"\n")]
    parts[-1] = parts[-1][:-1]
    return parts if parts[-1] else parts[:-1]


def first_difference(got, want):
    """None if equal, else the report line of the first line (1-based) where `got` and `want` differ."""
    if got == want:
        return None
    got_lines, want_lines = lines(got), lines(want)
    for number in range(1, max(len(got_lines), len(want_lines)) + 1):
        g = got_lines[number - 1] if number <= len(got_lines) else None
        w = want_lines[number - 1] if number <= len(want_lines) else None
        if g != w:
            g_text = "the end of the output" if g is None else shown(g)
            w_text = "the end of the file" if w is None else shown(w)
            return "stdout line %d differs: got %s, want %s" % (number, g_text, w_text)
    return "stdout differs"   # unreachable: equal line lists join to equal bytes


def judge(session, want, run):
    """The failed checks (empty: the session passes). `run` is (returncode, stdout, stderr) or a str: why it did not run."""
    problems = []
    if not ends_in_quit(session):
        problems.append("the session does not end with the line `quit` (a checked session is a clean one: exit 0)")
    if isinstance(run, str):
        return problems + [run]
    code, out, err = run
    if code < 0:
        problems.append("the probe was killed by signal %d" % -code)
    elif code != 0:
        problems.append("exit status %d, want 0" % code)
    if err:
        problems.append("stderr is not empty (%d bytes): %s" % (len(err), shown(err.split(b"\n")[0])))
    difference = first_difference(out, want)
    if difference is not None:
        problems.append(difference)
    return problems


def collect(proc, caps, deadline):
    """Read the probe's stdout and stderr to their ends, each up to its cap. None when both ended, else why the probe
    is being killed (a cap passed or the deadline): a recorded failing verdict, never an unbounded read."""
    out = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    names = {proc.stdout: "stdout", proc.stderr: "stderr"}
    sel = selectors.DefaultSelector()
    for stream in out:
        sel.register(stream, selectors.EVENT_READ)
    try:
        while sel.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                return out, "the probe did not end within %d s (killed)" % TIMEOUT_S
            for key, _ in sel.select(left):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                out[key.fileobj] += chunk
                if len(out[key.fileobj]) > caps[names[key.fileobj]]:
                    return out, "the probe wrote more than %d bytes on %s (killed)" % (
                        caps[names[key.fileobj]], names[key.fileobj])
        return out, None
    finally:
        sel.close()


def run_probe(probe, session_path, want_len):
    """(returncode, stdout, stderr), or a str: why the run is a failure without an exit status (timeout, a cap)."""
    env = {k: os.environ[k] for k in SAN_VARS if k in os.environ}
    caps = {"stdout": want_len + STDOUT_SLACK, "stderr": STDERR_CAP}
    deadline = time.monotonic() + TIMEOUT_S
    try:
        with open(session_path, "rb") as stdin:
            proc = subprocess.Popen([probe], stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    except OSError as exc:
        raise Usage("cannot run the probe %s: %s" % (probe, exc)) from exc
    try:
        out, why = collect(proc, caps, deadline)
        if why is None:
            try:
                code = proc.wait(timeout=max(deadline - time.monotonic(), 0.001))
            except subprocess.TimeoutExpired:
                why = "the probe did not end within %d s (killed)" % TIMEOUT_S
        if why is not None:
            return why
        return code, bytes(out[proc.stdout]), bytes(out[proc.stderr])
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def read(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise Usage("cannot read %s: %s" % (path, exc)) from exc


def write(path, data):
    try:
        with open(path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise Usage("cannot write %s: %s" % (path, exc)) from exc


def outputs(args, problems, want):
    """(results, report, verdict) bytes."""
    status = "fail" if problems else "pass"
    record = {"id": args.id, "status": status, "asserts": CHECKS}
    if problems:   # the results format caps a reason at 1024 characters: a longer one says where the rest is
        first = problems[0]
        record["reason"] = first if len(first) <= 1024 else first[:990] + " ... (cut here: see the report)"
    results = (json.dumps(record, sort_keys=True) + "\n"
               + json.dumps({"summary": {"total": 1, "passed": 0 if problems else 1}}, sort_keys=True) + "\n")
    if problems:
        report = "c_ui_probe_session %s: FAIL\n" % args.label + "".join("  %s\n" % p for p in problems)
    else:
        report = "c_ui_probe_session %s: PASS (%d bytes, %d lines match %s)\n" % (
            args.label, len(want), want.count(b"\n"), args.expected)
    return results.encode(), report.encode(), status.encode() + b"\n"


def main(argv):
    parser = argparse.ArgumentParser(prog="probe_session.py", allow_abbrev=False)
    for flag in ("--probe", "--session", "--expected", "--id", "--label", "--out", "--report", "--verdict"):
        parser.add_argument(flag, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        if not ID.fullmatch(args.id):
            raise Usage("bad test id %r" % args.id)
        session, want = read(args.session), read(args.expected)
        problems = judge(session, want, run_probe(args.probe, args.session, len(want)))
        results, report, verdict = outputs(args, problems, want)
        write(args.out, results)
        write(args.report, report)
        write(args.verdict, verdict)
    except Usage as exc:
        print("probe_session: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
