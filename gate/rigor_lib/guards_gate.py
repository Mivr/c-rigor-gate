"""`rigor guards`: where the guards (`rigor_require`, gate//rt:require) of a product are, and how many are declared (T131).

    rigor guards --facts DIR --structure DIR --policy P.toml [--out F]

A guard is a call of `rigor_require` in a source file of a module (the `guards` list of the facts, from `cscan`).
The policy key `[module."//pkg:name"] guards = N` declares how many of the module's guards no public call can make
false (P003 6: a guard for an invariant the module's own code upholds); absent means 0. Findings:

  guard-budget-over-sites   (error)  N is larger than the number of guard call sites of the module
  guard-budget-over-cap     (error)  N is larger than the density cap: one declared guard per DENSITY_LINES lines
                                     of the module's own source files (the structure facts' line counts)
  structure-missing         (error)  a module with guards or a declaration and no structure facts: the cap cannot be decided
  guards                    (info)   per module: sites, declared, cap

Only guards in a module's own source files (`srcs`) count: a guard in a header is not code the mutation gate judges
(`unmutated-function`). Fails closed like the other judges: a malformed input is exit 2. What it does not do yet: treat
declared guards specially in mutation, or check that a guard was executed (docs/require.md).
"""

from rigor_lib import facts_data, facts_policy, facts_third_party, grade_policy, structure_data
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "guards"
DENSITY_LINES = 40          # the cap: one declared guard per this many lines of the module's own source files
MODULE_KINDS = ("c_library", "c_binary")


def own_sites(label, facts, structure):
    """The distinct guard call sites (file, line, function) of the module in its own source files, and the lines
    of those files. `structure` None: the lines are unknown (None)."""
    if structure is None:
        return set(), None
    srcs = set(structure.srcs)
    sites = {site for unit in facts.units for site in unit.guards if site[0] in srcs} if facts else set()
    lines = {}
    for unit in structure.units:
        for fact in unit.files:
            if fact.path in srcs:
                lines[fact.path] = fact.lines
    return sites, sum(lines.values())


def module_findings(label, declared, facts, structure):
    sites, lines = own_sites(label, facts, structure)
    count = len(sites)
    cap = None if lines is None else lines // DENSITY_LINES
    found = [finding("guards", severity=SEVERITY_INFO, module=label, sites=count, declared=declared, cap=cap)]
    if lines is None and (declared or (facts and any(unit.guards for unit in facts.units))):
        found.append(finding("structure-missing", module=label))
    if declared > count:
        found.append(finding("guard-budget-over-sites", module=label, declared=declared, sites=count))
    if cap is not None and declared > cap:
        found.append(finding("guard-budget-over-cap", module=label, declared=declared, cap=cap, lines=lines,
                             lines_per_guard=DENSITY_LINES))
    return found


def module_tables(document):
    tables = document.get("module", {})
    if not isinstance(tables, dict) or not all(isinstance(t, dict) for t in tables.values()):
        raise InternalError("policy: [module] must be a table of tables")
    for label in tables:
        if not facts_data.LABEL.fullmatch(label):
            raise InternalError("policy: bad module label %r" % label)
    return tables


def decide(document, facts_by_label, structures, third):
    products, _, found = facts_third_party.split(facts_by_label, third)
    tables = module_tables(document)
    declared = {label: facts_policy.declared_guards(label, table) for label, table in tables.items()}
    judged = set(declared) | {label for label, s in structures.items() if s.kind in MODULE_KINDS}
    judged |= {label for label, f in products.items() if f.kind in MODULE_KINDS and any(u.guards for u in f.units)}
    for label in sorted(judged):
        facts = products.get(label)
        if facts is not None and facts.kind not in MODULE_KINDS:
            raise InternalError("guards: %s is a %s, not a module" % (label, facts.kind))
        found.extend(module_findings(label, declared.get(label, 0), facts, structures.get(label)))
    return GateResult(GATE_ID, found, {"modules": len(judged), "density_lines": DENSITY_LINES})


def run(args):
    document = grade_policy.load_document(args.policy)
    facts_by_label = facts_data.load_facts_dir(args.facts)
    structures = structure_data.load_structure_dir(args.structure)
    return decide(document, facts_by_label, structures, facts_third_party.load())


def add_parser(subparsers):
    parser = subparsers.add_parser("guards", allow_abbrev=False,
                                   help="guard call sites per module and the declared guard budget")
    parser.add_argument("--facts", required=True)
    parser.add_argument("--structure", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
