"""Gate `symbols`: what the objects define and reference, against the gate-owned policy.

A product module may reference only symbols that its declared deps define, or that its policy
entry allows; a global deny list names what no product module may touch at all (process control,
clock, environment, files, network, ...). It may not define a symbol the C library or a trusted
gate module (ctest) exports, which would interpose it. Trusted modules are the gate's own code.
"""

from rigor_lib.facts_policy import Module
from rigor_lib.findings import GateResult, finding

GATE_ID = "symbols"


def policy_coverage_findings(facts_by_label, policy):
    found = []
    for label in sorted(facts_by_label):
        if label not in policy.trusted and label not in policy.modules:
            found.append(finding("module-not-in-policy", target=label))
    for label in sorted(set(policy.modules) - set(facts_by_label)):
        found.append(finding("policy-module-without-facts", target=label))
    for label in sorted(policy.trusted - set(facts_by_label)):
        found.append(finding("trusted-module-without-facts", target=label))
    return found


def exports_of(facts):
    return frozenset().union(*(unit.defined for unit in facts.units)) if facts.units else frozenset()


def dep_exports(facts, facts_by_label, found):
    exports = set()
    for dep in facts.deps:
        if dep in facts_by_label:
            exports |= exports_of(facts_by_label[dep])
        else:
            found.append(finding("missing-dep-facts", target=facts.label, dep=dep))
    return exports


def unit_findings(facts, unit, module, policy, allowed, own, reserved):
    where = {"target": facts.label, "unit": unit.name}
    found = []
    for symbol in sorted(unit.defined & reserved):
        found.append(finding("symbol-collision", symbol=symbol, **where))
    for symbol in sorted(unit.weak):
        found.append(finding("weak-symbol", symbol=symbol, **where))
    for symbol in sorted(unit.undefined - own):
        if symbol in policy.deny and symbol not in module.deny_exempt:
            found.append(finding("denied-symbol", symbol=symbol, **where))
        elif symbol not in allowed and symbol not in module.allow and symbol not in module.deny_exempt:
            found.append(finding("undeclared-symbol", symbol=symbol, **where))
    return found


def run(facts_by_label, policy, libc):
    found = policy_coverage_findings(facts_by_label, policy)
    reserved = set(libc)
    for label in policy.trusted & set(facts_by_label):
        reserved |= exports_of(facts_by_label[label])
    units = 0
    for label in sorted(facts_by_label):
        if label in policy.trusted:
            continue
        facts = facts_by_label[label]
        module = policy.modules.get(label, Module())
        allowed = dep_exports(facts, facts_by_label, found)
        own = exports_of(facts)
        for unit in facts.units:
            units += 1
            found.extend(unit_findings(facts, unit, module, policy, allowed, own, reserved))
    return GateResult(GATE_ID, found, {"targets": len(facts_by_label), "units": units})
