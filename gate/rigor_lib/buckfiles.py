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
# gate-owned allowlists `third_party/ALLOWED_LABELS` (any macro) and `third_party/ALLOWED_TEST_LABELS`
# (a `c_test` only), see facts_third_party. `//third_party...` is how the gate prints its own targets
# when it is the root cell, so that same-cell spelling is refused too.
DEP_LABEL = re.compile(r"(:[A-Za-z0-9_.+-]+|//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+)")
GATE_THIRD_PARTY = re.compile(r"//third_party[/:]")
TEST_MACRO = "c_test"
# Targets the `c_test` macro creates besides the test itself; none of them may be a dep of anything.
TEST_DERIVED = ("", "_facts", "_facts_san", "_results", "_coverage")

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


def _dep_problem(node, allowed, test_allowed, macro):
    """None, or the `why` of the finding for a `deps` value."""
    if not isinstance(node, ast.List):
        return "dep"
    problem = None
    for element in node.elts:
        label = element.value
        if label in allowed or (macro == TEST_MACRO and label in test_allowed):
            continue
        if label in test_allowed:
            problem = "test-only-dep"
        elif not DEP_LABEL.fullmatch(label) or GATE_THIRD_PARTY.match(label):
            return "dep"
    return problem


def load_findings(path, node):
    call = node.value
    ok = (len(call.args) >= 1 and not call.keywords and all(_is_string(a) for a in call.args)
          and call.args[0].value == LOAD_PATH
          and all(a.value in MACROS for a in call.args[1:]))
    if ok:
        return []
    return [finding("bad-load", path=path, line=node.lineno)]


def call_findings(path, node, allowed, test_allowed):
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
        elif keyword.arg == "deps":
            why = _dep_problem(keyword.value, allowed, test_allowed, call.func.id)
            if why is not None:
                found.append(finding("bad-argument", path=path, line=node.lineno, why=why))
    return found


def _keyword_strings(call, name):
    for keyword in call.keywords:
        if keyword.arg == name:
            if _is_string(keyword.value):
                return [keyword.value.value]
            if isinstance(keyword.value, ast.List) and all(_is_string(e) for e in keyword.value.elts):
                return [e.value for e in keyword.value.elts]
    return []


def test_target_findings(calls, tests):
    """A dep may not name a `c_test` or a target the macro derives from it (`_facts`, `_results`, ...):
    that would link a test, and what the test links (the TLS peer), into a non-test target. `:x` is
    resolved by directory; `//pkg:x` matches a test directory by its trailing path (the walked root
    need not be the cell root). Over-matching is a refusal, never a pass."""
    found = []
    for path, line, label in calls:
        if label.startswith("//"):
            package, _, name = label[2:].rpartition(":")
            here = None
        else:
            package, name, here = None, label[1:], os.path.dirname(path)
        for test_dir, test_name in tests:
            if name not in [test_name + suffix for suffix in TEST_DERIVED]:
                continue
            if here == test_dir if package is None else (
                    package == test_dir or (test_dir != "" and package.endswith("/" + test_dir))):
                found.append(finding("bad-argument", path=path, line=line, why="test-target"))
                break
    return found


def statement_findings(path, tree, allowed, test_allowed, tests=None, calls=None):
    found, loads = [], 0
    for node in tree.body:
        is_call = isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        if is_call and isinstance(node.value.func, ast.Name) and node.value.func.id == "load":
            loads += 1
            found.extend(load_findings(path, node))
            if loads > 1:
                found.append(finding("extra-load", path=path, line=node.lineno))
        elif is_call:
            found.extend(call_findings(path, node, allowed, test_allowed))
            if tests is not None and isinstance(node.value.func, ast.Name) and node.value.func.id in MACROS:
                directory = os.path.dirname(path)
                if node.value.func.id == TEST_MACRO:
                    tests.extend((directory, n) for n in _keyword_strings(node.value, "name"))
                calls.extend((path, node.lineno, d) for d in _keyword_strings(node.value, "deps")
                             if DEP_LABEL.fullmatch(d))
        else:
            found.append(finding("bad-statement", path=path, line=node.lineno,
                                 kind=type(node).__name__))
    return found


def build_file_findings(path, data, allowed, test_allowed, tests=None, calls=None):
    try:
        tree = ast.parse(data.decode("utf-8"), filename=path, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [finding("parse-error", path=path)]
    return statement_findings(path, tree, allowed, test_allowed, tests, calls)


def default_labels(file_name):
    return facts_third_party.load_allowed_labels(os.path.join(facts_third_party.DEFAULT_DIR, file_name))


def walk_findings(root, allowed=None, test_allowed=None):
    """`allowed`: exact cell-prefixed dep labels (default: the gate's own `third_party/ALLOWED_LABELS`);
    `test_allowed`: those only a `c_test` may name (default: `third_party/ALLOWED_TEST_LABELS`)."""
    allowed = default_labels(facts_third_party.ALLOWED_FILE) if allowed is None else allowed
    test_allowed = (default_labels(facts_third_party.TEST_ALLOWED_FILE) if test_allowed is None
                    else test_allowed)
    found, tests, calls = [], [], []
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
                found.extend(build_file_findings(shown, jsonio.read_bytes(full), allowed, test_allowed, tests, calls))
        for name in subdirs:
            if os.path.islink(os.path.join(directory, name)):
                found.append(finding("symlink", path=os.path.relpath(
                    os.path.join(directory, name), root).replace(os.sep, "/")))
    found.extend(test_target_findings(calls, tests))
    return found


def run(args):
    if not os.path.isdir(args.root):
        raise InternalError("not a directory: %s" % args.root)
    lists = [None if path is None else facts_third_party.load_allowed_labels(path)
             for path in (args.allowed_labels, args.allowed_test_labels)]
    return GateResult(GATE_ID, walk_findings(args.root, *lists), {})


def add_parser(subparsers):
    parser = subparsers.add_parser("buckfiles", allow_abbrev=False,
                                   help="product build files may only call the gate macros")
    parser.add_argument("--root", required=True)
    parser.add_argument("--allowed-labels", help="override third_party/ALLOWED_LABELS (tests)")
    parser.add_argument("--allowed-test-labels", help="override third_party/ALLOWED_TEST_LABELS (tests)")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
