"""The UI contract (`products/<product>/ui/<name>.toml`): a strict loader, the typed pending result, the
completeness check and the dwell table of the UI gate (P004 section 6.2, docs/ui-contract.md).

The file is owner-sealed. Every entry carries a `provenance`; an entry the owner has not decided is written
`pending = "<P004 section 11 question>"` instead of `value`, and asking for it raises `ContractPending`, never a
default. Any defect of the file is exit 2 (InternalError): unknown key, missing key, wrong type, duplicate row,
dangling reference, entry without provenance.
"""

import math
import re
import tomllib
from dataclasses import dataclass

from rigor_lib import findings, jsonio
from rigor_lib.errors import InternalError

SCHEMA = "ui-contract/1"
PENDING_QUESTIONS = frozenset(str(n) for n in range(1, 18))   # P004 section 11 has questions 1..17
_PROVENANCE = re.compile(r"^(?:(spec):([^\s#]+)#(\S+)|(oracle):(\S.*\S|\S)|(literature):(\S+)|(owner):(\S+))$")
THRESHOLD_PREFIX = "literature:3.10/"   # every threshold cites its own P004 section 3.10 key


class ContractPending(Exception):
    """A judge asked for a value the owner has not decided (rule `contract-pending`). Not an InternalError."""

    def __init__(self, path, question):
        Exception.__init__(self, "contract entry %s is pending (P004 section 11 question %s)" % (path, question))
        self.path = path
        self.question = question


@dataclass(frozen=True)
class Pending:
    question: str


@dataclass(frozen=True)
class Entry:
    value: object          # a plain value, or a Pending
    provenance: str


def _fail(why):
    raise InternalError("ui-contract: %s" % why)


def _is_int(v):
    return type(v) is int


def _is_num(v):
    return type(v) in (int, float) and math.isfinite(v)


def _is_str(v):
    return isinstance(v, str) and v != ""


def _list_of(check):
    return lambda v: isinstance(v, list) and len(v) > 0 and all(check(x) for x in v) and len(set(v)) == len(v)


def _enum(*names):
    return lambda v: isinstance(v, str) and v in names


def _is_bool(v):
    return type(v) is bool


def _nonneg_int(v):
    return _is_int(v) and v >= 0


def _pos_int(v):
    return _is_int(v) and v > 0


def _pos_num(v):
    return _is_num(v) and v > 0


def _weight(v):
    return _is_int(v) and v in (400, 600)


def _strs_maybe_empty(v):
    return isinstance(v, list) and all(_is_str(x) for x in v) and len(set(v)) == len(v)


_POLICY_VALUE = {"error_dialog": _enum("fixed", "until-acknowledged"),
                 "target_population": _enum("younger-adult", "inclusive")}
# Scalar sections: every key is required, each is an entry `{value | pending, provenance}`.
SCALARS = {
    "window": {"width_px": _pos_int, "height_px": _pos_int, "unit_px": _pos_int, "pad_px": _nonneg_int,
               "gap_px": _nonneg_int},
    "panel": {"diagonal_in": _pos_num, "viewing_distance_mm": _pos_num},
    "type_scale": {n: _pos_int for n in ("display", "headline", "title", "body", "staff", "caption")},
    "reading": {"rate_wpm": _pos_num},
    "clock": {"tick_ms": _pos_int},
    "policy": _POLICY_VALUE,
    "thresholds": {
        "keypad_key_min_mm": _pos_num, "button_recommended_mm": _pos_num, "button_floor_mm": _pos_num,
        "touch_min_mm": _pos_num, "touch_min_dp": _pos_int, "hit_overlap_allowed": _is_bool,
        "spacing_hard_mm": _pos_num, "spacing_recommended_mm": _pos_num,
        "probe_grid_pct": _list_of(_is_num), "probe_disc_radius_mm": _pos_num,
        "feedback_rendered_frames_max": _pos_int, "feedback_target_frames": _pos_int, "frame_hz": _pos_int,
        "busy_indicator_ms": _pos_int, "busy_progress_cancel_ms": _pos_int,
        "dwell_base_ms": _nonneg_int, "dwell_floor_ms": _nonneg_int, "dwell_chars_per_word": _pos_num,
        "flicker_floor_ms": _pos_int, "legibility_xheight_deg": _pos_num,
        "contrast_text": _pos_num, "contrast_large": _pos_num, "pseudo_expansion_overall_pct": _nonneg_int,
        "relational_geometry_tol_px": _nonneg_int, "pixel_tolerance": _nonneg_int, "hierarchy_ratio_k": _pos_num,
    },
}
# Table sections (arrays of tables): name -> (id key, {key: checker}, optional keys). Every row needs `provenance`.
TABLES = {
    "style": ("id", {"id": _is_str, "token": _pos_int, "scale": _is_str, "weight": _weight, "usage": _enum("text", "button")}, ()),
    "role": ("id", {"id": _is_str, "style": _is_str, "align": _enum("centre", "left"),
                    "align_banner": _enum("centre", "left")}, ("align_banner",)),
    "role_min": ("role", {"role": _is_str, "font_px_min": _nonneg_int, "touch_dp_min": _nonneg_int}, ()),
    "timer": ("kind", {"kind": _is_str, "class": _enum("screen", "message"), "lifetime_ms": _nonneg_int,
                       "countdown_shown": _is_bool, "dismiss": _strs_maybe_empty}, ()),
    "state_class": ("id", {"id": _is_str, "required": _list_of(_is_str)}, ()),
    "importance": ("level", {"level": _pos_int, "roles": _list_of(_is_str)}, ()),
    "toggle_group": ("id", {"id": _is_str, "members": _list_of(_is_str), "exactly_one": _is_bool,
                            "shown_on": _list_of(_is_str)}, ()),
    "input_layer": ("layer", {"layer": _is_str, "blocks_input_below": _is_bool, "tap_outside_dismisses": _is_bool,
                              "accepts_input": _is_bool}, ()),
    "wrap": ("scope", {"scope": _is_str, "wrap": _enum("word", "char", "none"), "max_lines": _nonneg_int,
                       "ellipsis": _is_bool, "clip": _is_bool}, ()),
    "exception": ("id", {"id": _is_str, "rule": _is_str, "target": _is_str, "reason": _is_str}, ()),
}
OPTIONAL_TABLES = ("exception",)
_TOP = ("schema", "product")


def check_provenance(where, text):
    if not isinstance(text, str) or _PROVENANCE.match(text) is None:
        _fail("%s: provenance %r is not spec:<doc>#<anchor>, oracle:<what>, literature:<key> or owner:<id>"
              % (where, text))
    return text


def _entry(section, key, raw, check):
    where = "%s.%s" % (section, key)
    if not isinstance(raw, dict):
        _fail("%s must be a table with `value` or `pending` and `provenance`" % where)
    extra = sorted(set(raw) - {"value", "pending", "provenance"})
    if extra:
        _fail("%s: unknown keys %s" % (where, ", ".join(extra)))
    if "provenance" not in raw:
        _fail("%s has no provenance" % where)
    provenance = check_provenance(where, raw["provenance"])
    if ("value" in raw) == ("pending" in raw):
        _fail("%s needs exactly one of `value` and `pending`" % where)
    if section == "thresholds" and provenance != THRESHOLD_PREFIX + key:
        _fail("%s: a threshold must cite its own section 3.10 key, `%s%s`" % (where, THRESHOLD_PREFIX, key))
    if "pending" in raw:
        if raw["pending"] not in PENDING_QUESTIONS:
            _fail("%s: pending must be a P004 section 11 question number, \"1\" to \"17\"" % where)
        return Entry(Pending(raw["pending"]), provenance)
    if not check(raw["value"]):
        _fail("%s: value %r has the wrong type or range" % (where, raw["value"]))
    return Entry(raw["value"], provenance)


def _scalar_section(name, raw, keys):
    if not isinstance(raw, dict):
        _fail("section [%s] is missing or not a table" % name)
    missing, extra = sorted(set(keys) - set(raw)), sorted(set(raw) - set(keys))
    if missing:
        _fail("[%s] is missing entries: %s" % (name, ", ".join(missing)))
    if extra:
        _fail("[%s] has unknown entries: %s" % (name, ", ".join(extra)))
    return {key: _entry(name, key, raw[key], keys[key]) for key in keys}


def _row(name, index, raw, id_key, keys, optional):
    where = "[[%s]] #%d" % (name, index + 1)
    if not isinstance(raw, dict):
        _fail("%s is not a table" % where)
    allowed = set(keys) | {"provenance"}
    missing = sorted(set(keys) - set(optional) - set(raw))
    if missing:
        _fail("%s is missing keys: %s" % (where, ", ".join(missing)))
    extra = sorted(set(raw) - allowed)
    if extra:
        _fail("%s has unknown keys: %s" % (where, ", ".join(extra)))
    if "provenance" not in raw:
        _fail("%s (%s=%r) has no provenance" % (where, id_key, raw.get(id_key)))
    check_provenance("%s %r" % (where, raw.get(id_key)), raw["provenance"])
    for key, check in keys.items():
        if key in raw and not check(raw[key]):
            _fail("%s: key %r has the wrong type or range: %r" % (where, key, raw[key]))
    return dict(raw)


def _table(name, raw):
    id_key, keys, optional = TABLES[name]
    if raw is None:
        if name in OPTIONAL_TABLES:
            return []
        _fail("table [[%s]] is missing" % name)
    if not isinstance(raw, list) or (not raw and name not in OPTIONAL_TABLES):
        _fail("[[%s]] must be a non-empty array of tables" % name)
    rows = [_row(name, i, item, id_key, keys, optional) for i, item in enumerate(raw)]
    seen = set()
    for row in rows:
        if row[id_key] in seen:
            _fail("[[%s]] has a duplicate %s %r" % (name, id_key, row[id_key]))
        seen.add(row[id_key])
    return rows


class Contract:
    def __init__(self, product, scalars, tables):
        self.product = product
        self.scalars = scalars      # {section: {key: Entry}}
        self.tables = tables        # {name: [row dict]}

    def entry(self, section, key):
        try:
            return self.scalars[section][key]
        except KeyError:
            raise InternalError("ui-contract: no entry %s.%s in the schema" % (section, key)) from None

    def get(self, section, key):
        """The value, or ContractPending. A judge never gets a default."""
        value = self.entry(section, key).value
        if isinstance(value, Pending):
            raise ContractPending("%s.%s" % (section, key), value.question)
        return value

    def is_pending(self, section, key):
        return isinstance(self.entry(section, key).value, Pending)

    def pending_entries(self):
        return sorted(("%s.%s" % (s, k), e.value.question)
                      for s, keys in self.scalars.items() for k, e in keys.items() if isinstance(e.value, Pending))

    def ids(self, name):
        id_key = TABLES[name][0]
        return [row[id_key] for row in self.tables[name]]

    def row(self, name, ident):
        id_key = TABLES[name][0]
        for row in self.tables[name]:
            if row[id_key] == ident:
                return row
        raise InternalError("ui-contract: no [[%s]] row %s=%r" % (name, id_key, ident))

    def style_px(self, style):
        """Font size in px of a style row: its `scale` names a type_scale entry."""
        return self.get("type_scale", self.row("style", style)["scale"])

    def ppi(self):
        """Pixel density of the panel; ContractPending until the owner seals the diagonal (question 9)."""
        diagonal = self.get("panel", "diagonal_in")
        return math.hypot(self.get("window", "width_px"), self.get("window", "height_px")) / diagonal

    def mm_to_px(self, mm):
        return mm * self.ppi() / 25.4


def _check_refs(tables, scalars):
    styles = {r["id"] for r in tables["style"]}
    roles = {r["id"] for r in tables["role"]}
    states = {r["id"] for r in tables["state_class"]}
    for row in tables["style"]:
        if row["scale"] not in scalars["type_scale"]:
            _fail("[[style]] %r: scale %r is not a type_scale entry" % (row["id"], row["scale"]))
    for row in tables["role"]:
        if row["style"] not in styles:
            _fail("[[role]] %r: style %r is not a [[style]] id" % (row["id"], row["style"]))
    for row in tables["role_min"]:
        if row["role"] not in roles:
            _fail("[[role_min]]: role %r is not a [[role]] id" % row["role"])
    for row in tables["importance"]:
        for role in row["roles"]:
            if role not in roles:
                _fail("[[importance]] level %d: role %r is not a [[role]] id" % (row["level"], role))
    for row in tables["toggle_group"]:
        for state in row["shown_on"]:
            if state not in states:
                _fail("[[toggle_group]] %r: shown_on %r is not a [[state_class]] id" % (row["id"], state))


def loads(text):
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        _fail("not valid TOML: %s" % error)
    if document.get("schema") != SCHEMA:
        _fail("key `schema` must be %r" % SCHEMA)
    if not _is_str(document.get("product")):
        _fail("key `product` must be a non-empty string")
    known = set(_TOP) | set(SCALARS) | set(TABLES)
    unknown = sorted(set(document) - known)
    if unknown:
        _fail("unknown top-level keys: %s" % ", ".join(unknown))
    scalars = {name: _scalar_section(name, document.get(name), keys) for name, keys in SCALARS.items()}
    tables = {name: _table(name, document.get(name)) for name in TABLES}
    _check_refs(tables, scalars)
    return Contract(document["product"], scalars, tables)


def load(path):
    return loads(jsonio.read_bytes(path).decode("utf-8"))


def pending_finding(error, severity=findings.SEVERITY_ERROR):
    """The typed finding of a judge that asked for a pending value."""
    return findings.finding("contract-pending", severity, entry=error.path, question=error.question)


def incomplete(contract, timer_kinds=(), state_classes=(), roles=()):
    """Every timer kind, state class and role a product declares that the contract does not cover."""
    wanted = (("timer-kind", timer_kinds, "timer"), ("state-class", state_classes, "state_class"),
              ("role", roles, "role"))
    found = []
    for what, declared, table in wanted:
        have = set(contract.ids(table))
        found.extend(findings.finding("contract-incomplete", what=what, name=name)
                     for name in sorted(set(declared) - have))
    return found


def reading_ms(words, rate_wpm):
    return math.ceil(words * 60000 / rate_wpm)


def word_count(text):
    return len(text.split())


def dwell_table(contract, messages):
    """One row per (msgid, lang): word count, reading time at the contract's rate, the minimum dwell, the timer.

    `messages` is an iterable of (msgid, lang, kind, text). Raises ContractPending while the reading rate is
    pending. A kind the contract has no timer for gets `lifetime_ms = None` (see `dwell_findings`).
    """
    rate = contract.get("reading", "rate_wpm")
    base = contract.get("thresholds", "dwell_base_ms")
    floor = contract.get("thresholds", "dwell_floor_ms")
    timers = {r["kind"]: r for r in contract.tables["timer"]}
    rows = []
    for msgid, lang, kind, text in sorted(messages):
        words = word_count(text)
        reading = reading_ms(words, rate)
        timer = timers.get(kind)
        rows.append({"msgid": msgid, "lang": lang, "kind": kind, "words": words, "reading_ms": reading,
                     "min_dwell_ms": max(floor, base + reading),
                     "lifetime_ms": None if timer is None else timer["lifetime_ms"]})
    return rows


def dwell_findings(rows):
    """`dwell-below-reading-time` for a timed message shorter than its minimum; 0 means untimed (no limit)."""
    found = []
    for row in rows:
        if row["lifetime_ms"] is None:
            found.append(findings.finding("contract-incomplete", what="timer-kind", name=row["kind"]))
        elif 0 < row["lifetime_ms"] < row["min_dwell_ms"]:
            found.append(findings.finding("dwell-below-reading-time", msgid=row["msgid"], lang=row["lang"],
                                          kind=row["kind"], lifetime_ms=row["lifetime_ms"],
                                          min_dwell_ms=row["min_dwell_ms"]))
    return found
