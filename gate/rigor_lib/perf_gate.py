"""The `perf` step of `rigor grade` (T090, G30): the cost counts of every `c_perf` target the policy declares a
complexity class for, judged by `perf_judge`.

What is judged is gate-owned: the targets, their drivers and their classes come from `products/<p>/policy.toml`
(`[module."//x:y".perf.<name>]`) and from the perf bundle (`--perf DIR`), see `perf_policy`; never from the product.
The step writes the package `gate-perf/` (`perf_package`) into the grading tree, builds the `<name>_perf` targets in the
release platform (cached like any build; `--uncached` applies), reads each `perf.jsonl` and removes the package again.
Findings:

    perf-class-exceeded       a counter at n2 is above what the class allows (target, class, both counts, ratio)
    perf-counter-unavailable  the counter could not be read on the worker: no verdict without counts, so an error
    perf-record-bad           a record whose status is not ok (gen-overflow, run-error, crash, timeout), or too few
    perf-build-failed         the target did not build

A product without perf entries passes with info `no-perf-targets`. In role test-author the head is the stub commit:
PASS with info `not-applicable`. NOT_RUN unless the tree built and every test passed.
"""

import os

from rigor_lib import contract, grade_build, grade_context, grade_mutants, grade_policy, jsonio, perf_judge
from rigor_lib import perf_package, perf_policy
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = "perf"
REQUIRED = ("assemble", "buckfiles", "build", "tests-release", "tests-san")
PLATFORM = "toolchains//:linux_release"
_TAIL_CHARS = 4000


def judge_target(label, module, cost_class, records):
    """The findings of one target, from its parsed records."""
    first, last, why = perf_judge.usable(records)
    where = {"module": module, "target": label, "class": cost_class}
    if why == "record":
        return [finding("perf-record-bad", status=perf_judge.status_of(records), records=len(records), **where)]
    if why == "unavailable":
        return [finding("perf-counter-unavailable", counter=first.get("counter"), errno=first.get("errno"), **where)]
    return [finding("perf-class-exceeded", **dict(where, **item)) for item in perf_judge.exceeded(cost_class, records)]


def _summary(records):
    return [{key: record.get(key) for key in ("n", "status", "instructions", "libc_bytes")} for record in records]


def perf_gate(g):
    if g.status.get("assemble") != "PASS":
        return None
    targets = perf_policy.load(grade_policy.policy_path(g), g.perf)
    if not targets:
        return GateResult(GATE_ID, [finding("no-perf-targets", SEVERITY_INFO)], {"targets": {}})
    role = contract.load_contract(g.args.task).role
    if role == contract.ROLE_TEST_AUTHOR:
        return GateResult(GATE_ID, [finding("not-applicable", SEVERITY_INFO, role=role)], {"role": role, "targets": {}})
    if any(g.status.get(gate) != "PASS" for gate in REQUIRED):
        return None
    try:
        return _run(g, targets)
    finally:
        grade_context.kill_daemon(g.tree)
        perf_package.remove(g.tree)
        grade_mutants.remove_shared_package_file(g.tree)


def _run(g, targets):
    grade_mutants.write_shared_package_file(g.tree)
    perf_package.write(g.tree, targets)
    by_label = {t.label: t for t in targets}
    labels = sorted(by_label)
    report = os.path.join(g.work, "build-report-perf.json")
    if os.path.lexists(report):
        os.unlink(report)
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", PLATFORM, "--keep-going",
                                                 "--build-report", report] + flags + labels)
    executed, cached = grade_build.action_counts(g.tree)
    metadata = {"executed_actions": executed, "cached_actions": cached, "exit_code": code, "targets": {}}
    if code != 0:
        metadata["stderr_tail"] = err[-_TAIL_CHARS:]
    results = grade_build.read_report(report) or {}
    found = []
    for label in labels:
        module, cost_class = by_label[label].module, by_label[label].cost_class
        entry = results.get("root" + label)
        path = grade_build.output_path(g.tree, label, entry) if entry and entry.get("success") == "SUCCESS" else None
        if path is None:
            found.append(finding("perf-build-failed", module=module, target=label, **{"class": cost_class}))
            continue
        records = perf_judge.parse_records(label, jsonio.read_bytes(path))
        metadata["targets"][label] = {"class": cost_class, "records": _summary(records)}
        found.extend(judge_target(label, module, cost_class, records))
    return GateResult(GATE_ID, found, metadata)
