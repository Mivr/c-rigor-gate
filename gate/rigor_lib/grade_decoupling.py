"""Gate `decoupling` of `rigor grade`: the decoupling rules of a product, under its baseline ratchet.

A product adopts the rules with `products/<p>/decoupling.toml` (`decoupling_config`); without it the gate is PASS
with the info `not-applicable`, before anything is read. With it:
  * the head is modelled from the assembled tree (`decoupling_model`: the BUCK files and the `#include` lines) and
    the facts both fact gates already built say whose symbols each target's objects reference;
  * `decoupling_rules` lists every violation and `decoupling_baseline` judges them against
    `products/<p>/decoupling-baseline.toml` (absent: nothing is tolerated): a violation the list does not name is an
    error, and so is an entry that is no longer a violation (`stale-baseline`);
  * `decoupling_iface` compares the frozen headers of the merge base with the head (`interface-changed`).
The info `decoupling-inputs` carries the sha256 of both product files, so the verdict commits to them.
NOT_RUN unless `assemble` and `buckfiles` passed and the facts built. docs/decoupling.md.
"""

import os

from rigor_lib import decoupling_baseline, decoupling_config, decoupling_iface, decoupling_model, decoupling_rules
from rigor_lib import facts_data, gitrun, grade_checks, grade_steps, grade_toolchain, grade_tree, jsonio, layering
from rigor_lib import paths, product_layout
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = "decoupling"
INPUTS = "decoupling-inputs"
_PLAIN_FILE_MODES = ("100644", "100755")


def _product_file(g, name):
    return os.path.join(os.path.dirname(g.args.product), name)


def load_config(g):
    """The product's Config, or None when it has no `decoupling.toml`."""
    path = _product_file(g, decoupling_config.FILE_NAME)
    if not os.path.isfile(path):
        return None
    arch_path = _product_file(g, grade_checks.ARCHITECTURE_FILE)
    return decoupling_config.load(path, layering.load(arch_path) if os.path.isfile(arch_path) else None)


def load_baseline_file(directory):
    """The baseline of the product files in `directory`; without the file nothing is tolerated."""
    path = os.path.join(directory, decoupling_baseline.FILE_NAME)
    return decoupling_baseline.load(path) if os.path.isfile(path) else decoupling_baseline.parse("")


def _sha256(g, name):
    path = _product_file(g, name)
    return jsonio.sha256_hex(jsonio.read_bytes(path)) if os.path.isfile(path) else None


def head_model(g):
    def read(path):
        return jsonio.read_bytes(os.path.join(g.tree, path))
    return decoupling_model.load(g.product_paths, read)


def commit_model(repo, commit, product):
    """The model of the files of `commit` that the product's layout copies, read from the blobs."""
    entries = {}
    for entry in grade_tree.list_tree(repo, commit):
        try:
            text = entry.path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if (paths.unsafe_path_reason(text) is None and entry.mode in _PLAIN_FILE_MODES
                and product_layout.classify(product, text) == product_layout.COPY):
            entries[text] = entry
    return decoupling_model.load(entries, lambda path: grade_tree.read_blob(repo, entries[path]))


def _interfaces(g, config, head):
    """The frozen-interface findings; the base is read only when the product declares something to freeze."""
    if not (config.contract or config.frozen):
        return [], []
    base = commit_model(g.src, gitrun.merge_base(g.src, g.base, g.head), g.product)
    return decoupling_iface.findings(base, head, config)


def _fan_out_summary(model):
    counts = decoupling_rules.fan_out(model)
    return {"modules": len(counts), "tests_relinked_max": max((c[1] for c in counts.values()), default=0),
            "tests_relinked_sum": sum(c[1] for c in counts.values()), "per_module": counts}


def judge(g, config, facts):
    head = head_model(g)
    violations, levels = decoupling_rules.violations(head, config, decoupling_rules.uses_from_facts(head, facts))
    found, counts = decoupling_baseline.judge(violations, load_baseline_file(os.path.dirname(g.args.product)))
    interface_found, frozen = _interfaces(g, config, head)
    found.extend(interface_found)
    found.append(finding(INPUTS, severity=SEVERITY_INFO, config_sha256=_sha256(g, decoupling_config.FILE_NAME),
                         baseline_sha256=_sha256(g, decoupling_baseline.FILE_NAME)))
    return GateResult(GATE_ID, found, {"rules": counts, "tests": levels, "frozen": frozen,
                                       "targets": len(head.targets), "fan_out": _fan_out_summary(head)})


def decoupling_gate(g):
    if not os.path.isfile(_product_file(g, decoupling_config.FILE_NAME)):
        return GateResult(GATE_ID, [finding(grade_steps.NOT_APPLICABLE, severity=SEVERITY_INFO)], {})
    config = load_config(g)

    def judged(grading):
        if any(grading.status.get(gate) != "PASS" for gate in ("assemble", "buckfiles")):
            return None
        built = grade_checks.build_facts(grading)
        if isinstance(built, str):
            return None
        result = judge(grading, config, facts_data.load_facts_dir(built.directory))
        result.metadata.update(built.metadata)
        return result
    return grade_toolchain.needs_toolchain(GATE_ID, judged)(g)


def apart_tests(g, tests):
    """The `tests` that are integration or simulation tests by the product's declarations: never a module's own
    tests, whatever their package holds (`grade_mutants.own_tests`)."""
    config = load_config(g)
    if config is None:
        return frozenset()
    return frozenset(t for t in tests if config.is_in("integration", t) or config.is_in("simulation", t))
