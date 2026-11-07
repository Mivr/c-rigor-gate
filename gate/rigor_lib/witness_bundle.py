"""The witness bundle: gate-held implementation files that a module's tests are graded against (P002, Q1).

A bundle is a directory with exactly two entries:

    <bundle>/witness.toml
    <bundle>/files/<product path>        # e.g. files/annas/src/api.c

    product = "annas-c"                  # must equal product.toml's name
    [module."//annas:annas"]
    origin = "A012"                      # the task that wrote it (information)
    written_against = "<40-hex>"         # the test-author head it was calibrated on (information)

The bundle is gate-owned input: every defect (symlinks, special files, unsafe or non-UTF-8 names,
empty directories, unknown keys, wrong types) is an InternalError (exit 2), never a pass.
`load` reads the files once into memory; nothing later goes back to the directory. The library is pure
apart from `load`: `digest`, `check` and `overlay` work on the loaded `Bundle` and on path lists.
"""

import os
import re
import stat
import tomllib
from dataclasses import dataclass

from rigor_lib import globs, jsonio, paths
from rigor_lib.errors import InternalError

MANIFEST = "witness.toml"
FILES_DIR = "files"
LABEL = re.compile(r"//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+")
_SHA1 = re.compile(r"[0-9a-f]{40}")
_TOP_KEYS = {"product", "module"}
_MODULE_KEYS = {"origin", "written_against"}


@dataclass(frozen=True)
class ModuleEntry:
    label: str
    origin: str
    written_against: str


@dataclass(frozen=True)
class WitnessFile:
    path: str   # product-relative ("annas/src/api.c"), without the "files/" prefix
    data: bytes

    @property
    def sha256(self):
        return jsonio.sha256_hex(self.data)


@dataclass(frozen=True)
class Bundle:
    product: str
    modules: dict          # label -> ModuleEntry
    files: tuple           # WitnessFile, sorted by path
    manifest_sha256: str   # sha256 of witness.toml as read


def _read_regular(path):
    """Read a regular file without following a symlink at the last component."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise InternalError("witness bundle: cannot open %s: %s" % (path, exc)) from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise InternalError("witness bundle: not a regular file: %s" % path)
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
        raise InternalError("witness bundle: cannot stat %s: %s" % (path, exc)) from exc


def _entry_name(name, where):
    """A directory entry name as text; non-UTF-8 names are refused."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        raise InternalError("witness bundle: non-UTF-8 name in %s" % where) from None
    return name


def _list_dir(path):
    try:
        names = os.listdir(path)
    except OSError as exc:
        raise InternalError("witness bundle: cannot list %s: %s" % (path, exc)) from exc
    return sorted(_entry_name(name, path) for name in names)


def _walk_files(root):
    """Every regular file under `root` as (relative path, bytes). Symlinks, special files and empty
    directories are refused. Iterative, so a deep tree cannot exhaust the stack."""
    found = []
    pending = [""]
    while pending:
        rel = pending.pop()
        directory = os.path.join(root, rel) if rel else root
        names = _list_dir(directory)
        if not names:
            raise InternalError("witness bundle: empty directory %s/%s" % (FILES_DIR, rel))
        for name in names:
            child_rel = rel + "/" + name if rel else name
            reason = paths.unsafe_path_reason(child_rel)
            if reason is not None:
                raise InternalError("witness bundle: bad path %r: %s" % (child_rel, reason))
            mode = _lstat(os.path.join(root, child_rel)).st_mode
            if stat.S_ISDIR(mode):
                pending.append(child_rel)
            elif stat.S_ISREG(mode):
                found.append((child_rel, _read_regular(os.path.join(root, child_rel))))
            elif stat.S_ISLNK(mode):
                raise InternalError("witness bundle: symlink %s/%s" % (FILES_DIR, child_rel))
            else:
                raise InternalError("witness bundle: special file %s/%s" % (FILES_DIR, child_rel))
    return sorted(found)


def _string(value, what):
    if not isinstance(value, str) or value == "":
        raise InternalError("witness.toml: %s must be a non-empty string" % what)
    return value


def _module_entry(label, table):
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        raise InternalError("witness.toml: bad module label %r" % (label,))
    if not isinstance(table, dict):
        raise InternalError("witness.toml: module %s must be a table" % label)
    if set(table) != _MODULE_KEYS:
        raise InternalError("witness.toml: module %s must have exactly the keys %s"
                            % (label, ", ".join(sorted(_MODULE_KEYS))))
    origin = _string(table["origin"], "module %s origin" % label)
    against = _string(table["written_against"], "module %s written_against" % label)
    if not _SHA1.fullmatch(against):
        raise InternalError("witness.toml: module %s written_against must be 40 lowercase hex" % label)
    return ModuleEntry(label, origin, against)


def parse_manifest(data):
    """(product, {label: ModuleEntry}) from the bytes of witness.toml."""
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InternalError("witness.toml is not valid UTF-8 TOML: %s" % exc) from exc
    if set(document) != _TOP_KEYS:
        raise InternalError("witness.toml must have exactly the keys product and [module]")
    product = _string(document["product"], "product")
    modules = document["module"]
    if not isinstance(modules, dict) or not modules:
        raise InternalError("witness.toml: [module] must list at least one module")
    return product, {label: _module_entry(label, table) for label, table in modules.items()}


def load(directory):
    """Read and validate a bundle directory. Any defect is an InternalError."""
    if not stat.S_ISDIR(_lstat(directory).st_mode):
        raise InternalError("witness bundle is not a directory (or is a symlink): %s" % directory)
    entries = _list_dir(directory)
    if entries != sorted([MANIFEST, FILES_DIR]):
        raise InternalError("witness bundle must hold exactly %s and %s/, found %s"
                            % (MANIFEST, FILES_DIR, entries))
    manifest = _read_regular(os.path.join(directory, MANIFEST))
    product, modules = parse_manifest(manifest)
    files_root = os.path.join(directory, FILES_DIR)
    if not stat.S_ISDIR(_lstat(files_root).st_mode):
        raise InternalError("witness bundle: %s is not a directory" % FILES_DIR)
    files = tuple(WitnessFile(rel, data) for rel, data in _walk_files(files_root))
    return Bundle(product, modules, files, jsonio.sha256_hex(manifest))


def digest_entries(bundle):
    """The digested list: witness.toml first, then every file by its bundle path (`files/...`), sorted."""
    return [[MANIFEST, bundle.manifest_sha256]] + [[FILES_DIR + "/" + f.path, f.sha256] for f in bundle.files]


def entries_digest(entries):
    """sha256 of the canonical JSON of a `[[path, sha256], ...]` list (shared with the perf bundle)."""
    return jsonio.sha256_hex(jsonio.canonical_dumps(entries))


def digest(bundle):
    """`witness_sha256`: independent of where the bundle was stored."""
    return entries_digest(digest_entries(bundle))


def compile_impl_map(impl_map):
    """{label: [compiled globs]}; a label that is not //pkg:name or globs that are not a non-empty list of
    valid patterns are an InternalError."""
    if not isinstance(impl_map, dict):
        raise InternalError("impl map must be a dict")
    compiled = {}
    for label, patterns in impl_map.items():
        if not isinstance(label, str) or not LABEL.fullmatch(label):
            raise InternalError("bad module label in impl map: %r" % (label,))
        if not isinstance(patterns, (list, tuple)) or not patterns or \
                not all(isinstance(p, str) for p in patterns):
            raise InternalError("impl paths of %s must be a non-empty list of globs" % (label,))
        compiled[label] = [globs.compile_glob(p) for p in patterns]
    return compiled


def _owners(compiled, path):
    return sorted(label for label, patterns in compiled.items() if any(globs.matches(g, path) for g in patterns))


def check(bundle, product_name, impl_map):
    """Each file lies in the impl paths of exactly one module of `impl_map`, and that module is listed in
    the bundle; every listed module has impl paths and at least one file. Returns {label: [paths]}."""
    if bundle.product != product_name:
        raise InternalError("witness bundle is for product %r, not %r" % (bundle.product, product_name))
    compiled = compile_impl_map(impl_map)
    unknown = sorted(set(bundle.modules) - set(compiled))
    if unknown:
        raise InternalError("witness bundle lists modules without impl paths: %s" % ", ".join(unknown))
    owned = {label: [] for label in bundle.modules}
    for item in bundle.files:
        owners = _owners(compiled, item.path)
        if len(owners) != 1:
            raise InternalError("witness file %s matches the impl paths of %d modules (%s), not exactly one"
                                % (item.path, len(owners), ", ".join(owners)))
        if owners[0] not in owned:
            raise InternalError("witness file %s belongs to %s, which the bundle does not list"
                                % (item.path, owners[0]))
        owned[owners[0]].append(item.path)
    empty = sorted(label for label, files in owned.items() if not files)
    if empty:
        raise InternalError("witness bundle lists modules with no files: %s" % ", ".join(empty))
    return owned


def _check_paths(head_paths):
    if not isinstance(head_paths, (list, tuple)):
        raise InternalError("head paths must be a list")
    for path in head_paths:
        reason = paths.unsafe_path_reason(path) if isinstance(path, str) else "not a string"
        if reason is not None:
            raise InternalError("bad head path %r: %s" % (path, reason))
    if len(set(head_paths)) != len(head_paths):
        raise InternalError("duplicate head paths")


def _check_layout(final_paths):
    """No path may be both a file and a directory of another path."""
    directories = set()
    for path in final_paths:
        parts = path.split("/")
        directories.update("/".join(parts[:n]) for n in range(1, len(parts)))
    clash = sorted(set(final_paths) & directories)
    if clash:
        raise InternalError("witness overlay makes %s both a file and a directory" % clash[0])


def overlay(head_paths, bundle, modules):
    """The witness tree's product files, as a pure function over path lists.

    `modules` maps each module to overlay (W) to its impl globs. For every one of them that the bundle
    lists, the head paths matching its globs are left out and the bundle files matching them are added.
    Modules the bundle does not list keep their head files (the gate reports `witness-missing`).
    Returns (kept head paths in input order, witness files sorted by path).
    """
    _check_paths(head_paths)
    compiled = compile_impl_map(modules)
    replaced = [label for label in sorted(compiled) if label in bundle.modules]
    patterns = [g for label in replaced for g in compiled[label]]
    kept = [p for p in head_paths if not any(globs.matches(g, p) for g in patterns)]
    written = []
    for label in replaced:
        own = [f for f in bundle.files if any(globs.matches(g, f.path) for g in compiled[label])]
        if not own:
            raise InternalError("witness bundle has no files for %s" % label)
        written.extend(own)
    unique = {f.path: f for f in written}
    files = [unique[path] for path in sorted(unique)]
    _check_layout(kept + [f.path for f in files])
    return kept, files
