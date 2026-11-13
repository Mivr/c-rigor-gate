"""The `structure` and `mode-divergence` steps of `rigor grade` (T032; backlog B1, B2, B3).

Both read facts that Buck2 makes on RE from the product's own targets; the product declares nothing:

  * `structure`: for every module that has sources, one `c_structure` target. A source file can only be
    named from its own package, so the targets are appended to the BUCK file of the module's package in
    the grading tree (after `buckfiles` has read the product's own files; the original bytes are put
    back when the step ends). The modules, sources, headers and dependencies come from `buck2 uquery`
    over the `c_facts` and `mutsrc` targets of the tree, never from the product's words. Header-only
    modules have no compile, so no target and no dependency edge (their text is read in every unit that
    includes it). Tests and fuzz targets get facts and are not graded (T011). `rigor structure` decides,
    with a policy the gate writes: every built module, with the level of `products/<p>/policy.toml`
    (L4 and L5 are mutation levels; the structure limits stop at L3, so they are L3), or none for a
    module the policy has no level for (L3 and a note).
  * `mode-divergence`: the release facts and the `san` twins (`<name>_facts_san`, rule `c_san_facts`)
    with their `[calls]` sub-targets, compared by `rigor facts --modes`. A twin that is missing is a
    finding, a malformed or one-sided directory is exit 2.

Both are NOT_RUN unless the `build` gate passed (a product that does not compile has no facts), and both
are cached Buck2 builds like every other step (`--uncached` applies).
"""

import os
import re
from argparse import Namespace

from rigor_lib import facts_modes, grade_build, grade_context, grade_policy, grade_sanmodes, jsonio, structure
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding

BUILD_FILE = "BUCK"
LOAD_LINE = 'load("@gate//rules:structure.bzl", "c_structure")\n'
RELEASE = "toolchains//:linux_release"
ANDROID = "toolchains//:android_release"
SAN = "toolchains//:linux_san"
FACTS_RULE = "c_facts"
STRUCTURE_FACTS_RULE = '"^(c_facts|c_android_facts)$"'   # a c_android_so's facts are read in the android mode (T-G2)
ANDROID_KIND = "c_android_so"
ANDROID_LOAD_LINE = 'load("@gate//rules:structure.bzl", "c_android_structure")\n'
SAN_RULE = "c_san_facts"
# The modes compared with release (T138): the mode, and the rule of its facts twins.
MODE_RULES = (("san", SAN_RULE), ("msan", "c_msan_facts"), ("tsan", "c_tsan_facts"))
PLATFORMS = {"san": SAN, "msan": "toolchains//:linux_msan", "tsan": "toolchains//:linux_tsan"}
KINDS = ("c_library", "c_binary", "c_test", "c_fuzz", ANDROID_KIND)
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


def package_of(module):
    return module.label[len("//"):].partition(":")[0]


def target_name(module):
    return module.label.rpartition(":")[2] + "__structure"


def target_label(module):
    return "//%s:%s" % (package_of(module), target_name(module))


def _list(items):
    return "[%s]" % ", ".join(jsonio.canonical_dumps(item).decode("utf-8").strip() for item in items)


def _quoted(text):
    return jsonio.canonical_dumps(text).decode("utf-8").strip()


def call_text(module):
    """The `c_structure` call of one module, written in the BUCK file of its package."""
    if module.kind == ANDROID_KIND:
        return ("c_android_structure(\n    name = %s,\n    module = %s,\n    srcs = %s,\n    headers = %s,\n"
                "    deps = %s,\n    facts_name = %s,\n)\n"
                % (_quoted(target_name(module)), _quoted(":" + module.unit.rpartition(":")[2]), _list(module.srcs),
                   _list(module.headers), _list(module.deps), _quoted(module.label.rpartition(":")[2])))
    return ("c_structure(\n    name = %s,\n    module = %s,\n    srcs = %s,\n    headers = %s,\n"
            "    deps = %s,\n    kind = %s,\n    facts_name = %s,\n)\n"
            % (_quoted(target_name(module)), _quoted(":" + module.unit.rpartition(":")[2]), _list(module.srcs),
               _list(module.headers), _list(module.deps), _quoted(module.kind),
               _quoted(module.label.rpartition(":")[2])))


def extended_text(original, modules):
    """The BUCK file with the load first and the calls after it."""
    loads = LOAD_LINE + (ANDROID_LOAD_LINE if any(m.kind == ANDROID_KIND for m in modules) else "")
    return loads.encode("utf-8") + original + b"\n" + "\n".join(call_text(m) for m in modules).encode("utf-8")


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


def extend_build_files(tree, modules):
    """Append the targets; returns {path: (original bytes, mode)} for `restore_build_files`.

    A module whose unit is not in its own package would need a file of another package: refused."""
    originals = {}
    try:
        for package in sorted({package_of(m) for m in modules}):
            path = os.path.join(tree, package, BUILD_FILE)
            if not os.path.isfile(path) or os.path.islink(path):
                raise InternalError("no %s in the package %r" % (BUILD_FILE, package))
            data = jsonio.read_bytes(path)
            mode = os.stat(path).st_mode & 0o777
            originals[path] = (data, mode)
            here = [m for m in modules if package_of(m) == package]
            if any(m.unit.rpartition(":")[0] != "//" + package for m in here):
                raise InternalError("a unit outside its package in %r" % (package,))
            os.chmod(path, 0o644)
            with open(path, "wb") as handle:
                handle.write(extended_text(data, here))
    except BaseException:
        restore_build_files(originals)
        raise
    return originals


def restore_build_files(originals):
    for path, (data, mode) in originals.items():
        os.chmod(path, 0o644)
        with open(path, "wb") as handle:
            handle.write(data)
        os.chmod(path, mode)


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
    facts = query_json(tree, "kind(%s, //...)" % STRUCTURE_FACTS_RULE, "^(kind|srcs|facts_deps|unit|facts_name)$")
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


def output_of(g, results, label, key="DEFAULT"):
    """The one artifact of a built target (or of its named sub-target output `key`); `label` is spelled
    `root//...` as the build report does."""
    entry = results.get(label)
    if entry is None or entry.get("success") != "SUCCESS":
        return None
    outputs = entry.get("outputs", {})
    if key not in outputs:
        return None
    return grade_build.output_path(g.tree, label, {"outputs": {"DEFAULT": outputs[key]}})


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
    originals = {}
    try:
        return _structure(g, originals)
    finally:
        restore_build_files(originals)
        grade_context.kill_daemon(g.tree)


def _structure(g, originals):
    modules, every = read_modules(g.tree)
    levels = grade_policy.load_levels(grade_policy.policy_path(g))
    found = [finding("policy-module-without-facts", module=label)
             for label in sorted(set(levels) - every)]
    if not modules:
        found.append(finding("no-structure-modules"))
        return GateResult(structure.GATE_ID, found, {"modules": {}})
    originals.update(extend_build_files(g.tree, modules))
    labels = [target_label(m) for m in modules]
    linux = [target_label(m) for m in modules if m.kind != ANDROID_KIND]
    results, metadata = run_build(g, RELEASE, linux, "structure") if linux else ({}, {"executed_actions": 0, "cached_actions": 0, "exit_code": 0})
    android = [target_label(m) for m in modules if m.kind == ANDROID_KIND]
    if android:
        # A c_android_so has no Linux build: its structure facts come from the android mode (NDK clang, NDK headers).
        more, extra = run_build(g, ANDROID, android, "structure-android")
        results = {**results, **more}
        for key in ("executed_actions", "cached_actions"):
            metadata[key] += extra[key]
        metadata["exit_code"] = metadata["exit_code"] or extra["exit_code"]
        if "stderr_tail" in extra:
            metadata["stderr_tail"] = metadata.get("stderr_tail", "") + extra["stderr_tail"]
    directory = fresh_dir(g, "structure-facts")
    built = []
    for index, label in enumerate(labels):
        source = output_of(g, results, "root" + label)
        if source is None:
            found.append(finding("structure-build-failed", module=modules[index].label))
            continue
        copy_file(source, os.path.join(directory, "%03d.json" % index))
        built.append(modules[index])
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
    return twin(label, "san")


def twin(label, mode):
    """`//pkg:x_facts` -> `//pkg:x_facts_<mode>`."""
    return "%s_%s" % (label, mode)


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
        facts, calls = output_of(g, results, label), output_of(g, results, label, "calls")
        if facts is None or calls is None:
            continue
        copy_file(facts, os.path.join(directory, "%03d.json" % index))
        copy_file(calls, os.path.join(directory, "%03d.calls.json" % index))
        built.append(label)
    return built, metadata


def _twins_of(release, mode, existing, blockers):
    """(the twins of `mode` the release targets must have, the findings for the ones that do not exist).

    A target with a sysroot library beyond libc and pthread in its closure has no msan twin (`msan-not-applicable`
    in `tests-msan` names the library for tests): it is left out of the msan comparison."""
    found, twins = [], []
    for label in release:
        if mode == "msan" and blockers.get(grade_sanmodes.facts_module(label)) is not None:
            continue
        if twin(label, mode) in existing:
            twins.append(twin(label, mode))
        else:
            found.append(finding("missing-%s-twin" % mode, target=label))
    return twins, found


def _modes(g):
    release = query_labels(g.tree, "kind(%s, //...)" % FACTS_RULE)
    existing = {mode: query_labels(g.tree, "kind(%s, //...)" % rule) for mode, rule in MODE_RULES}
    found = []
    for mode, _ in MODE_RULES:
        found += [finding("missing-release-twin", target=label, mode=mode) if mode != "san" else
                  finding("missing-release-twin", target=label)
                  for label in existing[mode] if label[:-len("_" + mode)] not in release]
    if not release:
        found.append(finding("no-mode-targets"))
        return GateResult(facts_modes.GATE_ID, found, {})
    blockers = grade_sanmodes.msan_blockers(g.tree)
    twins = {}
    for mode, _ in MODE_RULES:
        twins[mode], missing = _twins_of(release, mode, existing[mode], blockers)
        found += missing
    release_dir = fresh_dir(g, "modes-release")
    built_release, release_meta = _build_mode(g, RELEASE, release, "modes-release", release_dir)
    found += [finding("modes-build-failed", target=label, mode="release") for label in release if label not in built_release]
    metadata = {"release": release_meta, "targets": len(release)}
    directories = {}
    for mode, _ in MODE_RULES:
        if not twins[mode]:
            metadata[mode] = {"executed_actions": 0, "cached_actions": 0, "exit_code": 0}   # nothing to compare (msan: all blocked)
            continue
        directories[mode] = fresh_dir(g, "modes-" + mode)
        built, metadata[mode] = _build_mode(g, PLATFORMS[mode], twins[mode], "modes-" + mode, directories[mode])
        found += [finding("modes-build-failed", target=label, mode=mode) for label in twins[mode] if label not in built]
    for counter in ("executed_actions", "cached_actions"):
        metadata[counter] = release_meta[counter] + sum(metadata[mode][counter] for mode, _ in MODE_RULES)
    if found:
        # Something is missing or did not build: the directories cannot line up, and a comparison
        # of what is left would pass a module it never saw.
        return GateResult(facts_modes.GATE_ID, found, metadata)
    return _compared(g, release_dir, directories, twins, release, metadata)


def _release_subset(g, release_dir, release, twins, mode):
    """A directory with the release facts of the targets that have a twin in `mode` (the files are named by the
    index of the target among `release`, as `_build_mode` wrote them)."""
    directory = fresh_dir(g, "modes-release-" + mode)
    for index, label in enumerate(release):
        if twin(label, mode) in twins:
            for suffix in (".json", ".calls.json"):
                copy_file(os.path.join(release_dir, "%03d%s" % (index, suffix)),
                          os.path.join(directory, "%03d%s" % (index, suffix)))
    return directory


def _compared(g, release_dir, directories, twins, release, metadata):
    """Release against each mode's twins, from the directories that hold the facts. A mode compares only the targets
    it has a twin for (msan has none for a module with a sysroot library beyond pthread), so the release side is cut
    to the same targets."""
    found = []
    for mode, _ in MODE_RULES:
        if not twins[mode]:
            continue
        side = release_dir
        if len(twins[mode]) != len(release):
            side = _release_subset(g, release_dir, release, twins[mode], mode)
        result = facts_modes.run(Namespace(modes=[side, directories[mode]], mode_name=mode))
        found += result.findings
        metadata[mode + "_units"] = result.metadata["units"]
    metadata["units"] = metadata.get("san_units", 0)
    return GateResult(facts_modes.GATE_ID, found, metadata)
