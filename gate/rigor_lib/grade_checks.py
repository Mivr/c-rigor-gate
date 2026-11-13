"""The product checks of `rigor grade` (T004 gates): `buckfiles`, `semantic-suppressions`, `symbols`.

They run after `assemble` and before `build`. `buckfiles` reads the product files of the tree (not
the gate's own). The two fact gates share one Buck2 build of every `*_facts` target (release) plus
the gate's `ctest_facts` and the libc export list; the policy is `products/<p>/policy.toml` (both gates
read it whole, `level` included: the symbols gate needs it for `exports`), next to `product.toml` (gate-owned, never read from the product). If the facts cannot be built (for example
the product does not compile) the fact gates are NOT_RUN, which fails the verdict; the `build` gate
reports why.
"""

import os
import shutil
import sys
from dataclasses import dataclass

from rigor_lib import buckfiles, facts_data, facts_policy, facts_semantic, facts_symbols, layering, layering_check
from rigor_lib import grade_build, grade_context, grade_policy, facts_third_party, grade_toolchain, grade_tree
from rigor_lib import paths, product_layout
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

FACTS_KIND = "c_facts"
ANDROID_FACTS_KIND = "c_android_facts"   # the facts of every c_android_so (T-G2), built in the android mode
ANDROID_SO_KIND = "android_so"           # the rule the c_android_so macro makes its output with
ANDROID_APK_CHECK_KIND = "apk_check"     # the rule of every c_apk's `<name>_check` (T-G3)
CTEST_FACTS = "gate//ctest:ctest_facts"
LIBC_TARGET = "toolchains//:libc_symbols"
LIBC_ANDROID_TARGET = "toolchains//:libc_symbols_android"
PLATFORM = "toolchains//:linux_release"
ANDROID_PLATFORM = "toolchains//:android_release"


@dataclass(frozen=True)
class FactsBuild:
    directory: str   # one *.json per facts target
    libc: str        # the libc export list
    metadata: dict
    libc_android: str = None   # the NDK's export list, read for the facts of a c_android_so; None: the product has none


def _display(text):
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def layout_findings(g):
    """The layout coverage rule (B14): product code the layout leaves out is a finding, not silence.

    Reads the product head from the clone (git blobs, as `assemble` does) and the BUCK files that were
    copied into the tree. It is part of this gate because `assemble` cannot be extended from here.
    """
    entries = [(paths.match_text(e.path), e.mode) for e in grade_tree.list_tree(g.src, g.head)]
    buck_texts = []
    for path in g.product_paths:
        if product_layout.is_build_file(path):
            with open(os.path.join(g.tree, path), "rb") as handle:
                buck_texts.append((path, handle.read().decode("utf-8", "replace")))
    return [finding(rule, path=_display(path), reason=reason)
            for rule, path, reason in product_layout.coverage_findings(g.product, entries, buck_texts)]


def buckfiles_gate(g):
    if g.status.get("assemble") != "PASS":
        return None
    view = os.path.join(g.work, "tmp", "product-view")
    for path in g.product_paths:
        target = os.path.join(view, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(g.tree, path), target)
    os.makedirs(view, exist_ok=True)
    found = buckfiles.walk_findings(view) + layout_findings(g)
    return GateResult(buckfiles.GATE_ID, found, {"files": len(g.product_paths)})


def _artifacts(g, labels, results):
    """({label: artifact path}, [labels that did not build])."""
    bad, found = [], {}
    for label in labels:
        entry = results.get(label)
        path = None
        if entry is not None and entry.get("success") == "SUCCESS":
            path = grade_build.output_path(g.tree, label, entry)
        if path is None:
            bad.append(label)
        found[label] = path
    return found, bad


def _copy_facts(found, labels, directory, start):
    """Copy the artifact of every label to `directory` as <start + index>.json."""
    os.makedirs(directory, exist_ok=True)
    for index, label in enumerate(labels):
        shutil.copyfile(found[label], os.path.join(directory, "%03d.json" % (start + index)))


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
    # B12: the facts of every gate-owned library a product may use (`<label>_symbols`), trusted by name.
    labels += sorted(label + "_symbols" for label in facts_third_party.load().trusted)
    labels += [CTEST_FACTS]
    report = os.path.join(g.work, "build-report-facts.json")
    flags = ["--no-remote-cache"] if g.args.uncached else []
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", PLATFORM,
                                                 "--keep-going", "--build-report", report] + flags
                                        + labels + [LIBC_TARGET])
    executed, cached = grade_build.action_counts(g.tree)
    results = grade_build.read_report(report)
    if code != 0 or results is None:
        return "build failed: %s" % err.strip()[-500:]
    found, bad = _artifacts(g, labels + [LIBC_TARGET], results)
    if bad:
        return "no output for %s" % ", ".join(bad)
    directory = os.path.join(g.work, "facts")
    _copy_facts(found, labels, directory, 0)
    libc = os.path.join(g.work, "libc.symbols")
    shutil.copyfile(found[LIBC_TARGET], libc)
    android = _android_facts(g, directory, len(labels), flags)
    if isinstance(android, str):
        return android
    metadata = {"facts_targets": len(labels), "executed_actions": executed, "cached_actions": cached}
    if android is None:
        return FactsBuild(directory, libc, metadata)
    metadata["android_facts_targets"] = android["targets"]
    metadata["executed_actions"] += android["executed"]
    metadata["cached_actions"] += android["cached"]
    return FactsBuild(directory, libc, metadata, android["libc"])


def _android_facts(g, directory, start, flags):
    """The facts of every c_android_so, built in the android mode. None: the product has none; a string: why not.

    A c_android_so has no Linux build, so nothing of it reaches the release facts; without these it would escape the
    fact gates. Each `android_so` must have its `<name>_facts` (the macro makes both; this refuses anything else), and
    the shared objects are built too (their link and their ELF check), and so is the `_check` of every `c_apk` (its APK is packaged, aligned, signed and checked: T-G3), and a build failure is a reason like the release one: the fact gates are NOT_RUN, which fails the verdict."""
    code, out, err = grade_build.run_buck(g.tree, ["uquery", "kind(%s, //...)" % ANDROID_FACTS_KIND])
    if code != 0:
        return "android query failed: %s" % err.strip()[-500:]
    labels = sorted(line.strip() for line in out.splitlines() if line.strip())
    code, out, err = grade_build.run_buck(g.tree, ["uquery", "kind(%s, //...)" % ANDROID_SO_KIND])
    if code != 0:
        return "android query failed: %s" % err.strip()[-500:]
    shared = sorted(line.strip() for line in out.splitlines() if line.strip())
    code, out, err = grade_build.run_buck(g.tree, ["uquery", "kind('^%s$', //...)" % ANDROID_APK_CHECK_KIND])
    if code != 0:
        return "android query failed: %s" % err.strip()[-500:]
    apk_checks = sorted(line.strip() for line in out.splitlines() if line.strip())
    missing = [label for label in shared if label + "_facts" not in labels]
    if missing:
        return "c_android_so without facts: %s" % ", ".join(missing)
    if not labels:
        return None
    report = os.path.join(g.work, "build-report-facts-android.json")
    code, _, err = grade_build.run_buck(g.tree, ["build", "--target-platforms", ANDROID_PLATFORM,
                                                 "--keep-going", "--build-report", report] + flags
                                        + labels + shared + apk_checks + [LIBC_ANDROID_TARGET])
    executed, cached = grade_build.action_counts(g.tree)
    results = grade_build.read_report(report)
    if code != 0 or results is None:
        return "android build failed: %s" % err.strip()[-500:]
    found, bad = _artifacts(g, labels + [LIBC_ANDROID_TARGET], results)
    if bad:
        return "no output for %s" % ", ".join(bad)
    _copy_facts(found, labels, directory, start)
    libc = os.path.join(g.work, "libc-android.symbols")
    shutil.copyfile(found[LIBC_ANDROID_TARGET], libc)
    return {"libc": libc, "targets": len(labels), "executed": executed, "cached": cached}


def _fact_gate(g, run):
    if g.status.get("assemble") != "PASS":
        return None
    built = build_facts(g)
    if isinstance(built, str):
        return None
    facts = facts_data.load_facts_dir(built.directory)
    policy = facts_policy.load_policy(grade_policy.policy_path(g))
    result = run(facts, policy, built)
    result.metadata.update(built.metadata)
    return result


def semantic_gate(g):
    return _fact_gate(g, lambda facts, policy, _built: facts_semantic.run(facts, policy))


def symbols_gate(g):
    return _fact_gate(g, lambda facts, policy, built: facts_symbols.run(
        facts, policy, facts_data.load_symbol_list(built.libc),
        libc_android=None if built.libc_android is None else facts_data.load_symbol_list(built.libc_android)))


ARCHITECTURE_FILE = "architecture.toml"
NO_ARCHITECTURE = "no-architecture"


def layering_gate(g):
    """Gate `layering` (T087): the facts against `products/<p>/architecture.toml`, next to `product.toml`.

    A product without the file has no contract: PASS with info `no-architecture` (a NOT_RUN would fail every
    product that has none), before any facts are looked at."""
    path = os.path.join(os.path.dirname(g.args.product), ARCHITECTURE_FILE)
    if not os.path.isfile(path):
        return GateResult(layering_check.GATE_ID, [finding(NO_ARCHITECTURE, severity=SEVERITY_INFO)], {})
    arch = layering.load(path)

    def judged(grading):
        return _fact_gate(grading, lambda facts, policy, _built: layering_check.run(facts, arch, policy.trusted))
    return grade_toolchain.needs_toolchain(layering_check.GATE_ID, judged)(g)
