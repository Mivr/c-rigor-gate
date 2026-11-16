"""The labels the platforms, selects and rules name in `toolchains/` and `rules/` exist (no Buck2 needed).

Why (#341 review): `toolchains//:wasm32_release` first named `prelude//cpu/constraints:wasm32`, which the pinned bundled
prelude does not have. Because `toolchains//:cxx` selected on it, the analysis of every target failed, native ones
included, and nothing short of a Buck2 build noticed. These checks catch that class of mistake in the unit tests:

  * every `prelude//cpu/constraints:*` and `prelude//os/constraints:*` label is one of the constraint values of the
    prelude bundled in the pinned Buck2 (`tools/buck2.version`); a new pin must re-list them (`buck2 uquery
    'prelude//cpu/constraints:' 'prelude//os/constraints:'`) and update PINNED_BUCK2 below;
  * every `toolchains//:<name>` label in `rules/*.bzl` and `toolchains/*.bzl`, and every `":<name>"` string in
    `toolchains/BUCK`, is a target that `toolchains/BUCK` defines (literal names and the names its list
    comprehensions build from literal lists).
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLCHAINS_BUCK = ROOT / "toolchains" / "BUCK"

# The constraint values of the prelude bundled in the pinned Buck2, as listed on the build host for #341.
PINNED_BUCK2 = "400f5fde930a62ff6f64513fb5a7e88fa1847afa85758cadd9484dc93446fa94"
PRELUDE_CONSTRAINTS = {
    "cpu": {"arm32", "arm64", "x86_32", "x86_64"},
    "os": {"android", "freebsd", "iphoneos", "linux", "macos", "none", "wasi", "watchos", "windows"},
}
PRELUDE_LABEL = re.compile(r"prelude//(cpu|os)/constraints:([A-Za-z0-9_.+-]+)")
GATE_LABEL = re.compile(r"toolchains//:([A-Za-z0-9_.+-]+)")
LOCAL_LABEL = re.compile(r":([A-Za-z0-9_.+-]+)")


def sources():
    """{path: [(line, string literal)]} of toolchains/BUCK and the .bzl files of toolchains/ and rules/. Comments and
    docstrings are prose, not labels, and are left out (Starlark parses as Python here)."""
    files = [TOOLCHAINS_BUCK] + sorted((ROOT / "toolchains").glob("*.bzl")) + sorted((ROOT / "rules").glob("*.bzl"))
    found = {}
    for path in files:
        tree = ast.parse(path.read_text(), filename=str(path))
        prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        found[path] = [(n.lineno, n.value) for n in ast.walk(tree)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in prose]
    return found


def _value(node, env):
    """A name expression of toolchains/BUCK: a string literal, a comprehension variable, or `+` of those; else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _value(node.left, env), _value(node.right, env)
        return left + right if left is not None and right is not None else None
    return None


def _names_in(node, env):
    names = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            for keyword in call.keywords:
                if keyword.arg == "name":
                    value = _value(keyword.value, env)
                    if value is not None:
                        names.add(value)
    return names


def defined_names(text):
    """The target names toolchains/BUCK defines: `name = "x"`, and `name = "a" + v` / `name = v` inside
    `[... for v in ["p", "q"]]` (one generator over a literal list of strings, as the file uses)."""
    tree = ast.parse(text)
    names = _names_in(tree, {})
    for comp in ast.walk(tree):
        if not isinstance(comp, ast.ListComp) or len(comp.generators) != 1:
            continue
        gen = comp.generators[0]
        if not isinstance(gen.target, ast.Name) or not isinstance(gen.iter, (ast.List, ast.BinOp)):
            continue
        items = _literal_list(gen.iter)
        for item in items:
            names |= _names_in(comp.elt, {gen.target.id: item})
    return names


def _literal_list(node):
    """A literal list of strings, or two of them joined by `+` (`["a"] + [x for ...]` is not one)."""
    if isinstance(node, ast.List) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_list(node.left) + _literal_list(node.right)
    return []


class PreludeConstraintTest(unittest.TestCase):
    def test_the_list_is_for_the_pinned_buck2(self):
        pinned = (ROOT / "tools" / "buck2.version").read_text().strip()
        self.assertEqual(pinned, PINNED_BUCK2, "a new Buck2 pin: re-list the prelude constraint values (see the docstring)")

    def test_every_prelude_constraint_label_exists_in_the_pinned_prelude(self):
        seen = 0
        for path, strings in sources().items():
            for line, text in strings:
                for match in PRELUDE_LABEL.finditer(text):
                    seen += 1
                    family, name = match.groups()
                    self.assertIn(name, PRELUDE_CONSTRAINTS[family], "%s:%d names %s, which the pinned prelude does not define"
                                  % (path.relative_to(ROOT), line, match.group(0)))
        self.assertGreater(seen, 0)

    def test_the_check_catches_the_original_mistake(self):
        match = PRELUDE_LABEL.search("prelude//cpu/constraints:wasm32")
        self.assertNotIn(match.group(2), PRELUDE_CONSTRAINTS[match.group(1)])


class GateLabelTest(unittest.TestCase):
    def setUp(self):
        self.defined = defined_names(TOOLCHAINS_BUCK.read_text())

    def test_the_names_of_comprehensions_are_expanded(self):
        for name in ("linux_release", "linux_san", "release", "never", "android", "llvm-ar", "ndk-llvm-readelf",
                     "llvm_ref", "jdk_verified", "wasm32", "wasm32_release", "wasm_cpu", "cxx", "cxx_wasm"):
            self.assertIn(name, self.defined)

    def test_every_toolchains_label_is_defined(self):
        seen = 0
        for path, strings in sources().items():
            for line, text in strings:
                for match in GATE_LABEL.finditer(text):
                    seen += 1
                    self.assertIn(match.group(1), self.defined,
                                  "%s:%d names %s" % (path.relative_to(ROOT), line, match.group(0)))
        self.assertGreater(seen, 0)

    def test_every_local_label_in_toolchains_buck_is_defined(self):
        tree = ast.parse(TOOLCHAINS_BUCK.read_text())
        loads = {id(a) for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id == "load" for a in c.args}   # `load(":fetch.bzl", ...)` names files, not targets
        seen = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in loads
                    and LOCAL_LABEL.fullmatch(node.value)):
                seen += 1
                self.assertIn(node.value[1:], self.defined, "toolchains/BUCK names %s (line %d)" % (node.value, node.lineno))
        self.assertGreater(seen, 0)

    def test_an_undefined_label_is_caught(self):
        self.assertNotIn("wasm64", self.defined)


if __name__ == "__main__":
    unittest.main()
