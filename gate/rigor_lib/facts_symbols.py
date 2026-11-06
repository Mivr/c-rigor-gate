"""Gate `symbols`: what the objects define and reference, against the gate-owned policy.

A product module may reference only symbols that its declared deps define, or that its policy
entry allows; a global deny list names what no product module may touch at all (process control,
clock, environment, files, network, ...). It may not define a symbol the C library or a trusted
gate module (ctest) exports, which would interpose it. Trusted modules are the gate's own code.

Gate-owned third-party libraries (`facts_third_party`) are trusted the same way, with two additions:
a module may depend on one only if its policy entry lists the label (`third_party = [...]`), and the
exports of the library, computed by the build from its objects, are reserved together with the
reserved prefixes (`mbedtls_`, `psa_`, `srv_`, `tls_peer_`), so no product can define a name the library owns.
A library that only tests may use (`ALLOWED_TEST_LABELS`) must not be reached by anything but a `c_test`.
"""

from rigor_lib import facts_third_party
from rigor_lib.facts_policy import Module
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, GateResult, finding

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


def dep_exports(facts, facts_by_label, libs, module, found):
    exports = set()
    for dep in facts.deps:
        if dep in libs:
            if facts_third_party.canonical(dep) in module.third_party:
                exports |= exports_of(libs[dep])
            else:
                found.append(finding("third-party-not-permitted", target=facts.label, dep=dep))
        elif dep in facts_by_label:
            exports |= exports_of(facts_by_label[dep])
        else:
            found.append(finding("missing-dep-facts", target=facts.label, dep=dep))
    return exports


def unit_findings(facts, unit, module, policy, allowed, own, reserved, prefixes):
    where = {"target": facts.label, "unit": unit.name}
    found = []
    for symbol in sorted(s for s in unit.defined if s in reserved or s.startswith(prefixes)):
        found.append(finding("symbol-collision", symbol=symbol, **where))
    for symbol in sorted(unit.weak):
        found.append(finding("weak-symbol", symbol=symbol, **where))
    for symbol in sorted(unit.undefined - own):
        if symbol in policy.deny and symbol not in module.deny_exempt:
            found.append(finding("denied-symbol", symbol=symbol, **where))
        elif symbol not in allowed and symbol not in module.allow and symbol not in module.deny_exempt:
            found.append(finding("undeclared-symbol", symbol=symbol, **where))
    return found


def export_findings(facts, module):
    """The exports policy (T033, R003 G7): what a module defines against its gate-owned `exports` list.

    L1 is exempt. A module whose table has neither `level` nor `exports` is not checked (a legacy table).
    Any `exports` key, or a declared level above L1, arms it; with no level declared the level is L3.
    """
    level = module.level or "L3"
    if level == "L1" or (module.level is None and module.exports is None):
        return []
    strict = level != "L2"
    severity = SEVERITY_ERROR if strict else SEVERITY_INFO
    if module.exports is None:
        # Fail closed at L3: no list means nothing can be compared, which is never a pass.
        return [finding("exports-missing", severity=severity, target=facts.label)]
    found = []
    for unit in facts.units:
        where = {"target": facts.label, "unit": unit.name}
        for symbol in sorted(unit.defined - module.exports):
            found.append(finding("unexpected-export", symbol=symbol, **where))
        for symbol in sorted(unit.mutable):
            found.append(finding("mutable-global-export", severity=severity, symbol=symbol, **where))
    return found


def run(facts_by_label, policy, libc, third=None):
    third = facts_third_party.load() if third is None else third
    facts_third_party.check_policy(policy, third)
    products, libs, found = facts_third_party.split(facts_by_label, third)
    found.extend(policy_coverage_findings(products, policy))
    found.extend(facts_third_party.test_only_findings(products, third))
    reserved = set(libc)
    for label in policy.trusted & set(products):
        reserved |= exports_of(products[label])
    for lib in libs.values():
        reserved |= exports_of(lib)
    prefixes = tuple(third.prefixes)
    units = 0
    for label in sorted(products):
        if label in policy.trusted:
            continue
        facts = products[label]
        module = policy.modules.get(label, Module())
        allowed = dep_exports(facts, products, libs, module, found)
        own = exports_of(facts)
        for unit in facts.units:
            units += 1
            found.extend(unit_findings(facts, unit, module, policy, allowed, own, reserved, prefixes))
        found.extend(export_findings(facts, module))
    return GateResult(GATE_ID, found, {"targets": len(products), "libraries": len(libs), "units": units})
