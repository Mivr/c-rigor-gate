"""The identity checks of the ui-scene judge (U24, P004 3.1): what the scene IS, read from the probe's `identity` reply
(ui/model/model.h, docs/ui-model.md "Scene identity"): the state class of the step and, per scene node, its element id,
msgid and formatted arguments. Contract tables: `[[state_class]]` (required elements), `[[value]]`,
`[[catalogue]]`, `[[identity_literal]]` (ui_contract_identity).

    required-element-missing  in a state of class C, an element id of C's `required` that no DRAWN node is (`drawn`:
                              gate-observed presence; `carries`: a role id by the gate's role of the node, any other
                              id by the product's tag); a class the contract has no row for is `contract-incomplete`
                              (`state-class`)
    value-split               the drawn nodes that are a `[[value]]` element number more than its `max_nodes`
    identity-role-mismatch    a product tag naming a role id (a `[[role]]` id or a structural role) the node does not
                              have
    raw-text (identity parts) `msgid`: a shown text node whose label is its msgid byte for byte, the msgid no
                              `[[identity_literal]]`, where the `[[catalogue]]` has key msgids (for source-text
                              msgids the verdict needs the catalogue: not applicable, U17b); `no-msgid`: a shown node
                              with a label and no msgid whose typographic role the `[[catalogue]]` lists in
                              `text_roles` (buttons and keys included)

A node outside the scene vocabulary takes part in no check (ui_judge_context): an element only such a node carries is
neither present nor missing (no verdict). Without identity (a probe that does not announce it) the checks are the
judge set's `check-blocked`, never a silent pass (ui_judge_findings).
"""

from rigor_lib import ui_contract_identity as tables
from rigor_lib.ui_judge_vocab import PURE_TEXT, STRUCTURAL_ROLES, TEXT_ROLES

ROLE_MISMATCH = "identity-role-mismatch"
CHECKS = ("required-element-missing", "value-split", ROLE_MISMATCH)
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
        identity_role_mismatch(ctx, report)
        required_element_missing(ctx, report)
        value_split(ctx, report)


def drawn(ctx, node):
    """Presence on gate-observed facts, never on the product's claim alone: the scene node is not hidden by its flag,
    it is associated with a rendered node, that node is shown (no hidden ancestor) with a non-empty visible box, and a
    text-bearing node has a non-empty label that is the drawn one (not a stage-text-mismatch)."""
    index = ctx.assoc.match.get(node.key)
    if node.hidden or index is None or not ctx.frame.shown(index) or ctx.frame.visible_box(index) is None:
        return False
    return node.role not in TEXT_ROLES or (node.label != b"" and node.key not in ctx.assoc.mismatch)


def carries(ctx, node, element):
    """Whether a node IS the element: a `[[role]]` id by the gate's typographic role of the node, a structural role
    (`countdown`) by the node's role, any other element id by the product's tag."""
    if element in _role_ids(ctx.contract):
        return ctx.role_of(node) == element
    if element in STRUCTURAL_ROLES:
        return node.role == element
    return ctx.identity.element(node.key) == element


def _role_ids(contract):
    return {row["id"] for row in contract.rows("role")}


def identity_role_mismatch(ctx, report):
    """A product tag that names a role id (a `[[role]]` id or a structural role) the node does not have: the product's
    claim contradicts what the gate reads, so the tag is not taken."""
    roles = _role_ids(ctx.contract)
    for node in ctx.scene:
        element = ctx.identity.element(node.key)
        if element not in roles and element not in STRUCTURAL_ROLES:
            continue
        report.examined(ROLE_MISMATCH)
        if not carries(ctx, node, element):
            report.add(ROLE_MISMATCH, [node.key],
                       {"stage": "O2", "key": node.key, "element": element, "role": ctx.role_of(node),
                        "scene_role": node.role}, target=node.key, records=ctx.identity.raw + [node.raw])


def required_element_missing(ctx, report):
    ident = ctx.identity
    row = next((r for r in ctx.contract.rows("state_class") if r["id"] == ident.state), None)
    if row is None:
        report.incomplete("state-class", ident.state)
        return
    unread = {element for key, (element, _m, _a) in ident.nodes.items() if key not in ctx.by_key}
    for element in row["required"]:
        carriers = [node for node in ctx.scene if carries(ctx, node, element)]
        present = [node for node in carriers if drawn(ctx, node)]
        if not present and not carriers and element in unread:
            continue                                  # only a node outside the vocabulary carries it: no verdict
        report.examined("required-element-missing")
        if present:
            continue
        undrawn = sorted(node.key for node in carriers)
        report.add("required-element-missing", [ident.state, element],
                   {"stage": "O2", "state_class": ident.state, "element": element, "undrawn": undrawn},
                   target=element, records=ident.raw + [ctx.by_key[key].raw for key in undrawn])


def value_split(ctx, report):
    for row in ctx.contract.rows("value"):
        nodes = [node for node in ctx.scene if carries(ctx, node, row["element"]) and drawn(ctx, node)]
        if not nodes:
            continue
        report.examined("value-split")
        limit = tables.max_nodes(row)
        if len(nodes) > limit:
            report.add("value-split", [row["id"]],
                       {"stage": "O2", "value": row["id"], "element": row["element"],
                        "nodes": sorted(node.key for node in nodes), "max_nodes": limit},
                       target=row["id"], records=[node.raw for node in nodes])


def seen_names(ctx):
    """The exception targets a state with identity visits: the element ids its class requires and the value ids."""
    if ctx.identity is None:
        return set()
    row = next((r for r in ctx.contract.rows("state_class") if r["id"] == ctx.identity.state), None)
    return set(row["required"] if row else ()) | {r["id"] for r in ctx.contract.rows("value")}


def raw_text(ctx, report, node):
    """The identity parts of raw-text for one shown node of role text or countdown (its verdict is counted by the
    caller): `msgid`, then `no-msgid`."""
    ident = ctx.identity
    if ident is None:
        return
    msgid = ident.msgid(node.key)
    if msgid is None:
        no_msgid(ctx, report, node)
    elif not tables.msgids_are_keys(ctx.contract):
        report.not_applicable(RAW)
    elif node.label == msgid and msgid not in tables.literals(ctx.contract):
        report.add(RAW, [node.key, "msgid"], {"stage": "O2", "key": node.key, "part": "msgid"},
                   target=node.key, records=[node.raw])


def no_msgid(ctx, report, node):
    """`no-msgid`: a shown node with a label and no msgid whose typographic role a `[[catalogue]]` lists in
    `text_roles` (any text-bearing role: a button's or key's label too)."""
    if ctx.identity.msgid(node.key) is None and node.label != b"" \
            and ctx.role_of(node) in tables.text_roles(ctx.contract):
        report.add(RAW, [node.key, "no-msgid"], {"stage": "O2", "key": node.key, "part": "no-msgid",
                                                 "role": ctx.role_of(node)}, target=node.key, records=[node.raw])


def other_text(ctx, report):
    """`no-msgid` over the shown text-bearing nodes raw-text does not otherwise examine (buttons, keys): one verdict
    per node whose typographic role is catalogue text."""
    if ctx.identity is None:
        return
    for node in ctx.scene:
        if node.role in TEXT_ROLES and node.role not in PURE_TEXT and not node.hidden \
                and ctx.role_of(node) in tables.text_roles(ctx.contract):
            report.examined(RAW)
            no_msgid(ctx, report, node)


def blocked(contract):
    """The checks that need identity and apply to the contract: what a run without identity cannot judge."""
    out = ["required-element-missing"] if contract.rows("state_class") else []
    out += ["value-split"] if contract.rows("value") else []
    out += [RAW] if contract.rows("catalogue") else []
    return out


def applies(check, contract):
    """identity-role-mismatch is never vacuous: a product that tags no node with a role id gives it nothing to judge."""
    if check == ROLE_MISMATCH:
        return False
    return bool(contract.rows("state_class" if check == "required-element-missing" else "value"))
