"""The `sim` step of `rigor grade` (T2G2, P330 §1.8): every `c_sim` target of the product is built in the san platform (its
verdict, stats, hashes and report) and in the release platform (its hashes: seeds 0 to 9 must be the same), the outputs are
collected into `<work>/sim/` in the layout `rigor sim` reads, and `sim_judge` judges them.

The run is a build action with declared outputs (`rules/sim.bzl`): seeds are derived from the salt, so the action is
deterministic and the action cache answers a repeat grade (`--uncached` applies as for every build). The salt is
`<work>/inputs/sim-salt` (the grader's `--sim-salt`, else the product's public `sim-salt.public`, else none), passed to
Buck2 as `-c rigor.sim_salt=HEX`; only its sha256 enters the verdict (`inputs.sim_salt_id`). Findings of this step besides
the judge's:

    sim-build-failed   a target did not build, or built without one of its outputs (an error)

A product without a `c_sim` target and without `[sim] required = true` passes with info `no-sim-targets`. In role
test-author the head is the stub commit: PASS with info `not-applicable`. NOT_RUN unless the tree built, the facts exist
and every test passed.
"""

import os
import re
import shutil
from argparse import Namespace

from rigor_lib import contract, grade_build, grade_checks, grade_fuzz, grade_policy, grade_tier, jsonio, sim_judge, sim_policy
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = sim_judge.GATE_ID
REQUIRED = grade_fuzz.REQUIRED
KIND = "sim_merge"
SAN, RELEASE = "toolchains//:linux_san", "toolchains//:linux_release"
SPEC_NAME = "sim.toml"
REGRESSIONS_NAME = "sim-regressions.json"
SALT_NAME = "sim-salt"           # the snapshot of the salt in <work>/inputs
RESULTS_DIR = "sim"
# sub-target of the san build -> suffix of its file in the results directory; the release build gives `release.hashes`
SAN_OUTPUTS = {"verdict": ".verdict", "report": ".report", "stats": ".stats.json", "hashes": ".hashes"}
RELEASE_OUTPUTS = {"hashes": ".release.hashes"}
_TAIL_CHARS = 4000
_LABEL = re.compile(r"root//[A-Za-z0-9_./+-]*:[A-Za-z0-9_./+-]+")


def _built(results, label):
    entry = results.get(label)
    return entry is not None and entry.get("success") == "SUCCESS"


def _output_file(tree, entry, name):
    """The path of the output `name` of a built target (inside buck-out, a regular file), or None."""
    outputs = (entry.get("outputs") or {}).get(name)
    if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], str):
        return None
    path = os.path.realpath(os.path.join(tree, outputs[0]))
    if not path.startswith(os.path.realpath(os.path.join(tree, "buck-out")) + os.sep):
        raise InternalError("sim output outside buck-out: %s" % outputs[0])
    return path if os.path.isfile(path) else None


def sim_targets(tree):
    """(code, labels of every c_sim target of the product, sorted, stderr)."""
    code, out, err = grade_build.run_buck(tree, ["uquery", "kind(%s, //...)" % KIND])
    if code != 0:
        return code, [], err
    labels = sorted(line.strip() for line in out.splitlines() if line.strip())
    for label in labels:
        if not _LABEL.fullmatch(label):
            raise InternalError("odd target label from buck2: %r" % label)
    return 0, labels, err


def salt_path(g):
    """The snapshot of the salt, or None (the empty salt)."""
    path = os.path.join(g.work, "inputs", SALT_NAME)
    return path if os.path.isfile(path) else None


def _build(g, platform, outputs, labels, salt_hex):
    """One build of every label's outputs in PLATFORM; retried once when it died of a transport failure and left a target
    unbuilt (the rule of the fuzz and mutants builds). Returns (results, exit code, stderr, executed, cached)."""
    report = os.path.join(g.work, "build-report-sim-%s.json" % platform.rsplit("_", 1)[1])
    flags = ["--no-remote-cache"] if g.args.uncached else []
    if salt_hex:
        flags += ["-c", "rigor.sim_salt=" + salt_hex]
    wanted = ["%s[%s]" % (label, name) for label in labels for name in outputs]
    executed = cached = 0
    retried = False
    while True:
        if os.path.lexists(report):
            os.unlink(report)
        code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", platform, "--keep-going",
                                                     "--build-report", report] + flags + wanted)
        done_executed, done_cached = grade_build.action_counts(g.tree)
        executed, cached = executed + done_executed, cached + done_cached
        results = grade_build.read_report(report) or {}
        missing = not all(_built(results, label) for label in labels)
        if retried or not (code != 0 and missing and grade_build.transport_failure(err)):
            return results, code, err, executed, cached
        retried = True


def collect(tree, labels, built, directory):
    """Copy the outputs of every target that built in both platforms into `directory`, write `index.json`.
    `built` is ({san results}, {release results}). Returns (the labels that did not build or lack an output, {facts label: id})."""
    os.makedirs(directory)
    failed, index = [], {}
    for number, label in enumerate(labels):
        paths = {}
        for results, outputs in zip(built, (SAN_OUTPUTS, RELEASE_OUTPUTS)):
            entry = results.get(label)
            if _built(results, label):
                paths.update({suffix: _output_file(tree, entry, name) for name, suffix in outputs.items()})
        if len(paths) != len(SAN_OUTPUTS) + len(RELEASE_OUTPUTS) or None in paths.values():
            failed.append(label)
            continue
        ident = "t%03d" % number
        for suffix, path in paths.items():
            shutil.copyfile(path, os.path.join(directory, ident + suffix))
        index[grade_fuzz.facts_label(label)] = ident
    jsonio.write_atomic(os.path.join(directory, sim_judge.INDEX), jsonio.canonical_dumps(index))
    return failed, index


def _sibling(g, name):
    path = os.path.join(os.path.dirname(g.args.product), name)
    return path if os.path.isfile(path) else None


def judge(g, facts_dir, directory, failed):
    """The judge's result over the collected directory, without `sim-not-run` for what failed to build."""
    result = sim_judge.run(Namespace(
        policy=grade_policy.policy_path(g), facts=facts_dir, results=directory, spec=_sibling(g, SPEC_NAME),
        regressions=_sibling(g, REGRESSIONS_NAME), salt=salt_path(g), salt_id=None, tier=grade_tier.tier_of(g)))
    skipped = {grade_fuzz.facts_label(label) for label in failed}
    kept = [item for item in result.findings if not (item["rule"] == "sim-not-run" and item.get("target") in skipped)]
    return kept, result.metadata


def _salt_hex(g):
    path = salt_path(g)
    return "" if path is None else sim_policy.load_salt(path)[0].hex()


def _step(g):
    code, labels, err = sim_targets(g.tree)
    if code != 0:
        return GateResult(GATE_ID, [finding("query-failed")], {"stderr_tail": err[-_TAIL_CHARS:]})
    policy = sim_policy.load_policy(grade_policy.policy_path(g))
    if not labels and not policy.required:
        return GateResult(GATE_ID, [finding("no-sim-targets", SEVERITY_INFO)], {"targets": {}})
    facts = grade_checks.build_facts(g)
    if isinstance(facts, str):
        return None  # the facts did not build: nothing to judge against
    directory = os.path.join(g.work, RESULTS_DIR)
    executed = cached = 0
    built, code, err = ({}, {}), 0, ""
    if labels:
        salt_hex = _salt_hex(g)
        san, code, err, executed, cached = _build(g, SAN, SAN_OUTPUTS, labels, salt_hex)
        release, code2, err2, done_executed, done_cached = _build(g, RELEASE, RELEASE_OUTPUTS, labels, salt_hex)
        built, executed, cached = (san, release), executed + done_executed, cached + done_cached
        code, err = (code, err) if code != 0 else (code2, err2)
    failed, _ = collect(g.tree, labels, built, directory)
    found, metadata = judge(g, facts.directory, directory, failed)
    found.extend(finding("sim-build-failed", target=grade_fuzz.facts_label(label)) for label in failed)
    metadata.update({"executed_actions": executed, "cached_actions": cached, "exit_code": code})
    if code != 0:
        metadata["stderr_tail"] = err[-_TAIL_CHARS:]
    return GateResult(GATE_ID, found, metadata)


def sim_gate_step(g):
    if any(g.status.get(gate) != "PASS" for gate in REQUIRED):
        return None  # no clean build and green tests: nothing to judge
    role = contract.load_contract(g.args.task).role
    if role == contract.ROLE_TEST_AUTHOR:
        return GateResult(GATE_ID, [finding("not-applicable", SEVERITY_INFO, role=role)], {"role": role, "targets": {}})
    return _step(g)
