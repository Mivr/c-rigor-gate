"""The decoupling declarations of a product (`products/<product>/decoupling.toml`), as gate `decoupling` reads them.

Gate-owned, optional, next to `product.toml`. Any defect is exit 2 (InternalError). Every key is optional:

    [modules]
    contract    = ["//apps/shop/contracts/**"]    # interface modules: types, constants, function-pointer tables
    component   = ["//apps/shop/parts/**"]        # implementations that meet only through contracts
    composition = ["//apps/shop/main:*"]          # the modules that bind implementations to interfaces
    fake        = ["//apps/shop/contracts/clock:fake"]   # test-only libraries: fakes and test kits
    frozen      = ["//apps/shop/parts/cart:cart"] # besides the contracts: modules whose public headers are frozen
    [contract]
    may_use = ["//lib/base/**"]                   # what a contract may depend on besides other contracts
    allow   = ["memcpy", "memset", "memcmp"]      # the only outside symbols a contract's objects may reference (default)
    [tests]
    integration = ["//apps/shop/itest/**"]        # packages without a module: their tests are integration tests
    simulation  = ["//apps/shop/sim/**"]          # the same, counted apart

An entry is a module pattern as in `architecture.toml` (`//pkg:name`, `//pkg:*`, `//pkg/**`), or the name of a layer
of the product's `architecture.toml`, which stands for that layer's patterns. The `[testkit]` modules of the
architecture are fakes too. A module in none of the lists (a library, a pure domain module) is not restricted.
"""

import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio, layering
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import SYMBOL

FILE_NAME = "decoupling.toml"
MODULE_KEYS = ("contract", "component", "composition", "fake", "frozen")
CONTRACT_KEYS = ("may_use", "allow")
TEST_KEYS = ("integration", "simulation")
DEFAULT_ALLOW = ("memcpy", "memset", "memcmp")


@dataclass(frozen=True)
class Config:
    contract: tuple = ()        # module patterns
    component: tuple = ()
    composition: tuple = ()
    fake: tuple = ()
    frozen: tuple = ()
    may_use: tuple = ()
    integration: tuple = ()
    simulation: tuple = ()
    allow: frozenset = frozenset(DEFAULT_ALLOW)

    def is_in(self, key, label):
        """Does one of the patterns of the list `key` match the module `label`?"""
        return any(layering.matches(pattern, label) for pattern in getattr(self, key))


def _fail(why):
    raise InternalError("decoupling: %s" % why)


def _table(document, name, allowed):
    table = document.get(name, {})
    if not isinstance(table, dict) or not set(table) <= set(allowed):
        _fail("[%s] may only contain %s" % (name, sorted(allowed)))
    return table


def _entries(where, value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _fail("%s must be a list of strings" % where)
    if len(set(value)) != len(value):
        _fail("%s has duplicates" % where)
    return value


def _patterns(where, value, arch):
    """The entries as module patterns; a layer name becomes the patterns of that layer."""
    found = []
    for entry in _entries(where, value):
        if layering.PATTERN.fullmatch(entry):
            found.append(entry)
        elif arch is not None and entry in arch.layers:
            found.extend(arch.layers[entry])
        else:
            _fail("%s: %r is neither a module pattern nor a layer of architecture.toml" % (where, entry))
    return tuple(found)


def _symbols(where, value):
    names = _entries(where, value)
    if not all(SYMBOL.fullmatch(name) for name in names):
        _fail("%s must be a list of symbol names" % where)
    return frozenset(names)


def parse(text, arch=None):
    """`arch`: the product's `layering.Architecture`, or None when it has no `architecture.toml`."""
    try:
        document = tomllib.loads(text)
    except ValueError as exc:
        raise InternalError("decoupling is not valid TOML: %s" % exc) from exc
    if not set(document) <= {"modules", "contract", "tests"}:
        _fail("top level may only contain [modules], [contract] and [tests]")
    modules = _table(document, "modules", MODULE_KEYS)
    contract = _table(document, "contract", CONTRACT_KEYS)
    tests = _table(document, "tests", TEST_KEYS)
    lists = {key: _patterns("[modules] " + key, modules.get(key, []), arch) for key in MODULE_KEYS}
    lists["fake"] += tuple(arch.testkit) if arch is not None else ()
    lists.update({key: _patterns("[tests] " + key, tests.get(key, []), arch) for key in TEST_KEYS})
    return Config(may_use=_patterns("[contract] may_use", contract.get("may_use", []), arch),
                  allow=_symbols("[contract] allow", contract.get("allow", list(DEFAULT_ALLOW))), **lists)


def load(path, arch=None):
    try:
        return parse(jsonio.read_bytes(path).decode("utf-8"), arch)
    except UnicodeDecodeError as exc:
        raise InternalError("%s: not UTF-8" % path) from exc
