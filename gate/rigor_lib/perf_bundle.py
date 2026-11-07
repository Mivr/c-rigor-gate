"""The perf bundle: gate-held generators and drivers that an implementation's performance is judged against (R011, B13).

A bundle is a directory with `perf.toml` and exactly the source files that it names (docs/perf.md):

    version = 1
    product = "annas-c"
    [[target]]
    id = "json-many-keys"        # unique, [a-z0-9-]
    module = "//json:json"       # in the product policy, level L3 or above
    srcs = ["gen/json_keys.c"]   # generator + driver (ctest/perf.h), paths inside the bundle
    sizes = [1000, 4000]         # exactly two, second = k * first, k >= 2
    seed = 1
    class = "linear"             # linear | nlogn

It is gate-owned input: every defect (symlinks, special files, empty directories, unsafe or non-UTF-8 names,
unknown keys, wrong types, files the manifest does not name, named files that are missing) is an InternalError
(exit 2), never a pass. `load` reads the files once into memory; the rest of the library is pure. The digest
uses the witness bundle's scheme (`witness_bundle.entries_digest`) over `perf.toml` and the named sources.
"""

import os
import re
import stat
import tomllib
from dataclasses import dataclass

from rigor_lib import paths, witness_bundle
from rigor_lib.errors import InternalError
from rigor_lib.jsonio import sha256_hex

MANIFEST = "perf.toml"
VERSION = 1
CLASSES = ("linear", "nlogn")
MIN_LEVEL_INDEX = 2  # L3 and above
_ID = re.compile(r"[a-z0-9-]+")
_TOP_KEYS = {"version", "product", "target"}
_TARGET_KEYS = {"id", "module", "srcs", "sizes", "seed", "class"}
_SEED_LIMIT = 1 << 64


@dataclass(frozen=True)
class Target:
    id: str
    module: str
    srcs: tuple
    sizes: tuple
    seed: int
    cost_class: str


@dataclass(frozen=True)
class PerfFile:
    path: str
    data: bytes

    @property
    def sha256(self):
        return sha256_hex(self.data)


@dataclass(frozen=True)
class Bundle:
    product: str
    targets: tuple         # Target, in manifest order
    files: tuple           # PerfFile, sorted by path (not perf.toml)
    manifest_sha256: str   # sha256 of perf.toml as read


def _fail(message):
    raise InternalError("perf bundle: " + message)


def _read_regular(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        _fail("cannot open %s: %s" % (path, exc))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            _fail("not a regular file: %s" % path)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError as exc:
        _fail("cannot stat %s: %s" % (path, exc))


def _list_dir(path):
    try:
        names = os.listdir(path)
    except OSError as exc:
        _fail("cannot list %s: %s" % (path, exc))
    for name in names:
        try:
            name.encode("utf-8")
        except UnicodeEncodeError:
            _fail("non-UTF-8 name in %s" % path)
    return sorted(names)


def _walk(root):
    """{relative path: bytes} of every regular file under `root`; symlinks, special files and empty
    directories are refused. Iterative."""
    found = {}
    pending = [""]
    while pending:
        rel = pending.pop()
        names = _list_dir(os.path.join(root, rel) if rel else root)
        if rel and not names:
            _fail("empty directory %s" % rel)
        for name in names:
            child = rel + "/" + name if rel else name
            reason = paths.unsafe_path_reason(child)
            if reason is not None:
                _fail("bad path %r: %s" % (child, reason))
            mode = _lstat(os.path.join(root, child)).st_mode
            if stat.S_ISDIR(mode):
                pending.append(child)
            elif stat.S_ISREG(mode):
                found[child] = _read_regular(os.path.join(root, child))
            elif stat.S_ISLNK(mode):
                _fail("symlink %s" % child)
            else:
                _fail("special file %s" % child)
    return found


def _int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InternalError("perf.toml: %s must be an integer" % what)
    return value


def _string(value, what):
    if not isinstance(value, str) or value == "":
        raise InternalError("perf.toml: %s must be a non-empty string" % what)
    return value


def _srcs(value, where):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise InternalError("perf.toml: %s srcs must be a non-empty list of strings" % where)
    if len(set(value)) != len(value):
        raise InternalError("perf.toml: %s srcs has duplicates" % where)
    for item in value:
        reason = paths.unsafe_path_reason(item)
        if reason is not None:
            raise InternalError("perf.toml: %s src %r: %s" % (where, item, reason))
        if item == MANIFEST:
            raise InternalError("perf.toml: %s src may not be %s" % (where, MANIFEST))
    return tuple(value)


def _sizes(value, where):
    if not isinstance(value, list) or len(value) != 2:
        raise InternalError("perf.toml: %s sizes must be exactly two integers" % where)
    first, second = (_int(item, where + " sizes") for item in value)
    if first < 1 or second % first != 0 or second // first < 2:
        raise InternalError("perf.toml: %s sizes must be [n, k*n] with n >= 1 and k >= 2, got %s" % (where, value))
    return first, second


def _target(table, index):
    where = "target %d" % (index + 1)
    if not isinstance(table, dict):
        raise InternalError("perf.toml: %s must be a table" % where)
    if set(table) != _TARGET_KEYS:
        raise InternalError("perf.toml: %s must have exactly the keys %s" % (where, ", ".join(sorted(_TARGET_KEYS))))
    ident = _string(table["id"], where + " id")
    if not _ID.fullmatch(ident):
        raise InternalError("perf.toml: %s id %r must match [a-z0-9-]+" % (where, ident))
    where = "target %s" % ident
    module = _string(table["module"], where + " module")
    if not witness_bundle.LABEL.fullmatch(module):
        raise InternalError("perf.toml: %s module %r is not //pkg:name" % (where, module))
    seed = _int(table["seed"], where + " seed")
    if not 0 <= seed < _SEED_LIMIT:
        raise InternalError("perf.toml: %s seed must be in [0, 2^64)" % where)
    cost_class = table["class"]
    if cost_class not in CLASSES:
        raise InternalError("perf.toml: %s class must be one of %s" % (where, ", ".join(CLASSES)))
    return Target(ident, module, _srcs(table["srcs"], where), _sizes(table["sizes"], where), seed, cost_class)


def parse_manifest(data):
    """(product, [Target]) from the bytes of perf.toml."""
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InternalError("perf.toml is not valid UTF-8 TOML: %s" % exc) from exc
    if set(document) != _TOP_KEYS:
        raise InternalError("perf.toml must have exactly the keys version, product and [[target]]")
    if _int(document["version"], "version") != VERSION:
        raise InternalError("perf.toml: version must be %d" % VERSION)
    product = _string(document["product"], "product")
    tables = document["target"]
    if not isinstance(tables, list) or not tables:
        raise InternalError("perf.toml: [[target]] must list at least one target")
    targets = tuple(_target(table, index) for index, table in enumerate(tables))
    ids = [t.id for t in targets]
    if len(set(ids)) != len(ids):
        raise InternalError("perf.toml: duplicate target ids")
    return product, targets


def load(directory):
    """Read and validate a bundle directory. Any defect is an InternalError."""
    if not stat.S_ISDIR(_lstat(directory).st_mode):
        _fail("not a directory (or is a symlink): %s" % directory)
    found = _walk(directory)
    if MANIFEST not in found:
        _fail("missing %s" % MANIFEST)
    manifest = found.pop(MANIFEST)
    product, targets = parse_manifest(manifest)
    named = {src for target in targets for src in target.srcs}
    missing = sorted(named - set(found))
    if missing:
        _fail("%s names missing files: %s" % (MANIFEST, ", ".join(missing)))
    extra = sorted(set(found) - named)
    if extra:
        _fail("files that %s does not name: %s" % (MANIFEST, ", ".join(extra)))
    files = tuple(PerfFile(path, found[path]) for path in sorted(found))
    return Bundle(product, targets, files, sha256_hex(manifest))


def digest_entries(bundle):
    """perf.toml first, then every named file by its bundle path, sorted."""
    return [[MANIFEST, bundle.manifest_sha256]] + [[f.path, f.sha256] for f in bundle.files]


def digest(bundle):
    """`perf_sha256`: independent of where the bundle was stored."""
    return witness_bundle.entries_digest(digest_entries(bundle))


def check(bundle, product_name, levels):
    """The bundle is for this product and every target's module is in the policy at level L3 or above."""
    if bundle.product != product_name:
        raise InternalError("perf bundle is for product %r, not %r" % (bundle.product, product_name))
    order = ("L1", "L2", "L3", "L4", "L5")
    for target in bundle.targets:
        level = levels.get(target.module)
        if level is None:
            raise InternalError("perf target %s: module %s is not in the product policy" % (target.id, target.module))
        if order.index(level) < MIN_LEVEL_INDEX:
            raise InternalError("perf target %s: module %s is level %s, below L3" % (target.id, target.module, level))
