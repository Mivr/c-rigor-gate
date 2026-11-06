"""The product checks of `rigor grade` (T004 gates): `buckfiles`, `semantic-suppressions`, `symbols`.

They run after `assemble` and before `build`. `buckfiles` reads the product files of the tree (not
the gate's own). The two fact gates share one Buck2 build of every `*_facts` target (release) plus
the gate's `ctest_facts` and the libc export list; the policy is `products/<p>/policy.toml`, next to
`product.toml` (gate-owned, never read from the product). If the facts cannot be built (for example
the product does not compile) the fact gates are NOT_RUN, which fails the verdict; the `build` gate
reports why.
"""

import os
import shutil
import sys
from dataclasses import dataclass

from rigor_lib import buckfiles, facts_data, facts_policy, facts_semantic, facts_symbols
from rigor_lib import grade_build, grade_context
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult

FACTS_KIND = "c_facts"
CTEST_FACTS = "gate//ctest:ctest_facts"
LIBC_TARGET = "toolchains//:libc_symbols"
PLATFORM = "toolchains//:linux_release"


@dataclass(frozen=True)
class FactsBuild:
    directory: str   # one *.json per facts target
    libc: str        # the libc export list
    metadata: dict


def buckfiles_gate(g):
    if g.status.get("assemble") != "PASS":
        return None
    view = os.path.join(g.work, "tmp", "product-view")
    for path in g.product_paths:
        target = os.path.join(view, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(g.tree, path), target)
    os.makedirs(view, exist_ok=True)
    return GateResult(buckfiles.GATE_ID, buckfiles.walk_findings(view), {"files": len(g.product_paths)})


def _copy_outputs(g, labels, results, directory):
    """Copy the artifact of every label; returns the labels that did not build, or None if all did."""
    bad = []
    paths = {}
    for label in labels:
        entry = results.get(label)
        path = None
        if entry is not None and entry.get("success") == "SUCCESS":
            path = grade_build.output_path(g.tree, label, entry)
        if path is None:
            bad.append(label)
        paths[label] = path
    if bad:
        return bad
    os.makedirs(directory)
    for index, label in enumerate(labels[:-1]):  # the last label is the libc list
        shutil.copyfile(paths[label], os.path.join(directory, "%03d.json" % index))
    return []


def build_facts(g):
    """Build the facts once. Returns a FactsBuild, or a string (why not) for the fact gates."""
    if g.facts is not None:
        return g.facts
    g.facts = _build_facts(g)
    if isinstance(g.facts, str):
        print("facts          not built: %s" % g.facts, file=sys.stderr)
    return g.facts


def _build_facts(g):
    code, out, err = grade_build.run_buck(g.tree, ["uquery", "kind(%s, //...)" % FACTS_KIND])
    if code != 0:
        return "query failed: %s" % err.strip()[-500:]
    labels = sorted(line.strip() for line in out.splitlines() if line.strip())
    labels += [CTEST_FACTS, LIBC_TARGET]  # libc last: _copy_outputs relies on it
    report = os.path.join(g.work, "build-report-facts.json")
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", PLATFORM,
                                                 "--keep-going", "--build-report", report] + flags + labels)
    executed, cached = grade_build.action_counts(g.tree)
    results = grade_build.read_report(report)
    if code != 0 or results is None:
        return "build failed: %s" % err.strip()[-500:]
    directory = os.path.join(g.work, "facts")
    bad = _copy_outputs(g, labels, results, directory)
    if bad:
        return "no output for %s" % ", ".join(bad)
    libc = os.path.join(g.work, "libc.symbols")
    shutil.copyfile(grade_build.output_path(g.tree, LIBC_TARGET, results[LIBC_TARGET]), libc)
    return FactsBuild(directory, libc, {"facts_targets": len(labels) - 1,
                                        "executed_actions": executed, "cached_actions": cached})


def _policy_path(g):
    path = os.path.join(os.path.dirname(g.args.product), "policy.toml")
    if not os.path.isfile(path):
        raise InternalError("missing %s" % path)
    return path


def _fact_gate(g, run):
    if g.status.get("assemble") != "PASS":
        return None
    built = build_facts(g)
    if isinstance(built, str):
        return None
    facts = facts_data.load_facts_dir(built.directory)
    policy = facts_policy.load_policy(_policy_path(g))
    result = run(facts, policy, built)
    result.metadata.update(built.metadata)
    return result


def semantic_gate(g):
    return _fact_gate(g, lambda facts, policy, _built: facts_semantic.run(facts, policy))


def symbols_gate(g):
    return _fact_gate(g, lambda facts, policy, built: facts_symbols.run(
        facts, policy, facts_data.load_symbol_list(built.libc)))
