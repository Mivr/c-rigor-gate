"""The RAM budget of a binary (T089, P002 G26): how many bytes of writable static data it links.

A binary's RAM is the sum of `size` over every data object in a `data`, `bss` or `tls` section (the
`data` facts of `cscan.py`) of every unit it links: its own units and those of every library it reaches
through `deps`, product code and trusted third-party code counted separately. Read-only data is not RAM.

`products/<p>/ram-budget.toml` (gate-owned, next to `policy.toml`; no file means no check). The same
`[binary."//x:y"]` tables are also accepted inside `policy.toml` (the grade snapshots only `policy.toml` today,
see verdict_inputs.PRODUCT_FILES); having both is exit 2:

    [binary."//apps/x:x"]
    max_bytes = 16384

Findings (gate `symbols`): `ram-over-budget` (a binary above its `max_bytes`) and `ram-unbudgeted` (a binary
the file does not list).
"""

import os
import tomllib

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL, WRITABLE
from rigor_lib.findings import finding

FILE_NAME = "ram-budget.toml"


def parse(text, where="ram budget"):
    """label -> max_bytes. The file is gate-owned, so any defect is exit 2."""
    try:
        document = tomllib.loads(text)
    except ValueError as exc:
        raise InternalError("%s is not valid TOML: %s" % (where, exc)) from exc
    if set(document) - {"binary"}:
        raise InternalError("%s: only a [binary.\"//x:y\"] table is allowed" % where)
    return from_table(document.get("binary", {}), where)


def from_table(table, where):
    """label -> max_bytes from the parsed `binary` table (in `ram-budget.toml`, or in `policy.toml` itself)."""
    if not isinstance(table, dict):
        raise InternalError("%s: `binary` must be a table of tables" % where)
    budget = {}
    for label, entry in table.items():
        if not LABEL.fullmatch(label):
            raise InternalError("%s: bad binary label %r" % (where, label))
        if not isinstance(entry, dict) or set(entry) != {"max_bytes"}:
            raise InternalError("%s: [binary.%s] must have exactly `max_bytes`" % (where, label))
        value = entry["max_bytes"]
        if type(value) is not int or value < 0:
            raise InternalError("%s: max_bytes of %s must be a non-negative integer" % (where, label))
        budget[label] = value
    return budget


def load_sibling(policy_path):
    """The budget next to a policy file, or None when there is no such file."""
    path = os.path.join(os.path.dirname(policy_path), FILE_NAME)
    if not os.path.lexists(path):
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        raise InternalError("%s: not a regular file" % path)
    return parse(jsonio.read_bytes(path).decode("utf-8"), path)


def writable_bytes(unit):
    return sum(size for _name, size, section, _local in unit.data if section in WRITABLE)


def linked(label, products, libs):
    """(product labels, library labels) of `label` and everything it reaches through `deps`."""
    seen_products, seen_libs, todo = set(), set(), [label]
    while todo:
        current = todo.pop()
        if current in libs:
            seen_libs.add(current)
        elif current in products and current not in seen_products:
            seen_products.add(current)
            todo.extend(products[current].deps)
    return seen_products, seen_libs


def totals(label, products, libs):
    """{"product", "third_party", "total", "unmeasured"} writable bytes of one binary. `unmeasured` lists
    the third-party libraries whose facts carry no `data` (they count as 0 until their facts are measured)."""
    own, third = linked(label, products, libs)
    product = sum(writable_bytes(unit) for name in own for unit in products[name].units)
    external = sum(writable_bytes(unit) for name in third for unit in libs[name].units)
    unmeasured = sorted(name for name in third if not any(unit.data for unit in libs[name].units))
    return {"product": product, "third_party": external, "total": product + external, "unmeasured": unmeasured}


def findings(products, libs, budget):
    """(findings, {binary label: totals}) for every `c_binary`; `budget` is None when there is no file."""
    found, measured = [], {}
    for label in sorted(products):
        if products[label].kind != "c_binary":
            continue
        measured[label] = totals(label, products, libs)
        if budget is None:
            continue
        total = measured[label]["total"]
        if label not in budget:
            found.append(finding("ram-unbudgeted", target=label, bytes=total))
        elif total > budget[label]:
            found.append(finding("ram-over-budget", target=label, bytes=total, max_bytes=budget[label]))
    return found, measured
