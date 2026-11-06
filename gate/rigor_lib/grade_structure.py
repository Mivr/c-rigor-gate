"""The `structure` and `mode-divergence` steps of `rigor grade` (T032; backlog B1, B2, B3).

Both read facts that Buck2 makes on RE from the product's own targets; the product declares nothing:

  * `structure`: for every module that has sources, one `c_structure` target in a generated package
    (`gate-structure/BUCK`, written after the product was copied, so `buckfiles` never sees it; a root
    `PACKAGE` file makes the product's targets visible to it and both are removed when the step ends,
    because the `mutants` step writes its own). The modules, sources, headers and dependencies come
    from `buck2 uquery` over the `c_facts` and `mutsrc` targets of the tree, never from the product's
    words. Header-only modules have no compile, so no target and no dependency edge (their text is
    read in every unit that includes it). Tests and fuzz targets get facts and are not graded (T011).
    `rigor structure` decides, with a policy the gate writes: every built module, with the level of
    `products/<p>/policy.toml` (L4 and L5 are mutation levels; the structure limits stop at L3, so
    they are L3), or none for a module the policy has no level for (L3 and a note).
  * `mode-divergence`: the release facts and the `san` twins (`<name>_facts_san`, rule `c_san_facts`)
    with their `[calls]` sub-targets, compared by `rigor facts --modes`. A twin that is missing is a
    finding, a malformed or one-sided directory is exit 2.

Both are NOT_RUN unless the `build` gate passed (a product that does not compile has no facts), and both
are cached Buck2 builds like every other step (`--uncached` applies).
"""

import os
import re
import shutil
from argparse import Namespace

from rigor_lib import facts_modes, grade_build, grade_context, grade_policy, jsonio, structure
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.grade_tree import write_file

PACKAGE_DIR = "gate-structure"
PACKAGE_FILE = "PACKAGE"
PACKAGE_TEXT = 'package(visibility = ["PUBLIC"], inherit = True)\n'
RELEASE = "toolchains//:linux_release"
SAN = "toolchains//:linux_san"
FACTS_RULE = "c_facts"
SAN_RULE = "c_san_facts"
KINDS = ("c_library", "c_binary", "c_test", "c_fuzz")
MAX_STRUCTURE_LEVEL = "L3"
_ROOT = "root//"
_GATE = "gate//"
_LABEL = re.compile(r"(root|gate)//[A-Za-z0-9_./+-]*:[A-Za-z0-9_./+-]+")
_TAIL_CHARS = 4000


class Module:
    """One module with sources: what the generated `c_structure` target is made of."""

    def __init__(self, label, unit, kind, srcs, headers, deps):
        self.label, self.unit, self.kind = label, unit, kind
        self.srcs, self.headers, self.deps = tuple(srcs), tuple(headers), tuple(deps)


def _split(label):
    """`root//pkg:name` -> ("pkg", "name"); anything else is an internal error."""
    if not isinstance(label, str) or not label.startswith(_ROOT) or not _LABEL.fullmatch(label):
        raise InternalError("odd target label from buck2: %r" % (label,))
    package, _, name = label[len(_ROOT):].partition(":")
    return package, name


def _strings(label, entry, key):
    value = entry.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InternalError("%s: odd %s from buck2" % (label, key))
    return value


def _file_name(label, text):
    """`root//pkg/file.h` (how buck2 prints a source file) -> `file.h`, for a file of the package of `label`."""
    package, _ = _split(label)
    prefix = _ROOT + package + "/" if package else _ROOT
    if not text.startswith(prefix) or len(text) == len(prefix):
        raise InternalError("%s: a file of another package: %r" % (label, text))
    return text[len(prefix):]


def _dep_label(text):
    """The label a dependency is written as in the generated package, or None when it is not ours to
    graph (another cell than the product and the gate: `buckfiles` and `symbols` already refuse it)."""
    if text.startswith(_ROOT):
        return "//" + text[len(_ROOT):]
    return text if text.startswith(_GATE) else None


def parse_modules(facts, mutsrc):
    """-> (modules in label order, every module label including header-only ones).

    `facts`: the attributes of every `c_facts` target (`kind`, `srcs`, `facts_deps`, `unit`, `facts_name`);
    `mutsrc`: those of every `mutsrc` target (`headers`), whose name is the library's plus `_mutsrc`.
    """
    if not isinstance(facts, dict) or not isinstance(mutsrc, dict):
        raise InternalError("odd query output from buck2")
    headers = {}
    for label, entry in mutsrc.items():
        package, name = _split(label)
        if not name.endswith("_mutsrc") or not isinstance(entry, dict):
            raise InternalError("odd mutsrc target from buck2: %r" % (label,))
        headers["//%s:%s" % (package, name[:-len("_mutsrc")])] = [
            _file_name(label, h) for h in _strings(label, entry, "headers")]
    every, header_only, drafts = set(), set(), []
    for label, entry in sorted(facts.items()):
        package, _ = _split(label)
        if not isinstance(entry, dict) or entry.get("kind") not in KINDS or not isinstance(entry.get("facts_name"), str):
            raise InternalError("%s: odd c_facts attributes from buck2" % label)
        module = "//%s:%s" % (package, entry["facts_name"])
        every.add(module)
        srcs = _strings(label, entry, "srcs")
        if not srcs:
            header_only.add(module)
        else:
            drafts.append((module, label, entry, srcs))
    modules = []
    for module, label, entry, srcs in drafts:
        unit = entry.get("unit")
        if not isinstance(unit, str):
            raise InternalError("%s: no unit from buck2" % label)
        unit_package, unit_name = _split(unit)
        deps = sorted({d for d in (_dep_label(t) for t in _strings(label, entry, "facts_deps")) if d is not None} - header_only)
        modules.append(Module(module, "//%s:%s" % (unit_package, unit_name), entry["kind"], srcs,
                              headers.get(module, []), deps))
    return modules, every


def target_name(index, module):
    return "s%03d_%s" % (index, re.sub(r"[^A-Za-z0-9_]", "_", module.label.lstrip("/")))


def target_label(index, module):
    return "//%s:%s" % (PACKAGE_DIR, target_name(index, module))


def _list(items):
    return "[%s]" % ", ".join(jsonio.canonical_dumps(item).decode("utf-8").strip() for item in items)


def _owned(label, name):
    """A file of the package of a module label (`//pkg:x`) as a label."""
    return "%s:%s" % (label.rpartition(":")[0], name)


def build_file_text(modules):
    calls = []
    for index, module in enumerate(modules):
        name = module.label.rpartition(":")[2]
        calls.append("c_structure(\n    name = %s,\n    module = %s,\n    srcs = %s,\n    headers = %s,\n"
                     "    deps = %s,\n    kind = %s,\n    facts_name = %s,\n)\n"
                     % (_list([target_name(index, module)])[1:-1], _list([module.unit])[1:-1],
                        _list([_owned(module.label, s) for s in module.srcs]),
                        _list([_owned(module.label, h) for h in module.headers]),
                        _list(module.deps), _list([module.kind])[1:-1], _list([name])[1:-1]))
    return 'load("@gate//rules:structure.bzl", "c_structure")\n\n' + "\n".join(calls)


def structure_level(level):
    """The structure limits stop at L3; the mutation levels L4 and L5 ask for at least that much."""
    if level is None or level == "L1" or level == "L2":
        return level
    return MAX_STRUCTURE_LEVEL


def policy_text(modules, levels):
    """The `rigor structure` policy for the modules that built. A test or fuzz target has no level."""
    out = []
    for module in modules:
        level = None if module.kind in ("c_test", "c_fuzz") else structure_level(levels.get(module.label))
        out.append('[module.%s]\n%s' % (jsonio.canonical_dumps(module.label).decode("utf-8").strip(),
                                        "" if level is None else 'level = "%s"\n' % level))
    return "\n".join(out)


def write_package(tree, modules):
    for name in (PACKAGE_DIR, PACKAGE_FILE):
        if os.path.lexists(os.path.join(tree, name)):
            raise InternalError("%s exists in the grading tree before the structure step" % name)
    write_file(tree, PACKAGE_FILE, PACKAGE_TEXT.encode("utf-8"), 0o644)
    return write_file(tree, PACKAGE_DIR + "/BUCK", build_file_text(modules).encode("utf-8"), 0o644)


def remove_package(tree):
    """Take the generated package away again: the `mutants` step refuses a tree that already has one."""
    package = os.path.join(tree, PACKAGE_DIR)
    if os.path.lexists(package):
        grade_context.remove_tree(package)
    if os.path.lexists(os.path.join(tree, PACKAGE_FILE)):
        os.unlink(os.path.join(tree, PACKAGE_FILE))


def query_json(tree, expression, attributes):
    code, out, err = grade_build.run_buck(tree, ["uquery", expression, "--output-format", "json",
                                                 "--output-attribute", attributes])
    if code != 0:
        raise InternalError("buck2 uquery failed: %s" % err.strip()[-500:])
    return jsonio.strict_loads(out.encode("utf-8"))


def query_labels(tree, expression):
    code, out, err = grade_build.run_buck(tree, ["uquery", expression])
    if code != 0:
        raise InternalError("buck2 uquery failed: %s" % err.strip()[-500:])
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def read_modules(tree):
    facts = query_json(tree, "kind(%s, //...)" % FACTS_RULE, "^(kind|srcs|facts_deps|unit|facts_name)$")
    mutsrc = query_json(tree, "kind(mutsrc, //...)", "^headers$")
    return parse_modules(facts, mutsrc)


def run_build(g, platform, labels, tag):
    """Build `labels`. Returns (report results, metadata)."""
    report = os.path.join(g.work, "build-report-%s.json" % tag)
    if os.path.lexists(report):
        os.unlink(report)
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", platform, "--keep-going",
                                                 "--build-report", report] + flags + labels)
    executed, cached = grade_build.action_counts(g.tree)
    metadata = {"executed_actions": executed, "cached_actions": cached, "exit_code": code}
    if code != 0:
        metadata["stderr_tail"] = err[-_TAIL_CHARS:]
    return grade_build.read_report(report) or {}, metadata


def output_of(g, results, label):
    """The one artifact of a built target; `label` is spelled `root//...` as the build report does."""
    entry = results.get(label)
    if entry is None or entry.get("success") != "SUCCESS":
        return None
    return grade_build.output_path(g.tree, label, entry)


def fresh_dir(g, name):
    path = os.path.join(g.work, name)
    if os.path.lexists(path):
        grade_context.remove_tree(path)
    os.makedirs(path)
    return path


def copy_file(source, target):
    with open(target, "xb") as handle:
        handle.write(jsonio.read_bytes(source))


def structure_enabled(g):
    return g.status.get("assemble") == "PASS" and g.status.get("build") == "PASS"


def structure_gate(g):
    if not structure_enabled(g):
        return None   # no tree that compiles: nothing to read
    try:
        return _structure(g)
    finally:
        remove_package(g.tree)
        grade_context.kill_daemon(g.tree)


def _structure(g):
    modules, every = read_modules(g.tree)
    levels = grade_policy.load_levels(grade_policy.policy_path(g))
    found = [finding("policy-module-without-facts", module=label)
             for label in sorted(set(levels) - every)]
    if not modules:
        found.append(finding("no-structure-modules"))
        return GateResult(structure.GATE_ID, found, {"modules": {}})
    package_sha = write_package(g.tree, modules)
    labels = [target_label(i, m) for i, m in enumerate(modules)]
    results, metadata = run_build(g, RELEASE, labels, "structure")
    directory = fresh_dir(g, "structure-facts")
    built = []
    for index, label in enumerate(labels):
        source = output_of(g, results, "root" + label)
        if source is None:
            found.append(finding("structure-build-failed", module=modules[index].label))
            continue
        copy_file(source, os.path.join(directory, "%03d.json" % index))
        built.append(modules[index])
    metadata["package_sha256"] = package_sha
    metadata["modules"] = {}
    if built:
        policy = os.path.join(g.work, "tmp", "structure-policy.toml")
        os.makedirs(os.path.dirname(policy), exist_ok=True)
        if os.path.lexists(policy):
            os.unlink(policy)
        with open(policy, "xb") as handle:
            handle.write(policy_text(built, levels).encode("utf-8"))
        result = structure.run(Namespace(facts=directory, policy=policy))
        found.extend(result.findings)
        metadata.update({k: v for k, v in result.metadata.items() if k != "modules"})
        metadata["modules"] = result.metadata["modules"]
    return GateResult(structure.GATE_ID, found, metadata)


# ---------------------------------------------------------------------------------------------
# mode-divergence
# ---------------------------------------------------------------------------------------------

def san_twin(label):
    """`//pkg:x_facts` -> `//pkg:x_facts_san`."""
    return label + "_san"


def modes_gate(g):
    if not structure_enabled(g):
        return None
    try:
        return _modes(g)
    finally:
        grade_context.kill_daemon(g.tree)


def _build_mode(g, platform, labels, tag, directory):
    """Build each label and its `[calls]`; copy both. Returns the labels that built, and the metadata."""
    wanted = [text for label in labels for text in (label, label + "[calls]")]
    results, metadata = run_build(g, platform, wanted, tag)
    built = []
    for index, label in enumerate(labels):
        facts, calls = (output_of(g, results, text) for text in (label, label + "[calls]"))
        if facts is None or calls is None:
            continue
        copy_file(facts, os.path.join(directory, "%03d.json" % index))
        copy_file(calls, os.path.join(directory, "%03d.calls.json" % index))
        built.append(label)
    return built, metadata


def _modes(g):
    release = query_labels(g.tree, "kind(%s, //...)" % FACTS_RULE)
    san = query_labels(g.tree, "kind(%s, //...)" % SAN_RULE)
    found = [finding("missing-san-twin", target=label) for label in release if san_twin(label) not in san]
    found += [finding("missing-release-twin", target=label) for label in san if label[:-len("_san")] not in release]
    if not release:
        found.append(finding("no-mode-targets"))
        return GateResult(facts_modes.GATE_ID, found, {})
    twins = [san_twin(label) for label in release if san_twin(label) in san]
    release_dir, san_dir = fresh_dir(g, "modes-release"), fresh_dir(g, "modes-san")
    built_release, release_meta = _build_mode(g, RELEASE, release, "modes-release", release_dir)
    built_san, san_meta = _build_mode(g, SAN, twins, "modes-san", san_dir)
    found += [finding("modes-build-failed", target=label, mode="release") for label in release if label not in built_release]
    found += [finding("modes-build-failed", target=label, mode="san") for label in twins if label not in built_san]
    metadata = {"release": release_meta, "san": san_meta, "targets": len(release)}
    for counter in ("executed_actions", "cached_actions"):
        metadata[counter] = release_meta[counter] + san_meta[counter]
    if found:
        # Something is missing or did not build: the two directories cannot line up, and a comparison
        # of what is left would pass a module it never saw.
        return GateResult(facts_modes.GATE_ID, found, metadata)
    result = facts_modes.run(Namespace(modes=[release_dir, san_dir]))
    metadata.update(result.metadata)
    return GateResult(facts_modes.GATE_ID, result.findings, metadata)
