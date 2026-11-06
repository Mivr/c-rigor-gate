"""`rigor grade`: grade one product change end to end and write a verdict.

The product repository is cloned; everything after that reads the clone. The grading tree is
built from gate files plus the product files its layout allows. Gates are listed in
grade_pipeline.GATES. See docs/grade.md.
"""

import os
import subprocess
import sys
import time

from rigor_lib import grade_context, grade_pipeline, jsonio, product_layout, runner, verdict
from rigor_lib import approval_args, verdict_inputs
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
    for name in ("product_repo", "task", "product", "approvals", "witness", "sign_key", "work",
                 "verdict_out"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, os.path.abspath(value))


def start_grading(args):
    absolute_arguments(args)
    discard(args.verdict_out)  # no stale verdict, and none if we die before writing a new one
    discard(args.verdict_out + ".sig")
    gate_sha, gate_clean = grade_context.gate_checkout_state(args.allow_dirty_gate)
    grade_context.prepare_work(args.work)
    # From here on every subprocess (git, ssh-keygen, Buck2) inherits only the sealed environment.
    grade_context.seal_process_environment(args.work)
    work = args.work
    # Read every input file once. The grade uses the copies; the verdict hashes the same bytes.
    inputs = verdict_inputs.snapshot_inputs(args, work)
    inputs["allowed_signers_sha256"] = file_sha256(approval_args.DEFAULT_ALLOWED_SIGNERS)
    order_bytes = jsonio.read_bytes(grade_context.ORDER_FILE)
    inputs["order_sha256"] = jsonio.sha256_hex(order_bytes)
    # P002 Q1: a bad bundle is exit 2 here, before `clone`.
    witness, inputs["witness_sha256"] = verdict_inputs.snapshot_witness(
        args.witness, os.path.join(work, verdict_inputs.INPUTS_DIR, verdict_inputs.WITNESS_NAME))
    product = product_layout.load_product(args.product)
    return grade_context.Grading(
        args=args, product=product, gate_sha=gate_sha, work=work,
        src=os.path.join(work, "src"), tree=os.path.join(work, "tree"),
        results=os.path.join(work, "results"), test_results=os.path.join(work, "test-results"),
        inputs=inputs, order_bytes=order_bytes, gate_clean=gate_clean, witness=witness)


def file_sha256(path):
    return jsonio.sha256_hex(jsonio.read_bytes(path))


def write_verdict(g):
    """`rigor verdict` over the results, plus the bound inputs (and `uncached`) in the hashed core."""
    order = verdict.parse_order(g.order_bytes)
    documents = verdict.load_results(g.results, order)
    core = verdict.build_core(order, documents)
    core["uncached"] = bool(g.args.uncached)
    core["inputs"] = verdict_inputs.build_inputs(g, documents)
    if core["overall"] == verdict.STATUS_PASS and verdict_inputs.missing_inputs(core["inputs"]):
        raise InternalError("a PASS without every input bound: %s"
                            % verdict_inputs.missing_inputs(core["inputs"]))
    document = verdict.build_verdict(core, grade_context.ORDER_FILE, g.results, order, documents)
    jsonio.write_atomic(g.args.verdict_out, jsonio.canonical_dumps(document))
    for entry in core["gates"]:
        print("  %-14s %s" % (entry["id"], entry["status"]))
    print("verdict: %s%s" % (core["overall"], " (uncached)" if core["uncached"] else ""))
    return runner.EXIT_PASS if core["overall"] == verdict.STATUS_PASS else runner.EXIT_FAIL


def run(args):
    g = start_grading(args)
    try:
        failure = run_gates(g)
    finally:
        grade_context.kill_daemon(g.tree)
        grade_context.kill_daemon(os.path.join(g.work, grade_context.WITNESS_TREE))
    code = write_verdict(g)
    if failure is not None:
        raise InternalError("grading stopped by an internal error: %s" % (failure,))
    if args.sign_key is not None and not g.gate_clean:
        print("rigor grade: dirty gate: the verdict is left unsigned", file=sys.stderr)
    elif args.sign_key is not None:
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
    parser.add_argument("--witness", metavar="DIR",
                        help="witness bundle (docs/witness.md); snapshotted into <work>/inputs/witness "
                             "and bound as witness_sha256 (null without it)")
    parser.add_argument("--sign-key")
    parser.add_argument("--work", required=True)
    parser.add_argument("--allow-dirty-gate", action="store_true",
                        help="grade although tracked gate files differ from HEAD; the verdict records "
                             "gate_clean=false, is never signed and never verifies")
    parser.add_argument("--uncached", action="store_true",
                        help="no remote action-cache reads or writes: every action runs on a worker")
    # Not `dest="out"`: cli.report_internal_error deletes args.out, but a failed grading must
    # leave the FAIL verdict it wrote.
    parser.add_argument("--out", dest="verdict_out", required=True)
    parser.set_defaults(handler=run, gate_id=None)
