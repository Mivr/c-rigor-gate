"""The tables of the UI contract that the identity checks of the ui-scene judge read (U24; docs/ui-contract.md). The
loader (ui_contract) takes their schema from `table_specs`, accepts them absent (no row: the check they feed has nothing
to judge) and runs `check` after its own checks.

| Table | Id | Keys |
|---|---|---|
| `[[value]]` | `id` | `element`: the element id whose shown nodes make ONE value (lockers: the locker number, the entered code); optional `max_nodes` (1..64, 1 when absent): how many nodes may carry it |
| `[[catalogue]]` | `id` | `msgids` (`key`: a msgid is a catalogue key, never display text; `source-text`: a msgid is the source language's text, as gettext's), `text_roles`: the typographic roles whose text must come from the catalogue (a msgid on every node) |
| `[[identity_literal]]` | `msgid` | a msgid whose formatted text is the msgid itself in every language (raw-text does not report it) |
"""

from rigor_lib.errors import InternalError
from rigor_lib.ui_contract_checks import EXTRA_ELEMENTS

TABLES = ("value", "catalogue", "identity_literal")
MAX_NODES = 1                 # [[value]].max_nodes when the row does not give it


def table_specs(ident, is_str, integer, enum, list_of):
    """The schema of the tables, in the loader's form (id key, {key: checker}, optional keys)."""
    return {
        "value": ("id", {"id": ident, "element": ident, "max_nodes": integer(1, 64)}, ("max_nodes",)),
        "catalogue": ("id", {"id": ident, "msgids": enum("key", "source-text"),
                             "text_roles": list_of(ident, minimum=0)}, ()),
        "identity_literal": ("msgid", {"msgid": is_str}, ()),
    }


def _fail(why):
    raise InternalError("ui-contract: %s" % why)


def check(tables):
    """A value names a known element (a role id, an extra element of the loader, an `[[element]]` id), at most one
    value per element; a catalogue's text roles are `[[role]]` ids."""
    roles = {row["id"] for row in tables["role"]}
    known = roles | EXTRA_ELEMENTS | {row["id"] for row in tables["element"]}
    seen = set()
    for row in tables["value"]:
        if row["element"] not in known:
            _fail("[[value]] %r: element %r is no [[role]], [[element]] or extra element id" % (row["id"], row["element"]))
        if row["element"] in seen:
            _fail("[[value]] %r: element %r already makes another value" % (row["id"], row["element"]))
        seen.add(row["element"])
    for row in tables["catalogue"]:
        for role in row["text_roles"]:
            if role not in roles:
                _fail("[[catalogue]] %r: text role %r is not a [[role]] id" % (row["id"], role))


def max_nodes(row):
    return row.get("max_nodes", MAX_NODES)


def msgids_are_keys(contract):
    """Whether label == msgid is decidable from identity alone: the contract has a catalogue and every catalogue's
    msgids are keys (for `source-text` msgids a label equal to its msgid is right in the source language)."""
    rows = contract.rows("catalogue")
    return bool(rows) and all(row["msgids"] == "key" for row in rows)


def text_roles(contract):
    return {role for row in contract.rows("catalogue") for role in row["text_roles"]}


def literals(contract):
    return {row["msgid"].encode("utf-8") for row in contract.rows("identity_literal")}
