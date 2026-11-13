"""Reading the files `c_structure` produces (rules/structure.bzl, structure_scan.py).

They come out of a build action but are still input: the reader accepts exactly the documented shape and
nothing else (exit 2 otherwise), so a malformed or padded file cannot pass. Facts only; `structure` decides.
"""

import os
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL

SCHEMA = 1
KINDS = ("c_library", "c_binary", "c_test", "c_fuzz", "c_android_so")
EXEMPT_KINDS = ("c_test", "c_fuzz")   # present, but not graded
FUNCTION_KEYS = ("name", "key", "static", "file", "line", "end_line", "body_lines", "split", "macro",
                 "params", "nesting", "cyclomatic", "statements", "calls", "indirect", "refs")
# Type facts (T063). Optional so that facts made before them still read; their absence means "untyped": the
# decision then falls back to the rule that needs no types (structure.py).
FUNCTION_TYPE_KEYS = ("type", "conversions")
VENDOR_CALL_KEYS = ("lib", "passes", "opaque")
CONVERSION_KINDS = ("cast", "union", "copy", "vararg")


@dataclass(frozen=True)
class Func:
    name: str
    key: str
    file: str
    line: int
    end_line: int
    body_lines: object   # int, or None when the body is split over files
    split: bool
    macro: bool
    params: int
    nesting: int
    cyclomatic: int
    statements: int
    calls: tuple         # of (to, fp_args)
    indirect: tuple      # of (file, line, canonical type of the pointee function, or None)
    refs: tuple          # of (to, file, line, type of the referenced declaration or None): the address is taken
    type: object = None  # canonical function type of the definition, or None (unknown or absent)
    conversions: object = None   # tuple of Conversion, or None when the facts carry none
    vendor: tuple = ()   # of (to, lib, passes, opaque, line): the calls into gate-owned vendored libraries (T106)


@dataclass(frozen=True)
class Conversion:
    """A place where a function pointer may change type. `types` are the canonical function types involved;
    None = the scanner could not tell."""
    file: str
    line: int
    kind: str
    types: object


@dataclass(frozen=True)
class FileFact:
    path: str
    lines: int
    bytes: int
    longest_line: int


@dataclass(frozen=True)
class Unit:
    src: str
    files: tuple
    functions: tuple
    refs: tuple
    conversions: object = None   # tuple of Conversion made outside every function, or None when absent


@dataclass(frozen=True)
class Structure:
    label: str
    kind: str
    deps: tuple
    srcs: tuple
    units: tuple


def _fail(path, why):
    raise InternalError("%s: %s" % (path, why))


def _exact(path, obj, keys, what):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        _fail(path, "%s must be an object with exactly the keys %s" % (what, sorted(keys)))
    return obj


def _int(path, value, what):
    if type(value) is not int or value < 0:
        _fail(path, "%s must be a non-negative integer" % what)
    return value


def _text(path, value, what):
    if not isinstance(value, str) or not value:
        _fail(path, "%s must be a non-empty string" % what)
    return value


def _bool(path, value, what):
    if type(value) is not bool:
        _fail(path, "%s must be a boolean" % what)
    return value


def _list(path, value, what):
    if not isinstance(value, list):
        _fail(path, "%s must be a list" % what)
    return value


def _optional(path, obj, required, optional, what):
    if not isinstance(obj, dict) or not set(required) <= set(obj) <= set(required) | set(optional):
        _fail(path, "%s must be an object with the keys %s and maybe %s" % (what, sorted(required), sorted(optional)))
    return obj


def _type(path, value, what):
    """A canonical function type, or null for unknown (a key that is absent is unknown as well)."""
    if value is not None and (not isinstance(value, str) or "(" not in value or not value.endswith(")")):
        _fail(path, "%s must be a canonical function type `RET ( PARAMS )` or null" % what)
    return value


def _sites(path, entries, what):
    found = []
    for entry in _list(path, entries, what):
        _optional(path, entry, ("file", "line"), ("type",), what)
        found.append((_text(path, entry["file"], what), _int(path, entry["line"], what),
                      _type(path, entry.get("type"), what + " type")))
    return tuple(found)


def _refs(path, entries, what):
    found = []
    for entry in _list(path, entries, what):
        _optional(path, entry, ("to", "file", "line"), ("type",), what)
        found.append((_text(path, entry["to"], what), _text(path, entry["file"], what),
                      _int(path, entry["line"], what), _type(path, entry.get("type"), what + " type")))
    return tuple(found)


def _conversions(path, entries):
    if entries is None:
        return None
    found = []
    for entry in _list(path, entries, "conversions"):
        _exact(path, entry, ("file", "line", "kind", "types"), "conversion")
        if entry["kind"] not in CONVERSION_KINDS:
            _fail(path, "bad conversion kind %r" % (entry["kind"],))
        types = entry["types"]
        if types is not None:
            types = tuple(_type(path, t, "conversion type") or _fail(path, "a conversion type is null")
                          for t in _list(path, types, "conversion types"))
        found.append(Conversion(_text(path, entry["file"], "conversion file"), _int(path, entry["line"], "line"),
                                entry["kind"], types))
    return tuple(found)


def _calls(path, entries):
    """-> (calls, vendor calls). The keys `lib`, `passes` and `opaque` (T106) come all together or not at all."""
    found, vendor = [], []
    for entry in _list(path, entries, "calls"):
        _optional(path, entry, ("to", "fp_args", "line"), VENDOR_CALL_KEYS, "call")
        target = _text(path, entry["to"], "call target")
        found.append((target, _bool(path, entry["fp_args"], "fp_args")))
        line = _int(path, entry["line"], "call line")
        extra = set(entry) & set(VENDOR_CALL_KEYS)
        if extra and extra != set(VENDOR_CALL_KEYS):
            _fail(path, "a call lists %s: lib, passes and opaque come together" % sorted(extra))
        if extra:
            passes = tuple(_text(path, p, "passed function") for p in _list(path, entry["passes"], "passes"))
            vendor.append((target, _text(path, entry["lib"], "lib"), passes, _bool(path, entry["opaque"], "opaque"), line))
    return tuple(found), tuple(vendor)


def parse_function(path, entry):
    _optional(path, entry, FUNCTION_KEYS, FUNCTION_TYPE_KEYS, "function")
    _bool(path, entry["static"], "static")
    split = _bool(path, entry["split"], "split")
    body = entry["body_lines"]
    if split != (body is None) or (not split and _int(path, body, "body_lines") < 1):
        _fail(path, "body_lines must be null exactly when the body is split")
    calls, vendor = _calls(path, entry["calls"])
    return Func(
        name=_text(path, entry["name"], "function name"), key=_text(path, entry["key"], "function key"),
        file=_text(path, entry["file"], "function file"), line=_int(path, entry["line"], "line"),
        end_line=_int(path, entry["end_line"], "end_line"), body_lines=body, split=split,
        macro=_bool(path, entry["macro"], "macro"), params=_int(path, entry["params"], "params"),
        nesting=_int(path, entry["nesting"], "nesting"), cyclomatic=_int(path, entry["cyclomatic"], "cyclomatic"),
        statements=_int(path, entry["statements"], "statements"), calls=calls,
        indirect=_sites(path, entry["indirect"], "indirect"), refs=_refs(path, entry["refs"], "refs"),
        type=_type(path, entry.get("type"), "function type"), conversions=_conversions(path, entry.get("conversions")), vendor=vendor)


def parse_file(path, entry):
    _exact(path, entry, ("path", "lines", "bytes", "longest_line"), "file")
    return FileFact(_text(path, entry["path"], "file path"), _int(path, entry["lines"], "lines"),
                    _int(path, entry["bytes"], "bytes"), _int(path, entry["longest_line"], "longest_line"))


def parse_unit(path, unit):
    _optional(path, unit, ("src", "files", "functions", "refs"), ("conversions",), "unit")
    files = tuple(parse_file(path, f) for f in _list(path, unit["files"], "files"))
    if len({f.path for f in files}) != len(files):
        _fail(path, "a file listed twice in a unit")
    src = _text(path, unit["src"], "unit src")
    if src not in {f.path for f in files}:
        _fail(path, "unit %s does not list its own source among its files" % src)
    return Unit(src, files, tuple(parse_function(path, f) for f in _list(path, unit["functions"], "functions")),
                _refs(path, unit["refs"], "refs"), _conversions(path, unit.get("conversions")))


def parse_structure(path, data):
    try:
        document = jsonio.strict_loads(data)
    except ValueError as exc:
        raise InternalError("%s: not valid JSON: %s" % (path, exc)) from exc
    _exact(path, document, ("schema", "label", "kind", "deps", "srcs", "units"), "structure file")
    if type(document["schema"]) is not int or document["schema"] != SCHEMA:
        _fail(path, "unsupported schema")
    label = document["label"]
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        _fail(path, "bad label %r" % (label,))
    if document["kind"] not in KINDS:
        _fail(path, "bad kind %r" % (document["kind"],))
    deps = _list(path, document["deps"], "deps")
    if not all(isinstance(d, str) and LABEL.fullmatch(d) for d in deps) or len(set(deps)) != len(deps):
        _fail(path, "deps must be distinct labels")
    srcs = _list(path, document["srcs"], "srcs")
    units = tuple(parse_unit(path, u) for u in _list(path, document["units"], "units"))
    if not units or sorted(srcs) != sorted(u.src for u in units) or len(set(srcs)) != len(srcs):
        _fail(path, "srcs and units disagree (a source without a unit, or the reverse)")
    return Structure(label, document["kind"], tuple(sorted(deps)), tuple(sorted(srcs)), units)


def load_structure_dir(directory):
    """label -> Structure for every `*.json` in `directory`. Anything else, an empty directory, or two
    files for one label is exit 2."""
    if not os.path.isdir(directory):
        raise InternalError("structure facts path is not a directory: %s" % directory)
    result = {}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if not name.endswith(".json") or not os.path.isfile(full) or os.path.islink(full):
            raise InternalError("%s: not a structure file (only regular *.json files belong here)" % full)
        parsed = parse_structure(full, jsonio.read_bytes(full))
        if parsed.label in result:
            raise InternalError("%s: second structure file for %s" % (full, parsed.label))
        result[parsed.label] = parsed
    if not result:
        raise InternalError("no structure facts in %s" % directory)
    return result
