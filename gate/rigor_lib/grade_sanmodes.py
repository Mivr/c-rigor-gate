"""The gates `tests-msan` and `tests-tsan` of `rigor grade` (T138; P003 7.1), and what they and `mode-divergence` read
from the product's targets.

Both judge the results of their mode with the `tests` rules of `tests-release` and `tests-san` (`tests_gate`: expected
ids, fail-closed results, assertion counts), in role test-author with the same `presence_only`. Unlike those two they
build their own results: the `build` gate builds release and san for every `<name>_results`, and a target that does not
exist in a mode cannot be named in a build of it (Buck2 refuses an incompatible target named by label). So each gate
builds the subset of targets its mode has, in one Buck2 invocation of the head tree, and is NOT_RUN under the same
conditions as `tests-san` (no clean results of the build gate; this one also needs release, whose results say which test
ids each target holds).

  * `tests-msan` expects every expected id except those of a test whose link closure has a sysroot library beyond libc
    and pthread (rules/c.bzl: no msan results target). Each such test is the info `msan-not-applicable`, naming the library.
  * `tests-tsan` expects exactly the ids of the tests declared `threads = True` (the `threads` attribute of the
    `ctest_results` target); none declared is a PASS with the info `no-threaded-tests`.
  * Results of a mode that end with the sanitizer runtime's own start-up CHECK (the farm refuses
    `personality(ADDR_NO_RANDOMIZE)`, docs/toolchain.md) are the error `sanitizer-startup`, not a list of missing tests.
    There is no retry.
"""

import os
import re
from argparse import Namespace

from rigor_lib import contract, grade_build, grade_context, grade_steps, jsonio, results_parse, tests_gate
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

SANITIZER_MODES = ("msan", "tsan")
FACTS_RULE = "c_facts"
# The runtime's own words when it cannot re-exec itself (the `startup_diag` of selftest/sanmodes.sh).
STARTUP = re.compile(r"personality\(.*\) *!= *\(?\(?-1|memory layout is incompatible")
PREREQUISITE = "the RE worker must allow personality(ADDR_NO_RANDOMIZE) (docs/toolchain.md, The farm prerequisite)"
_ROOT = "root//"


def _query(tree, expression, attributes):
    code, out, err = grade_build.run_buck(tree, ["uquery", expression, "--output-format", "json",
                                                 "--output-attribute", attributes])
    if code != 0:
        raise InternalError("buck2 uquery failed: %s" % err.strip()[-500:])
    document = jsonio.strict_loads(out.encode("utf-8"))
    if not isinstance(document, dict) or not all(isinstance(v, dict) for v in document.values()):
        raise InternalError("odd query output from buck2")
    return document


def _module(label):
    """`root//pkg:name` -> `//pkg:name` (how the facts files name a target)."""
    if not isinstance(label, str) or not label.startswith(_ROOT):
        raise InternalError("odd target label from buck2: %r" % (label,))
    return "//" + label[len(_ROOT):]


def facts_module(label):
    """`root//pkg:name_facts` -> `//pkg:name`: the one form `msan_blockers` keys by (and `_scope` looks up)."""
    module = _module(label)
    if not module.endswith("_facts"):
        raise InternalError("odd c_facts label from buck2: %r" % (label,))
    return module[:-len("_facts")]


def results_attributes(tree):
    """{`ctest_results` label: (the module of its test, whether the test declares `threads = True`)}."""
    found = {}
    for label, entry in _query(tree, "kind(%s, //...)" % grade_build.RESULT_KIND, "^(test|threads)$").items():
        threads = entry.get("threads", False)
        if type(threads) is not bool:
            raise InternalError("%s: odd threads from buck2: %r" % (label, threads))
        found[label] = (_module(entry.get("test")), threads)
    return found


def declared_threads(tree):
    """{module of a `c_test`: its `threads` declaration}."""
    return dict(results_attributes(tree).values())


def msan_blockers(tree):
    """{module: the first sysroot library beyond pthread in its link closure, or None} for every module with facts.

    The closure follows `facts_deps` (a library's `exported_deps` are in them), iteratively; the msan mode has no
    target for such a module (rules/c.bzl `_NOT_IN_MSAN`) or for anything that depends on it."""
    own, edges = {}, {}
    for label, entry in _query(tree, "kind(%s, //...)" % FACTS_RULE, "^(facts_deps|system_libs|facts_name)$").items():
        module = "//%s:%s" % (_module(label)[2:].partition(":")[0], entry.get("facts_name"))
        own[module] = {lib for lib in entry.get("system_libs", []) if lib != "pthread"}
        edges[module] = [_module(dep) for dep in entry.get("facts_deps", []) if dep.startswith(_ROOT)]
    blockers = {}
    for module in sorted(own):
        libs, seen, todo = set(), set(), [module]
        while todo:
            current = todo.pop()
            if current in seen or current not in own:
                continue
            seen.add(current)
            libs |= own[current]
            todo.extend(edges[current])
        blockers[module] = sorted(libs)[0] if libs else None
    return blockers


def _release_ids(release_dir, labels):
    """{label: the test ids of its release results file}: the build gate named the files by the label's index."""
    ids = {}
    for index, label in enumerate(labels):
        name = grade_build.result_file_name(index, label)
        path = os.path.join(release_dir, name)
        if not os.path.isfile(path):
            raise InternalError("no release results for %s: %s" % (label, path))
        ids[label] = {record.test_id for record in results_parse.parse_file(name, jsonio.read_bytes(path)).records}
    return ids


def _build(g, mode, labels):
    """(findings, metadata, results directory) of one Buck2 build of `labels` in `mode`."""
    report = os.path.join(g.work, "build-report-%s.json" % mode)
    if os.path.lexists(report):
        os.unlink(report)
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", "toolchains//:linux_" + mode,
                                                 "--keep-going", "--build-report", report] + flags + labels)
    executed, cached = grade_build.action_counts(g.tree)
    metadata = {"executed_actions": executed, "cached_actions": cached, "exit_code": code, "targets": labels}
    if code != 0 and STARTUP.search(err):
        return [finding("sanitizer-startup", mode=mode, prerequisite=PREREQUISITE)], metadata, None
    directory = os.path.join(g.test_results, mode)
    found = grade_build.collect_mode(g.tree, mode, labels, report, directory)
    if code != 0 and not found:
        found.append(finding("build-failed", mode=mode, target="*"))
    return found, metadata, directory


def _write_expected(g, mode, ids):
    directory = os.path.join(g.work, "tmp")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "expected-%s.json" % mode)
    with open(path, "wb") as handle:
        handle.write(jsonio.canonical_dumps({"ids": sorted(ids)}))
    return path


def _scope(mode, labels, attributes, blockers):
    """(labels the mode has a results target for, the info findings for the ones it has not)."""
    if mode == "tsan":
        return [label for label in labels if attributes[label][1]], []
    chosen, infos = [], []
    for label in labels:
        library = blockers.get(attributes[label][0])
        if library is None:
            chosen.append(label)
        else:
            infos.append(finding("msan-not-applicable", severity=SEVERITY_INFO, target=attributes[label][0],
                                 library=library))
    return chosen, infos


def _expected_for(mode, expected, ids, labels, chosen):
    """The ids this mode must show: msan everything but the ids of the targets it lacks, tsan the ids of its targets."""
    if mode == "tsan":
        return expected & set().union(*(ids[label] for label in chosen)) if chosen else set()
    return expected - set().union(*(ids[label] for label in labels if label not in chosen))


def _judge(g, mode, release_dir):
    attributes = results_attributes(g.tree)
    labels = sorted(attributes)
    ids = _release_ids(release_dir, labels)
    chosen, infos = _scope(mode, labels, attributes, msan_blockers(g.tree) if mode == "msan" else {})
    gate_id = "tests-" + mode
    metadata = {"mode": mode, "targets": chosen}
    if not chosen:
        rule = "no-threaded-tests" if mode == "tsan" else "no-msan-targets"
        return GateResult(gate_id, infos + [finding(rule, severity=SEVERITY_INFO)], metadata)
    wanted = _expected_for(mode, tests_gate.load_id_list(grade_steps._expected_input(g)), ids, labels, chosen)
    found, built, directory = _build(g, mode, chosen)
    metadata.update(built)
    if found:
        return GateResult(gate_id, infos + found, metadata)
    result = tests_gate.run(Namespace(
        results=directory, expected=_write_expected(g, mode, wanted), previous=None,
        approvals=g.args.approvals, repo=g.src, head=g.head, allowed_signers=g.args.allowed_signers,
        presence_only=grade_steps.role(g) == contract.ROLE_TEST_AUTHOR))
    metadata.update(result.metadata)
    return GateResult(gate_id, infos + result.findings, metadata)


def sanitizer_tests_gate(mode):
    """The gate `tests-<mode>` for `msan` or `tsan` (module docstring)."""
    if mode not in SANITIZER_MODES:
        raise InternalError("no such sanitizer mode: %s" % mode)

    def gate(g):
        release, san = g.built.get("release"), g.built.get("san")
        if release is None or san is None:
            return None  # the build did not produce clean results (tests-san's condition; release names the ids)
        try:
            return _judge(g, mode, release)
        finally:
            grade_context.kill_daemon(g.tree)
    return gate
