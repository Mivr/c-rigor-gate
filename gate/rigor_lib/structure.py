"""`rigor structure`: recursion and size/complexity limits, decided from the facts `c_structure` produced.

    rigor structure --facts DIR --policy products/<p>/policy.toml [--out FILE]

`DIR` holds one `*.json` per module (see structure_data). The policy names the modules and their level
(`[module."//core:core"] level = "L3"`; a module without `level` is L3 and a note says so; other keys are
not ours). Findings, all errors unless noted (the limits are in structure_limits.py):

  recursion                  a cycle in the direct call graph of the product, self-recursion and mutual
                             recursion across files included; names the cycle. Every level.
  indirect-cycle-possible    an L3 module (info for L2) takes the address of one of its own functions F, and some
                             function G of the product makes a call through a value (or passes a function
                             pointer to code outside the product), and F reaches G by direct calls.
  function-length, parameter-count, nesting-depth, cyclomatic-complexity, statement-count
                             a function over the limit of its level (the strictest level of the modules that
                             contain it; one definition in a shared header is judged once)
  file-length, line-length   a file over the limit (every file the compiler read, headers included)
  split-function-body        a body whose `{` and `}` are in different files (L2/L3)
  macro-defined-function     a function whose body is written in a macro (L3; info in L2)
  included-non-header        an L2/L3 unit includes a file that is not a `.h`
  duplicate-definition       two definitions of one external function in the product
  module-not-in-policy, policy-module-without-facts, missing-dep-facts
                             facts and policy disagree, or a dependency has no facts: never a pass

Tests and fuzz targets (kind c_test, c_fuzz) must be present but are not graded.
"""

import tomllib

from rigor_lib import jsonio, structure_data, structure_graph, structure_limits
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "structure"
GATE_OWNED = ("gate//", "//third_party/", "//ctest:")   # gate-owned code: graded by the gate's own tests, not here


def load_policy(path):
    """-> (label -> level or None, trusted labels). Gate-owned, so any defect is exit 2."""
    try:
        document = tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc
    modules = document.get("module", {})
    if not isinstance(modules, dict):
        raise InternalError("policy: [module] must be a table of tables")
    levels = {}
    for label, table in modules.items():
        if not LABEL.fullmatch(label) or not isinstance(table, dict):
            raise InternalError("policy: bad module %r" % (label,))
        level = table.get("level")
        if level is not None and level not in structure_limits.LEVELS:
            raise InternalError("policy: module %s has level %r, expected L1, L2 or L3" % (label, level))
        levels[label] = level
    trusted = document.get("global", {}).get("trusted", [])
    if not isinstance(trusted, list) or not all(isinstance(t, str) for t in trusted):
        raise InternalError("policy: global.trusted must be a list of labels")
    return levels, frozenset(trusted)


class Model:
    """The graded part of the product. Functions are graph nodes: by key for libraries, by key and module for
    binaries (two programs may both define `main`); files by path, with the levels that apply."""

    def __init__(self, structures, levels):
        self.structures = structures
        self.levels = levels
        self.graded = {l: s for l, s in structures.items() if s.kind not in structure_data.EXEMPT_KINDS}
        self.nodes = {}       # node -> {"func": Func, "modules": set, "idents": set}
        self.files = {}       # path -> {"fact": FileFact, "modules": set}
        for label, structure in sorted(self.graded.items()):
            for unit in structure.units:
                for func in unit.functions:
                    entry = self.nodes.setdefault(self.node_id(func.key, label),
                                                  {"func": func, "modules": set(), "idents": set()})
                    entry["modules"].add(label)
                    entry["idents"].add((func.file, func.line))
                for fact in unit.files:
                    self.files.setdefault(fact.path, {"fact": fact, "modules": set()})["modules"].add(label)

    def node_id(self, key, label):
        return "%s@%s" % (key, label) if self.graded[label].kind == "c_binary" else key

    def resolve(self, to, label):
        """The nodes a call to `to` made from module `label` can reach: the program's own definition, else
        the library's, else (a hook the program defines for a library) any program's."""
        own = self.node_id(to, label)
        if own in self.nodes:
            return [own]
        if to in self.nodes:
            return [to]
        return sorted(n for n, e in self.nodes.items() if e["func"].key == to)

    def level_of(self, label):
        return self.levels.get(label) or structure_limits.DEFAULT_LEVEL

    def strictest(self, labels):
        return structure_limits.strictest([self.level_of(m) for m in labels])

    def graph(self):
        graph = {node: set() for node in self.nodes}
        for node, entry in self.nodes.items():
            for label in entry["modules"]:
                for to, _ in entry["func"].calls:
                    graph[node].update(self.resolve(to, label))
        return graph


def where(func):
    return "%s:%d" % (func.file, func.line)


def consistency_findings(structures, levels, trusted):
    found = []
    for label in sorted(structures):
        if label not in levels:
            found.append(finding("module-not-in-policy", module=label))
        for dep in structures[label].deps:
            if dep not in structures and dep not in trusted and not dep.startswith(GATE_OWNED):
                found.append(finding("missing-dep-facts", module=label, dep=dep))
    for label in sorted(levels):
        if label not in structures and label not in trusted:
            found.append(finding("policy-module-without-facts", module=label))
    return found


def recursion_findings(model):
    graph = model.graph()
    found = []
    for members in structure_graph.cycles(graph):
        path = structure_graph.cycle_path(graph, members)
        first = model.nodes[members[0]]
        found.append(finding(
            "recursion", module=sorted(first["modules"])[0], function=first["func"].name,
            file=first["func"].file, line=first["func"].line,
            cycle=[model.nodes[k]["func"].name + " (" + where(model.nodes[k]["func"]) + ")" for k in path]))
    return found


def duplicate_findings(model):
    found = []
    for node, entry in sorted(model.nodes.items()):
        if len(entry["idents"]) > 1:
            found.append(finding("duplicate-definition", function=entry["func"].name,
                                 locations=["%s:%d" % ident for ident in sorted(entry["idents"])]))
    return found


def over(rule, value, limit, **fields):
    return [finding(rule, value=value, limit=limit, **fields)] if value > limit else []


def function_findings(model):
    found = []
    for _, entry in sorted(model.nodes.items()):
        func, modules = entry["func"], sorted(entry["modules"])
        level = model.strictest(modules)
        limits = structure_limits.LIMITS[level]
        if limits is None:
            continue
        who = dict(module=modules[0], function=func.name, file=func.file, line=func.line, level=level)
        if func.split:
            found.append(finding("split-function-body", **who))
        else:
            found += over("function-length", func.body_lines, limits.function_lines, **who)
        found += over("parameter-count", func.params, limits.params, **who)
        found += over("nesting-depth", func.nesting, limits.nesting, **who)
        found += over("cyclomatic-complexity", func.cyclomatic, limits.cyclomatic, **who)
        found += over("statement-count", func.statements, limits.statements, **who)
        if func.macro:
            found.append(finding("macro-defined-function", severity="error" if level == "L3" else SEVERITY_INFO, **who))
    return found


def file_findings(model):
    found = []
    for path, entry in sorted(model.files.items()):
        modules = sorted(entry["modules"])
        level = model.strictest(modules)
        limits = structure_limits.LIMITS[level]
        if limits is None:
            continue
        who = dict(module=modules[0], file=path, level=level)
        found += over("file-length", entry["fact"].lines, limits.file_lines, **who)
        found += over("line-length", entry["fact"].longest_line, limits.line_length, **who)
    return found


def include_findings(model):
    found = []
    for label, structure in sorted(model.graded.items()):
        if model.level_of(label) == "L1":
            continue
        for unit in structure.units:
            for fact in unit.files:
                if fact.path != unit.src and not fact.path.endswith(".h"):
                    found.append(finding("included-non-header", module=label, source=unit.src, file=fact.path))
    return found


def call_sites(model):
    """node -> list of (file, line, kind) of the calls it makes through a value, or passes a function
    pointer to code the product does not define (that code may call it back)."""
    sites = {}
    for node, entry in model.nodes.items():
        func = entry["func"]
        here = [(f, n, "pointer") for f, n in func.indirect]
        for to, fp in func.calls:
            if fp and not any(model.resolve(to, label) for label in entry["modules"]):
                here.append((func.file, func.line, "callback:" + to))
        if here:
            sites[node] = sorted(set(here))
    return sites


def address_taken(model):
    """(module, node) for every module that takes the address of a function it defines itself."""
    taken = set()
    for label, structure in model.graded.items():
        for unit in structure.units:
            refs = list(unit.refs) + [r for f in unit.functions for r in f.refs]
            own = {model.node_id(f.key, label) for u in structure.units for f in u.functions}
            taken.update((label, model.node_id(to, label)) for to, _, _ in refs
                         if model.node_id(to, label) in own)
    return sorted(taken)


def indirect_findings(model):
    graph = model.graph()
    sites = call_sites(model)
    found = []
    for module, node in address_taken(model):
        level = model.level_of(module)
        if level == "L1":
            continue
        reachable = structure_graph.reaches(graph, node)
        target = model.nodes[node]["func"]
        for caller in sorted(set(sites) & reachable):
            origin = model.nodes[caller]["func"]
            found.append(finding(
                "indirect-cycle-possible", module=module, function=target.name, file=target.file,
                line=target.line, caller=origin.name, caller_file=origin.file,
                sites=["%s:%d %s" % s for s in sites[caller]],
                severity="error" if level == "L3" else SEVERITY_INFO))
    return found


def metadata(model, notes):
    graph = model.graph()
    return {
        "notes": notes,
        "modules": {label: {"level": model.level_of(label), "functions": sum(1 for e in model.nodes.values()
                                                                          if label in e["modules"])}
                    for label in sorted(model.graded)},
        "functions": len(model.nodes),
        "calls": sum(len(v) for v in graph.values()),
        "indirect_sites": {k: ["%s:%d %s" % s for s in v] for k, v in sorted(call_sites(model).items())},
        "address_taken": ["%s %s" % t for t in address_taken(model)],
    }


def decide(structures, levels, trusted):
    notes = ["module %s has no level in the policy: treated as %s" % (label, structure_limits.DEFAULT_LEVEL)
             for label in sorted(structures) if label in levels and levels[label] is None
             and structures[label].kind not in structure_data.EXEMPT_KINDS]
    model = Model(structures, levels)
    findings = consistency_findings(structures, levels, trusted)
    for part in (recursion_findings, duplicate_findings, function_findings, file_findings, include_findings,
                 indirect_findings):
        findings += part(model)
    return GateResult(GATE_ID, findings, metadata(model, notes))


def run(args):
    levels, trusted = load_policy(args.policy)
    structures = structure_data.load_structure_dir(args.facts)
    result = decide(structures, levels, trusted)
    for note in result.metadata["notes"]:
        print("note: " + note)
    return result


def add_parser(subparsers):
    parser = subparsers.add_parser("structure", allow_abbrev=False,
                                   help="recursion and size/complexity limits from the clang AST facts")
    parser.add_argument("--facts", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
