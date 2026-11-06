"""`rigor grade`: grade one product change end to end and write a verdict.

The product repository is cloned; everything after that reads the clone. The grading tree is
built from gate files plus the product files its layout allows. Gates are listed in
grade_pipeline.GATES. See docs/grade.md.
"""

import os
import subprocess
import sys
import time
from argparse import Namespace

from rigor_lib import grade_context, grade_pipeline, jsonio, product_layout, runner, verdict
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding

SIGN_NAMESPACE = "c-rigor-gate-verdict"
SIGN_TIMEOUT_SECONDS = 60


def run_gates(g):
    """Run the pipeline. Returns the exception that stopped it, or None."""
    for gate_id, step in grade_pipeline.GATES:
        started = time.monotonic()
        try:
            result = step(g)
        except Exception as exc:  # fail closed: record the gate as failed and stop
            result = GateResult(gate_id, [finding("internal-error")],
                                {"error": "%s: %s" % (type(exc).__name__, exc)})
            write_result(g, result, started)
            print("%-14s FAIL (internal error: %s)" % (gate_id, exc), file=sys.stderr)
            return exc
        if result is None:
            print("%-14s NOT_RUN" % gate_id)
            continue
        write_result(g, result, started)
        g.status[gate_id] = result.status
        print("%-14s %s (%d findings, %.1fs)" % (gate_id, result.status, len(result.findings),
                                                 time.monotonic() - started))
    return None


def write_result(g, result, started):
    result.metadata["seconds"] = round(time.monotonic() - started, 1)
    jsonio.write_atomic(os.path.join(g.results, result.gate + ".json"), result.to_json_bytes())


def sign_verdict(path, key):
    command = ["ssh-keygen", "-Y", "sign", "-n", SIGN_NAMESPACE, "-f", key, path]
    try:
        done = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=SIGN_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InternalError("cannot run ssh-keygen: %s" % exc) from exc
    if done.returncode != 0 or not os.path.isfile(path + ".sig"):
        raise InternalError("signing failed: %s" % done.stderr.decode("utf-8", "replace").strip())


def discard(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def absolute_arguments(args):
    for name in ("product_repo", "task", "product", "approvals", "sign_key", "work", "verdict_out"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, os.path.abspath(value))


def start_grading(args):
    absolute_arguments(args)
    discard(args.verdict_out)  # no stale verdict, and none if we die before writing a new one
    discard(args.verdict_out + ".sig")
    product = product_layout.load_product(args.product)
    gate_sha = grade_context.gate_checkout_sha()
    grade_context.prepare_work(args.work)
    work = args.work
    return grade_context.Grading(
        args=args, product=product, gate_sha=gate_sha, work=work,
        src=os.path.join(work, "src"), tree=os.path.join(work, "tree"),
        results=os.path.join(work, "results"), test_results=os.path.join(work, "test-results"))


def run(args):
    g = start_grading(args)
    try:
        failure = run_gates(g)
    finally:
        grade_context.kill_daemon(g.tree)
    code = verdict.run(Namespace(order=grade_context.ORDER_FILE, results=g.results,
                                 out=args.verdict_out))
    if failure is not None:
        raise InternalError("grading stopped by an internal error: %s" % (failure,))
    if args.sign_key is not None:
        try:
            sign_verdict(args.verdict_out, args.sign_key)
        except InternalError:
            discard(args.verdict_out)
            raise
    return code


def add_parser(subparsers):
    parser = subparsers.add_parser("grade", allow_abbrev=False,
                                   help="clone, assemble, build and judge one product change")
    parser.add_argument("--product-repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--task", required=True, help="TASK.toml (the contract)")
    parser.add_argument("--product", required=True, help="products/<name>/product.toml")
    parser.add_argument("--approvals")
    parser.add_argument("--sign-key")
    parser.add_argument("--work", required=True)
    # Not `dest="out"`: cli.report_internal_error deletes args.out, but a failed grading must
    # leave the FAIL verdict it wrote.
    parser.add_argument("--out", dest="verdict_out", required=True)
    parser.set_defaults(handler=run, gate_id=None)
