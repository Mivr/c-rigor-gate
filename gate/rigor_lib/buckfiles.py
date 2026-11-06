"""`rigor buckfiles`: a product's build files may only declare targets through the gate macros.

Each `BUCK` is parsed (never run) with Python's `ast`; the Starlark subset used is a Python
subset. Allowed: one `load("@gate//rules:c.bzl", ...)` naming only the four macros, and top-level
calls to those macros with keyword arguments whose values are string literals or lists of string
literals. Everything else is a finding, and so is any other file that Buck2 would read as build
configuration (`.bzl`, `BUCK.v2` which takes priority over `BUCK`, `PACKAGE`, `.buckconfig`, ...).
"""

import ast
import os
import re

from rigor_lib import facts_third_party, jsonio
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "buckfiles"

LOAD_PATH = "@gate//rules:c.bzl"
MACROS = ("c_library", "c_binary", "c_test", "c_fuzz")
KEYWORDS = ("name", "srcs", "headers", "deps", "visibility")
BUILD_FILE = "BUCK"
# Same-cell labels only: no cell prefix, so no raw rules of another cell and nothing from the prelude.
# (The macros add `gate//ctest:ctest` themselves.) The one exception is an exact label of the
# gate-owned allowlist `third_party/ALLOWED_LABELS` (see facts_third_party).
DEP_LABEL = re.compile(r"(:[A-Za-z0-9_.+-]+|//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+)")

# Names Buck2 reads as build configuration, besides the exact `BUCK`.
FORBIDDEN_NAMES = ("TARGETS", "PACKAGE", ".buckconfig", ".buckconfig.local", ".buckroot",
                   ".buckjavaversion", ".buckignore")
FORBIDDEN_PREFIXES = ("BUCK.", "TARGETS.", "PACKAGE.", ".buckconfig")
FORBIDDEN_SUFFIXES = (".bzl", ".bxl")


def forbidden_name(name):
    if name != BUILD_FILE and name.lower() == BUILD_FILE.lower():
        return True   # `buck`, `Buck`: the same file on a case-insensitive file system
    return (name in FORBIDDEN_NAMES or name.startswith(FORBIDDEN_PREFIXES)
            or name.endswith(FORBIDDEN_SUFFIXES))


def _is_string(node):
    return isinstance(node, ast.Constant) and type(node.value) is str


def _is_value(node):
    return _is_string(node) or (isinstance(node, ast.List) and all(_is_string(e) for e in node.elts))


def _is_dep_list(node, allowed):
    return isinstance(node, ast.List) and all(DEP_LABEL.fullmatch(e.value) or e.value in allowed
                                              for e in node.elts)


def load_findings(path, node):
    call = node.value
    ok = (len(call.args) >= 1 and not call.keywords and all(_is_string(a) for a in call.args)
          and call.args[0].value == LOAD_PATH
          and all(a.value in MACROS for a in call.args[1:]))
    if ok:
        return []
    return [finding("bad-load", path=path, line=node.lineno)]


def call_findings(path, node, allowed):
    call = node.value
    if not isinstance(call.func, ast.Name) or call.func.id not in MACROS:
        return [finding("bad-call", path=path, line=node.lineno)]
    found = []
    if call.args:
        found.append(finding("bad-argument", path=path, line=node.lineno, why="positional"))
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in KEYWORDS:
            found.append(finding("bad-argument", path=path, line=node.lineno, why="keyword"))
        elif not _is_value(keyword.value):
            found.append(finding("bad-argument", path=path, line=node.lineno, why="value"))
        elif keyword.arg == "deps" and not _is_dep_list(keyword.value, allowed):
            found.append(finding("bad-argument", path=path, line=node.lineno, why="dep"))
    return found


def statement_findings(path, tree, allowed):
    found, loads = [], 0
    for node in tree.body:
        is_call = isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        if is_call and isinstance(node.value.func, ast.Name) and node.value.func.id == "load":
            loads += 1
            found.extend(load_findings(path, node))
            if loads > 1:
                found.append(finding("extra-load", path=path, line=node.lineno))
        elif is_call:
            found.extend(call_findings(path, node, allowed))
        else:
            found.append(finding("bad-statement", path=path, line=node.lineno,
                                 kind=type(node).__name__))
    return found


def build_file_findings(path, data, allowed):
    try:
        tree = ast.parse(data.decode("utf-8"), filename=path, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [finding("parse-error", path=path)]
    return statement_findings(path, tree, allowed)


def default_allowed_labels():
    return facts_third_party.load_allowed_labels(
        os.path.join(facts_third_party.DEFAULT_DIR, facts_third_party.ALLOWED_FILE))


def walk_findings(root, allowed=None):
    """`allowed`: exact cell-prefixed dep labels (default: the gate's own `third_party/ALLOWED_LABELS`)."""
    allowed = default_allowed_labels() if allowed is None else allowed
    found = []
    for directory, subdirs, files in os.walk(root, followlinks=False):
        subdirs.sort()
        for name in sorted(files):
            full = os.path.join(directory, name)
            shown = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                found.append(finding("symlink", path=shown))
            elif forbidden_name(name):
                found.append(finding("forbidden-file", path=shown))
            elif name == BUILD_FILE:
                found.extend(build_file_findings(shown, jsonio.read_bytes(full), allowed))
        for name in subdirs:
            if os.path.islink(os.path.join(directory, name)):
                found.append(finding("symlink", path=os.path.relpath(
                    os.path.join(directory, name), root).replace(os.sep, "/")))
    return found


def run(args):
    if not os.path.isdir(args.root):
        raise InternalError("not a directory: %s" % args.root)
    allowed = None if args.allowed_labels is None else facts_third_party.load_allowed_labels(args.allowed_labels)
    return GateResult(GATE_ID, walk_findings(args.root, allowed), {})


def add_parser(subparsers):
    parser = subparsers.add_parser("buckfiles", allow_abbrev=False,
                                   help="product build files may only call the gate macros")
    parser.add_argument("--root", required=True)
    parser.add_argument("--allowed-labels", help="override third_party/ALLOWED_LABELS (tests)")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
