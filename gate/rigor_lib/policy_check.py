"""`rigor policy-check`: a policy may add profiles and levels to what the facts force, never drop below it (P003 10.1).

    rigor policy-check --policy P.toml --facts DIR --structure DIR [--architecture A.toml]
                       [--require-profiles] [--emit-profiles] [--out F]

The policy key is `[module."//pkg:name"] profile = ["pure", "parser"]` (a single string is accepted). Findings:
`profile-unknown` (error), `profile-missing` (info; error with `--require-profiles`), `profile-below-floor` (error:
module, the missing profile, the floor rule, the symbol or function that triggered it), `level-below-floor` (error:
module, level, floor, the dependent that sets it), `structure-missing` (error: a judged module with compiled units
and no structure facts; F-parser cannot be decided), `facts-missing` (error: a policy module with a `level` and no
facts) and the info `profile-floor` per module. Any defect in an input is
exit 2. `--emit-profiles` prints the floor of every policy module as a `[module]` table with a `profile` line, sorted,
for pasting into a policy; the summary then goes to stderr. Floors are computed in `profiles`; see docs/profiles.md.
"""

import sys

from rigor_lib import facts_data, facts_third_party, grade_policy, jsonio, layering, profiles, structure_data
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS

GATE_ID = "policy-check"
PRODUCT_KINDS = ("c_library", "c_binary")


def declared_profiles(label, table):
    """The tuple of profile names of a module table, None when the key is absent or empty. A wrong shape is exit 2."""
    if "profile" not in table:
        return None
    value = table["profile"]
    names = [value] if isinstance(value, str) else value
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise InternalError("policy: module %s: profile must be a name or a list of names" % label)
    if len(set(names)) != len(names):
        raise InternalError("policy: module %s: profile has duplicates" % label)
    return tuple(names) or None


def _module_tables(document):
    tables = document.get("module", {})
    if not isinstance(tables, dict) or not all(isinstance(t, dict) for t in tables.values()):
        raise InternalError("policy: [module] must be a table of tables")
    for label in tables:
        if not facts_data.LABEL.fullmatch(label):
            raise InternalError("policy: bad module label %r" % label)
    return tables


def _level_of(label, table):
    level = table.get("level")
    if level is not None and level not in profiles.LEVELS:
        raise InternalError("policy: module %s: level must be one of %s" % (label, ", ".join(profiles.LEVELS)))
    return level


def _layer_of(arch, label):
    found = [name for name in arch.order if any(layering.matches(p, label) for p in arch.layers[name])]
    if len(found) > 1:
        raise InternalError("architecture: %s is listed by two layers: %s" % (label, found))
    return found[0] if found else None


def edge_kind(arch, source, target):
    """The kind a dependency edge counts as for the level floor: `pure` when an edge that allows it is `pure` or
    `composition`, `data` when every allowing edge is `data` or `port`, None (counts) when none allows it or there is
    no architecture."""
    if arch is None:
        return None
    src, dst = (source, _layer_of(arch, source)), (target, _layer_of(arch, target))
    kinds = set()
    for edge in arch.edges:
        ok_src = edge.source == src[1] if edge.source in arch.layers else edge.source == src[0]
        ok_dst = edge.target == dst[1] if edge.target in arch.layers else edge.target == dst[0]
        if ok_src and ok_dst:
            kinds.add(edge.kind)
    if not kinds:
        return None
    return "pure" if kinds & {"pure", "composition"} else "data"


def dependency_graph(facts_by_label, labels, arch):
    """{dependent: {dependency: kind}} over the product modules in `labels`; tests and fuzzers depend on anything."""
    graph = {}
    for label in sorted(labels):
        facts = facts_by_label.get(label)
        if facts is None or facts.kind in profiles.TEST_KINDS:
            continue
        graph[label] = {dep: edge_kind(arch, label, dep) for dep in facts.deps if dep in labels}
    return graph


def _floor_findings(label, table, declared, reasons, floor, require):
    found = [finding("profile-floor", severity=SEVERITY_INFO, module=label, floor=sorted(floor),
                     declared=sorted(declared or ()))]
    if declared is None:
        found.append(finding("profile-missing", severity=SEVERITY_ERROR if require else SEVERITY_INFO, module=label))
        return found
    for name in declared:
        if name not in profiles.PROFILES:
            found.append(finding("profile-unknown", module=label, profile=name))
    if any(name not in profiles.PROFILES for name in declared):
        return found
    for profile in profiles.FLOORED:
        if profile in declared:
            continue
        for rule, detail in reasons.get(profile, []):
            key = "function" if rule == profiles.RULE_PARSER else "symbol"
            found.append(finding("profile-below-floor", module=label, profile=profile, floor_rule=rule, **{key: detail}))
    return found


def _level_findings(levels, graph):
    found = []
    for label, (floor, who) in sorted(profiles.level_floor_detail(graph, levels).items()):
        if profiles.LEVELS.index(levels[label]) < profiles.LEVELS.index(floor):
            found.append(finding("level-below-floor", module=label, level=levels[label], floor=floor, dependent=who))
    return found


def decide(document, facts_by_label, structures=None, arch=None, require=False, third=None):
    """(GateResult, {label: floor}) for the parsed policy `document`."""
    tables = _module_tables(document)
    prefixes = tuple(third.prefixes) if third else ()
    third_labels = frozenset(third.trusted) if third else frozenset()
    structures = {} if structures is None else structures
    judged = [label for label in sorted(tables) if label in facts_by_label
              and facts_by_label[label].kind in PRODUCT_KINDS]
    found, floors, levels = [], {}, {}
    for label in sorted(tables):
        if "level" in tables[label] and label not in facts_by_label:
            found.append(finding("facts-missing", module=label))
    for label in judged:
        table = tables[label]
        if facts_by_label[label].units and label not in structures:
            found.append(finding("structure-missing", module=label))
        reasons = profiles.floor_reasons(facts_by_label[label], structures.get(label), prefixes,
                                         third_labels)
        floors[label] = set(reasons) or {"pure"}
        found.extend(_floor_findings(label, table, declared_profiles(label, table), reasons, floors[label], require))
        if _level_of(label, table) is not None:
            levels[label] = table["level"]
    graph = dependency_graph(facts_by_label, set(levels), arch)
    found.extend(_level_findings(levels, graph))
    return GateResult(GATE_ID, found, {"modules": len(judged), "levels": len(levels)}), floors


def emit_lines(floors):
    """The pasteable text: a `[module]` table with a `profile` line per module, sorted by label."""
    lines = []
    for label in sorted(floors):
        lines.append('[module."%s"]' % label)
        lines.append("profile = [%s]" % ", ".join('"%s"' % name for name in sorted(floors[label])))
    return lines


def _load_optional(args):
    structures = structure_data.load_structure_dir(args.structure)
    arch = layering.load(args.architecture) if args.architecture else None
    return structures, arch


def summary(result, stream):
    print("%s: %s (%d findings)" % (result.gate, result.status, len(result.findings)), file=stream)
    for item in result.sorted_findings():
        print("  " + jsonio.canonical_dumps(item).decode("ascii").rstrip("\n"), file=stream)


def handle(args):
    document = grade_policy.load_document(args.policy)
    facts_by_label = facts_data.load_facts_dir(args.facts)
    structures, arch = _load_optional(args)
    result, floors = decide(document, facts_by_label, structures, arch, args.require_profiles,
                            facts_third_party.load())
    if args.out:
        jsonio.write_atomic(args.out, result.to_json_bytes())
    if args.emit_profiles:
        sys.stdout.write("".join(line + "\n" for line in emit_lines(floors)))
        summary(result, sys.stderr)
    else:
        summary(result, sys.stdout)
    return EXIT_PASS if result.status == "PASS" else EXIT_FAIL


def add_parser(subparsers):
    parser = subparsers.add_parser("policy-check", allow_abbrev=False,
                                   help="profiles and levels of a policy against the floors computed from facts")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--structure", required=True)
    parser.add_argument("--architecture")
    parser.add_argument("--require-profiles", action="store_true")
    parser.add_argument("--emit-profiles", action="store_true")
    parser.add_argument("--out")
    parser.set_defaults(handler=handle, gate_id=GATE_ID)
