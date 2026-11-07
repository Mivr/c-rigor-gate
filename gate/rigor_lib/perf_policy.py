"""The perf targets of a grade and their classes (T090): the perf part of `products/<p>/policy.toml`, and the perf bundle.

A product cannot declare `c_perf` (the `buckfiles` gate allows no such macro): the gate generates the package
`gate-perf/BUCK` (`perf_package`) from gate-held definitions. A definition is a *target*: a driver and generator
(`ctest/perf.h` API), the module it exercises, the sizes and seed, and the complexity class it must keep.

    # in policy.toml (gate-owned, bound by the verdict's policy snapshot); `srcs` are paths in the gate repository,
    # relative to the directory of policy.toml (so the product cannot change the driver)
    [module."//x:y".perf.lookup]           # name [a-z][a-z0-9_]*; the target is //gate-perf:lookup_perf
    class = "O(1)"                         # O(1) | O(log n) | O(n) | O(n log n)
    srcs = ["perf/lookup.c"]               # generator + driver
    sizes = [2000, 8000]                   # 2 to 8 increasing sizes; the first and the last are judged
    seed = 3

The hidden perf bundle (`--perf DIR`, perf_bundle, T080) supplies targets of the same shape (`bundle_<id>`, class
`linear` = O(n), `nlogn` = O(n log n)). The `perf` gate judges them all; `c_mutants` of a module runs its targets for the
mutants that survive the tests (docs/mutate.md). Any defect is exit 2.
"""

import os
import re
import stat
from dataclasses import dataclass

from rigor_lib import grade_policy, paths
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL
from rigor_lib.perf_judge import CLASSES

PACKAGE = "gate-perf"
SUFFIX = "_perf"
BUNDLE_PREFIX = "bundle_"
BUNDLE_CLASSES = {"linear": "O(n)", "nlogn": "O(n log n)"}
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_KEYS = {"class", "srcs", "sizes", "seed"}
_SEED_LIMIT = 1 << 64


@dataclass(frozen=True)
class Target:
    name: str
    module: str
    cost_class: str
    sizes: tuple
    seed: int
    srcs: tuple            # paths (policy: relative to policy.toml; bundle: inside the bundle)
    files: tuple = ()      # ((path, bytes), ...) once loaded

    @property
    def binary(self):
        return "//%s:%s" % (PACKAGE, self.name)

    @property
    def label(self):
        return self.binary + SUFFIX


def _fail(where, why):
    raise InternalError("policy: %s: %s" % (where, why))


def _target(label, name, entry):
    where = "module %s perf %s" % (label, name)
    if not _NAME.fullmatch(name):
        _fail(where, "a perf target name matches [a-z][a-z0-9_]*")
    if not isinstance(entry, dict) or set(entry) != _KEYS:
        _fail(where, "needs exactly the keys %s" % ", ".join(sorted(_KEYS)))
    if entry["class"] not in CLASSES:
        _fail(where, "class must be one of %s" % ", ".join(CLASSES))
    srcs, sizes, seed = entry["srcs"], entry["sizes"], entry["seed"]
    if not isinstance(srcs, list) or not srcs or not all(isinstance(s, str) for s in srcs) or len(set(srcs)) != len(srcs):
        _fail(where, "srcs must be a non-empty list of distinct paths")
    for src in srcs:
        reason = paths.unsafe_path_reason(src)
        if reason is not None or not src.endswith(".c") or ":" in src or src.startswith("@"):
            _fail(where, "src %r must be a plain relative path ending in .c%s" % (src, "" if reason is None else " (%s)" % reason))
    ok = isinstance(sizes, list) and 2 <= len(sizes) <= 8 and all(type(n) is int and n >= 1 for n in sizes)
    if not ok or sorted(set(sizes)) != sizes:
        _fail(where, "sizes must be 2 to 8 increasing positive integers")
    if type(seed) is not int or not 0 <= seed < _SEED_LIMIT:
        _fail(where, "seed must be in [0, 2^64)")
    return Target(name, label, entry["class"], tuple(sizes), seed, tuple(srcs))


def parse_module(label, table):
    """[Target] of one module table (`perf` sub-tables), without reading any file. [] without `perf`."""
    perf = table.get("perf", {}) if isinstance(table, dict) else {}
    if not isinstance(perf, dict):
        _fail("module %s" % label, "perf must be a table of tables")
    return [_target(label, name, entry) for name, entry in sorted(perf.items())]


def _read(base, rel):
    """The bytes of `base/rel`: a regular file, no symlink in the path."""
    current = base
    parts = rel.split("/")
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            raise InternalError("perf source %s: %s" % (rel, exc)) from exc
        if stat.S_ISLNK(mode):
            raise InternalError("perf source %s: symlink" % rel)
        if index == len(parts) - 1 and not stat.S_ISREG(mode):
            raise InternalError("perf source %s: not a regular file" % rel)
    with open(current, "rb") as handle:
        return handle.read()


def from_policy(path):
    """The targets declared in the policy file, with their sources read from the policy's directory."""
    modules = grade_policy.load_document(path).get("module", {})
    if not isinstance(modules, dict):
        _fail("[module]", "must be a table of tables")
    base = os.path.dirname(os.path.abspath(path))
    found = []
    for label, table in modules.items():
        for target in parse_module(label, table):
            files = tuple((src, _read(base, src)) for src in target.srcs)
            found.append(Target(target.name, target.module, target.cost_class, target.sizes, target.seed, target.srcs, files))
    return found


def from_bundle(bundle):
    """The targets of the perf bundle (perf_bundle.Bundle), or []."""
    if bundle is None:
        return []
    data = {f.path: f.data for f in bundle.files}
    return [Target(BUNDLE_PREFIX + t.id.replace("-", "_"), t.module, BUNDLE_CLASSES[t.cost_class], t.sizes, t.seed,
                   t.srcs, tuple((src, data[src]) for src in t.srcs))
            for t in bundle.targets]


def load(path, bundle=None):
    """Every perf target of the grade, sorted by name; a name used twice is exit 2."""
    found = sorted(from_policy(path) + from_bundle(bundle), key=lambda t: t.name)
    names = [t.name for t in found]
    if len(set(names)) != len(names):
        raise InternalError("policy: perf target names must be unique: %s" % sorted({n for n in names if names.count(n) > 1}))
    for target in found:
        if not LABEL.fullmatch(target.label):
            raise InternalError("policy: odd perf target %s" % target.label)
    return found


def by_module(targets):
    """{module label: {perf target label: class}}."""
    result = {}
    for target in targets:
        result.setdefault(target.module, {})[target.label] = target.cost_class
    return result
