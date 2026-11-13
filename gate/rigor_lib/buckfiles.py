"""`rigor buckfiles`: a product's build files may only declare targets through the gate macros.

Each `BUCK` is parsed (never run) with Python's `ast`; the Starlark subset used is a Python
subset. Allowed: one `load("@gate//rules:c.bzl", ...)` naming only the gate macros, and top-level
calls to those macros with keyword arguments whose values are string literals or lists of string
literals. T102: `srcs` and `headers` of `c_library`, `c_binary` and `c_test` may also be `glob([...])`
(package-local `src/*.c`, `src/*.h`, `src/<name>.c|.h` patterns only) or one string list joined to one such glob by a
single `+`. Everything else is a finding, and so is any other file that Buck2 would read as build
configuration (`.bzl`, `BUCK.v2` which takes priority over `BUCK`, `PACKAGE`, `.buckconfig`, ...).
"""

import ast
import os
import re

from rigor_lib import facts_rt, facts_third_party, jsonio
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "buckfiles"

LOAD_PATH = "@gate//rules:c.bzl"
MACROS = ("c_library", "c_binary", "c_test", "c_fuzz", "c_sim", "c_catalog", "c_embed")
KEYWORDS = ("name", "srcs", "headers", "deps", "visibility")
# Keywords of one macro only (T095): `system_libs` names sysroot libraries a library links; the macro checks the names.
# T135: `c_fuzz` takes `corpus` (the form `srcs` has on a `c_fuzz`: string literals, never a glob; the macro checks the paths)
# and `runs` (an int literal).
# T2G1: `c_sim` takes the integer budgets `seeds`, `run_ms` and `shards` (int literals; srcs are string literals, never a glob).
MACRO_KEYWORDS = {"c_library": ("system_libs", "exported_deps"), "c_fuzz": ("corpus", "runs"), "c_test": ("threads",),
                  "c_sim": ("seeds", "run_ms", "shards")}
# T105: `c_catalog` has keywords of its own and no `srcs`/`headers`. `pots`, `langs`, `source_lang` and `symbol`
# are strings or lists of strings, `po` is a dict of string -> list of strings (the only dict a macro takes), `runtime`
# is one string that is checked as a dep, and `deps` is the usual dep list (the libraries the runtime header includes from).
CATALOG_MACRO = "c_catalog"
CATALOG_KEYWORDS = ("name", "visibility", "deps", "pots", "po", "langs", "source_lang", "symbol", "runtime", "names")
# T112: `c_embed` has keywords of its own and no `srcs`/`headers`/`deps`: `src` and `symbol` are strings, `max_bytes` is an
# int literal (the only int a macro takes; no bool, no expression) and `nul` a True/False literal (the only bool), `visibility` the usual list.
EMBED_MACRO = "c_embed"
EMBED_KEYWORDS = ("name", "visibility", "src", "symbol", "max_bytes", "nul")
BUILD_FILE = "BUCK"
# Same-cell labels only: no cell prefix, so no raw rules of another cell and nothing from the prelude.
# (The macros add `gate//ctest:ctest` themselves.) The one exception is an exact label of the
# gate-owned allowlists `third_party/ALLOWED_LABELS` (any macro) and `third_party/ALLOWED_TEST_LABELS`
# (a `c_test` only), see facts_third_party. `//third_party...` is how the gate prints its own targets
# when it is the root cell, so that same-cell spelling is refused too.
DEP_LABEL = re.compile(r"(:[A-Za-z0-9_.+-]+|//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+)")
GATE_THIRD_PARTY = re.compile(r"//third_party[/:]")
TEST_MACRO = "c_test"
# T128: `gate//rt:require` (facts_rt) is the one more gate label, for a library, a binary or a test only.
REQUIRE_MACROS = ("c_library", "c_binary", TEST_MACRO)
# Targets the `c_test` macro creates besides the test itself; none of them may be a dep of anything.
TEST_DERIVED = ("", "_facts", "_facts_san", "_facts_msan", "_facts_tsan", "_results", "_coverage")

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


def _is_string_list(node):
    return isinstance(node, ast.List) and all(_is_string(e) for e in node.elts)


def _is_int(node):
    return isinstance(node, ast.Constant) and type(node.value) is int


def _is_bool(node):
    return isinstance(node, ast.Constant) and type(node.value) is bool


def _is_string_dict(node):
    """`{"msgid": "WORDS", ...}`: literal string keys and values."""
    return (isinstance(node, ast.Dict) and all(k is not None and _is_string(k) for k in node.keys)
            and all(_is_string(v) for v in node.values))


def _is_po_dict(node):
    """`{"bg": ["a.po", ...], ...}`: literal string keys (no `**`), literal lists of strings as values."""
    return (isinstance(node, ast.Dict) and all(k is not None and _is_string(k) for k in node.keys)
            and all(_is_string_list(v) for v in node.values))


# T102: the one package-local source glob form, only as `srcs` or `headers` of these macros. The pattern is
# `src/<stem>.c|.h` where the stem is a plain name or has exactly one `*` (`src/*.c`, `src/scene_*.c`, `src/a.c`).
GLOB_MACROS = ("c_library", "c_binary", "c_test")
GLOB_KEYWORDS = ("srcs", "headers")
GLOB_PATTERN = re.compile(r"src/(?=[^*]*\*?[^*]*\.[ch]\Z)[A-Za-z0-9_+*-]+\.[ch]")


def _is_glob(node):
    """`glob([<patterns>])`: a literal non-empty list of allowed patterns, no other argument."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "glob"
            and not node.keywords and len(node.args) == 1 and isinstance(node.args[0], ast.List)
            and len(node.args[0].elts) >= 1
            and all(_is_string(e) and GLOB_PATTERN.fullmatch(e.value) for e in node.args[0].elts))


def _is_glob_value(node):
    """`glob([...])`, or one literal string list and one glob joined by a single `+`, in either order."""
    if _is_glob(node):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        pair = (node.left, node.right)
        return (any(isinstance(n, ast.List) and n.elts and all(_is_string(e) for e in n.elts) for n in pair)
                and any(_is_glob(n) for n in pair))
    return False


def _dep_problem(node, allowed, test_allowed, macro):
    """None, or the `why` of the finding for a `deps` value."""
    if not isinstance(node, ast.List):
        return "dep"
    problem = None
    for element in node.elts:
        label = element.value
        if label == facts_rt.LABEL and macro in REQUIRE_MACROS:
            continue
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


def _known_keywords(macro):
    if macro == CATALOG_MACRO:
        return CATALOG_KEYWORDS
    if macro == EMBED_MACRO:
        return EMBED_KEYWORDS
    return KEYWORDS + MACRO_KEYWORDS.get(macro, ())


def _value_ok(macro, keyword):
    """Is the literal form of this keyword's value one the macro takes?"""
    arg, node = keyword.arg, keyword.value
    if macro == CATALOG_MACRO and arg == "po":
        return _is_po_dict(node)
    if macro == CATALOG_MACRO and arg == "names":
        return _is_string_dict(node)
    if macro == EMBED_MACRO and arg == "max_bytes":
        return _is_int(node)
    if macro == "c_fuzz" and arg == "runs":
        return _is_int(node)
    if macro == "c_sim" and arg in ("seeds", "run_ms", "shards"):
        return _is_int(node)
    if (macro == EMBED_MACRO and arg == "nul") or (macro == TEST_MACRO and arg == "threads"):
        return _is_bool(node)
    if macro == EMBED_MACRO and arg in ("src", "symbol"):
        return _is_string(node)
    return _is_value(node) or (macro in GLOB_MACROS and arg in GLOB_KEYWORDS and _is_glob_value(node))


def call_findings(path, node, allowed, test_allowed):
    call = node.value
    if not isinstance(call.func, ast.Name) or call.func.id not in MACROS:
        return [finding("bad-call", path=path, line=node.lineno)]
    found = []
    macro = call.func.id
    known = _known_keywords(macro)
    if call.args:
        found.append(finding("bad-argument", path=path, line=node.lineno, why="positional"))
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in known:
            found.append(finding("bad-argument", path=path, line=node.lineno, why="keyword"))
        elif not _value_ok(macro, keyword):
            found.append(finding("bad-argument", path=path, line=node.lineno, why="value"))
        elif keyword.arg == "runtime" and not _is_string(keyword.value):
            found.append(finding("bad-argument", path=path, line=node.lineno, why="value"))
        elif keyword.arg in ("deps", "exported_deps", "runtime"):
            value = keyword.value if keyword.arg != "runtime" else ast.List(elts=[keyword.value])
            why = _dep_problem(value, allowed, test_allowed, macro)
            if why is not None:
                found.append(finding("bad-argument", path=path, line=node.lineno, why=why))
    return found


def _dep_strings(call):
    """The labels a macro call depends on: `deps`, and the `runtime` of a `c_catalog`."""
    return _keyword_strings(call, "deps") + _keyword_strings(call, "exported_deps") + (_keyword_strings(call, "runtime") if call.func.id == CATALOG_MACRO else [])


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
                calls.extend((path, node.lineno, d) for d in _dep_strings(node.value)
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
