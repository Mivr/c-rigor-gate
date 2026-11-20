"""The `oracle` step of `rigor grade` (T2G7, P330 §3.3; docs/oracle.md): the product's replayer runs every hidden Rust trace of the
`--oracle` bundle and `oracle_judge` compares the output with the trace.

The replayer is a plain `c_binary` of the product that the gate-owned `oracle-policy.toml` names (`replayer`): it reads one
`vm-trace/1` file on stdin and writes the replayed one on stdout (the `cfg` and `in` lines, and for each input the `fx` and `vw`
lines of the C app). The gate writes the package `gate-oracle/` into the grading tree after the product was copied (so `buckfiles`
never sees it): the bundle's traces (the excluded ones left out) and one `genrule` that runs the replayer, built in the san platform,
over each of them on a worker. The outputs are copied into `<work>/oracle/` and the package is removed again; the verdict holds
hashes and positions only, never trace text (`inputs.oracle_sha256`, the gate files' hashes, findings of oracle_judge). Besides the
judge's findings:

    oracle-replay-failed   the replayer did not build, or died or failed on a trace (the whole replay is one action)

A product without a policy and without `--oracle` passes with info `no-oracle`; with a bundle but no policy replayer it is exit 2.
In role test-author the head is the stub commit: PASS with info `not-applicable`. NOT_RUN unless the tree built and every test passed.
"""

import os
import shutil

from rigor_lib import contract, grade_build, grade_context, grade_fuzz, grade_mutants, grade_tree, jsonio, oracle_bundle, oracle_judge
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = oracle_judge.GATE_ID
REQUIRED = grade_fuzz.REQUIRED
PLATFORM = "toolchains//:linux_san"
PACKAGE = "gate-oracle"
TARGET = "//%s:replay" % PACKAGE
RESULTS_DIR = "oracle"
POLICY_NAME, NORMALISE_NAME, EXCLUDED_NAME = "oracle-policy.toml", "oracle-normalise.toml", "oracle-excluded.toml"
_TAIL_CHARS = 4000


def _sibling(g, name):
    path = os.path.join(os.path.dirname(g.args.product), name)
    return path if os.path.isfile(path) else None


def build_file_text(replayer, trace_ids):
    """The generated BUCK file: one genrule that replays every listed trace with the replayer (stdin to stdout)."""
    sources = ", ".join('"files/%s%s"' % (trace_id, oracle_bundle.SUFFIX) for trace_id in trace_ids)
    command = 'mkdir -p $OUT && for f in $SRCS; do $(location %s) < $f > $OUT/${f##*/} || exit 1; done' % replayer
    return 'native.genrule(\n    name = "replay",\n    srcs = [%s],\n    out = "traces",\n    cmd = %s,\n)\n' % (
        sources, jsonio.canonical_dumps(command).decode("ascii"))


def write_package(tree, replayer, path, bundle, due):
    """Write `gate-oracle/` (BUCK, the traces to replay) and the root PACKAGE file; refuses what the product put in the way."""
    text = build_file_text(replayer, due)
    grade_mutants.write_gate_package(tree, PACKAGE, text)
    for trace_id in due:
        data = jsonio.read_bytes(os.path.join(path, oracle_bundle.FILES_DIR, trace_id + oracle_bundle.SUFFIX))
        if jsonio.sha256_hex(data) != bundle.file_sha256[trace_id]:
            raise InternalError("oracle bundle changed after it was snapshotted: %s" % trace_id)
        grade_tree.write_file(tree, "%s/files/%s%s" % (PACKAGE, trace_id, oracle_bundle.SUFFIX), data, 0o644)


def remove_package(tree):
    shutil.rmtree(os.path.join(tree, PACKAGE), ignore_errors=True)
    grade_mutants.remove_shared_package_file(tree)


def _replay(g, replayer, path, bundle, due, directory):
    """Build the replay package, copy its outputs into `directory`. Returns (findings, metadata)."""
    write_package(g.tree, replayer, path, bundle, due)
    report = os.path.join(g.work, "build-report-oracle.json")
    if os.path.lexists(report):
        os.unlink(report)
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", PLATFORM, "--build-report", report] + flags + [TARGET])
    executed, cached = grade_build.action_counts(g.tree)
    metadata = {"executed_actions": executed, "cached_actions": cached, "exit_code": code}
    entry = (grade_build.read_report(report) or {}).get("root" + TARGET)
    produced = _output_directory(g.tree, entry) if entry and entry.get("success") == "SUCCESS" else None
    if produced is None:
        # The replayer's own diagnostics are not kept: they may quote the trace it was given.
        return [finding("oracle-replay-failed", replayer=replayer)], metadata
    os.makedirs(directory)
    for name in sorted(os.listdir(produced)):
        shutil.copyfile(os.path.join(produced, name), os.path.join(directory, name))
    return [], metadata


def _output_directory(tree, entry):
    outputs = entry.get("outputs", {}).get("DEFAULT", [])
    if len(outputs) != 1 or not isinstance(outputs[0], str):
        return None
    path = os.path.realpath(os.path.join(tree, outputs[0]))
    if not path.startswith(os.path.realpath(os.path.join(tree, "buck-out")) + os.sep):
        raise InternalError("oracle output outside buck-out: %s" % outputs[0])
    return path if os.path.isdir(path) else None


def _step(g):
    policy = oracle_judge.load_policy(_sibling(g, POLICY_NAME))
    path = getattr(g.args, "oracle", None)
    bundle = oracle_bundle.load(path) if path is not None else None
    table = oracle_judge.load_table(_sibling(g, NORMALISE_NAME))
    excluded = oracle_judge.load_excluded(_sibling(g, EXCLUDED_NAME))
    if bundle is None and not policy.required:
        return GateResult(GATE_ID, [finding("no-oracle", SEVERITY_INFO)], {"traces": 0})
    if bundle is not None:
        oracle_bundle.check(bundle, g.product.name)
        if oracle_bundle.digest(bundle) != g.inputs.get("oracle_sha256"):
            raise InternalError("oracle bundle differs from the one the verdict binds")
        if policy.replayer == "":
            raise InternalError("an oracle bundle needs `replayer` in %s" % POLICY_NAME)
    due = [trace_id for trace_id in (bundle.ids if bundle else ()) if trace_id not in excluded.entries]
    found, metadata, directory = [], {}, os.path.join(g.work, RESULTS_DIR)
    if due:
        try:
            found, metadata = _replay(g, policy.replayer, path, bundle, due, directory)
        finally:
            grade_context.kill_daemon(g.tree)
            remove_package(g.tree)
    if found:   # the replay failed: nothing to compare (a count-short finding would only repeat it)
        metadata.update(oracle_judge.metadata_of(bundle, {}, table, excluded))
        return GateResult(GATE_ID, found + oracle_judge.policy_findings(policy, bundle, excluded), metadata)
    os.makedirs(directory, exist_ok=True)
    results = oracle_judge.load_results(directory, bundle, excluded) if bundle is not None else {}
    metadata.update(oracle_judge.metadata_of(bundle, results, table, excluded))
    return GateResult(GATE_ID, oracle_judge.judge(policy, bundle, table, excluded, results), metadata)


def oracle_gate_step(g):
    if any(g.status.get(gate) != "PASS" for gate in REQUIRED):
        return None  # no clean build and green tests: nothing to judge
    role = contract.load_contract(g.args.task).role
    if role == contract.ROLE_TEST_AUTHOR:
        return GateResult(GATE_ID, [finding("not-applicable", SEVERITY_INFO, role=role)], {"role": role, "traces": 0})
    return _step(g)

