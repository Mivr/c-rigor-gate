"""`rigor grade`: grade one product change end to end and write a verdict.

The product repository is cloned; everything after that reads the clone. The grading tree is
built from gate files plus the product files its layout allows. Gates are listed in
grade_pipeline.GATES. See docs/grade.md.
"""

import os
import sys
import time

from rigor_lib import approval_args, approvals, grade_context, grade_pipeline, grade_policy, grade_tier, jsonio, product_layout, runner, verdict
from rigor_lib import verdict_inputs
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding


def run_gates(g):
    """Run the pipeline. Returns the exception that stopped it, or None."""
    chosen = getattr(g, "selected", None)
    for gate_id, step in grade_pipeline.GATES:
        if chosen is not None and gate_id not in chosen:
            continue   # `--only`: not part of this grade (nor of its order)
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


def discard(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def absolute_arguments(args):
    for name in ("product_repo", "task", "product", "approvals", "witness", "perf", "oracle", "sim_salt", "work",
                 "verdict_out"):
        value = getattr(args, name, None)
        if value is not None:
            setattr(args, name, os.path.abspath(value))


def start_grading(args):
    absolute_arguments(args)
    approval_args.refuse_planted_approvals(args)
    discard(args.verdict_out)  # no stale verdict, and none if we die before writing a new one
    gate_sha, gate_clean = grade_context.gate_checkout_state(args.allow_dirty_gate)
    grade_context.prepare_work(args.work)
    # From here on every subprocess (git, Buck2) inherits only the sealed environment.
    grade_context.seal_process_environment(args.work)
    work = args.work
    # Read every input file once. The grade uses the copies; the verdict hashes the same bytes.
    inputs = verdict_inputs.snapshot_inputs(args, work)
    order_bytes = jsonio.read_bytes(args.order_file)  # the snapshot; its hash is in `inputs`
    # P002 Q1: a bad bundle is exit 2 here, before `clone`.
    witness, inputs["witness_sha256"] = verdict_inputs.snapshot_witness(
        args.witness, os.path.join(work, verdict_inputs.INPUTS_DIR, verdict_inputs.WITNESS_NAME))
    selected = None
    if getattr(args, "only", None) is not None:   # a partial grade: its order file lists only what runs (and is hashed so;
        # `rigor verify` refuses it: its order is not the gate revision's order)
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        selected = grade_pipeline.selection(args.only, ids)
        order_bytes = "".join(i + "\n" for i in ids if i in selected).encode("ascii")
        with open(args.order_file, "wb") as handle:
            handle.write(order_bytes)
        inputs["order_sha256"] = jsonio.sha256_hex(order_bytes)
    product = product_layout.load_product(args.product)
    # T2G7: the oracle bundle (the hidden half of the replay) is copied and bound like the witness; `args.oracle` then names the
    # copy, which the `oracle` gate loads again. Only its hash enters the verdict.
    oracle_source = getattr(args, "oracle", None)
    if oracle_source is not None:
        args.oracle = os.path.join(work, verdict_inputs.INPUTS_DIR, verdict_inputs.ORACLE_NAME)
    inputs["oracle_sha256"] = verdict_inputs.snapshot_oracle(oracle_source, getattr(args, "oracle", None),
                                                             product.name)
    perf_source = getattr(args, "perf", None)  # callers that build args by hand may omit it
    levels = {}
    if perf_source is not None:  # the snapshot of the policy, like every other reader
        levels = grade_policy.load_levels(os.path.join(os.path.dirname(args.product), "policy.toml"))
    perf, inputs["perf_sha256"] = verdict_inputs.snapshot_perf(
        perf_source, os.path.join(work, verdict_inputs.INPUTS_DIR, verdict_inputs.PERF_NAME), product.name, levels)
    return grade_context.Grading(
        args=args, product=product, gate_sha=gate_sha, work=work,
        src=os.path.join(work, "src"), tree=os.path.join(work, "tree"),
        results=os.path.join(work, "results"), test_results=os.path.join(work, "test-results"),
        inputs=inputs, order_bytes=order_bytes, gate_clean=gate_clean, witness=witness, perf=perf,
        selected=selected)


def file_sha256(path):
    return jsonio.sha256_hex(jsonio.read_bytes(path))


def approvals_in_force(g):
    """The approvals valid for the graded head (U30: no signature; schema, name and ancestry checked).
    Approvals that failed validation are reported by their gates already and are not in `valid`. Without
    a graded head (the clone gate did not finish) validity cannot be judged and the list is empty; that
    grade is a FAIL anyway."""
    if g.args.approvals is None or not g.head:
        return []
    return approvals.load_approvals(g.args.approvals, g.src, g.head).valid


def write_verdict(g):
    """`rigor verdict` over the results, plus the bound inputs (and `uncached`) in the hashed core."""
    order = verdict.parse_order(g.order_bytes)
    documents = verdict.load_results(g.results, order)
    core = verdict.build_core(order, documents)
    core["uncached"] = bool(g.args.uncached)
    valid = approvals_in_force(g)
    core["unused_approvals"] = verdict.unused_approval_findings(valid, documents)
    core["approvals"] = verdict.approvals_in_force(valid)
    core["inputs"] = verdict_inputs.build_inputs(g, documents)
    if core["overall"] == verdict.STATUS_PASS and verdict_inputs.missing_inputs(core["inputs"]):
        raise InternalError("a PASS without every input bound: %s"
                            % verdict_inputs.missing_inputs(core["inputs"]))
    document = verdict.build_verdict(core, g.args.order_file, g.results, order, documents)
    jsonio.write_atomic(g.args.verdict_out, jsonio.canonical_dumps(document))
    for entry in core["gates"]:
        print("  %-14s %s" % (entry["id"], entry["status"]))
    print("approvals in force (loosenings): %d" % core["approvals"]["count"])
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
    return code


def _gate_list(text):
    return text.split(",")


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
    parser.add_argument("--perf", metavar="DIR",
                        help="perf bundle (docs/perf.md); snapshotted into <work>/inputs/perf and bound as "
                             "perf_sha256 (null without it); loaded and checked, no gate judges it yet")
    parser.add_argument("--oracle", metavar="DIR",
                        help="oracle bundle (docs/oracle.md): the hidden Rust traces the `oracle` gate replays; snapshotted into "
                             "<work>/inputs/oracle and bound as oracle_sha256 (null without it)")
    parser.add_argument("--sim-salt", metavar="FILE",
                        help="the salt of the simulation seeds (lowercase hex; docs/sim.md): the grader's hidden one. Only "
                             "its sha256 enters the verdict (inputs.sim_salt_id); without it the product's "
                             "sim-salt.public is used, else no salt")
    parser.add_argument("--only", type=_gate_list, metavar="A,B",
                        help="a partial grade: run these gates and what they need (grade_pipeline.selection); the others "
                             "are left out of the order, so the verdict can PASS; `rigor verify` never accepts it (historical canaries, docs/canaries.md)")
    parser.add_argument("--work", required=True)
    parser.add_argument("--allow-dirty-gate", action="store_true",
                        help="grade although tracked gate files differ from HEAD; the verdict records "
                             "gate_clean=false and never verifies")
    parser.add_argument("--tier", choices=grade_tier.TIERS, default=grade_tier.DEFAULT,
                        help="nightly (default): the whole grade; merge: report-only mutation is deferred "
                             "(docs/grade.md); bound into the verdict")
    parser.add_argument("--uncached", action="store_true",
                        help="no remote action-cache reads or writes: every action runs on a worker")
    # Not `dest="out"`: cli.report_internal_error deletes args.out, but a failed grading must
    # leave the FAIL verdict it wrote.
    parser.add_argument("--out", dest="verdict_out", required=True)
    parser.set_defaults(handler=run, gate_id=None)
