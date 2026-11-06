"""Command line front end. Exit 0 = PASS, 1 = FAIL, 2 = internal error."""

import argparse
import os
import sys

from rigor_lib.errors import InternalError
from rigor_lib import grade
from rigor_lib import approve, contract, jsonio, ratchet, suppressions, tests_gate, verdict
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import EXIT_ERROR, EXIT_FAIL, EXIT_PASS
from rigor_lib import mutants_gate, product_checks

# Each module has add_parser(subparsers).
COMMANDS = [contract, suppressions, tests_gate, ratchet, verdict, approve, product_checks, mutants_gate, grade]


def build_parser():
    parser = argparse.ArgumentParser(prog="rigor", allow_abbrev=False,
                                     description="c-rigor-gate decision kernel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in COMMANDS:
        module.add_parser(subparsers)
    return parser


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
        code = args.handler(args)
        if type(code) is not int or code not in (EXIT_PASS, EXIT_FAIL):  # bool is not accepted
            raise InternalError("handler returned %r instead of 0 or 1" % (code,))
        return code
    except Exception as exc:  # fail closed: every error is exit 2
        report_internal_error(args, exc)
        return EXIT_ERROR
