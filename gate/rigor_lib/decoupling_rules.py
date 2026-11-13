"""The rules of gate `decoupling` that the baseline ratchets: every violation of a tree, by rule and stable key.

`violations(model, config, uses)` -> {rule: {key: fields}}; `key` is what the baseline file lists and `fields` what
the finding carries. `uses` is `Uses`: per target, the dependencies whose symbols its objects reference, and what
the contract rule needs from the objects. In a grade it comes from the facts (`uses_from_facts`); the baseline tool
without facts approximates it from the text and the policy's `exports` (`uses_from_text`). docs/decoupling.md.
"""

from dataclasses import dataclass, field

from rigor_lib import decoupling_model, decoupling_scan
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import WRITABLE
from rigor_lib.facts_symbols import exports_of

UNUSED_DEP = "unused-dep"
MISSING_EXPORT = "missing-export"
NEEDLESS_EXPORT = "needless-export"
TEST_LINKS = "unit-test-links-component"
UNLEVELED = "unleveled-test"
LIBRARY_IN_TESTS = "library-in-test-package"
BEHAVIOUR = "contract-has-behaviour"
RULES = (UNUSED_DEP, MISSING_EXPORT, NEEDLESS_EXPORT, TEST_LINKS, UNLEVELED, LIBRARY_IN_TESTS, BEHAVIOUR)
LEVELS = ("unit", "integration", "simulation", "unleveled")
TEST_KIND = "c_test"


@dataclass(frozen=True)
class Uses:
    symbols: dict                               # target -> the deps whose exported symbols its objects reference
    outside: dict = field(default_factory=dict)  # target -> the undefined symbols none of its deps defines
    state: frozenset = frozenset()               # the targets that define writable static data
    exact: bool = True                           # False: approximated from the text


def uses_from_facts(model, facts_by_label):
    """From the built facts: a target uses a dep when an undefined symbol of its objects is one the dep defines."""
    symbols, outside, state = {}, {}, set()
    for label, target in model.targets.items():
        facts = facts_by_label.get(label)
        if facts is None:
            if target.kind in decoupling_model.JUDGED_KINDS and target.srcs:
                raise InternalError("decoupling: no facts for %s" % label)
            continue
        own = exports_of(facts)
        wanted = frozenset().union(*(unit.undefined for unit in facts.units)) - own if facts.units else frozenset()
        exports = {dep: exports_of(facts_by_label[dep]) for dep in target.every_dep if dep in facts_by_label}
        symbols[label] = frozenset(dep for dep, names in exports.items() if wanted & names)
        outside[label] = wanted - frozenset().union(*exports.values()) if exports else wanted
        if any(section in WRITABLE for unit in facts.units for _name, _size, section, _local in unit.data):
            state.add(label)
    return Uses(symbols, outside, frozenset(state))


def uses_from_text(model, exports_by_label):
    """Without a build: a target uses a dep when its own files name a symbol the policy lists in the dep's
    `exports`. A name behind a macro of another module is missed and a name in dead code counts."""
    symbols = {}
    for label, target in model.targets.items():
        names = frozenset().union(*(decoupling_scan.identifiers(model.text(path)) for path in target.srcs + target.headers))
        symbols[label] = frozenset(dep for dep in target.every_dep if names & exports_by_label.get(dep, frozenset()))
    return Uses(symbols, exact=False)


def _key(subject, detail=None, separator=" -> "):
    return subject if detail is None else subject + separator + detail


def dependency_violations(model, uses, found):
    """G1: declared equals used, and exported equals what the public headers include."""
    for label in sorted(model.targets):
        target = model.targets[label]
        if target.kind not in decoupling_model.JUDGED_KINDS:
            continue
        included = model.included(target.srcs + target.headers) - {label}
        public = model.included(target.public_headers) - {label}
        used = included | uses.symbols.get(label, frozenset())
        for name, deps in (("deps", target.deps), ("exported_deps", target.exported_deps)):
            for dep in deps:
                if dep in model.targets and dep not in used:
                    found[UNUSED_DEP][_key(label, dep)] = {"target": label, "dep": dep, "list": name}
        if target.kind != "c_library":
            continue
        for dep in sorted(public - set(target.exported_deps)):
            found[MISSING_EXPORT][_key(label, dep)] = {"target": label, "dep": dep}
        for dep in target.exported_deps:
            if dep in model.targets and dep in used and dep not in public:
                found[NEEDLESS_EXPORT][_key(label, dep)] = {"target": label, "dep": dep}


def _is_module(config, target):
    """A module: a library that is not a fake or test kit, or a binary."""
    if target.kind == "c_binary":
        return True
    return target.kind in decoupling_model.LIBRARY_KINDS and not config.is_in("fake", target.label)


def _package_modules(model, config):
    modules = {}
    for label, target in model.targets.items():
        if _is_module(config, target):
            modules.setdefault(target.package, []).append(label)
    return modules


def test_level(config, label, modules_here):
    """The level of one `c_test`: its package decides (simulation, integration, a module's own unit test)."""
    for level in ("simulation", "integration"):
        if config.is_in(level, label):
            return level
    return "unit" if modules_here else "unleveled"


def _restricted(config, label):
    return config.is_in("component", label) or config.is_in("composition", label)


def _foreign_components(model, config, test, own):
    """The component and composition modules a unit test links besides the modules of its own package (and, when
    one of those is a composition module, besides what that module itself links: binding is its job)."""
    bound = set()
    for label in own:
        if config.is_in("composition", label):
            bound |= model.closure(label)
    return sorted(dep for dep in model.closure(test) - set(own) - bound
                  if dep in model.targets and _is_module(config, model.targets[dep]) and _restricted(config, dep))


def test_violations(model, config, found):
    """G2 and G3: what a unit test links, tests without a level, and libraries in test packages.
    Returns the number of tests per level."""
    modules = _package_modules(model, config)
    counts = dict.fromkeys(LEVELS, 0)
    for label in sorted(model.targets):
        target = model.targets[label]
        apart = config.is_in("integration", label) or config.is_in("simulation", label)
        if target.kind in decoupling_model.LIBRARY_KINDS and apart and _is_module(config, target):
            found[LIBRARY_IN_TESTS][label] = {"target": label}
        if target.kind != TEST_KIND:
            continue
        own = modules.get(target.package, [])
        level = test_level(config, label, own)
        counts[level] += 1
        if level == "unleveled":
            found[UNLEVELED][label] = {"target": label}
        elif level == "unit":
            for module in _foreign_components(model, config, label, own):
                found[TEST_LINKS][_key(label, module)] = {"target": label, "module": module}
    return counts


def contract_violations(model, config, uses, found):
    """G5: a contract depends only on contracts and on what `[contract] may_use` lists, its objects reference
    nothing outside those but the `allow` symbols, and it holds no writable static data."""
    for label in sorted(model.targets):
        target = model.targets[label]
        if not config.is_in("contract", label) or not _is_module(config, target) or target.kind == "c_binary":
            continue
        where = {"target": label, "module": label}
        for dep in target.every_dep:
            if not (config.is_in("contract", dep) or config.is_in("may_use", dep)):
                found[BEHAVIOUR][_key(label, dep)] = dict(where, reason="dep", dep=dep)
        for symbol in sorted(uses.outside.get(label, frozenset()) - config.allow):
            found[BEHAVIOUR][_key(label, symbol, " : ")] = dict(where, reason="symbol", symbol=symbol)
        if label in uses.state:
            found[BEHAVIOUR][_key(label, "static-data", " : ")] = dict(where, reason="static-data")


def violations(model, config, uses):
    """-> ({rule: {key: fields}}, {level: number of tests})."""
    found = {rule: {} for rule in RULES}
    dependency_violations(model, uses, found)
    levels = test_violations(model, config, found)
    contract_violations(model, config, uses, found)
    return found, levels


def fan_out(model):
    """G6, a report: per library, [the targets that are not tests, the tests] an edit of it relinks."""
    counts = {label: [0, 0] for label, t in model.targets.items() if t.kind in decoupling_model.LIBRARY_KINDS}
    for label, target in model.targets.items():
        for dep in model.closure(label):
            if dep in counts:
                counts[dep][target.kind == TEST_KIND] += 1
    return counts
