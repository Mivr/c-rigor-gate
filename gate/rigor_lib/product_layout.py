"""`products/<name>/product.toml`: which product files may enter a grading tree.

    name = "annas-c"
    [layout]
    include = ["core/**", "json/**"]   # globs (see globs.py); BUCK files are ordinary files
    exclude = []                       # optional, further globs to leave out (non-code paths only)

Coverage (`coverage_findings`): the layout is an allow-list, so on its own a new product directory
would be silently ungraded. Every file at the product head that is code (a BUCK-like file, a C or
header extension, or any file a copied BUCK names) must be copied; anything else is a finding.

Whatever the product says, the files in ALWAYS_EXCLUDED never enter the tree: they are the
ones through which a product could change the build environment (Buck2 configuration, tools,
toolchains, prelude, a copy of the gate, any `.bzl` file, git metadata).
"""

import posixpath
import re
import tomllib
import unicodedata

from rigor_lib import globs, jsonio
from rigor_lib.errors import InternalError

# The one list of paths the gate refuses from a product. Globs as in globs.py.
ALWAYS_EXCLUDED = (
    "**/.buckconfig*",
    "**/.buckroot",
    "**/*.bzl",
    "tools/**",
    "third_party/**",   # vendored libraries come from gate//third_party, never from the product
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


# ---------------------------------------------------------------------------------------------
# Coverage: nothing that is code may be left out of the grading silently.
# ---------------------------------------------------------------------------------------------

# Extensions (lower case) that mean code or build input whatever the directory is called. Broad on
# purpose: an odd one only costs the product a layout line, a missing one hides code.
CODE_EXTENSIONS = frozenset((
    "c", "h", "inc", "def", "cc", "cpp", "cxx", "c++", "hpp", "hh", "hxx", "ipp", "tpp", "inl",
    "s", "asm", "i", "ii", "ld", "lds"))
# Build files by name (lower case), exactly or followed by ".<suffix>" (BUCK.v2, TARGETS.v2).
BUILD_FILE_NAMES = ("buck", "targets", "package")

UNGRADED_PATH = "ungraded-path"
EXCLUDED_CODE = "excluded-code"
IGNORED_CODE = "ignored-code"
STALE_INCLUDE = "stale-include"
CASE_COLLISION = "case-collision"

GITLINK_MODE = "160000"
_QUOTED = re.compile(r'"([^"\\\n]*)"' + "|" + r"'([^'\\\n]*)'")


def _lower(path_text):
    return unicodedata.normalize("NFC", path_text).casefold()


def _base(path_text):
    return _lower(path_text).rsplit("/", 1)[-1].rstrip(". ")


def is_build_file(path_text):
    base = _base(path_text)
    return any(base == name or base.startswith(name + ".") for name in BUILD_FILE_NAMES)


def is_code_name(path_text):
    """True if the file name alone says code: a build file, or a C/header-like extension."""
    base = _base(path_text)
    return is_build_file(path_text) or "." in base and base.rsplit(".", 1)[1] in CODE_EXTENSIONS


def is_gate_excluded(path_text):
    """True if an always-excluded glob covers the path, spelled as is or in any letter case."""
    spelled = (path_text, _lower(path_text))
    return any(globs.matches(glob, text) for glob in _ALWAYS for text in spelled)


def _is_gate_excluded_dir(path_text):
    return is_gate_excluded(path_text + "/x")


def named_files(buck_texts, known):
    """Paths in `known` that some BUCK names in a string literal (srcs, headers, data, ...).

    `buck_texts` is a list of (BUCK path, its text). Labels (':x', '//x:y') and escaping paths never
    name a file; every other literal is joined to the BUCK's directory and normalised.
    """
    named = set()
    for buck_path, text in buck_texts:
        directory = posixpath.dirname(buck_path)
        for double, single in _QUOTED.findall(text):
            value = double or single
            if value == "" or ":" in value or value.startswith("/"):
                continue
            joined = posixpath.normpath(posixpath.join(directory, value))
            if joined in known:
                named.add(joined)
    return named


def _stale_includes(config, paths_seen):
    found = []
    for pattern, glob in config.include:
        inert = any(globs.matches(always, pattern) for always in _ALWAYS)  # names only gate-excluded paths
        if not inert and not any(globs.matches(glob, path) for path in paths_seen):
            found.append((STALE_INCLUDE, pattern, "no file at the product head matches this include"))
    return found


def _case_collisions(paths_seen):
    groups = {}
    for path in paths_seen:
        groups.setdefault(_lower(path), []).append(path)
    return [(CASE_COLLISION, path, "differs only in letter case or Unicode form from another path")
            for group in groups.values() if len(group) > 1 for path in sorted(group)]


def _entry_finding(config, path, mode, named):
    """The (rule, path, reason) for one head entry, or None if it is covered."""
    if mode == GITLINK_MODE:
        if _is_gate_excluded_dir(path):
            return None
        return (UNGRADED_PATH, path, "a submodule holds code the gate cannot read")
    if not (is_code_name(path) or path in named):
        return None
    if is_gate_excluded(path):
        return (IGNORED_CODE, path, "code inside a path the gate always excludes")
    if any(globs.matches(glob, path) for _, glob in config.exclude):
        return (EXCLUDED_CODE, path, "product exclude covers a BUCK or C file")
    if not any(globs.matches(glob, path) for _, glob in config.include):
        return (UNGRADED_PATH, path, "code outside layout.include")
    return None


def coverage_findings(config, entries, buck_texts):
    """Every way the layout leaves product code out. Sorted tuples (rule, path, reason).

    `entries` is [(path text, git mode)] for the whole product head; `buck_texts` is
    [(BUCK path, text)] of the BUCK files the layout copies.
    """
    paths_seen = [path for path, _ in entries]
    named = named_files(buck_texts, set(paths_seen))
    found = _stale_includes(config, paths_seen) + _case_collisions(paths_seen)
    for path, mode in entries:
        item = _entry_finding(config, path, mode, named)
        if item is not None:
            found.append(item)
    return sorted(found)
