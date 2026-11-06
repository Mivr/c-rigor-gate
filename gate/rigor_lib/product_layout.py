"""`products/<name>/product.toml`: which product files may enter a grading tree.

    name = "annas-c"
    [layout]
    include = ["core/**", "json/**"]   # globs (see globs.py); BUCK files are ordinary files
    exclude = []                       # optional, further globs to leave out

Whatever the product says, the files in ALWAYS_EXCLUDED never enter the tree: they are the
ones through which a product could change the build environment (Buck2 configuration, tools,
toolchains, prelude, a copy of the gate, any `.bzl` file, git metadata).
"""

import re
import tomllib

from rigor_lib import globs, jsonio
from rigor_lib.errors import InternalError

# The one list of paths the gate refuses from a product. Globs as in globs.py.
ALWAYS_EXCLUDED = (
    "**/.buckconfig*",
    "**/.buckroot",
    "**/*.bzl",
    "tools/**",
    "toolchains/**",
    "prelude/**",
    "gate/**",
    "**/.git*",
    "**/.git*/**",
)

NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
_TOP_KEYS = {"name", "layout"}
_LAYOUT_KEYS = {"include", "exclude"}

COPY = "copy"
NOT_INCLUDED = "not-included"
EXCLUDED_BY_PRODUCT = "excluded-by-product"
EXCLUDED_BY_GATE = "excluded-by-gate"


class ProductConfig:
    def __init__(self, name, include, exclude):
        self.name = name
        self.include = include    # list of (pattern text, compiled glob)
        self.exclude = exclude


def _glob_list(table, key, required):
    if key not in table:
        if required:
            raise InternalError("product.toml: [layout] is missing %r" % key)
        return []
    value = table[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InternalError("product.toml: layout.%s must be a list of strings" % key)
    return [(item, globs.compile_glob(item)) for item in value]


def load_product(path):
    table = tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    if set(table) != _TOP_KEYS:
        raise InternalError("product.toml: keys must be exactly %s" % sorted(_TOP_KEYS))
    name = table["name"]
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise InternalError("product.toml: bad name %r" % (name,))
    layout = table["layout"]
    if not isinstance(layout, dict) or not set(layout) <= _LAYOUT_KEYS:
        raise InternalError("product.toml: [layout] holds only %s" % sorted(_LAYOUT_KEYS))
    include = _glob_list(layout, "include", required=True)
    if not include:
        raise InternalError("product.toml: layout.include is empty")
    return ProductConfig(name, include, _glob_list(layout, "exclude", required=False))


_ALWAYS = [globs.compile_glob(pattern) for pattern in ALWAYS_EXCLUDED]


def classify(config, path_text):
    """What to do with one product path: COPY or one of the reasons it is left out."""
    if not any(globs.matches(glob, path_text) for _, glob in config.include):
        return NOT_INCLUDED
    if any(globs.matches(glob, path_text) for glob in _ALWAYS):
        return EXCLUDED_BY_GATE
    if any(globs.matches(glob, path_text) for _, glob in config.exclude):
        return EXCLUDED_BY_PRODUCT
    return COPY
