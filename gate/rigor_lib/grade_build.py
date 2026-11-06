"""The `build` gate: build every `*_results` target in release and san, collect the artifacts.

Buck2 runs through the pinned wrapper `tools/buck2` of the gate checkout inside the tree (so
the same sha256 check applies), with the generated .buckconfig, on the RE farm. Whatever the
product wrote anywhere is not consulted. The daemon is always killed when the gate ends.
"""

import os
import re
import subprocess

from rigor_lib import grade_context, jsonio
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding

BUCK_TIMEOUT_SECONDS = 3600
RESULT_KIND = "ctest_results"
_LABEL = re.compile(r"root//[A-Za-z0-9_./+-]*:[A-Za-z0-9_./+-]+")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TAIL_CHARS = 4000


def run_buck(tree, args):
    """Run the pinned Buck2 in `tree`; returns (exit code, stdout text, stderr text)."""
    command = ["bash", os.path.join(tree, "gate", "tools", "buck2")] + args
    try:
        done = subprocess.run(command, cwd=tree, stdin=subprocess.DEVNULL, capture_output=True,
                              env=grade_context.sealed_env(os.path.dirname(tree)),
                              timeout=BUCK_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InternalError("cannot run buck2: %s" % exc) from exc
    return (done.returncode, _ANSI.sub("", done.stdout.decode("utf-8", "replace")),
            _ANSI.sub("", done.stderr.decode("utf-8", "replace")))


def result_targets(tree):
    """Labels of every ctest_results target in the product, sorted. (code, labels, stderr)."""
    code, out, err = run_buck(tree, ["uquery", "kind(%s, //...)" % RESULT_KIND])
    if code != 0:
        return code, [], err
    labels = sorted(line.strip() for line in out.splitlines() if line.strip())
    for label in labels:
        if not _LABEL.fullmatch(label):
            raise InternalError("odd target label from buck2: %r" % label)
    return 0, labels, err


def action_counts(tree):
    """(executed, cached) action counts of the last Buck2 command, from `log what-ran`.

    Column 3 is the executor: `cache` for an action-cache hit, otherwise where it really ran.
    """
    code, out, err = run_buck(tree, ["log", "what-ran"])
    if code != 0:
        raise InternalError("buck2 log what-ran failed: %s" % err.strip()[-500:])
    executed = cached = 0
    for line in out.splitlines():
        if not line.strip() or line.startswith("Showing"):
            continue
        fields = line.split("\t")
        if len(fields) < 4:
            raise InternalError("odd what-ran line: %r" % line)
        if fields[2] == "cache":
            cached += 1
        else:
            executed += 1
    return executed, cached


def read_report(path):
    if not os.path.isfile(path):
        return None
    document = jsonio.strict_loads(jsonio.read_bytes(path))
    if not isinstance(document, dict) or not isinstance(document.get("results"), dict):
        raise InternalError("odd build report")
    return document["results"]


def output_path(tree, label, entry):
    """The one artifact of a successful target, as a path checked to be inside buck-out."""
    outputs = entry.get("outputs", {}).get("DEFAULT", [])
    if len(outputs) != 1 or not isinstance(outputs[0], str):
        return None
    path = os.path.realpath(os.path.join(tree, outputs[0]))
    if not path.startswith(os.path.realpath(os.path.join(tree, "buck-out")) + os.sep):
        raise InternalError("%s: output outside buck-out: %s" % (label, outputs[0]))
    return path if os.path.isfile(path) else None


def collect_mode(tree, mode, labels, report_path, out_dir):
    """Findings for one mode; copies each target's results file into `out_dir`."""
    results = read_report(report_path)
    found = []
    os.makedirs(out_dir)
    for index, label in enumerate(labels):
        entry = (results or {}).get(label)
        if entry is None or entry.get("success") != "SUCCESS":
            found.append(finding("build-failed", mode=mode, target=label))
            continue
        source = output_path(tree, label, entry)
        if source is None:
            found.append(finding("missing-output", mode=mode, target=label))
            continue
        name = "%03d-%s.jsonl" % (index, re.sub(r"[^A-Za-z0-9_.-]", "_", label))
        with open(os.path.join(out_dir, name), "xb") as handle:
            handle.write(jsonio.read_bytes(source))
    return found


def build_mode(g, mode, labels):
    """Build all labels in one mode. Returns (findings, metadata)."""
    report = os.path.join(g.work, "build-report-%s.json" % mode)
    if os.path.lexists(report):
        os.unlink(report)
    # --uncached: no remote action-cache lookups or writes, so every action runs on a worker.
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = run_buck(g.tree, ["build", "--target-platforms", "toolchains//:linux_" + mode,
                                     "--keep-going", "--build-report", report] + flags + labels)
    executed, cached = action_counts(g.tree)
    metadata = {"executed_actions": executed, "cached_actions": cached, "exit_code": code}
    out_dir = os.path.join(g.test_results, mode)
    found = collect_mode(g.tree, mode, labels, report, out_dir)
    if code != 0 and not found:
        found.append(finding("build-failed", mode=mode, target="*"))
    if code != 0:
        metadata["stderr_tail"] = err[-_TAIL_CHARS:]
    if not found:
        g.built[mode] = out_dir
    return found, metadata


def build_gate(g):
    if g.status.get("assemble") != "PASS":
        return None  # no trustworthy tree to build
    try:
        code, labels, err = result_targets(g.tree)
        if code != 0:
            return GateResult("build", [finding("query-failed")], {"stderr_tail": err[-_TAIL_CHARS:]})
        if not labels:
            return GateResult("build", [finding("no-results-targets")], {})
        found, metadata = [], {"targets": labels}
        for mode in grade_context.MODES:
            mode_found, mode_metadata = build_mode(g, mode, labels)
            found.extend(mode_found)
            metadata[mode] = mode_metadata
        for counter in ("executed_actions", "cached_actions"):
            metadata[counter] = sum(metadata[m][counter] for m in grade_context.MODES)
        return GateResult("build", found, metadata)
    finally:
        grade_context.kill_daemon(g.tree)
