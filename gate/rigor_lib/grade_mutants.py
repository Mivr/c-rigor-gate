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
In role test-author it is PASS with info `not-applicable`: the head is the stub commit (P002 Q2).
"""

import os
import re
from argparse import Namespace
from dataclasses import dataclass

from rigor_lib import approval_args, approvals, contract, grade_build, grade_context, grade_policy, jsonio, perf_package, perf_policy
from rigor_lib import mutants_gate as rigor_mutants
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.grade_tree import write_file

PACKAGE_DIR = "gate-mutants"
PACKAGE_FILE = "PACKAGE"
PACKAGE_TEXT = 'package(visibility = ["PUBLIC"], inherit = True)\n'
REQUIRED = ("assemble", "buckfiles", "build", "tests-release", "tests-san")
PLATFORM = "toolchains//:linux_release"
_ROOT = "root//"
_LABEL = re.compile(r"[A-Za-z0-9_.-]+//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+")
_TAIL_CHARS = 4000
PERF_DIR = "mutants-perf"
PERF_KIT = "gate//ctest:perf"   # the harness has a main of its own: never linked into a test


@dataclass(frozen=True)
class Layout:
    libs: frozenset      # c_library labels ("//pkg:name")
    binaries: frozenset  # c_binary labels
    tests: frozenset     # c_test labels
    deps: dict           # label -> tuple of direct dependency labels of the product's own cell
    external: frozenset = frozenset()  # libraries of other cells ("gate//third_party/..:x"), linkable like libs
    links: dict = None   # label -> direct `deps` + `exported_deps` of every cell: what the tests link (T070)


@dataclass(frozen=True)
class Module:
    label: str
    level: str
    tests: tuple   # c_tests that depend on the module directly
    deps: tuple    # libraries linked into those tests besides the module (any cell), dependents first
    perf: tuple = ()   # ((`//x:y_perf` target, class), ...) the policy declares for the module (T090), sorted


@dataclass(frozen=True)
class Plan:
    modules: list
    findings: list


def _short(label):
    """`root//pkg:name` -> `//pkg:name`; a label of another cell keeps its cell (`gate//pkg:name`)."""
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise InternalError("odd target label from buck2: %r" % (label,))
    return label[len("root"):] if label.startswith(_ROOT) else label


def _direct_deps(label, entry, keys=("deps",)):
    out = []
    for key in keys:
        deps = entry.get(key, [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise InternalError("%s: odd %s from buck2" % (label, key))
        out.extend(_short(d) for d in deps)
    return tuple(out)


def parse_layout(result_targets, attributes, binaries):
    """Layout from the three queries: `ctest_results` targets (attribute `test`), the attributes of every
    library, test, binary and `mutsrc` of the product and the libraries they reach in other cells (a library `x`
    of the product is a `c_library` iff `x_mutsrc` exists), and the labels of the `cxx_binary` targets."""
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
    ours = {label for label in entries if label.startswith("//")}
    libs = {label for label in ours if label + "_mutsrc" in entries}
    external = {label for label in entries if not label.startswith("//")}
    binary_labels = {_short(label) for label in binaries}
    missing = (tests | binary_labels) - set(entries)
    if missing:
        raise InternalError("no attributes for %s" % sorted(missing))
    labels = sorted(libs | tests | binary_labels | external)
    links = {label: _direct_deps(label, entries[label], _DEP_KEYS) for label in labels}
    deps = {label: tuple(d for d in links[label] if d.startswith("//")) for label in labels if label.startswith("//")}
    return Layout(frozenset(libs), frozenset(binary_labels), frozenset(tests), deps, frozenset(external), links)


_EXTERNAL_KINDS = "^(cxx_library|prebuilt_cxx_library)$"
_DEP_KEYS = ("deps", "exported_deps")


def add_external(attributes, query):
    """Add to ATTRIBUTES (label -> attributes, as the queries print them) the libraries of other cells that
    the product reaches through `deps` and `exported_deps`, closed under the same two attributes. `query(labels)`
    returns the attributes of those labels that are libraries. (`deps(//...)` cannot do this in the unconfigured
    graph: it also follows the toolchain's hidden deps.) A dep that is not a library stays out and is reported
    by `plan` as `unresolved-link-dep`."""
    seen = set(attributes)
    pending = set()

    def note(entry):
        for key in _DEP_KEYS:
            deps = entry.get(key, []) if isinstance(entry, dict) else []
            if isinstance(deps, list):
                pending.update(d for d in deps if isinstance(d, str) and not d.startswith(_ROOT))
    for entry in list(attributes.values()):
        note(entry)
    while pending - seen:
        asked = sorted(pending - seen)
        seen.update(asked)
        found = query(asked)
        if not isinstance(found, dict):
            raise InternalError("odd query output from buck2")
        for label, entry in found.items():
            attributes[label] = entry
            note(entry)
    return attributes


def read_layout(run):
    def query(args):
        code, out, err = grade_build.run_buck(run.tree, ["uquery"] + args)
        if code != 0:
            raise InternalError("buck2 uquery failed: %s" % err.strip()[-500:])
        return out
    attribute = ["--output-format", "json", "--output-attribute"]

    def libraries(labels):
        expression = "kind('%s', set(%s))" % (_EXTERNAL_KINDS, " ".join(labels))
        return jsonio.strict_loads(query([expression] + attribute + ["^(deps|exported_deps)$"]).encode("utf-8"))
    results = jsonio.strict_loads(query(["kind(ctest_results, //...)"] + attribute + ["^test$"]).encode("utf-8"))
    attributes = jsonio.strict_loads(query(
        ["kind('^(cxx_library|cxx_binary|cxx_test|mutsrc)$', //...)"] + attribute + ["^(deps|exported_deps)$"]).encode("utf-8"))
    binaries = [line.strip() for line in query(["kind(cxx_binary, //...)"]).splitlines() if line.strip()]
    if not isinstance(attributes, dict):
        raise InternalError("odd query output from buck2")
    return parse_layout(results, add_external(attributes, libraries), binaries)


def _link_deps(layout, module, tests, extra=(), skip=()):
    """What the module's tests link besides the module, as `(deps, unresolved)`. `deps` is the closure of their
    deps and of the module's over every library of the layout, first-party or from another cell (third-party
    ones included), without the module; a library comes before the ones it depends on (static archives, one
    pass). `unresolved` lists the labels reached that are no library of the layout: never dropped silently."""
    linkable = layout.libs | layout.external
    wanted = set()
    unresolved = set()
    links = layout.deps if layout.links is None else layout.links
    stack = [d for t in tests for d in links[t]] + list(links[module]) + [d for b in extra for d in links[b]]
    while stack:
        label = stack.pop()
        if label == module or label in wanted or label in unresolved or label in skip:
            continue
        if label in linkable:
            wanted.add(label)
            stack.extend(links[label])
        else:
            unresolved.add(label)
    order = []

    def visit(label):  # post-order over the library graph: dependencies are emitted first
        if label in order:
            return
        for dep in sorted(links[label]):
            if dep in wanted:
                visit(dep)
        order.append(label)
    for label in sorted(wanted):
        visit(label)
    return tuple(reversed(order)), tuple(sorted(unresolved))


def perf_binary(target):
    """The `c_perf` binary behind a `<name>_perf` target label."""
    return target[:-len(perf_policy.SUFFIX)]


def plan(layout, levels, perf=None):
    """Which modules get mutants, with which tests; and the findings about modules that cannot.
    `perf` is the policy's {module: {perf target: class}} (T090): the modules that have entries also run those
    perf targets for their survivors, so what the perf binaries link is linked into the mutants too."""
    perf = perf or {}
    found = []
    for label in sorted(set(levels) & layout.tests):
        found.append(finding("level-on-test", module=label))
    modules = []
    wanted = 0
    for label in sorted(layout.libs | layout.binaries):
        if label.startswith("//%s:" % perf_policy.PACKAGE):
            continue   # the gate's own perf binaries (perf_package): no level
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
                classes = perf.get(label, {})
                for target in sorted(classes):
                    if perf_binary(target) not in layout.binaries:
                        found.append(finding("perf-target-unknown", module=label, target=target))
                classes = {t: c for t, c in classes.items() if perf_binary(t) in layout.binaries}
                linked, unresolved = _link_deps(layout, label, tests, [perf_binary(t) for t in classes], (PERF_KIT,))
                for dep in unresolved:
                    found.append(finding("unresolved-link-dep", module=label, dep=dep))
                if not unresolved:
                    modules.append(Module(label, level, tests, linked, tuple(sorted(classes.items()))))
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
    calls = []
    for i, m in enumerate(modules):
        if m.perf:  # T090: the module's perf targets run for the survivors
            calls.append('c_mutants_with_perf(\n    name = "%s",\n    module = "%s",\n    tests = %s,\n    perf = %s,\n    deps = %s,\n)\n'
                         % (target_name(i, m), m.label, _list(m.tests), _list([t for t, _ in m.perf]), _list(m.deps)))
        else:
            calls.append('c_mutants(\n    name = "%s",\n    module = "%s",\n    tests = %s,\n    deps = %s,\n)\n'
                         % (target_name(i, m), m.label, _list(m.tests), _list(m.deps)))
    loads = 'load("@gate//rules:c.bzl", "c_mutants")\n'
    if any(m.perf for m in modules):
        loads += 'load("@gate//rules:mutate.bzl", "c_mutants_with_perf")\n'
    return loads + "\n" + "\n".join(calls)


def policy_text(modules, indexes=None):
    """The `rigor mutants` policy; `indexes` are the package positions of `modules` (default: all)."""
    indexes = range(len(modules)) if indexes is None else indexes
    return "\n".join('[module."%s"]\nlevel = "%s"\n' % (target_label(i, m), m.level)
                     + "".join('[module."%s".perf."%s"]\nclass = "%s"\n' % (target_label(i, m), t, c) for t, c in m.perf)
                     for i, m in zip(indexes, modules))


def write_shared_package_file(tree):
    """The root `PACKAGE` file that makes the product's targets visible to the gate's packages. Refuses to touch
    anything the product put in its place."""
    if os.path.lexists(os.path.join(tree, PACKAGE_FILE)):
        raise InternalError("%s exists in the grading tree before the gate package was written" % PACKAGE_FILE)
    write_file(tree, PACKAGE_FILE, PACKAGE_TEXT.encode("utf-8"), 0o644)


def remove_shared_package_file(tree):
    path = os.path.join(tree, PACKAGE_FILE)
    if os.path.isfile(path) and not os.path.islink(path) and jsonio.read_bytes(path) == PACKAGE_TEXT.encode("utf-8"):
        os.unlink(path)


def write_gate_package(tree, package_dir, build_text, shared=False):
    """Write a gate-owned package (`<package_dir>/BUCK`) and the root `PACKAGE` file that makes the product's
    targets visible to it (`shared`: the file was written by `gate-perf/`'s writer and is left alone). Refuses to touch
    anything the product put in their place. Returns the BUCK sha256. Shared with the hidden-test package of B7."""
    if os.path.lexists(os.path.join(tree, package_dir)):
        raise InternalError("%s exists in the grading tree before the gate package was written" % package_dir)
    if not shared:
        write_shared_package_file(tree)
    return write_file(tree, package_dir + "/BUCK", build_text.encode("utf-8"), 0o644)


def write_package(run, modules, shared=False):
    """Write the `c_mutants` package of the tree."""
    return write_gate_package(run.tree, PACKAGE_DIR, build_file_text(modules), shared)


def build_reports(run, uncached, modules):
    """Build every c_mutants target; copy the reports. Returns (findings, metadata, built indexes)."""
    labels = [target_label(i, m) for i, m in enumerate(modules)]
    perf_labels = {i: target_label(i, m) + "[perf]" for i, m in enumerate(modules) if m.perf}
    report = run.report_path("mutants")
    if os.path.lexists(report):
        os.unlink(report)  # never read a report an earlier run left
    flags = ["--no-remote-cache"] if uncached else []
    code, _, err = grade_build.run_buck(run.tree, ["build", "--target-platforms", PLATFORM, "--keep-going",
                                                 "--build-report", report] + flags + labels + sorted(perf_labels.values()))
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
    found.extend(_copy_perf(run, results, perf_labels, built, modules))
    return found, metadata, built


def _copy_perf(run, results, perf_labels, built, modules):
    """Copy the perf evidence of the modules that have it into `<work>/mutants-perf/` (beside the reports)."""
    if not perf_labels:
        return []
    out_dir = os.path.join(os.path.dirname(run.mutants_reports), PERF_DIR)
    os.makedirs(out_dir, exist_ok=True)
    found = []
    for index, label in sorted(perf_labels.items()):
        entry = results.get("root" + label)
        source = None
        if entry is not None and entry.get("success") == "SUCCESS":
            source = grade_build.output_path(run.tree, label, entry)
        if source is None:
            found.append(finding("perf-build-failed", module=modules[index].label))
            continue
        with open(os.path.join(out_dir, "%03d.json" % index), "xb") as handle:
            handle.write(jsonio.read_bytes(source))
    return found


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
    perf_dir = os.path.join(os.path.dirname(run.mutants_reports), PERF_DIR)
    result = rigor_mutants.run(Namespace(
        results=run.mutants_reports, policy=policy, perf_results=perf_dir, approvals=g.args.approvals,
        repo=g.src, head=g.head, allowed_signers=g.args.allowed_signers), approval_kind)
    names = {target_label(i, modules[i]): modules[i].label for i in built}
    summaries = {names.get(label, label): summary for label, summary in result.metadata["modules"].items()}
    found = [dict(item, rule=renames.get(item["rule"], item["rule"])) for item in
             _relabel(result.findings, names)] if renames else _relabel(result.findings, names)
    return found, summaries, result.metadata["approvals_used"]


def mutants_gate(g):
    if any(g.status.get(gate) != "PASS" for gate in REQUIRED):
        return None  # no clean build and green tests: nothing to judge
    role = contract.load_contract(g.args.task).role
    if role == contract.ROLE_TEST_AUTHOR:
        # The head is the stub commit: its mutants could only be `baseline-red`. The witness is mutated
        # instead (`mutants-witness`), and modules outside W kept their code and tests (P002 Q2).
        return GateResult(rigor_mutants.GATE_ID, [finding("not-applicable", SEVERITY_INFO, role=role)],
                          {"role": role, "modules": {}})
    run = grade_build.TreeRun(g.tree, g.work, mutants_reports=os.path.join(g.work, "mutants-reports"))
    try:
        return _run(g, run)
    finally:
        grade_context.kill_daemon(run.tree)


def _run(g, run):
    levels = grade_policy.load_levels(grade_policy.policy_path(g))
    targets = perf_policy.load(grade_policy.policy_path(g), getattr(g, "perf", None))
    if targets:   # the perf binaries must be in the tree before the layout is read
        write_shared_package_file(run.tree)
        perf_package.write(run.tree, targets)
    chosen = plan(read_layout(run), levels, perf_policy.by_module(targets))
    found = list(chosen.findings)
    if not chosen.modules:
        return GateResult(rigor_mutants.GATE_ID, found, {"modules": {}})
    package_sha = write_package(run, chosen.modules, bool(targets))
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
