"""Command line front end. Exit 0 = PASS, 1 = FAIL, 2 = internal error."""

import argparse
import os
import sys

from rigor_lib import jsonio
from rigor_lib.findings import GateResult, finding

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

COMMANDS = []  # command modules; each has add_parser(subparsers)


def build_parser():
    parser = argparse.ArgumentParser(prog="rigor", allow_abbrev=False,
                                     description="c-rigor-gate decision kernel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in COMMANDS:
        module.add_parser(subparsers)
    return parser


def gate_handler(run):
    """Wrap a gate's `run(args) -> GateResult` into a handler returning the exit code."""
    def handler(args):
        result = run(args)
        if args.out:
            jsonio.write_atomic(args.out, result.to_json_bytes())
        print_summary(result)
        return EXIT_PASS if result.status == "PASS" else EXIT_FAIL
    return handler


def print_summary(result):
    print("%s: %s (%d findings)" % (result.gate, result.status, len(result.findings)))
    for item in result.sorted_findings():
        print("  " + jsonio.canonical_dumps(item).decode("ascii").rstrip("\n"))


def report_internal_error(args, exc):
    """Print the error and replace any stale result file so it cannot read as PASS."""
    print("rigor: internal error: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    out = getattr(args, "out", None)
    if not out:
        return
    gate_id = getattr(args, "gate_id", None)
    try:
        if gate_id is None:
            discard_file(out)
        else:
            failed = GateResult(gate_id, [finding("internal-error")],
                                {"error": "%s: %s" % (type(exc).__name__, exc)})
            jsonio.write_atomic(out, failed.to_json_bytes())
    except OSError as write_error:
        print("rigor: could not update %s: %s" % (out, write_error), file=sys.stderr)


def discard_file(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def main(argv):
    args = None
    try:
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except Exception as exc:  # fail closed: every error is exit 2
        report_internal_error(args, exc)
        return EXIT_ERROR
