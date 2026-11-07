"""The perf targets of a grade and their classes (T090): the perf part of `products/<p>/policy.toml`, and the perf bundle.

A product cannot declare `c_perf` (the `buckfiles` gate allows no such macro): the gate generates the package
`gate-perf/BUCK` (`perf_package`) from gate-held definitions. A definition is a *target*: a driver and generator
(`ctest/perf.h` API), the module it exercises, the sizes and seed, and the complexity class it must keep.

    # in policy.toml (gate-owned). The sources are in the policy itself, so the verdict's policy snapshot binds them
    [module."//x:y".perf.lookup]           # name [a-z][a-z0-9_]*; the target is //gate-perf:lookup_perf
    class = "O(1)"                         # O(1) | O(log n) | O(n) | O(n log n)
    sizes = [2000, 8000]                   # 2 to 8 increasing sizes; the first and the last are judged
    seed = 3
    [module."//x:y".perf.lookup.srcs]      # generator + driver: file name -> text (a literal multi-line string)
    "lookup.c" = '''
    ...
    '''

The hidden perf bundle (`--perf DIR`, perf_bundle, T080) supplies targets of the same shape (`bundle_<id>`, class
`linear` = O(n), `nlogn` = O(n log n)). The `perf` gate judges them all; `c_mutants` of a module runs its targets for the
mutants that survive the tests (docs/mutate.md). Any defect is exit 2.
"""

import re
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
MAX_SOURCE_BYTES = 1 << 20
_SEED_LIMIT = 1 << 64


@dataclass(frozen=True)
class Target:
    name: str
    module: str
    cost_class: str
    sizes: tuple
    seed: int
    srcs: tuple            # source paths, sorted
    files: tuple = ()      # ((path, bytes), ...) in the same order

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
    if not isinstance(srcs, dict) or not srcs:
        _fail(where, "srcs must be a table of file name = text")
    for src, text in srcs.items():
        reason = paths.unsafe_path_reason(src)
        if reason is not None or not src.endswith(".c") or ":" in src or src.startswith("@"):
            _fail(where, "src %r must be a plain relative path ending in .c%s" % (src, "" if reason is None else " (%s)" % reason))
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
            _fail(where, "src %r must be non-empty text of at most %d bytes" % (src, MAX_SOURCE_BYTES))
    ok = isinstance(sizes, list) and 2 <= len(sizes) <= 8 and all(type(n) is int and n >= 1 for n in sizes)
    if not ok or sorted(set(sizes)) != sizes:
        _fail(where, "sizes must be 2 to 8 increasing positive integers")
    if type(seed) is not int or not 0 <= seed < _SEED_LIMIT:
        _fail(where, "seed must be in [0, 2^64)")
    names = tuple(sorted(srcs))
    return Target(name, label, entry["class"], tuple(sizes), seed, names, tuple((n, srcs[n].encode("utf-8")) for n in names))


def parse_module(label, table):
    """[Target] of one module table (`perf` sub-tables), without reading any file. [] without `perf`."""
    perf = table.get("perf", {}) if isinstance(table, dict) else {}
    if not isinstance(perf, dict):
        _fail("module %s" % label, "perf must be a table of tables")
    return [_target(label, name, entry) for name, entry in sorted(perf.items())]


def from_policy(path):
    """The targets declared in the policy file."""
    modules = grade_policy.load_document(path).get("module", {})
    if not isinstance(modules, dict):
        _fail("[module]", "must be a table of tables")
    return [target for label, table in modules.items() for target in parse_module(label, table)]


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
