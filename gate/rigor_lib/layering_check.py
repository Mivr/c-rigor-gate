"""Gate `layering`: the facts of every module against the architecture contract (`layering.py`).

Reads, per module, its direct `deps` and the `undefined` symbols of its units, and each dep's exports.
Test-only targets (`c_test`, and the contract's `[testkit]`) are exempt as sources of edges; a production
module that depends on one is an `undeclared-edge`. Gate-owned trusted modules (`policy` `trusted`) and
third-party libraries are outside the contract (the `symbols` gate judges them).

Findings, all errors: `ungoverned-module`, `undeclared-edge`, `upward-edge`, `edge-kind-violation`,
`contract-stale`. An ungoverned module gets only `ungoverned-module` (its edges cannot be judged).
The facts do not say which defined symbols are functions, so `data` and `port` edges are judged on every
symbol the target defines: a reference outside the edge's `symbols` list is a violation (fail closed).
"""

from rigor_lib import facts_third_party, layering
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.facts_symbols import exports_of

GATE_ID = "layering"
TEST_KIND = "c_test"
TESTKIT = "testkit"


def _layer_of(arch, label):
    """The one layer whose modules list `label`, or None. Two layers is a contract defect (exit 2)."""
    found = [name for name in arch.order if any(layering.matches(p, label) for p in arch.layers[name])]
    if len(found) > 1:
        raise InternalError("architecture: %s is listed by two layers: %s" % (label, found))
    return found[0] if found else None


def _any(patterns, label):
    return any(layering.matches(p, label) for p in patterns)


def stale_findings(arch, labels):
    patterns = [("layer " + name, p) for name in arch.order for p in arch.layers[name]]
    patterns += [(TESTKIT, p) for p in arch.testkit] + [("composition", p) for p in arch.composition]
    patterns += [("edge", e) for edge in arch.edges for e in (edge.source, edge.target) if "//" in e]
    return [finding("contract-stale", entry=pattern, where=where)
            for where, pattern in sorted(set(patterns)) if not any(layering.matches(pattern, l) for l in labels)]


def _endpoint_matches(arch, endpoint, label, layer):
    return (endpoint == layer) if endpoint in arch.layers else (endpoint == label)


def _allowing(arch, source, target):
    """The edges that allow source -> target; each is (label, layer) for both ends."""
    return [e for e in arch.edges
            if _endpoint_matches(arch, e.source, source[0], source[1])
            and _endpoint_matches(arch, e.target, target[0], target[1])]


def _references(facts, unit, exports):
    return sorted((unit.undefined - exports_of(facts)) & exports)


def _kind_findings(arch, facts, dep_facts, edges, composition_ok):
    """Violations of the most permissive allowing edge; none if any edge is fully satisfied."""
    problems = []
    for edge in sorted(edges, key=lambda e: e.kind):
        if edge.kind == "composition" and not composition_ok:
            problems.append([finding("edge-kind-violation", target=facts.label, dep=dep_facts.label,
                                     kind=edge.kind, reason="composition-not-permitted")])
            continue
        if edge.kind in ("pure", "composition"):
            return []
        exports = exports_of(dep_facts)
        problems.append([finding("edge-kind-violation", target=facts.label, dep=dep_facts.label,
                                 kind=edge.kind, unit=unit.name, symbol=symbol)
                         for unit in facts.units for symbol in _references(facts, unit, exports)
                         if symbol not in edge.symbols])
        if not problems[-1]:
            return []
    return min(problems, key=len)


def edge_findings(arch, facts, dep_facts, layers):
    source = (facts.label, layers[facts.label])
    target = (dep_facts.label, layers[dep_facts.label])
    where = {"target": facts.label, "dep": dep_facts.label, "from_layer": source[1], "to_layer": target[1]}
    found = []
    if arch.rank(target[1]) > arch.rank(source[1]):
        found.append(finding("upward-edge", **where))
    edges = _allowing(arch, source, target)
    if not edges:
        return found + [finding("undeclared-edge", **where)]
    return found + _kind_findings(arch, facts, dep_facts, edges, _any(arch.composition, facts.label))


def _is_test_only(arch, facts):
    return facts.kind == TEST_KIND or _any(arch.testkit, facts.label)


def run(facts_by_label, arch, trusted=frozenset(), third=None):
    third = facts_third_party.load() if third is None else third
    products, _libs, _ = facts_third_party.split(facts_by_label, third)
    modules = {l: f for l, f in products.items() if l not in trusted}
    found = stale_findings(arch, sorted(modules))
    layers, edges = {}, 0
    for label in sorted(modules):
        if _is_test_only(arch, modules[label]):
            continue
        layer = _layer_of(arch, label)
        if layer is None:
            found.append(finding("ungoverned-module", target=label))
        else:
            layers[label] = layer
    for label in sorted(layers):
        for dep in modules[label].deps:
            if dep not in modules:
                continue
            edges += 1
            if dep in layers:
                found.extend(edge_findings(arch, modules[label], modules[dep], layers))
            elif _is_test_only(arch, modules[dep]):
                found.append(finding("undeclared-edge", target=label, dep=dep, from_layer=layers[label],
                                     to_layer=TESTKIT))
    return GateResult(GATE_ID, found, {"modules": len(layers), "edges": edges})
