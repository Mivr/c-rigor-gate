"""Gate `semantic-suppressions`: what the compiler saw must contain no switch-off of any check.
A user `#line` that renames the file or goes back is a finding too: it is how text would be made
to look like a system header; so are product macros that could rewrite a toolchain header (a
reserved name, a keyword or a toolchain macro) and a toolchain header included inside a brace.

Compiler builtins are default-deny: only the gate's `semantic_table.ALLOWED_BUILTINS`, the guarded
ones a module's policy allows, and `__builtin_setjmp`/`__builtin_longjmp` where the module may use
`setjmp`/`longjmp` pass; the alloca family never does.

Gate-owned third-party libraries (kind `c_third_party`, label on the allowlist) are not scanned; a
`c_third_party` facts file the allowlist does not name is a finding.

Decided on the preprocessed text of every source (facts from `cscan.py`): after macros, token
pasting, `_Pragma` and line splices have been resolved, so none of them can hide anything.
"""

from rigor_lib import facts_rt, facts_third_party, semantic_table
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding

GATE_ID = "semantic-suppressions"


def unit_findings(facts, unit, module, policy):
    where = {"target": facts.label, "unit": unit.name}
    found = []
    for file, line, text in unit.pragmas:
        found.append(finding("pragma", file=file, line=line, text=text, **where))
    for name, file, line in unit.line_directives:
        found.append(finding("line-directive", name=name, file=file, line=line, **where))
    for name, file, line in unit.identifiers:
        if facts_rt.is_gate_trap(facts, name, file):
            continue    # the trap inside gate//rt:require's header (T128), not the product's
        rule = identifier_rule(name, module, policy)
        if rule is not None:
            found.append(finding(rule, name=name, file=file, line=line, **where))
    for name, file, line in unit.attributes:
        normal = semantic_table.normalise_attribute(name)
        if normal in semantic_table.FORBIDDEN_ATTRIBUTES:
            found.append(finding("forbidden-attribute", name=normal, file=file, line=line, **where))
    return found


def identifier_rule(name, module, policy):
    """The finding rule for one identifier fact, or None when it is allowed."""
    rule = semantic_table.FORBIDDEN_IDENTIFIERS.get(name)
    if rule is not None:
        return rule
    if name.startswith(semantic_table.MACRO_DIRECTIVES):
        return None if semantic_table.macro_allowed(name) else "reserved-macro"
    if name.startswith(semantic_table.BLOCK_INCLUDE):
        return "block-scope-include"
    if not semantic_table.is_builtin(name):
        # The scanner reports something this table does not know: fail closed.
        raise InternalError("scanner reported unknown identifier %r" % name)
    kind = semantic_table.builtin_class(name)
    if kind == "banned":
        return "banned-builtin"
    if kind == "allowed":
        return None
    if kind == "guarded" and module is not None and name in module.allow_builtins:
        return None
    if kind == "symbol" and module is not None and may_reference(module, policy,
                                                                 semantic_table.SYMBOL_BUILTINS[name]):
        return None
    return "forbidden-builtin"


def may_reference(module, policy, symbol):
    """What the `symbols` gate lets this module reference: a denied symbol only with `deny_exempt`."""
    if symbol in policy.deny:
        return symbol in module.deny_exempt
    return symbol in module.allow


def run(facts_by_label, policy, third=None):
    third = facts_third_party.load() if third is None else third
    facts_by_label, _, found = facts_third_party.split(facts_by_label, third)
    units = 0
    for label in sorted(facts_by_label):
        facts = facts_by_label[label]
        module = policy.modules.get(label)
        for unit in facts.units:
            units += 1
            found.extend(unit_findings(facts, unit, module, policy))
    return GateResult(GATE_ID, found, {"targets": len(facts_by_label), "units": units})
