"""The architecture contract (`products/<product>/architecture.toml`) as `layering_check` reads it.

Gate-owned, optional per product, next to `product.toml`. Any defect is exit 2 (InternalError).

    [layers]
    order = ["lib-base", "app-domain"]        # bottom to top; every layer needs a [layer."x"] table
    [layer."lib-base"]
    modules = ["//lib/base/core:core", "//lib/base/fmt:*", "//lib/util/**"]
    [layer."app-domain"]
    modules = ["//apps/a/domain:*"]
    [testkit]                                  # optional: non-c_test targets that only tests may use
    modules = ["//lib/base/core:testkit"]
    [composition]                              # optional: modules that may hold `composition` edges
    modules = ["//apps/a/root:*"]
    [[edge]]                                   # every allowed dependency edge
    from = "app-domain"                        # a layer name, or a module label
    to = "lib-base"                            # a layer name, or a module label
    kind = "pure"                              # data | pure | port | composition
    symbols = ["fmt_init"]                     # port: required, the target symbols the edge may reference

A module entry is an exact label (`//pkg:name`), a package glob (`//pkg:*`) or a tree glob (`//pkg/**`, the package
and every package below it). Edge endpoints are layer names (no `//`) or exact module labels.
"""

import re
import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL, SYMBOL

KINDS = ("data", "pure", "port", "composition")
_PACKAGE = r"//[A-Za-z0-9_./+-]*"
PATTERN = re.compile(r"(%s:[A-Za-z0-9_.+-]+|%s:\*|%s/\*\*)" % (_PACKAGE, _PACKAGE, _PACKAGE))
LAYER_NAME = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class Edge:
    source: str      # layer name or module label
    target: str
    kind: str
    symbols: frozenset


@dataclass(frozen=True)
class Architecture:
    order: tuple     # layer names, bottom to top
    layers: dict     # layer name -> tuple of patterns
    testkit: tuple
    composition: tuple
    edges: tuple

    def rank(self, layer):
        return self.order.index(layer)


def matches(pattern, label):
    """Does the label-or-glob `pattern` match the module `label`?"""
    if pattern.endswith(":*"):
        return label.rpartition(":")[0] == pattern[:-2]
    if pattern.endswith("/**"):
        package = label.rpartition(":")[0]
        root = pattern[:-3]
        return package == root or package.startswith(root + "/")
    return pattern == label


def _fail(why):
    raise InternalError("architecture: %s" % why)


def _only(where, table, allowed):
    if not isinstance(table, dict) or not set(table) <= set(allowed):
        _fail("%s may only contain %s" % (where, sorted(allowed)))


def _list(where, value, pattern):
    if not isinstance(value, list) or not all(isinstance(v, str) and pattern.fullmatch(v) for v in value):
        _fail("%s must be a list of valid names" % where)
    if len(set(value)) != len(value):
        _fail("%s has duplicates" % where)
    return tuple(value)


def _layers(document):
    section = document.get("layers")
    _only("[layers]", section, ("order",))
    order = _list("[layers] order", section.get("order"), LAYER_NAME)
    tables = document.get("layer", {})
    if not order or not isinstance(tables, dict) or set(tables) != set(order):
        _fail("[layer.*] tables must be exactly the layers of [layers] order (and there must be one)")
    layers = {}
    for name in order:
        _only("[layer.%s]" % name, tables[name], ("modules",))
        layers[name] = _list("[layer.%s] modules" % name, tables[name].get("modules"), PATTERN)
    return order, layers


def _modules_of(document, key):
    table = document.get(key, {})
    _only("[%s]" % key, table, ("modules",))
    return _list("[%s] modules" % key, table.get("modules", []), PATTERN)


def _endpoint(order, where, value):
    if isinstance(value, str) and value in order:
        return value
    if isinstance(value, str) and LABEL.fullmatch(value):
        return value
    _fail("%s must be a layer name or a module label, got %r" % (where, value))


def _edge(order, index, table):
    where = "edge #%d" % (index + 1)
    _only(where, table, ("from", "to", "kind", "symbols"))
    source = _endpoint(order, where + " from", table.get("from"))
    target = _endpoint(order, where + " to", table.get("to"))
    kind = table.get("kind")
    if kind not in KINDS:
        _fail("%s kind must be one of %s" % (where, ", ".join(KINDS)))
    symbols = frozenset(_list(where + " symbols", table.get("symbols", []), SYMBOL))
    if (kind == "port") != bool(symbols):
        _fail("%s: a port edge needs a non-empty `symbols`; no other kind may have one" % where)
    if source in order and target in order and order.index(source) < order.index(target):
        _fail("%s: %s -> %s points upward (a contract defect)" % (where, source, target))
    return Edge(source, target, kind, symbols)


def parse(text):
    try:
        document = tomllib.loads(text)
    except ValueError as exc:
        raise InternalError("architecture is not valid TOML: %s" % exc) from exc
    _only("top level", document, ("layers", "layer", "testkit", "composition", "edge"))
    order, layers = _layers(document)
    raw = document.get("edge", [])
    if not isinstance(raw, list):
        _fail("[[edge]] must be an array of tables")
    edges = tuple(_edge(order, i, table) for i, table in enumerate(raw))
    keys = [(e.source, e.target, e.kind) for e in edges]
    if len(set(keys)) != len(keys):
        _fail("duplicate edge")
    return Architecture(order, layers, _modules_of(document, "testkit"), _modules_of(document, "composition"), edges)


def load(path):
    try:
        return parse(jsonio.read_bytes(path).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise InternalError("%s: not UTF-8" % path) from exc
