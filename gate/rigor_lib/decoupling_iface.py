"""Frozen interfaces (gate `decoupling`, rule `interface-changed`): a shared header is extended or versioned,
never edited.

A module is frozen when the product declares it a contract or lists it under `[modules] frozen`, and, at the base
of the change, a target of another package depends on it. Its frozen headers are its public headers (those not
under `src/`) and the headers of the module they include, directly or not. For each, the top-level declarations
(`decoupling_scan.declarations`) at the base must all still be there at the head, unchanged and in the same order:
  * a base declaration that is gone or different: error `interface-changed` (`reason` `declaration`; the base line);
  * the header itself gone while the module stays: `interface-changed`, `reason` `header-removed`;
  * a new `#define`/`#undef` of a name the base declarations use, or a new `#pragma`: `interface-changed`
    (`macro-shadows`, `pragma`): it could change what the old text means;
  * any other new declaration: info `interface-extended` with the count.
A module that is gone at the head is not judged (a dependent that is left no longer builds). Nothing is
baselined: the way to change a frozen interface is a new module next to it. The comparison is textual, after
comments and blank runs are removed: a reformatted declaration is a changed one, and what a header gets from the
headers of other modules is not followed (they are judged where they are frozen).
"""

from rigor_lib import decoupling_model, decoupling_scan
from rigor_lib.findings import SEVERITY_INFO, finding

CHANGED = "interface-changed"
EXTENDED = "interface-extended"


def is_declared(config, target):
    return (target.kind in decoupling_model.LIBRARY_KINDS and not config.is_in("fake", target.label)
            and (config.is_in("contract", target.label) or config.is_in("frozen", target.label)))


def frozen_modules(model, config):
    """The declared modules of `model` that a target of another package depends on, sorted."""
    shared = {dep for target in model.targets.values() for dep in target.every_dep
              if dep in model.targets and model.targets[dep].package != target.package}
    return sorted(label for label in shared if is_declared(config, model.targets[label]))


def frozen_headers(model, label):
    """The public headers of the module and the headers of the module they reach by `#include`, sorted."""
    target = model.targets[label]
    own, seen, stack = set(target.headers), set(), list(target.public_headers)
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in decoupling_scan.includes(model.text(path)):
            resolved = model.resolve(path, name)
            if resolved in own:
                stack.append(resolved)
    return sorted(seen)


def _missing(base, head):
    """The base declarations that are not, in order, declarations of the head; and the head ones that are new."""
    texts = [text for _line, text in head]
    lost, kept, position = [], set(), 0
    for line, text in base:
        try:
            position = texts.index(text, position) + 1
            kept.add(position - 1)
        except ValueError:
            lost.append(line)
    return lost, [texts[i] for i in range(len(texts)) if i not in kept]


def _hazards(base, added):
    """(reason, name) for each added declaration that may change what the base text means."""
    names = frozenset().union(*(decoupling_scan.identifiers(text) for _line, text in base)) if base else frozenset()
    found = []
    for text in added:
        name = decoupling_scan.defined_name(text)
        if name is not None and name in names:
            found.append(("macro-shadows", name))
        elif text.startswith("# pragma"):
            found.append(("pragma", ""))
    return found


def header_findings(label, path, base_text, head_text):
    where = {"target": label, "module": label, "file": path}
    if head_text is None:
        return [finding(CHANGED, reason="header-removed", **where)]
    base = decoupling_scan.declarations(base_text)
    lost, added = _missing(base, decoupling_scan.declarations(head_text))
    found = [finding(CHANGED, reason="declaration", line=line, **where) for line in lost]
    for reason, name in sorted(set(_hazards(base, added))):
        found.append(finding(CHANGED, reason=reason, **(dict(where, name=name) if name else where)))
    if added:
        found.append(finding(EXTENDED, severity=SEVERITY_INFO, declarations=len(added), **where))
    return found


def findings(base_model, head_model, config):
    """-> (findings, the frozen modules judged)."""
    found, judged = [], []
    for label in frozen_modules(base_model, config):
        if label not in head_model.targets:
            continue
        judged.append(label)
        for path in frozen_headers(base_model, label):
            head_text = head_model.text(path) if path in head_model.paths else None
            found.extend(header_findings(label, path, base_model.text(path), head_text))
    return found, judged
