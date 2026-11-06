"""The `mutants` step of `rigor grade`: mutation testing of every product module the policy puts at L2+.

Everything that decides what is mutated and against which tests is gate-owned:
  * the modules and their levels come from `products/<p>/policy.toml` (`grade_policy`); a library or
    binary of the product without a level is a finding, and a grading that would mutate nothing fails;
  * the tests of a module are every product `c_test` that lists the module directly in its `deps`,
    found with `buck2 uquery` in the grading tree, never declared by the product;
  * the `c_mutants` targets live in a generated package (`gate-mutants/BUCK`, one gate macro call per
    module) that is written after the product was copied, so `buckfiles` never sees it. A root `PACKAGE`
    file (the product may not carry one, `buckfiles` flags it) makes the product's targets visible to it.
The reports are built in release mode (cached like any build; `--uncached` applies) and judged by
`mutants_gate` (`rigor mutants`) in process. NOT_RUN unless the tree built and every test passed.
"""

import os
import re
from argparse import Namespace
from dataclasses import dataclass

from rigor_lib import approval_args, approvals, grade_build, grade_context, grade_policy, jsonio
from rigor_lib import mutants_gate as rigor_mutants
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.grade_tree import write_file

PACKAGE_DIR = "gate-mutants"
PACKAGE_FILE = "PACKAGE"
PACKAGE_TEXT = 'package(visibility = ["PUBLIC"], inherit = True)\n'
REQUIRED = ("assemble", "buckfiles", "build", "tests-release", "tests-san")
PLATFORM = "toolchains//:linux_release"
_ROOT = "root//"
_LABEL = re.compile(r"root//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+")
_TAIL_CHARS = 4000


@dataclass(frozen=True)
class Layout:
    libs: frozenset      # c_library labels ("//pkg:name")
    binaries: frozenset  # c_binary labels
    tests: frozenset     # c_test labels
    deps: dict           # label -> tuple of direct same-cell dependency labels


@dataclass(frozen=True)
class Module:
    label: str
    level: str
    tests: tuple   # c_tests that depend on the module directly
    deps: tuple    # libraries linked into those tests besides the module, dependents first


@dataclass(frozen=True)
class Plan:
    modules: list
    findings: list


def _short(label):
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise InternalError("odd target label from buck2: %r" % (label,))
    return label[len("root"):]


def _direct_deps(label, entry):
    deps = entry.get("deps", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise InternalError("%s: odd deps from buck2" % label)
    return tuple(_short(d) for d in deps if d.startswith(_ROOT))


def parse_layout(result_targets, attributes, binaries):
    """Layout from the three queries: `ctest_results` targets (attribute `test`), the attributes of every
    library, test, binary and `mutsrc` (a library `x` is a `c_library` iff `x_mutsrc` exists), and the
    labels of the `cxx_binary` targets."""
    if not isinstance(result_targets, dict) or not isinstance(attributes, dict):
        raise InternalError("odd query output from buck2")
    tests = set()
    for entry in result_targets.values():
        if not isinstance(entry, dict):
            raise InternalError("odd ctest_results from buck2")
        tests.add(_short(entry.get("test")))
    entries = {_short(label): entry for label, entry in attributes.items()}
    if not all(isinstance(entry, dict) for entry in entries.values()):
        raise InternalError("odd attributes from buck2")
    libs = {label for label in entries if label + "_mutsrc" in entries}
    binary_labels = {_short(label) for label in binaries}
    missing = (tests | binary_labels) - set(entries)
    if missing:
        raise InternalError("no attributes for %s" % sorted(missing))
    deps = {label: _direct_deps(label, entries[label]) for label in sorted(libs | tests | binary_labels)}
    return Layout(frozenset(libs), frozenset(binary_labels), frozenset(tests), deps)


def read_layout(run):
    def query(args):
        code, out, err = grade_build.run_buck(run.tree, ["uquery"] + args)
        if code != 0:
            raise InternalError("buck2 uquery failed: %s" % err.strip()[-500:])
        return out
    attribute = ["--output-format", "json", "--output-attribute"]
    results = jsonio.strict_loads(query(["kind(ctest_results, //...)"] + attribute + ["^test$"]).encode("utf-8"))
    attributes = jsonio.strict_loads(query(
        ["kind('^(cxx_library|cxx_binary|cxx_test|mutsrc)$', //...)"] + attribute + ["^deps$"]).encode("utf-8"))
    binaries = [line.strip() for line in query(["kind(cxx_binary, //...)"]).splitlines() if line.strip()]
    return parse_layout(results, attributes, binaries)


def _link_deps(layout, module, tests):
    """Libraries the module's tests need to link: the closure of their deps and of the module's,
    without the module. A library comes before the ones it depends on (static archives, one pass)."""
    wanted = set()
    stack = [d for t in tests for d in layout.deps[t]] + list(layout.deps[module])
    while stack:
        label = stack.pop()
        if label != module and label in layout.libs and label not in wanted:
            wanted.add(label)
            stack.extend(layout.deps[label])
    order = []

    def visit(label):  # post-order over the library graph: dependencies are emitted first
        if label in order:
            return
        for dep in sorted(layout.deps[label]):
            if dep in wanted:
                visit(dep)
        order.append(label)
    for label in sorted(wanted):
        visit(label)
    return tuple(reversed(order))


def plan(layout, levels):
    """Which modules get mutants, with which tests; and the findings about modules that cannot."""
    found = []
    for label in sorted(set(levels) & layout.tests):
        found.append(finding("level-on-test", module=label))
    modules = []
    wanted = 0
    for label in sorted(layout.libs | layout.binaries):
        level = levels.get(label)
        if level is None:
            found.append(finding("level-missing", module=label))
        elif level == "L1":
            continue
        elif label in layout.binaries:
            found.append(finding("unmutatable-module", module=label, level=level))
        else:
            wanted += 1
            tests = tuple(sorted(t for t in layout.tests if label in layout.deps[t]))
            if tests:
                modules.append(Module(label, level, tests, _link_deps(layout, label, tests)))
            else:
                found.append(finding("module-without-tests", module=label, level=level))
    if not wanted:
        found.append(finding("no-mutated-modules"))
    return Plan(modules, found)


def target_name(index, module):
    return "m%03d_%s" % (index, re.sub(r"[^A-Za-z0-9_]", "_", module.label.lstrip("/")))


def target_label(index, module):
    return "//%s:%s" % (PACKAGE_DIR, target_name(index, module))


def _list(items):
    return "[\n%s    ]" % "".join('        "%s",\n' % item for item in items)


def build_file_text(modules):
    calls = ['c_mutants(\n    name = "%s",\n    module = "%s",\n    tests = %s,\n    deps = %s,\n)\n'
             % (target_name(i, m), m.label, _list(m.tests), _list(m.deps)) for i, m in enumerate(modules)]
    return 'load("@gate//rules:c.bzl", "c_mutants")\n\n' + "\n".join(calls)


def policy_text(modules, indexes=None):
    """The `rigor mutants` policy; `indexes` are the package positions of `modules` (default: all)."""
    indexes = range(len(modules)) if indexes is None else indexes
    return "\n".join('[module."%s"]\nlevel = "%s"\n' % (target_label(i, m), m.level)
                     for i, m in zip(indexes, modules))


def write_package(run, modules):
    """Write the gate-owned package; refuses to touch anything the product put in its place."""
    for name in (PACKAGE_DIR, PACKAGE_FILE):
        if os.path.lexists(os.path.join(run.tree, name)):
            raise InternalError("%s exists in the grading tree before the mutants step" % name)
    write_file(run.tree, PACKAGE_FILE, PACKAGE_TEXT.encode("utf-8"), 0o644)
    return write_file(run.tree, PACKAGE_DIR + "/BUCK", build_file_text(modules).encode("utf-8"), 0o644)


def build_reports(run, uncached, modules):
    """Build every c_mutants target; copy the reports. Returns (findings, metadata, built indexes)."""
    labels = [target_label(i, m) for i, m in enumerate(modules)]
    report = run.report_path("mutants")
    if os.path.lexists(report):
        os.unlink(report)  # never read a report an earlier run left
    flags = ["--no-remote-cache"] if uncached else []
    code, _, err = grade_build.run_buck(run.tree, ["build", "--target-platforms", PLATFORM, "--keep-going",
                                                 "--build-report", report] + flags + labels)
    executed, cached = grade_build.action_counts(run.tree)
    metadata = {"executed_actions": executed, "cached_actions": cached, "exit_code": code}
    if code != 0:
        metadata["stderr_tail"] = err[-_TAIL_CHARS:]
    results = grade_build.read_report(report) or {}
    out_dir = run.mutants_reports
    os.makedirs(out_dir)
    found, built = [], []
    for index, label in enumerate(labels):
        entry = results.get("root" + label)
        source = None
        if entry is not None and entry.get("success") == "SUCCESS":
            source = grade_build.output_path(run.tree, label, entry)
        if source is None:
            found.append(finding("mutants-build-failed", module=modules[index].label))
            continue
        with open(os.path.join(out_dir, "%03d.json" % index), "xb") as handle:
            handle.write(jsonio.read_bytes(source))
        built.append(index)
    return found, metadata, built


def _relabel(found, names):
    return [dict(item, module=names.get(item["module"], item["module"])) if "module" in item else item
            for item in found]


def judge(g, run, modules, built, approval_kind=approvals.KIND_EQUIVALENT_MUTANT, renames=None):
    """`rigor mutants` over the reports of the modules that built, with a policy the gate writes.

    Returns (findings, per-module summaries, approvals used), all in terms of the product's labels.
    `approval_kind` is the approval that covers a survivor; `renames` maps a finding rule to the rule
    it is reported as (empty for the head).
    """
    policy = os.path.join(run.work, "tmp", "mutants-policy.toml")
    os.makedirs(os.path.dirname(policy), exist_ok=True)
    with open(policy, "xb") as handle:
        handle.write(policy_text([modules[i] for i in built], built).encode("utf-8"))
    result = rigor_mutants.run(Namespace(
        results=run.mutants_reports, policy=policy, approvals=g.args.approvals,
        repo=g.src, head=g.head, allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS), approval_kind)
    names = {target_label(i, modules[i]): modules[i].label for i in built}
    summaries = {names.get(label, label): summary for label, summary in result.metadata["modules"].items()}
    found = [dict(item, rule=renames.get(item["rule"], item["rule"])) for item in
             _relabel(result.findings, names)] if renames else _relabel(result.findings, names)
    return found, summaries, result.metadata["approvals_used"]


def mutants_gate(g):
    if any(g.status.get(gate) != "PASS" for gate in REQUIRED):
        return None  # no clean build and green tests: nothing to judge
    run = grade_build.TreeRun(g.tree, g.work, mutants_reports=os.path.join(g.work, "mutants-reports"))
    try:
        return _run(g, run)
    finally:
        grade_context.kill_daemon(run.tree)


def _run(g, run):
    levels = grade_policy.load_levels(grade_policy.policy_path(g))
    chosen = plan(read_layout(run), levels)
    found = list(chosen.findings)
    if not chosen.modules:
        return GateResult(rigor_mutants.GATE_ID, found, {"modules": {}})
    package_sha = write_package(run, chosen.modules)
    build_found, metadata, built = build_reports(run, g.args.uncached, chosen.modules)
    found.extend(build_found)
    metadata["package_sha256"] = package_sha
    metadata["targets"] = {m.label: target_label(i, m) for i, m in enumerate(chosen.modules)}
    metadata["modules"], metadata["approvals_used"] = {}, []
    if built:
        # The policy names only the modules that built: a missing one already has its own finding.
        judged, summaries, used = judge(g, run, chosen.modules, built)
        found.extend(judged)
        metadata["modules"], metadata["approvals_used"] = summaries, used
    return GateResult(rigor_mutants.GATE_ID, found, metadata)
