"""The symbol policy (`policy/<product>.toml`). Gate-owned, so any defect is exit 2.

    [global]
    deny = ["kill", ...]            # symbols no product module may reference
    trusted = ["//ctest:ctest"]     # gate-owned modules: they export symbols, nothing is checked on them
    [module."//core:core"]
    allow = ["memcpy"]              # external symbols this module may reference besides its deps' exports
    deny_exempt = ["open"]          # entries of global.deny it may use (implies allow)
    allow_builtins = ["__builtin_trap"]   # guarded builtins (semantic_table.GUARDED_BUILTINS) it may use
"""

import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio, semantic_table
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL, SYMBOL


@dataclass(frozen=True)
class Module:
    allow: frozenset = frozenset()
    deny_exempt: frozenset = frozenset()
    allow_builtins: frozenset = frozenset()


@dataclass(frozen=True)
class Policy:
    deny: frozenset
    trusted: frozenset
    modules: dict


def _names(where, value, pattern=SYMBOL):
    if not isinstance(value, list) or not all(isinstance(v, str) and pattern.fullmatch(v) for v in value):
        raise InternalError("policy: %s must be a list of valid names" % where)
    if len(set(value)) != len(value):
        raise InternalError("policy: %s has duplicates" % where)
    return frozenset(value)


def _only(where, table, allowed):
    if not isinstance(table, dict) or not set(table) <= set(allowed):
        raise InternalError("policy: %s may only contain %s" % (where, sorted(allowed)))


def _module(label, table, deny):
    where = "module %s" % label
    _only(where, table, ("allow", "deny_exempt", "allow_builtins"))
    exempt = _names(where + " deny_exempt", table.get("deny_exempt", []))
    if not exempt <= deny:
        raise InternalError("policy: %s deny_exempt names symbols that are not denied: %s"
                            % (label, sorted(exempt - deny)))
    builtins = _names(where + " allow_builtins", table.get("allow_builtins", []))
    if not builtins <= set(semantic_table.GUARDED_BUILTINS):
        raise InternalError("policy: %s allow_builtins names unguarded builtins" % label)
    return Module(_names(where + " allow", table.get("allow", [])), exempt, builtins)


def load_policy(path):
    try:
        document = tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc
    _only("top level", document, ("global", "module"))
    glob = document.get("global")
    _only("[global]", glob, ("deny", "trusted"))
    if "deny" not in glob:
        raise InternalError("policy: [global] needs `deny`")
    deny = _names("[global] deny", glob["deny"])
    trusted = _names("[global] trusted", glob.get("trusted", []), LABEL)
    tables = document.get("module", {})
    if not isinstance(tables, dict):
        raise InternalError("policy: [module] must be a table of tables")
    modules = {}
    for label, table in tables.items():
        if not LABEL.fullmatch(label):
            raise InternalError("policy: bad module label %r" % label)
        modules[label] = _module(label, table, deny)
    if trusted & set(modules):
        raise InternalError("policy: a module cannot be both trusted and listed: %s"
                            % sorted(trusted & set(modules)))
    return Policy(deny, trusted, modules)
