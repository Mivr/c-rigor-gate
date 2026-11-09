"""The `fuzz` step of `rigor grade` (T129, P003 §7.2, G23): every `c_fuzz` target of the product is built in the fuzz
platform, its outputs are collected into `<work>/fuzz/` in the layout `rigor fuzz` reads, and `fuzz_gate` judges them.

The run is a build action with declared outputs (`rules/fuzz.bzl`): a fixed seed and a number of runs, never a time, so
the action is deterministic and the action cache answers a repeat grade (`--uncached` applies as for every build).
What must be fuzzed is gate-owned (`fuzz = true` or the `parser` profile in `policy.toml`, `fuzz-regressions.json`
beside it), see `fuzz_gate`. Findings of this step besides the judge's:

    fuzz-build-failed   a target did not build, or built without one of its five outputs (an error)

A product without a `c_fuzz` target and without a module that must be fuzzed passes with info `no-fuzz-targets`. In role
test-author the head is the stub commit: PASS with info `not-applicable`. NOT_RUN unless the tree built, the facts exist
and every test passed.
"""

import os
import re
import shutil
from argparse import Namespace

from rigor_lib import contract, fuzz_gate, grade_build, grade_checks, grade_context, grade_policy, jsonio
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = fuzz_gate.GATE_ID
REQUIRED = ("assemble", "buckfiles", "build", "tests-release", "tests-san")
PLATFORM = "toolchains//:linux_fuzz"
KIND = "fuzz_run"
REGRESSIONS_NAME = "fuzz-regressions.json"
RESULTS_DIR = "fuzz"
# sub-target of the run action -> suffix of its file in the results directory (`fuzz_gate._SUFFIXES`)
OUTPUTS = {"verdict": ".verdict", "report": ".report", "crash": ".crash", "stats": ".stats.json",
           "replayed": ".replayed"}
_TAIL_CHARS = 4000
_LABEL = re.compile(r"root//[A-Za-z0-9_./+-]*:[A-Za-z0-9_./+-]+")


def fuzz_targets(tree):
    """(code, labels of every c_fuzz run target of the product, sorted, stderr)."""
    code, out, err = grade_build.run_buck(tree, ["uquery", "kind(%s, //...)" % KIND])
    if code != 0:
        return code, [], err
    labels = sorted(line.strip() for line in out.splitlines() if line.strip())
    for label in labels:
        if not _LABEL.fullmatch(label):
            raise InternalError("odd target label from buck2: %r" % label)
    return 0, labels, err


def _built(results, label):
    entry = results.get(label)
    return entry is not None and entry.get("success") == "SUCCESS"


def build_targets(g, labels):
    """One build of every label; retried once when it died of a transport failure and left a target unbuilt (the same
    rule as the mutants build). Returns (results, exit code, stderr, executed, cached)."""
    report = os.path.join(g.work, "build-report-fuzz.json")
    flags = ["--no-remote-cache"] if g.args.uncached else []
    wanted = ["%s[%s]" % (label, name) for label in labels for name in OUTPUTS]   # the report lists them per target
    executed = cached = 0
    retried = False
    while True:
        if os.path.lexists(report):
            os.unlink(report)
        code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", PLATFORM, "--keep-going",
                                                     "--build-report", report] + flags + wanted)
        done_executed, done_cached = grade_build.action_counts(g.tree)
        executed, cached = executed + done_executed, cached + done_cached
        results = grade_build.read_report(report) or {}
        missing = not all(_built(results, label) for label in labels)
        if retried or not (code != 0 and missing and grade_build.transport_failure(err)):
            return results, code, err, executed, cached
        retried = True


def _output_file(tree, entry, name):
    """The path of the output `name` of a built target (inside buck-out, a regular file), or None."""
    outputs = (entry.get("outputs") or {}).get(name)
    if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], str):
        return None
    path = os.path.realpath(os.path.join(tree, outputs[0]))
    if not path.startswith(os.path.realpath(os.path.join(tree, "buck-out")) + os.sep):
        raise InternalError("fuzz output outside buck-out: %s" % outputs[0])
    return path if os.path.isfile(path) else None


def collect(tree, labels, results, directory):
    """Copy the five outputs of every built target into `directory`, write `index.json`.
    Returns (the labels that did not build or lack an output, {facts label: id})."""
    os.makedirs(directory)
    failed, index = [], {}
    for number, label in enumerate(labels):
        entry = results.get(label)
        paths = {name: _output_file(tree, entry, name) for name in OUTPUTS} if _built(results, label) else {}
        if len(paths) != len(OUTPUTS) or None in paths.values():
            failed.append(label)
            continue
        ident = "t%03d" % number
        for name, suffix in OUTPUTS.items():
            shutil.copyfile(paths[name], os.path.join(directory, ident + suffix))
        index[facts_label(label)] = ident
    jsonio.write_atomic(os.path.join(directory, fuzz_gate.INDEX), jsonio.canonical_dumps(index))
    return failed, index


def facts_label(label):
    """`root//pkg:name` (Buck2) as the facts and the policy write it: `//pkg:name`."""
    return label[len("root"):] if label.startswith("root//") else label


def regressions_path(g):
    path = os.path.join(os.path.dirname(g.args.product), REGRESSIONS_NAME)
    return path if os.path.isfile(path) else None


def judge(g, facts_dir, directory, failed):
    """The judge's result over the collected directory, without `fuzz-not-run` for what failed to build."""
    result = fuzz_gate.run(Namespace(policy=grade_policy.policy_path(g), facts=facts_dir, results=directory,
                                     regressions=regressions_path(g)))
    skipped = {facts_label(label) for label in failed}
    kept = [item for item in result.findings if not (item["rule"] == "fuzz-not-run" and item.get("target") in skipped)]
    return kept, result.metadata


def _step(g):
    code, labels, err = fuzz_targets(g.tree)
    if code != 0:
        return GateResult(GATE_ID, [finding("query-failed")], {"stderr_tail": err[-_TAIL_CHARS:]})
    required = fuzz_gate.load_policy(grade_policy.policy_path(g))
    if not labels and not required:
        return GateResult(GATE_ID, [finding("no-fuzz-targets", SEVERITY_INFO)], {"targets": {}})
    facts = grade_checks.build_facts(g)
    if isinstance(facts, str):
        return None  # the facts did not build: nothing to judge against
    directory = os.path.join(g.work, RESULTS_DIR)
    results, code, err, executed, cached = {}, 0, "", 0, 0
    if labels:
        try:
            results, code, err, executed, cached = build_targets(g, labels)
        finally:
            grade_context.kill_daemon(g.tree)   # the fuzz runs are the longest actions: do not keep the daemon around
    failed, _ = collect(g.tree, labels, results, directory)
    found, metadata = judge(g, facts.directory, directory, failed)
    found.extend(finding("fuzz-build-failed", target=facts_label(label)) for label in failed)
    metadata.update({"executed_actions": executed, "cached_actions": cached, "exit_code": code})
    if code != 0:
        metadata["stderr_tail"] = err[-_TAIL_CHARS:]
    return GateResult(GATE_ID, found, metadata)


def fuzz_gate_step(g):
    if any(g.status.get(gate) != "PASS" for gate in REQUIRED):
        return None  # no clean build and green tests: nothing to judge
    role = contract.load_contract(g.args.task).role
    if role == contract.ROLE_TEST_AUTHOR:
        return GateResult(GATE_ID, [finding("not-applicable", SEVERITY_INFO, role=role)], {"role": role, "targets": {}})
    return _step(g)
