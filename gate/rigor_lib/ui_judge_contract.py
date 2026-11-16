"""The tables of the UI contract that the ui-scene and ui-fit judges added (U06), their checks and lookups. The loader
(ui_contract) takes their schema from `table_specs` and runs `check` after its own checks; the judges call the lookups.

| Table | Id | Keys |
|---|---|---|
| `[[style_role]]` | `style` | `role`: the typographic role of a style no `[[role]]` row names (a colour variant) |
| `[[role_wrap]]` | `role` | `scope`: the wrap scope of every node of the role (only where the spec decides it for all of them) |
| `[[element]]` | `id` | `key` (the scene key, unique), optional `wrap` (the scope of that node where the spec decides it per node),
                          optional `label = "accessible"` (its label is an accessible label only, never drawn) |
| `[[style_line]]` | `style` | `line_height_px`, provenance `product-baseline:<commit>` (and only this table may use it) |

The input policy of a layer is the sealed `[[input_layer]]` table's (orchestrator ruling R8), see `layer_rows`.
"""

from rigor_lib.errors import InternalError

U06_TABLES = ("style_role", "role_wrap", "element", "style_line")
BASELINE = "product-baseline:"


def table_specs(ident, is_str, integer, enum):
    """The schema of the tables, in the loader's form (id key, {key: checker}, optional keys)."""
    return {
        "style_role": ("style", {"style": ident, "role": ident}, ()),
        "role_wrap": ("role", {"role": ident, "scope": ident}, ()),
        "element": ("id", {"id": ident, "key": is_str, "wrap": ident, "label": enum("accessible")}, ("wrap", "label")),
        "style_line": ("style", {"style": ident, "line_height_px": integer(1, 2000)}, ()),
    }


def _fail(why):
    raise InternalError("ui-contract: %s" % why)


def check_provenance_form(table, provenance, where):
    """`product-baseline:` is the form of `[[style_line]]` alone, and that table has no other."""
    if (provenance.startswith(BASELINE)) != (table == "style_line"):
        _fail("%s: the provenance form %s is that of [[style_line]] alone, and that table has no other" % (where, BASELINE))


def check(tables):
    """References, one typographic role per style, unique element keys."""
    styles = {r["id"] for r in tables["style"]}
    roles = {r["id"] for r in tables["role"]}
    named = {r["style"] for r in tables["role"]}
    if len(named) != len(tables["role"]):
        _fail("[[role]]: two roles share a style, so a style token has no single role")
    for row in tables["style_role"]:
        if row["style"] not in styles or row["role"] not in roles:
            _fail("[[style_role]] %r: style and role must be [[style]] and [[role]] ids" % row["style"])
        if row["style"] in named:
            _fail("[[style_role]] %r: a [[role]] row already names this style" % row["style"])
    scopes = {r["scope"] for r in tables["wrap"]}
    for row in tables["role_wrap"]:
        if row["role"] not in roles or row["scope"] not in scopes:
            _fail("[[role_wrap]] %r: role and scope must be [[role]] and [[wrap]] ids" % row["role"])
    keys = [r["key"] for r in tables["element"]]
    if len(set(keys)) != len(keys):
        _fail("[[element]]: two elements have the same scene key")
    for row in tables["element"]:
        if "wrap" in row and row["wrap"] not in scopes:
            _fail("[[element]] %r: wrap %r is not a [[wrap]] scope" % (row["id"], row["wrap"]))
    elements = {r["id"] for r in tables["element"]}
    for row in tables["toggle_group"]:
        if not set(row["members"]) <= elements:
            _fail("[[toggle_group]] %r: every member must be an [[element]] id" % row["id"])
    for row in tables["style_line"]:
        if row["style"] not in styles:
            _fail("[[style_line]] %r is not a [[style]] id" % row["style"])


# ---- lookups --------------------------------------------------------------------------------------------------------
def style_by_token(contract, token):
    """The [[style]] row of a numeric style token, or None."""
    return next((row for row in contract.tables["style"] if row["token"] == token), None)


def role_of_style(contract, style):
    """The typographic role of a style: the [[role]] row that names it, else its [[style_role]] row; or None."""
    for row in contract.tables["role"]:
        if row["style"] == style:
            return row["id"]
    return next((row["role"] for row in contract.tables["style_role"] if row["style"] == style), None)


def element_of(contract, key):
    """The [[element]] row of a scene key, or None."""
    return next((row for row in contract.tables["element"] if row["key"] == key), None)


def scope_of(contract, key, role):
    """(the [[wrap]] row of a node: its element's `wrap`, else its role's [[role_wrap]]; or None, `role-wrap`)."""
    element = element_of(contract, key)
    scope = element.get("wrap") if element is not None else None
    if scope is None:
        scope = next((row["scope"] for row in contract.tables["role_wrap"] if row["role"] == role), None)
    if scope is None:
        return None
    return next(row for row in contract.tables["wrap"] if row["scope"] == scope)


def layer_rows(contract, role):
    """The sealed [[input_layer]] rows of a layer role: the row named the role, and the rows named `<role>_...` (its
    kinds: lockers' banner_notice and banner_persistent)."""
    return [row for row in contract.tables["input_layer"]
            if row["layer"] == role or row["layer"].startswith(role + "_")]
