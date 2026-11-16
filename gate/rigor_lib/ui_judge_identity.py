"""The identity checks of the ui-scene judge (U24, P004 3.1): what the scene IS, read from the probe's `identity` reply
(ui/model/model.h, docs/ui-model.md "Scene identity"): the state class of the step and, per scene node, its element id,
msgid and formatted arguments. Contract tables: `[[state_class]]` (required elements), `[[value]]`,
`[[catalogue]]`, `[[identity_literal]]` (ui_contract_identity).

    required-element-missing  in a state of class C, an element id of C's `required` that no shown node carries (a node
                              hidden by its scene flag does not count); a class the contract has no row for is
                              `contract-incomplete` (`state-class`)
    value-split               the shown nodes carrying a `[[value]]` element's id number more than its `max_nodes`
    raw-text (identity parts) `msgid`: a shown text node whose label is its msgid byte for byte, the msgid no
                              `[[identity_literal]]`, where every `[[catalogue]]` has key msgids (for source-text
                              msgids the verdict needs the catalogue: not applicable, U17b); `no-msgid`: a shown text
                              node with a label and no msgid whose typographic role a `[[catalogue]]` lists in
                              `text_roles`

A node outside the scene vocabulary takes part in no check (ui_judge_context): an element only such a node carries is
neither present nor missing (no verdict). Without identity (a probe that does not announce it) the checks are the
judge set's `check-blocked`, never a silent pass (ui_judge_findings).
"""

from rigor_lib import ui_contract_identity as tables

CHECKS = ("required-element-missing", "value-split")
RAW = "raw-text"


class Identity:
    """The parsed `identity` records of one step: `state` (the class id) and per node key (element id or None, msgid
    bytes or None, argument bytes)."""

    def __init__(self, records):
        self.state = _text(records[0].values[1])
        self.raw = [record.raw for record in records]     # the evidence of a finding no semantic record shows
        self.nodes = {}
        for record in records[1:]:
            element = None if record.fields[2] == "-" else _text(record.values[2])
            msgid = None if record.fields[3] == "-" else record.values[3]
            self.nodes[record.fields[1]] = (element, msgid, tuple(value[1:] for value in record.values[5:]))

    def element(self, key):
        return self.nodes.get(key, (None, None, ()))[0]

    def msgid(self, key):
        return self.nodes.get(key, (None, None, ()))[1]


def _text(value):
    return value.decode("utf-8", "surrogateescape")


def parse(records):
    """The Identity of a step's `identity` records, or None when the step has none."""
    return None if records is None else Identity(records)


def judge(ctx, report):
    if ctx.identity is not None:
        required_element_missing(ctx, report)
        value_split(ctx, report)


def required_element_missing(ctx, report):
    ident = ctx.identity
    row = next((r for r in ctx.contract.rows("state_class") if r["id"] == ident.state), None)
    if row is None:
        report.incomplete("state-class", ident.state)
        return
    present = {ident.element(node.key) for node in ctx.scene if not node.hidden}
    unread = {element for key, (element, _m, _a) in ident.nodes.items() if key not in ctx.by_key}
    for element in row["required"]:
        if element not in present and element in unread:
            continue                                  # only a node outside the vocabulary carries it: no verdict
        report.examined("required-element-missing")
        if element in present:
            continue
        hidden = sorted(node.key for node in ctx.scene if node.hidden and ident.element(node.key) == element)
        report.add("required-element-missing", [ident.state, element],
                   {"stage": "O2", "state_class": ident.state, "element": element, "hidden": hidden},
                   target=element, records=ident.raw + [ctx.by_key[key].raw for key in hidden])


def value_split(ctx, report):
    ident = ctx.identity
    for row in ctx.contract.rows("value"):
        nodes = [node for node in ctx.scene if not node.hidden and ident.element(node.key) == row["element"]]
        if not nodes:
            continue
        report.examined("value-split")
        limit = tables.max_nodes(row)
        if len(nodes) > limit:
            report.add("value-split", [row["id"]],
                       {"stage": "O2", "value": row["id"], "element": row["element"],
                        "nodes": sorted(node.key for node in nodes), "max_nodes": limit},
                       target=row["id"], records=[node.raw for node in nodes])


def raw_text(ctx, report, node):
    """The identity parts of raw-text for one shown text node (its verdict is counted by the caller)."""
    ident = ctx.identity
    if ident is None:
        return
    msgid = ident.msgid(node.key)
    if msgid is None:
        if node.label != b"" and ctx.role_of(node) in tables.text_roles(ctx.contract):
            report.add(RAW, [node.key, "no-msgid"], {"stage": "O2", "key": node.key, "part": "no-msgid",
                                                     "role": ctx.role_of(node)}, target=node.key, records=[node.raw])
        return
    if not tables.msgids_are_keys(ctx.contract):
        report.not_applicable(RAW)
    elif node.label == msgid and msgid not in tables.literals(ctx.contract):
        report.add(RAW, [node.key, "msgid"], {"stage": "O2", "key": node.key, "part": "msgid"},
                   target=node.key, records=[node.raw])


def blocked(contract):
    """The checks that need identity and apply to the contract: what a run without identity cannot judge."""
    out = ["required-element-missing"] if contract.rows("state_class") else []
    out += ["value-split"] if contract.rows("value") else []
    out += [RAW] if contract.rows("catalogue") else []
    return out


def applies(check, contract):
    return bool(contract.rows("state_class" if check == "required-element-missing" else "value"))
