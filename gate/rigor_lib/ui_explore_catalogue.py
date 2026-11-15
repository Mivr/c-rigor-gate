"""The event catalogue and abstraction key of `rigor ui-explore` (U05, P004 4.3 items 2 and 3): a strict TOML loader.

One sealed, versioned file per app (`products/<product>/ui/<app>.events.toml`; the toy's is
`selftest/ui_product/toy.events.toml`). Schema `ui-events/1`, documented in docs/ui-explore.md. Every class table is
required (an empty `events` list is allowed); an unknown key, a missing key, a wrong type, a duplicate id or a value out
of range is an `InternalError` (exit 2), never a default.
"""

import re
import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_probe import ADVANCE_MAX_MS, SEMANTIC_FIELDS, TEXT_MAX

SCHEMA = "ui-events/1"
CLASSES = ("u1", "u2", "u3", "u4", "u5", "e1", "t1")
BOUNDARIES = ("empty", "one-digit", "max-minus-1", "max", "max-plus-1", "valid-visitor", "valid-staff", "unknown",
              "expired", "non-digit")
T1_KINDS = ("fire-due", "before-due", "advance")
FACTS = ("deadline", "env-inputs")
KEY_FIELDS = SEMANTIC_FIELDS[1:]          # `key` (the node identity) is always part of the projection
RESERVED_IDS = ("open", "domain-at", "settle")
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_HEX = re.compile(r"(?:[0-9a-f]{2}){0,%d}" % TEXT_MAX)
_DIGITS = re.compile(r"[0-9]{0,%d}" % TEXT_MAX)
_TOP = ("schema", "product", "app", "version", "key") + CLASSES


@dataclass(frozen=True)
class Event:
    """One catalogue event. `cls` is its class; `spec` the class-specific fields as a sorted tuple of (name, value)."""
    id: str
    cls: str
    spec: tuple

    def get(self, name):
        return dict(self.spec)[name]


@dataclass(frozen=True)
class Key:
    fields: tuple       # semantic fields in the projection, in SEMANTIC_FIELDS order
    facts: tuple        # named model facts, in FACTS order
    ignore: tuple       # fields left out of the normalised tree that `key-too-coarse` compares


@dataclass(frozen=True)
class Catalogue:
    product: str
    app: str
    version: int
    key: Key
    events: tuple       # every event, class order then file order
    sha256: str

    def by_id(self, ident):
        for event in self.events:
            if event.id == ident:
                return event
        return None


def _fail(where, why):
    raise InternalError("event catalogue: %s: %s" % (where, why))


def _int(where, value, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        _fail(where, "must be an integer in %d..%d, got %r" % (lo, hi, value))
    return value


def _str(where, value, pattern):
    if type(value) is not str or not pattern.fullmatch(value):
        _fail(where, "must be a string matching %s, got %r" % (pattern.pattern, value))
    return value


def _keys(where, table, required):
    if type(table) is not dict:
        _fail(where, "must be a table")
    unknown = sorted(set(table) - set(required))
    missing = sorted(set(required) - set(table))
    if unknown:
        _fail(where, "unknown key(s) %s" % ", ".join(unknown))
    if missing:
        _fail(where, "missing key(s) %s" % ", ".join(missing))


def _names(where, value, allowed):
    if type(value) is not list or any(type(item) is not str for item in value):
        _fail(where, "must be a list of strings")
    if len(set(value)) != len(value):
        _fail(where, "duplicate entries")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(where, "unknown name(s) %s (allowed: %s)" % (", ".join(unknown), ", ".join(allowed)))
    return tuple(name for name in allowed if name in value)


def _intent(where, raw):
    _keys(where, raw, ("id", "intent", "arg"))
    return {"intent": _int(where + ".intent", raw["intent"], 0, 0xffffffff),
            "arg": _int(where + ".arg", raw["arg"], -2**31, 2**31 - 1)}


def _point(where, raw):
    _keys(where, raw, ("id", "x", "y"))
    return {"x": _int(where + ".x", raw["x"], 0, 65535), "y": _int(where + ".y", raw["y"], 0, 65535)}


def _code(where, raw):
    if type(raw) is not dict or raw.get("via") not in ("wedge", "pad"):
        _fail(where + ".via", "must be \"wedge\" or \"pad\"")
    if raw["via"] == "wedge":
        _keys(where, raw, ("id", "boundary", "via", "hex"))
        spec = {"hex": _str(where + ".hex", raw["hex"], _HEX)}
        if "00" in [spec["hex"][i:i + 2] for i in range(0, len(spec["hex"]), 2)]:
            _fail(where + ".hex", "a NUL byte cannot be sent")
    else:
        _keys(where, raw, ("id", "boundary", "via", "digits", "digit_intent", "enter_intent"))
        spec = {"digits": _str(where + ".digits", raw["digits"], _DIGITS),
                "digit_intent": _int(where + ".digit_intent", raw["digit_intent"], 0, 0xffffffff),
                "enter_intent": _int(where + ".enter_intent", raw["enter_intent"], 0, 0xffffffff)}
    if raw["boundary"] not in BOUNDARIES:
        _fail(where + ".boundary", "must be one of %s, got %r" % (", ".join(BOUNDARIES), raw["boundary"]))
    spec.update(boundary=raw["boundary"], via=raw["via"])
    return spec


def _env(where, raw):
    _keys(where, raw, ("id", "env", "arg", "hex"))
    spec = {"env": _int(where + ".env", raw["env"], 0, 0xffffffff),
            "arg": _int(where + ".arg", raw["arg"], -2**31, 2**31 - 1),
            "hex": _str(where + ".hex", raw["hex"], _HEX)}
    if "00" in [spec["hex"][i:i + 2] for i in range(0, len(spec["hex"]), 2)]:
        _fail(where + ".hex", "a NUL byte cannot be sent")
    return spec


def _time(where, raw):
    if type(raw) is not dict or raw.get("kind") not in T1_KINDS:
        _fail(where + ".kind", "must be one of %s" % ", ".join(T1_KINDS))
    if raw["kind"] == "advance":
        _keys(where, raw, ("id", "kind", "ms"))
        return {"kind": "advance", "ms": _int(where + ".ms", raw["ms"], 1, ADVANCE_MAX_MS)}
    _keys(where, raw, ("id", "kind"))
    return {"kind": raw["kind"]}


_PARSERS = {"u1": _intent, "u2": _point, "u3": _point, "u4": _code, "u5": _intent, "e1": _env, "t1": _time}


def _events(cls, raw, seen):
    _keys(cls, raw, ("events",))
    if type(raw["events"]) is not list:
        _fail(cls + ".events", "must be a list of tables")
    out = []
    for index, item in enumerate(raw["events"]):
        where = "%s.events[%d]" % (cls, index)
        if type(item) is not dict:
            _fail(where, "must be a table")
        ident = _str(where + ".id", item.get("id"), _ID)
        if ident in RESERVED_IDS:
            _fail(where + ".id", "%r is a reserved path word" % ident)
        if ident in seen:
            _fail(where + ".id", "duplicate event id %r" % ident)
        seen.add(ident)
        spec = _PARSERS[cls](where, item)
        out.append(Event(ident, cls, tuple(sorted(spec.items()))))
    return out


def _key(raw):
    _keys("key", raw, ("fields", "facts", "ignore"))
    fields = _names("key.fields", raw["fields"], KEY_FIELDS)
    ignore = _names("key.ignore", raw["ignore"], KEY_FIELDS)
    if set(fields) & set(ignore):
        _fail("key.ignore", "a field cannot be both in the key and ignored: %s" % ", ".join(sorted(set(fields) & set(ignore))))
    return Key(fields, _names("key.facts", raw["facts"], FACTS), ignore)


def loads(data):
    """A Catalogue from the bytes of a catalogue file."""
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        _fail("file", "not valid UTF-8 TOML: %s" % error)
    _keys("top level", document, _TOP)
    if document["schema"] != SCHEMA:
        _fail("schema", "must be %r, got %r" % (SCHEMA, document["schema"]))
    seen = set()
    events = []
    for cls in CLASSES:
        events.extend(_events(cls, document[cls], seen))
    return Catalogue(_str("product", document["product"], _NAME), _str("app", document["app"], _NAME),
                     _int("version", document["version"], 1, 2**31 - 1), _key(document["key"]), tuple(events),
                     jsonio.sha256_hex(data))


def load(path):
    try:
        data = jsonio.read_bytes(path)
    except OSError as error:
        raise InternalError("event catalogue: cannot read %s: %s" % (path, error.strerror))
    return loads(data)
