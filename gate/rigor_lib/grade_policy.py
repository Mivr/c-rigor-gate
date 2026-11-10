"""`products/<p>/policy.toml` as `rigor grade` reads it: one gate-owned file, read whole by every consumer.

The symbol and semantic-suppression gates read it with `facts_policy` (`allow`, `deny_exempt`, `allow_builtins`,
`exports` and `level` per module; the symbols gate needs `level` to arm the `exports` check, T055, and ignores
`impl`). The mutants gate reads only the module levels, `level = "L1".."L5"`, and the witness gates (T039) read
`level` and `impl`, the implementation paths a witness replaces:

    [module."//core:core"]
    level = "L3"                 # L1: not mutated; L2: survivors are reported; L3..L5: zero survivors
    impl = ["core/core.c"]       # globs; required for L2+ (finding `impl-missing`), see docs/witness.md
    allow = ["memcpy"]

Any defect in the file is exit 2, as for the other gate-owned files.
"""

import os
import tomllib

from rigor_lib import jsonio
from rigor_lib.errors import InternalError

LEVELS = ("L1", "L2", "L3", "L4", "L5")


def policy_path(g):
    return os.path.join(os.path.dirname(g.args.product), "policy.toml")


def _load(path):
    if not os.path.isfile(path):
        raise InternalError("missing %s" % path)
    try:
        return tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc


def load_document(path):
    """The parsed policy document (`witness_scope.impl_map` reads the `impl` keys from it)."""
    return _load(path)


def module_tables(document):
    modules = document.get("module", {})
    if not isinstance(modules, dict) or not all(isinstance(t, dict) for t in modules.values()):
        raise InternalError("policy: [module] must be a table of tables")
    return modules


def load_levels(path):
    """label -> level for every module table that has one."""
    levels = {}
    for label, table in module_tables(_load(path)).items():
        if "level" in table:
            if table["level"] not in LEVELS:
                raise InternalError("policy: module %s: level must be one of %s" % (label, ", ".join(LEVELS)))
            levels[label] = table["level"]
    return levels
