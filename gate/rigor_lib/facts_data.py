"""Reading the fact files produced by `<name>_facts` (see rules/facts.bzl and cscan.py).

Facts come out of a build action, but they are still input: the reader accepts exactly the
documented shape and nothing else (exit 2 otherwise), so a malformed or padded file cannot pass.
"""

import os
import re
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.errors import InternalError

SCHEMA = 1
LABEL = re.compile(r"[A-Za-z0-9_.-]*//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+-]+")
SYMBOL = re.compile(r"[A-Za-z0-9_.$@]+")
SECTIONS = ("ro", "data", "bss", "tls")     # the section classes of a data object
WRITABLE = ("data", "bss", "tls")
SYSTEM_LIBS = ("pthread", "X11")     # the sysroot libraries a c_library may name (T095); rules/c.bzl `_SYSTEM_LIBS` is the same list
KINDS = ("c_library", "c_binary", "c_test", "c_fuzz", "c_sim", "c_third_party")


@dataclass(frozen=True)
class Unit:
    name: str
    defined: frozenset
    weak: frozenset
    undefined: frozenset
    pragmas: tuple      # of (file, line, text)
    attributes: tuple   # of (name, file, line)
    identifiers: tuple  # of (name, file, line)
    line_directives: tuple  # of (name, file, line): a user `#line` that renames the file
    mutable: frozenset = frozenset()  # defined external objects in a writable data/bss section (T033)
    data: tuple = ()    # of (name, size, section, local): every defined data object, `static` ones too (T089)
    gate_identifiers: frozenset = frozenset()   # of (name, file, line): the identifier facts whose file is the gate's (T131)
    guards: tuple = ()  # of (file, line, function): every call of `rigor_require` in product code (T131)


@dataclass(frozen=True)
class Facts:
    label: str
    kind: str
    deps: tuple
    units: tuple
    system_libs: frozenset = frozenset()    # the `system_libs` of the c_library (T095); empty for every other kind


def _fail(path, why):
    raise InternalError("%s: %s" % (path, why))


def _exact(path, obj, keys, what):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        _fail(path, "%s must be an object with exactly the keys %s" % (what, sorted(keys)))
    return obj


def _strings(path, value, what, pattern=SYMBOL):
    if not isinstance(value, list) or not all(isinstance(v, str) and pattern.fullmatch(v) for v in value):
        _fail(path, "%s must be a list of valid names" % what)
    if len(set(value)) != len(value):
        _fail(path, "%s has duplicates" % what)
    return frozenset(value)


def _int(path, value, what):
    if type(value) is not int or value < 0:
        _fail(path, "%s must be a non-negative integer" % what)
    return value


def _text(path, value, what):
    if not isinstance(value, str):
        _fail(path, "%s must be a string" % what)
    return value


def _located(path, entries, key, what):
    """Entries are {key, file, line}; returns tuples (key, file, line)."""
    if not isinstance(entries, list):
        _fail(path, "%s must be a list" % what)
    found = []
    for entry in entries:
        _exact(path, entry, (key, "file", "line"), what)
        found.append((_text(path, entry[key], what), _text(path, entry["file"], what),
                      _int(path, entry["line"], what)))
    return tuple(found)


def _pragmas(path, entries):
    if not isinstance(entries, list):
        _fail(path, "pragmas must be a list")
    found = []
    for entry in entries:
        _exact(path, entry, ("text", "file", "line"), "pragma")
        found.append((_text(path, entry["file"], "pragma"), _int(path, entry["line"], "pragma"),
                      _text(path, entry["text"], "pragma")))
    return tuple(found)


def _data(path, entries):
    """`data` (T089): [{name, size, section, local}], one per defined data object of the unit."""
    if not isinstance(entries, list):
        _fail(path, "data must be a list")
    found = []
    for entry in entries:
        _exact(path, entry, ("name", "size", "section", "local"), "data object")
        name = entry["name"]
        if not isinstance(name, str) or not SYMBOL.fullmatch(name):
            _fail(path, "data object name must be a valid name")
        if entry["section"] not in SECTIONS:
            _fail(path, "data object section must be one of %s" % (SECTIONS,))
        if type(entry["local"]) is not bool:
            _fail(path, "data object local must be a boolean")
        found.append((name, _int(path, entry["size"], "data object size"), entry["section"], entry["local"]))
    return tuple(found)


def _identifiers(path, entries):
    """`identifiers`: {name, file, line} and, since T131, `gate` (the file is the gate's own). Older facts lack
    the key: nothing is the gate's then. Returns (all facts, the gate's)."""
    if not isinstance(entries, list):
        _fail(path, "identifier must be a list")
    found, gate = [], set()
    for entry in entries:
        keys = ("name", "file", "line") + (("gate",) if isinstance(entry, dict) and "gate" in entry else ())
        _exact(path, entry, keys, "identifier")
        fact = (_text(path, entry["name"], "identifier"), _text(path, entry["file"], "identifier"),
                _int(path, entry["line"], "identifier"))
        found.append(fact)
        if "gate" in entry:
            if type(entry["gate"]) is not bool:
                _fail(path, "identifier gate must be a boolean")
            if entry["gate"]:
                gate.add(fact)
    return tuple(found), frozenset(gate)


def _guards(path, entries):
    """`guards` (T131): [{file, line, function}], one per call site of `rigor_require` in product code."""
    if not isinstance(entries, list):
        _fail(path, "guards must be a list")
    found = []
    for entry in entries:
        _exact(path, entry, ("file", "line", "function"), "guard")
        found.append((_text(path, entry["file"], "guard"), _int(path, entry["line"], "guard"),
                      _text(path, entry["function"], "guard")))
    return tuple(found)


UNIT_KEYS = ("name", "defined", "weak", "undefined", "pragmas", "attributes", "identifiers", "line_directives")


def parse_unit(path, unit):
    # `mutable` (T033) is written by every product scan; only the gate's own third-party facts lack it.
    # `data` (T089) is written next to it; the gate-owned third-party facts may omit `mutable`.
    keys = UNIT_KEYS + tuple(k for k in ("mutable", "data", "guards") if isinstance(unit, dict) and k in unit)
    _exact(path, unit, keys, "unit")
    defined = _strings(path, unit["defined"], "defined")
    weak = _strings(path, unit["weak"], "weak")
    if not weak <= defined:
        _fail(path, "weak symbols must be defined symbols")
    mutable = _strings(path, unit["mutable"], "mutable") if "mutable" in unit else frozenset()
    if not mutable <= defined:
        _fail(path, "mutable symbols must be defined symbols")
    data = _data(path, unit["data"]) if "data" in unit else ()
    identifiers, gate = _identifiers(path, unit["identifiers"])
    return Unit(
        name=_text(path, unit["name"], "unit name"),
        defined=defined, weak=weak,
        undefined=_strings(path, unit["undefined"], "undefined"),
        pragmas=_pragmas(path, unit["pragmas"]),
        attributes=_located(path, unit["attributes"], "name", "attribute"),
        identifiers=identifiers,
        line_directives=_located(path, unit["line_directives"], "name", "line directive"),
        mutable=mutable,
        data=data,
        gate_identifiers=gate,
        guards=_guards(path, unit["guards"]) if "guards" in unit else (),
    )


def parse_facts(path, data):
    try:
        document = jsonio.strict_loads(data)
    except ValueError as exc:
        raise InternalError("%s: not valid JSON: %s" % (path, exc)) from exc
    keys = ("schema", "label", "kind", "deps", "units") + (("system_libs",) if "system_libs" in document else ())
    _exact(path, document, keys, "facts file")
    if document["schema"] != SCHEMA or type(document["schema"]) is not int:
        _fail(path, "unsupported schema")
    label = document["label"]
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        _fail(path, "bad label %r" % (label,))
    if document["kind"] not in KINDS:
        _fail(path, "bad kind %r" % (document["kind"],))
    deps = _strings(path, document["deps"], "deps", LABEL)
    if not isinstance(document["units"], list):
        _fail(path, "units must be a list")
    if document["kind"] != "c_third_party" and not all(isinstance(u, dict) and "mutable" in u and "data" in u
                                                        for u in document["units"]):
        _fail(path, "every unit of a product target needs `mutable` and `data`")
    # `system_libs` is written by every product scan; only the gate's own third-party facts lack it.
    system_libs = _strings(path, document["system_libs"], "system_libs") if "system_libs" in document else frozenset()
    if document["kind"] != "c_third_party" and "system_libs" not in document:
        _fail(path, "every product target needs `system_libs`")
    if not system_libs <= set(SYSTEM_LIBS):
        _fail(path, "system_libs may only name %s" % (list(SYSTEM_LIBS),))
    if system_libs and document["kind"] != "c_library":
        _fail(path, "only a c_library has system_libs")
    units = tuple(parse_unit(path, unit) for unit in document["units"])
    if len({unit.name for unit in units}) != len(units):
        _fail(path, "duplicate unit names")
    return Facts(label, document["kind"], tuple(sorted(deps)), units, system_libs)


def load_facts_dir(directory):
    """label -> Facts for every `*.json` in `directory` (not recursive). Anything else in it,
    an empty directory, or two files for one label is exit 2."""
    if not os.path.isdir(directory):
        raise InternalError("facts path is not a directory: %s" % directory)
    result = {}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if not name.endswith(".json") or not os.path.isfile(full) or os.path.islink(full):
            raise InternalError("%s: not a facts file (only regular *.json files belong here)" % full)
        facts = parse_facts(full, jsonio.read_bytes(full))
        if facts.label in result:
            raise InternalError("%s: second facts file for %s" % (full, facts.label))
        result[facts.label] = facts
    if not result:
        raise InternalError("no facts in %s" % directory)
    return result


def load_symbol_list(path):
    """One symbol per line (the libc export list). Empty or malformed is exit 2."""
    lines = jsonio.read_bytes(path).decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or not all(SYMBOL.fullmatch(line) for line in lines):
        raise InternalError("%s: expected one symbol per line, at least one" % path)
    return frozenset(lines)
