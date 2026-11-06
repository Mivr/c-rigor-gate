"""`products/<p>/policy.toml` as `rigor grade` reads it: one gate-owned file, two readers.

The symbol and semantic-suppression gates (`facts_policy`) know `allow`, `deny_exempt` and
`allow_builtins` per module. The mutants gate adds `level = "L1".."L5"` to the same module tables:

    [module."//core:core"]
    level = "L3"                 # L1: not mutated; L2: survivors are reported; L3..L5: zero survivors
    allow = ["memcpy"]

`facts_policy` rejects keys it does not know, so it is given a copy without `level` (written into the
work directory by `symbol_policy_path`); every other key is kept, so a typo is still rejected there.
Any defect in the file is exit 2, as for the other gate-owned files.
"""

import json
import os
import re
import tomllib

from rigor_lib import jsonio
from rigor_lib.errors import InternalError

LEVELS = ("L1", "L2", "L3", "L4", "L5")
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def policy_path(g):
    return os.path.join(os.path.dirname(g.args.product), "policy.toml")


def _load(path):
    if not os.path.isfile(path):
        raise InternalError("missing %s" % path)
    try:
        return tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc


def _module_tables(document):
    modules = document.get("module", {})
    if not isinstance(modules, dict) or not all(isinstance(t, dict) for t in modules.values()):
        raise InternalError("policy: [module] must be a table of tables")
    return modules


def load_levels(path):
    """label -> level for every module table that has one."""
    levels = {}
    for label, table in _module_tables(_load(path)).items():
        if "level" in table:
            if table["level"] not in LEVELS:
                raise InternalError("policy: module %s: level must be one of %s" % (label, ", ".join(LEVELS)))
            levels[label] = table["level"]
    return levels


def _key(name):
    return name if _BARE_KEY.fullmatch(name) else json.dumps(name)


def _string(value):
    if not isinstance(value, str):
        raise InternalError("policy: only strings and lists of strings are expected, got %r" % (value,))
    return json.dumps(value)


def _table(header, table):
    lines = ["[%s]" % header]
    for name, value in table.items():
        if not isinstance(value, list):
            raise InternalError("policy: %s.%s must be a list of strings" % (header, name))
        lines.append("%s = [%s]" % (_key(name), ", ".join(_string(item) for item in value)))
    return "\n".join(lines) + "\n"


def symbol_policy_text(path):
    """The policy without `level`, as TOML text. Shapes the policy never has are refused, not dropped."""
    document = _load(path)
    tables = []
    for name, value in document.items():
        if not isinstance(value, dict):
            raise InternalError("policy: top-level key %r must be a table" % name)
        if name == "module":
            for label, table in _module_tables(document).items():
                kept = {k: v for k, v in table.items() if k != "level"}
                tables.append(_table("module.%s" % json.dumps(label), kept))
        else:
            tables.append(_table(_key(name), value))
    return "\n".join(tables)


def symbol_policy_path(g):
    """Path of the copy of the policy for `facts_policy`; written once per grading."""
    target = os.path.join(g.work, "tmp", "symbol-policy.toml")
    if not os.path.isfile(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "xb") as handle:
            handle.write(symbol_policy_text(policy_path(g)).encode("utf-8"))
    return target
