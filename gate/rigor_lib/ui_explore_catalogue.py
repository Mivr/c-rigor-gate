"""The event catalogue and abstraction key of `rigor ui-explore` (U05, P004 4.3 items 2 and 3): a strict TOML loader.

One sealed, versioned file per app (`products/<product>/ui/<app>.events.toml`; the toy's is
`selftest/ui_product/toy.events.toml`). Schema `ui-events/1`, documented in docs/ui-explore.md. Every class table is
required, at least one T1 time event is required, `max_wait_ms` is required and capped in code; an unknown key, a
missing key, a wrong type, a duplicate id or name, a value out of range, a key with neither fields nor facts, an
`ignore` without provenance and reason: `InternalError` (exit 2), never a default.
"""

import re
import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio, ui_contract
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import SEMANTIC_FIELDS, TEXT_MAX

SCHEMA = "ui-events/1"
CLASSES = ("u1", "u2", "u3", "u4", "u5", "e1", "t1")
APPLY_CLASSES = ("u1", "u4", "u5", "e1")      # sent through `apply`: each declares whether it must ever be accepted
TAP_CLASSES = ("u2", "u3")
BOUNDARIES = ("empty", "one-digit", "max-minus-1", "max", "max-plus-1", "valid-visitor", "valid-staff", "unknown",
              "expired", "non-digit")
T1_KINDS = ("fire-due", "before-due", "advance", "until-change", "at")
EXPECT = ("accept", "refuse")
FACTS = ("deadline", "env-inputs")
KEY_FIELDS = SEMANTIC_FIELDS[1:]          # `key` (the node identity) is always part of the projection
DERIVED_OPS = ("bucket", "presence", "count", "select")
MEASURES = ("value", "length", "digits")
MODEL_SOURCES = ("due-in-ms", "env-count")
RESERVED_IDS = ("open", "domain-at", "settle", "wait-change", "at")
MAX_WAIT_CEILING_MS = 3600000             # the hard ceiling of `max_wait_ms` (one hour of virtual time)
TIME_MAX_MS = 1 << 52
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_HEX = re.compile(r"(?:[0-9a-f]{2}){0,%d}" % TEXT_MAX)
_DIGITS = re.compile(r"[0-9]{0,%d}" % TEXT_MAX)
_SELECTOR = re.compile(r"[ -\[\]-~]{1,64}")     # printable, no backslash (a record field in its escaped spelling)
_REASON = re.compile(r"[ -~]{1,400}")
_TOP = ("schema", "product", "app", "version", "max_wait_ms", "key") + CLASSES


@dataclass(frozen=True)
class Event:
    """One catalogue event. `cls` is its class; `spec` the class-specific fields as a sorted tuple of (name, value)."""
    id: str
    cls: str
    spec: tuple

    def get(self, name):
        return dict(self.spec)[name]


@dataclass(frozen=True)
class Derived:
    """A named derived fact: `op` over the records chosen by `node` (a node key) or `role`, or over a model source."""
    name: str
    op: str
    node: object
    role: object
    field: object
    measure: object
    model: object
    boundaries: tuple


@dataclass(frozen=True)
class Key:
    fields: tuple       # semantic fields in the projection, in SEMANTIC_FIELDS order
    facts: tuple        # named model facts, in FACTS order
    derived: tuple      # Derived facts, in file order
    ignore: tuple       # (field, provenance, reason): left out of the normalised record key-too-coarse compares


@dataclass(frozen=True)
class Catalogue:
    product: str
    app: str
    version: int
    max_wait_ms: int
    key: Key
    events: tuple       # every event, class order then file order
    sha256: str

    def __post_init__(self):
        object.__setattr__(self, "_index", {event.id: event for event in self.events})
        object.__setattr__(self, "event_ids", frozenset(self._index))

    def by_id(self, ident):
        return self._index.get(ident)


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


def _keys(where, table, required, optional=()):
    if type(table) is not dict:
        _fail(where, "must be a table")
    unknown = sorted(set(table) - set(required) - set(optional))
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


def _enum(where, value, allowed):
    if value not in allowed or type(value) is not str:
        _fail(where, "must be one of %s, got %r" % (", ".join(allowed), value))
    return value


def _hex(where, value):
    text = _str(where, value, _HEX)
    if "00" in [text[i:i + 2] for i in range(0, len(text), 2)]:
        _fail(where, "a NUL byte cannot be sent")
    return text


def _intent(where, raw):
    _keys(where, raw, ("id", "intent", "arg", "expect"))
    return {"intent": _int(where + ".intent", raw["intent"], 0, 0xffffffff),
            "arg": _int(where + ".arg", raw["arg"], -2**31, 2**31 - 1)}


def _point(where, raw):
    _keys(where, raw, ("id", "x", "y"))
    return {"x": _int(where + ".x", raw["x"], 0, 65535), "y": _int(where + ".y", raw["y"], 0, 65535)}


def _code(where, raw):
    if type(raw) is not dict or raw.get("via") not in ("wedge", "pad"):
        _fail(where + ".via", "must be \"wedge\" or \"pad\"")
    if raw["via"] == "wedge":
        _keys(where, raw, ("id", "boundary", "via", "hex", "expect"))
        spec = {"hex": _hex(where + ".hex", raw["hex"])}
    else:
        _keys(where, raw, ("id", "boundary", "via", "digits", "digit_intent", "enter_intent", "expect"))
        spec = {"digits": _str(where + ".digits", raw["digits"], _DIGITS),
                "digit_intent": _int(where + ".digit_intent", raw["digit_intent"], 0, 0xffffffff),
                "enter_intent": _int(where + ".enter_intent", raw["enter_intent"], 0, 0xffffffff)}
    spec.update(boundary=_enum(where + ".boundary", raw["boundary"], BOUNDARIES), via=raw["via"])
    return spec


def _env(where, raw):
    _keys(where, raw, ("id", "env", "arg", "hex", "expect"))
    return {"env": _int(where + ".env", raw["env"], 0, 0xffffffff),
            "arg": _int(where + ".arg", raw["arg"], -2**31, 2**31 - 1), "hex": _hex(where + ".hex", raw["hex"])}


def _time(where, raw, max_wait):
    if type(raw) is not dict:
        _fail(where, "must be a table")
    kind = _enum(where + ".kind", raw.get("kind"), T1_KINDS)
    if kind == "advance":
        _keys(where, raw, ("id", "kind", "ms"))
        return {"kind": kind, "ms": _int(where + ".ms", raw["ms"], 1, max_wait)}
    if kind == "at":
        _keys(where, raw, ("id", "kind", "offset_ms"))
        return {"kind": kind, "offset_ms": _int(where + ".offset_ms", raw["offset_ms"], 0, TIME_MAX_MS)}
    _keys(where, raw, ("id", "kind"))
    return {"kind": kind}


def _events(cls, raw, seen, max_wait):
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
        if cls == "t1":
            spec = _time(where, item, max_wait)
        else:
            spec = {"u1": _intent, "u2": _point, "u3": _point, "u4": _code, "u5": _intent, "e1": _env}[cls](where, item)
        if cls in APPLY_CLASSES:
            spec["expect"] = _enum(where + ".expect", item["expect"], EXPECT)
        out.append(Event(ident, cls, tuple(sorted(spec.items()))))
    return out


def _derived(where, raw, taken):
    if type(raw) is not dict:
        _fail(where, "must be a table")
    name = _str(where + ".name", raw.get("name"), _NAME)
    if name in taken:
        _fail(where + ".name", "duplicate fact name %r" % name)
    taken.add(name)
    op = _enum(where + ".op", raw.get("op"), DERIVED_OPS)
    if op == "bucket" and "model" in raw:
        _keys(where, raw, ("name", "op", "model", "boundaries"))
        return Derived(name, op, None, None, None, None, _enum(where + ".model", raw["model"], MODEL_SOURCES),
                       _boundaries(where, raw["boundaries"]))
    wanted = {"presence": (), "count": (), "select": ("field",), "bucket": ("field", "measure", "boundaries")}[op]
    _keys(where, raw, ("name", "op") + wanted, ("node", "role"))
    if ("node" in raw) == ("role" in raw):
        _fail(where, "needs exactly one of node and role")
    node = _str(where + ".node", raw["node"], _SELECTOR) if "node" in raw else None
    role = _str(where + ".role", raw["role"], _SELECTOR) if "role" in raw else None
    field = _enum(where + ".field", raw["field"], KEY_FIELDS) if "field" in raw else None
    measure = _enum(where + ".measure", raw["measure"], MEASURES) if "measure" in raw else None
    bounds = _boundaries(where, raw["boundaries"]) if "boundaries" in raw else ()
    return Derived(name, op, node, role, field, measure, None, bounds)


def _boundaries(where, value):
    if type(value) is not list or not 1 <= len(value) <= 32 or any(type(v) is not int for v in value) \
            or any(not -2**62 < v < 2**62 for v in value) or any(a >= b for a, b in zip(value, value[1:])):
        _fail(where + ".boundaries", "must be 1 to 32 strictly increasing integers")
    return tuple(value)


def _ignore(index, raw):
    where = "key.ignore[%d]" % index
    _keys(where, raw, ("field", "provenance", "reason"))
    field = _enum(where + ".field", raw["field"], KEY_FIELDS)
    ui_contract.check_provenance(where, raw["provenance"])
    return field, raw["provenance"], _str(where + ".reason", raw["reason"], _REASON)


def _key(raw):
    _keys("key", raw, ("fields", "facts", "derived", "ignore"))
    fields = _names("key.fields", raw["fields"], KEY_FIELDS)
    facts = _names("key.facts", raw["facts"], FACTS)
    if type(raw["derived"]) is not list or type(raw["ignore"]) is not list:
        _fail("key", "derived and ignore must be lists of tables")
    taken = set(FACTS)
    derived = tuple(_derived("key.derived[%d]" % i, item, taken) for i, item in enumerate(raw["derived"]))
    ignore = tuple(_ignore(i, item) for i, item in enumerate(raw["ignore"]))
    names = [item[0] for item in ignore]
    if len(set(names)) != len(names):
        _fail("key.ignore", "a field is ignored twice")
    if set(fields) & set(names):
        _fail("key.ignore", "a field cannot be both in the key and ignored: %s" % ", ".join(sorted(set(fields) & set(names))))
    if not fields and not facts and not derived:
        _fail("key", "a key with no fields, no facts and no derived facts keys every state alike")
    return Key(fields, facts, derived, ignore)


def loads(data):
    """A Catalogue from the bytes of a catalogue file."""
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        _fail("file", "not valid UTF-8 TOML: %s" % error)
    except RecursionError:
        _fail("file", "nested too deeply")
    _keys("top level", document, _TOP)
    if document["schema"] != SCHEMA:
        _fail("schema", "must be %r, got %r" % (SCHEMA, document["schema"]))
    max_wait = _int("max_wait_ms", document["max_wait_ms"], 1, MAX_WAIT_CEILING_MS)
    seen, events = set(), []
    for cls in CLASSES:
        events.extend(_events(cls, document[cls], seen, max_wait))
    if not any(event.cls == "t1" for event in events):
        _fail("t1", "needs at least one time event: states reached only through time must be explored")
    return Catalogue(_str("product", document["product"], _NAME), _str("app", document["app"], _NAME),
                     _int("version", document["version"], 1, 2**31 - 1), max_wait, _key(document["key"]),
                     tuple(events), jsonio.sha256_hex(data))


def load(path):
    try:
        data = jsonio.read_bytes(path)
    except OSError as error:
        raise InternalError("event catalogue: cannot read %s: %s" % (path, error.strerror))
    return loads(data)
