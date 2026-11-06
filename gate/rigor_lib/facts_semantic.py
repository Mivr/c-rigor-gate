"""Gate `semantic-suppressions`: what the compiler saw must contain no switch-off of any check.
A user `#line` that renames the file or goes back is a finding too: it is how text would be made
to look like a system header.

Decided on the preprocessed text of every source (facts from `cscan.py`): after macros, token
pasting, `_Pragma` and line splices have been resolved, so none of them can hide anything.
"""

from rigor_lib import semantic_table
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding

GATE_ID = "semantic-suppressions"


def unit_findings(facts, unit, module):
    where = {"target": facts.label, "unit": unit.name}
    found = []
    for file, line, text in unit.pragmas:
        found.append(finding("pragma", file=file, line=line, text=text, **where))
    for name, file, line in unit.line_directives:
        found.append(finding("line-directive", name=name, file=file, line=line, **where))
    for name, file, line in unit.identifiers:
        found.extend(identifier_findings(name, file, line, module, where))
    for name, file, line in unit.attributes:
        normal = semantic_table.normalise_attribute(name)
        if normal in semantic_table.FORBIDDEN_ATTRIBUTES:
            found.append(finding("forbidden-attribute", name=normal, file=file, line=line, **where))
    return found


def identifier_findings(name, file, line, module, where):
    rule = semantic_table.FORBIDDEN_IDENTIFIERS.get(name)
    if rule is not None:
        return [finding(rule, name=name, file=file, line=line, **where)]
    if name not in semantic_table.GUARDED_BUILTINS:
        # The scanner reports something this table does not know: fail closed.
        raise InternalError("scanner reported unknown identifier %r" % name)
    if module is not None and name in module.allow_builtins:
        return []
    return [finding("forbidden-builtin", name=name, file=file, line=line, **where)]


def run(facts_by_label, policy):
    found = []
    units = 0
    for label in sorted(facts_by_label):
        facts = facts_by_label[label]
        module = policy.modules.get(label)
        for unit in facts.units:
            units += 1
            found.extend(unit_findings(facts, unit, module))
    return GateResult(GATE_ID, found, {"targets": len(facts_by_label), "units": units})
