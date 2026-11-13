"""The static model gate `decoupling` judges: the targets of a product tree and what their own files include.

Built from the tree alone, a list of file paths and a function that reads one, so a grade (the assembled tree) and
the baseline tool (the blobs of a commit) get the same model. Each `BUCK` is parsed, never run, in the shape the
`buckfiles` gate enforces: top-level calls of the gate macros with literal strings, string lists and the
package-local `glob([...])`. Anything else is exit 2 here (in a grade, `buckfiles` has already failed on it).
"""

import ast
import posixpath
import re
from dataclasses import dataclass

from rigor_lib import buckfiles, decoupling_scan
from rigor_lib.errors import InternalError

LIBRARY_KINDS = ("c_library", "c_catalog", "c_embed")
JUDGED_KINDS = ("c_library", "c_binary", "c_test", "c_fuzz", "c_android_so")   # the kinds whose dependency lists are judged
GENERATED_KINDS = ("c_catalog", "c_embed")                     # their header is `<package>/<name>.h`, made by the build
PRIVATE_DIR = "src/"                                           # headers under it are not public (the gate's glob form)


@dataclass(frozen=True)
class Target:
    label: str
    kind: str
    srcs: tuple            # repository paths
    headers: tuple
    deps: tuple            # labels; `:x` already spelled `//pkg:x`
    exported_deps: tuple

    @property
    def package(self):
        return self.label[2:].rpartition(":")[0]

    @property
    def every_dep(self):
        return self.deps + self.exported_deps

    @property
    def provided(self):
        """The header paths a dependent may include from this target."""
        if self.kind in GENERATED_KINDS:
            return (posixpath.join(self.package, self.label.rpartition(":")[2] + ".h"),)
        return self.headers

    @property
    def public_headers(self):
        prefix = posixpath.join(self.package, PRIVATE_DIR)
        return tuple(h for h in self.headers if not h.startswith(prefix))


class Model:
    """`targets`: label -> Target. `read(path)` gives the text of a file of the tree."""

    def __init__(self, targets, paths, read):
        self.targets = targets
        self.paths = frozenset(paths)
        self._read = read
        self._texts = {}
        self._closures = {}
        self.owners = {}
        for label in sorted(targets):
            for header in targets[label].provided:
                self.owners.setdefault(header, []).append(label)

    def text(self, path):
        if path not in self._texts:
            self._texts[path] = self._read(path).decode("utf-8", "replace") if path in self.paths else ""
        return self._texts[path]

    def resolve(self, includer, name):
        """The repository path an `#include` operand names: next to the includer first, then from the root."""
        for candidate in (posixpath.normpath(posixpath.join(posixpath.dirname(includer), name)),
                          posixpath.normpath(name)):
            if candidate in self.owners or candidate in self.paths:
                return candidate
        return None

    def included(self, files):
        """The product targets whose headers the `files` include directly, as a set of labels."""
        found = set()
        for path in files:
            for name in decoupling_scan.includes(self.text(path)):
                found.update(self.owners.get(self.resolve(path, name), ()))
        return found

    def closure(self, label):
        """Every label `label` reaches through `deps` and `exported_deps`, itself excluded: what it links."""
        if label in self._closures:
            return self._closures[label]
        seen, stack = set(), [label]
        while stack:
            for dep in self.targets[stack.pop()].every_dep:
                if dep not in seen:
                    seen.add(dep)
                    if dep in self.targets:
                        stack.append(dep)
        seen.discard(label)
        self._closures[label] = frozenset(seen)
        return self._closures[label]


def _fail(path, why):
    raise InternalError("%s: %s" % (path, why))


def _strings(path, node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.List) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    _fail(path, "line %d: not a string or a list of strings" % node.lineno)


def _glob_match(pattern, name):
    return re.fullmatch("[^/]*".join(re.escape(part) for part in pattern.split("*")), name)


def _files(path, node, package, package_files):
    """The repository paths a `srcs`/`headers` value names: literals, `glob([...])`, or the two joined by `+`."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _files(path, node.left, package, package_files) + _files(path, node.right, package, package_files)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "glob" and len(node.args) == 1:
        patterns = _strings(path, node.args[0])
        names = sorted(n for n in package_files if any(_glob_match(p, n) for p in patterns))
    else:
        names = _strings(path, node)
    return [posixpath.join(package, name) for name in names]


def _label(package, text):
    return "//%s%s" % (package, text) if text.startswith(":") else text


def _target(path, call, package, package_files):
    kind = call.func.id
    values = {keyword.arg: keyword.value for keyword in call.keywords}
    if call.args or None in values or "name" not in values:
        _fail(path, "line %d: a macro call takes keyword arguments and a name" % call.lineno)
    name = _strings(path, values["name"])[0]

    def labels(key):
        return tuple(_label(package, d) for d in _strings(path, values[key])) if key in values else ()

    def files(key):
        if kind in GENERATED_KINDS or key not in values:
            return ()
        return tuple(_files(path, values[key], package, package_files))
    deps = (labels("runtime") if kind == buckfiles.CATALOG_MACRO else ()) + labels("deps")
    return Target("//%s:%s" % (package, name), kind, files("srcs"), files("headers"), deps, labels("exported_deps"))


def _calls(path, data):
    try:
        tree = ast.parse(data.decode("utf-8"), filename=path, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise InternalError("%s: not a build file the gate can read" % path) from exc
    for node in tree.body:
        call = node.value if isinstance(node, ast.Expr) else None
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            _fail(path, "line %d: not a macro call" % node.lineno)
        if call.func.id in buckfiles.MACROS:
            yield call
        elif call.func.id != "load":
            _fail(path, "line %d: not a gate macro" % node.lineno)


def _package_files(package, paths, packages):
    """The files of `package` by their package-relative name, without those of a package below it."""
    prefix = package + "/" if package else ""
    below = tuple(p + "/" for p in packages if p != package and p.startswith(prefix))
    return [p[len(prefix):] for p in paths if p.startswith(prefix) and not p.startswith(below)]


def load(paths, read):
    """`paths`: the files of the tree (repository-relative, `/`-separated); `read(path)` -> bytes."""
    paths = sorted(paths)
    build_files = [p for p in paths if posixpath.basename(p) == buckfiles.BUILD_FILE]
    packages = [posixpath.dirname(p) for p in build_files]
    targets = {}
    for path, package in zip(build_files, packages):
        package_files = _package_files(package, paths, packages)
        for call in _calls(path, read(path)):
            target = _target(path, call, package, package_files)
            if target.label in targets:
                _fail(path, "second target %s" % target.label)
            targets[target.label] = target
    return Model(targets, paths, read)
