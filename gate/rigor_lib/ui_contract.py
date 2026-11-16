"""The UI contract (`products/<product>/ui/<name>.toml`): a strict loader, the typed pending result, the
completeness check and the dwell table of the UI gate (P004 section 6.2, docs/ui-contract.md).

The file is owner-sealed. Every entry carries a `provenance`; an entry (or a whole table) the owner has not decided is
written `pending = "<P004 section 11 question>"` instead of a value, only where the closed lists below allow it, and
asking for it raises `ContractPending`, never a default. Any defect of the file is exit 2 (InternalError): unknown key,
missing key, wrong type or range, duplicate row, dangling reference, entry without provenance. What the loader hands
out is immutable.
"""

import datetime
import math
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from rigor_lib import findings, jsonio, ui_judge_contract
from rigor_lib.errors import InternalError

SCHEMA = "ui-contract/1"
SPEC_DOCS = frozenset(("ui-rules.md", "ui-look.md", "hardware-safety.md", "P004"))
PENDING_SEVERITY = "error"   # fixed: a judge cannot downgrade `contract-pending` (staging is not the loader's business)
# What may be pending, with the P004 section 11 question that decides it. Anything else pending is an error.
PENDING_ENTRIES = {
    ("panel", "diagonal_in"): "9", ("panel", "viewing_distance_mm"): "9",
    ("policy", "target_population"): "10", ("policy", "error_dialog"): "11", ("reading", "rate_wpm"): "11",
    ("thresholds", "keypad_key_min_mm"): "10", ("thresholds", "button_recommended_mm"): "10",
    ("thresholds", "button_floor_mm"): "10", ("thresholds", "contrast_text"): "15",
    ("thresholds", "contrast_large"): "15", ("thresholds", "flicker_floor_ms"): "5",
    ("thresholds", "hierarchy_ratio_k"): "5",
}
PENDING_TABLES = {"importance": "7"}
# Thresholds P004 3.10 marks [I] or [P] are design values, not literature (`design:P004#3.10-<key>`).
DESIGN_THRESHOLDS = frozenset(("probe_grid_pct", "feedback_target_frames", "frame_hz", "dwell_base_ms",
                               "dwell_floor_ms", "dwell_chars_per_word", "flicker_floor_ms",
                               "relational_geometry_tol_px", "hierarchy_ratio_k"))
# The finding ids of P004 3.1 to 3.9 and of the judges that add their own; an exception may name one of them.
EXCEPTION_RULES = frozenset((
    'a11y-stage-mismatch', 'align-mismatch', 'blocked-target-live', 'busy-indicator-late',
    'clock-origin-divergence', 'contrast-low', 'countdown-wrong', 'covered-node',
    'dead-intent', 'diff-render-divergence', 'dwell-below-reading-time', 'echo-correspondence',
    'effective-target-small', 'exactly-one-selected', 'feedback-late', 'flag-mismatch',
    'flash', 'font-below-min', 'font-shrunk', 'font-size-mismatch',
    'frame-mismatch', 'full-string-shown', 'glyph-run-gap', 'hierarchy-violated',
    'invisible-auto-transition', 'invisible-node', 'invisible-state-change', 'lang-msgid-relation',
    'legibility-floor', 'locale-relation', 'node-out-of-bounds', 'noop-tap-effect',
    'notice-lifetime-long', 'notice-lifetime-short', 'occluded-target', 'oracle-content-recall',
    'oracle-label-extra', 'oracle-label-missing', 'oracle-layout-relation', 'oracle-lifetime-diverged',
    'oracle-lockstep-diverged', 'oracle-node-property', 'oracle-scenario-diverged', 'oracle-screen-unreached',
    'oracle-size-class', 'overlay-captures-enabled', 'overlay-policy', 'phrase-too-long',
    'pinned-deviation', 'raw-text', 'render-geometry-mismatch', 'render-text-mismatch',
    'required-element-missing', 'round-trip', 'selection-iff', 'sibling-uniformity',
    'tap-misrouted', 'tap-swallowed-first', 'target-spacing', 'text-clipped',
    'text-overflow', 'text-overlap', 'text-scale-2x', 'toggle-group-indistinct',
    'toggle-state-invisible', 'touch-target-small', 'unresponsive-intent', 'value-split',
    'wrap-policy-undeclared',
    # U06: the ui-scene and ui-fit judges' own findings that an owner may except (docs/ui-judges.md)
    'fit-unmeasurable', 'glyph-missing', 'stage-unmatched', 'stage-text-mismatch', 'stage-unowned-target',
))
TOGGLE_MARKS = ("bg", "bg_opa", "style")   # U06: what tells a toggle group's selected member apart
EXTRA_ELEMENTS = frozenset(("countdown", "dismiss", "done", "cancel", "numpad", "language_switch",
                            "size_buttons"))
STYLE_TOKENS = 21
_PROVENANCE = re.compile(r"(?:spec:([A-Za-z0-9._-]+)#[A-Za-z0-9._/-]+|oracle:\S(?:[^\n]*\S)?|literature:\S+"
                         r"|design:P004#[A-Za-z0-9._/-]+|owner:[A-Z][A-Z0-9]*-?[0-9]+|product-baseline:[0-9a-f]{7,40})")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_IDENT = re.compile(r"[a-z][a-z0-9_-]*")
_TARGET = re.compile(r"[a-z][a-z0-9_.:/-]*")
_PRODUCT = re.compile(r"[a-z0-9][a-z0-9/_-]*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    value: object          # a plain (immutable) value, or a Pending
    provenance: str


def _fail(why):
    raise InternalError("ui-contract: %s" % why)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


# ---- value checkers -----------------------------------------------------------------------------------------------
def _is_str(v):
    return isinstance(v, str) and v != "" and v == v.strip() and "\n" not in v


def _ident(v):
    return isinstance(v, str) and _IDENT.fullmatch(v) is not None


def _is_bool(v):
    return type(v) is bool


def _int(lo, hi):
    return lambda v: type(v) is int and lo <= v <= hi


def _num(lo, hi):
    return lambda v: type(v) in (int, float) and math.isfinite(v) and lo <= v <= hi


def _enum(*names):
    return lambda v: isinstance(v, str) and v in names


def _list_of(check, minimum=1, increasing=False):
    def run(v):
        if not isinstance(v, list) or len(v) < minimum or not all(check(x) for x in v):
            return False
        if increasing:
            return all(a < b for a, b in zip(v, v[1:]))
        return len(set(v)) == len(v)
    return run


def _weight(v):
    return type(v) is int and v in (400, 600)


def _is_date(v):
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return True
    if not isinstance(v, str) or _DATE.fullmatch(v) is None:
        return False
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _concrete_target(v):
    return isinstance(v, str) and _TARGET.fullmatch(v) is not None


_MM = _num(0.1, 1000)
_MS = _int(1, 3600000)
# Scalar sections: every key is required, each is an entry `{value | pending, provenance}`.
SCALARS = {
    "window": {"width_px": _int(1, 20000), "height_px": _int(1, 20000), "unit_px": _int(1, 100),
               "pad_px": _int(0, 1000), "gap_px": _int(0, 1000)},
    "panel": {"diagonal_in": _num(1, 200), "viewing_distance_mm": _num(100, 10000)},
    "type_scale": {n: _int(1, 1000) for n in ("display", "headline", "title", "body", "staff", "caption")},
    "reading": {"rate_wpm": _num(50, 400)},
    "clock": {"tick_ms": _int(1, 10000)},
    "policy": {"error_dialog": _enum("fixed", "until-acknowledged"),
               "target_population": _enum("younger-adult", "inclusive")},
    "thresholds": {
        "keypad_key_min_mm": _MM, "button_recommended_mm": _MM, "button_floor_mm": _MM, "touch_min_mm": _MM,
        "touch_min_dp": _int(1, 500), "hit_overlap_allowed": _is_bool,
        "spacing_hard_mm": _MM, "spacing_recommended_mm": _MM,
        "probe_grid_pct": _list_of(_num(0, 100), increasing=True), "probe_disc_radius_mm": _MM,
        "feedback_rendered_frames_max": _int(1, 60), "feedback_target_frames": _int(1, 60), "frame_hz": _int(1, 1000),
        "busy_indicator_ms": _MS, "busy_progress_cancel_ms": _MS,
        "dwell_base_ms": _int(0, 60000), "dwell_floor_ms": _int(0, 60000), "dwell_chars_per_word": _num(3, 10),
        "flicker_floor_ms": _int(1, 10000), "legibility_xheight_deg": _num(0.01, 5),
        "contrast_text": _num(1, 21), "contrast_large": _num(1, 21), "pseudo_expansion_overall_pct": _int(0, 500),
        "relational_geometry_tol_px": _int(0, 100), "pixel_tolerance": _int(0, 100), "hierarchy_ratio_k": _num(1, 100),
    },
}
# Orderings P004 3.10 implies: the first value may not exceed the second (checked unless one is pending).
ORDER = (("touch_min_mm", "button_floor_mm"), ("button_floor_mm", "button_recommended_mm"),
         ("button_recommended_mm", "keypad_key_min_mm"), ("spacing_hard_mm", "spacing_recommended_mm"),
         ("feedback_target_frames", "feedback_rendered_frames_max"),
         ("busy_indicator_ms", "busy_progress_cancel_ms"), ("dwell_base_ms", "dwell_floor_ms"),
         ("contrast_large", "contrast_text"))
# Table sections (arrays of tables): name -> (id key, {key: checker}, optional keys). Every row needs `provenance`.
TABLES = {
    "style": ("id", {"id": _ident, "token": _int(1, STYLE_TOKENS), "scale": _ident, "weight": _weight,
                     "usage": _enum("text", "button")}, ()),
    "role": ("id", {"id": _ident, "style": _ident, "align": _enum("centre", "left"),
                    "align_banner": _enum("centre", "left")}, ("align_banner",)),
    "role_min": ("role", {"role": _ident, "font_px_min": _int(0, 1000), "touch_dp_min": _int(0, 500)}, ()),
    "timer": ("kind", {"kind": _ident, "class": _enum("screen", "message"), "lifetime_ms": _int(0, 3600000),
                       "countdown_shown": _is_bool, "dismiss": _list_of(_ident, minimum=0)}, ()),
    "state_class": ("id", {"id": _ident, "required": _list_of(_ident)}, ()),
    "importance": ("level", {"level": _int(1, 9), "roles": _list_of(_ident)}, ()),
    "toggle_group": ("id", {"id": _ident, "members": _list_of(_ident, minimum=2), "exactly_one": _is_bool,
                            "shown_on": _list_of(_ident), "marks": _list_of(_enum(*TOGGLE_MARKS))}, ()),
    "input_layer": ("layer", {"layer": _ident, "blocks_input_below": _is_bool, "tap_outside_dismisses": _is_bool,
                              "accepts_input": _is_bool}, ()),
    "wrap": ("scope", {"scope": _ident, "wrap": _enum("word", "char", "none"), "max_lines": _int(0, 1000),
                       "ellipsis": _is_bool, "clip": _is_bool}, ()),
    "exception": ("id", {"id": _ident, "rule": _enum(*sorted(EXCEPTION_RULES)), "target": _concrete_target,
                         "reason": _is_str, "expires": _is_date}, ()),
}
TABLES.update(ui_judge_contract.table_specs(_ident, _is_str, _int, _enum))   # U06: the judges' tables
OPTIONAL_TABLES = ("exception",)
_TOP = ("schema", "product", "pending_tables")


def check_provenance(where, text, table=None):
    """A provenance of one of the forms; `product-baseline:<commit>` only in the table `style_line` (U06)."""
    found = _PROVENANCE.fullmatch(text) if isinstance(text, str) else None
    if found is None or (found.group(1) is not None and found.group(1) not in SPEC_DOCS):
        _fail("%s: provenance %r is not spec:<doc>#<anchor> (doc one of %s), oracle:<what>, literature:<key>, "
              "design:P004#<section> or owner:<decision id>" % (where, text, ", ".join(sorted(SPEC_DOCS))))
    ui_judge_contract.check_provenance_form(table, text, where)
    return text


def _pending_value(where, raw, expected):
    if not isinstance(raw, str) or raw != expected:
        _fail("%s: pending must be exactly %r here (a closed list in the loader), got %r" % (where, expected, raw))
    return Pending(raw)


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
    if section == "thresholds":
        want = ("design:P004#3.10-" if key in DESIGN_THRESHOLDS else "literature:3.10/") + key
        if provenance != want:
            _fail("%s: a threshold must have the provenance `%s`" % (where, want))
    if ("value" in raw) == ("pending" in raw):
        _fail("%s needs exactly one of `value` and `pending`" % where)
    if "pending" in raw:
        expected = PENDING_ENTRIES.get((section, key))
        if expected is None:
            _fail("%s may not be pending" % where)
        return Entry(_pending_value(where, raw["pending"], expected), provenance)
    if not check(raw["value"]):
        _fail("%s: value %r has the wrong type or range" % (where, raw["value"]))
    return Entry(_freeze(raw["value"]), provenance)


def _scalar_section(name, raw, keys):
    if not isinstance(raw, dict):
        _fail("section [%s] is missing or not a table" % name)
    missing, extra = sorted(set(keys) - set(raw)), sorted(set(raw) - set(keys))
    if missing:
        _fail("[%s] is missing entries: %s" % (name, ", ".join(missing)))
    if extra:
        _fail("[%s] has unknown entries: %s" % (name, ", ".join(extra)))
    return MappingProxyType({key: _entry(name, key, raw[key], keys[key]) for key in keys})


def _pending_tables(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _fail("[pending_tables] must be a table")
    found = {}
    for name, entry in raw.items():
        if name not in PENDING_TABLES:
            _fail("[pending_tables] may not name %r (allowed: %s)" % (name, ", ".join(sorted(PENDING_TABLES))))
        if not isinstance(entry, dict) or set(entry) != {"pending", "provenance"}:
            _fail("pending_tables.%s must be { pending = \"<n>\", provenance = \"...\" }" % name)
        check_provenance("pending_tables.%s" % name, entry["provenance"])
        found[name] = _pending_value("pending_tables.%s" % name, entry["pending"], PENDING_TABLES[name])
    return found


def _row(name, index, raw, id_key, keys, optional):
    where = "[[%s]] #%d" % (name, index + 1)
    if not isinstance(raw, dict):
        _fail("%s is not a table" % where)
    missing = sorted(set(keys) - set(optional) - set(raw))
    if missing:
        _fail("%s is missing keys: %s" % (where, ", ".join(missing)))
    extra = sorted(set(raw) - set(keys) - {"provenance"})
    if extra:
        _fail("%s has unknown keys: %s" % (where, ", ".join(extra)))
    shown = raw.get(id_key) if isinstance(raw.get(id_key), str) else "?"
    if "provenance" not in raw:
        _fail("%s (%s=%r) has no provenance" % (where, id_key, shown))
    check_provenance("%s %r" % (where, shown), raw["provenance"], name)
    for key, check in keys.items():
        if key in raw and not check(raw[key]):
            _fail("%s: key %r has the wrong type or range: %r" % (where, key, raw[key]))
    if name == "exception" and not raw["provenance"].startswith("owner:"):
        _fail("%s: an exception needs an owner: provenance" % where)
    return _freeze(raw)


def _table(name, raw, pending):
    id_key, keys, optional = TABLES[name]
    if name in pending:
        if raw is not None:
            _fail("[[%s]] is pending (pending_tables) and must have no rows" % name)
        return ()
    if raw is None:
        if name in OPTIONAL_TABLES:
            return ()
        _fail("table [[%s]] is missing" % name)
    if not isinstance(raw, list) or (not raw and name not in OPTIONAL_TABLES):
        _fail("[[%s]] must be a non-empty array of tables" % name)
    rows = tuple(_row(name, i, item, id_key, keys, optional) for i, item in enumerate(raw))
    seen = set()
    for row in rows:
        if row[id_key] in seen:
            _fail("[[%s]] has a duplicate %s %r" % (name, id_key, row[id_key]))
        seen.add(row[id_key])
    return rows


class Contract:
    def __init__(self, product, scalars, tables, pending_tables):
        self.product = product
        self.scalars = MappingProxyType(scalars)           # {section: {key: Entry}}, all immutable
        self.tables = MappingProxyType(tables)             # {name: tuple of read-only rows}
        self.pending_tables = MappingProxyType(pending_tables)   # {name: Pending}

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
        """Sorted (path, question) of every pending entry and pending table."""
        found = [("%s.%s" % (s, k), e.value.question)
                 for s, keys in self.scalars.items() for k, e in keys.items() if isinstance(e.value, Pending)]
        found.extend(("table:%s" % name, p.question) for name, p in self.pending_tables.items())
        return sorted(found)

    def rows(self, name):
        """The rows of a table, or ContractPending when the owner has not decided the whole table."""
        if name in self.pending_tables:
            raise ContractPending("table:%s" % name, self.pending_tables[name].question)
        return self.tables[name]

    def ids(self, name):
        id_key = TABLES[name][0]
        return [row[id_key] for row in self.rows(name)]

    def row(self, name, ident):
        id_key = TABLES[name][0]
        for row in self.rows(name):
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

    def active_exceptions(self, today):
        """The exception rows that have not expired on the date `today` (a datetime.date)."""
        live = []
        for row in self.tables["exception"]:
            expires = row["expires"]
            expires = expires if isinstance(expires, datetime.date) else datetime.date.fromisoformat(expires)
            if today <= expires:
                live.append(row)
        return tuple(live)


def _check_thresholds(scalars):
    values = {k: e.value for k, e in scalars["thresholds"].items()}
    for low, high in ORDER:
        if not isinstance(values[low], Pending) and not isinstance(values[high], Pending) and values[low] > values[high]:
            _fail("thresholds: %s (%s) may not exceed %s (%s)" % (low, values[low], high, values[high]))
    window = scalars["window"]
    if window["pad_px"].value * 2 >= window["width_px"].value:
        _fail("window: pad_px is too large for width_px")


def _check_refs(tables, scalars):
    styles = {r["id"]: r for r in tables["style"]}
    roles = {r["id"]: r for r in tables["role"]}
    states = {r["id"] for r in tables["state_class"]}
    for row in tables["style"]:
        if row["scale"] not in scalars["type_scale"]:
            _fail("[[style]] %r: scale %r is not a type_scale entry" % (row["id"], row["scale"]))
    tokens = [r["token"] for r in tables["style"]]
    if len(set(tokens)) != len(tokens):
        _fail("[[style]] tokens are not unique")
    for row in tables["role"]:
        if row["style"] not in styles:
            _fail("[[role]] %r: style %r is not a [[style]] id" % (row["id"], row["style"]))
        _check_alignment(row, styles[row["style"]])
    for row in tables["role_min"]:
        _check_role_min(row, roles, styles, scalars)
    levels = [role for row in tables["importance"] for role in row["roles"]]
    if len(set(levels)) != len(levels):
        _fail("[[importance]]: a role is in more than one level (or twice in one)")
    for role in levels:
        if role not in roles:
            _fail("[[importance]]: role %r is not a [[role]] id" % role)
    for row in tables["state_class"]:
        for element in row["required"]:
            if element not in roles and element not in EXTRA_ELEMENTS:
                _fail("[[state_class]] %r: required element %r is unknown" % (row["id"], element))
    for row in tables["toggle_group"]:
        for state in row["shown_on"]:
            if state not in states:
                _fail("[[toggle_group]] %r: shown_on %r is not a [[state_class]] id" % (row["id"], state))


def _check_alignment(role, style):
    notice = style["id"].startswith("notice_")
    if "align_banner" in role and not notice:
        _fail("[[role]] %r: align_banner is only valid for a notice role" % role["id"])
    if not notice and role["align"] != "centre":
        _fail("[[role]] %r: only a notice role may be left-aligned" % role["id"])
    if style["usage"] == "button" and role["align"] != "centre":
        _fail("[[role]] %r: a button label is centred" % role["id"])


def _check_role_min(row, roles, styles, scalars):
    if row["role"] not in roles:
        _fail("[[role_min]]: role %r is not a [[role]] id" % row["role"])
    style = styles.get(roles[row["role"]]["style"])
    px = scalars["type_scale"][style["scale"]].value
    if row["font_px_min"] > px:
        _fail("[[role_min]] %r: font_px_min %d exceeds the role's style size %d" % (row["role"], row["font_px_min"], px))
    touch = scalars["thresholds"]["touch_min_dp"].value
    if style["usage"] == "button" and row["touch_dp_min"] < touch:
        _fail("[[role_min]] %r: a button needs touch_dp_min of at least %d" % (row["role"], touch))
    if 0 < row["touch_dp_min"] < touch:
        _fail("[[role_min]] %r: touch_dp_min is 0 or at least %d" % (row["role"], touch))


def _check_rows(tables):
    for row in tables["timer"]:
        if row["countdown_shown"] and row["lifetime_ms"] == 0:
            _fail("[[timer]] %r: a countdown needs lifetime_ms above 0" % row["kind"])
        if row["class"] == "message" and not row["dismiss"]:
            _fail("[[timer]] %r: every message can be dismissed (ui-rules.md): dismiss may not be empty" % row["kind"])
    for row in tables["wrap"]:
        if row["wrap"] == "none" and row["max_lines"] != 1:
            _fail("[[wrap]] %r: wrap none means max_lines 1" % row["scope"])
        if row["ellipsis"] and row["max_lines"] == 0:
            _fail("[[wrap]] %r: an ellipsis needs a line cap" % row["scope"])


def loads(text):
    try:
        return _loads(text)
    except (TypeError, KeyError, ValueError, AttributeError, RecursionError) as error:
        _fail("malformed contract (%s: %s)" % (type(error).__name__, error))


def _loads(text):
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        _fail("not valid TOML: %s" % error)
    if document.get("schema") != SCHEMA:
        _fail("key `schema` must be %r" % SCHEMA)
    product = document.get("product")
    if not isinstance(product, str) or _PRODUCT.fullmatch(product) is None:
        _fail("key `product` must be a name such as business-apps/lockers")
    unknown = sorted(set(document) - set(_TOP) - set(SCALARS) - set(TABLES))
    if unknown:
        _fail("unknown top-level keys: %s" % ", ".join(unknown))
    pending = _pending_tables(document.get("pending_tables"))
    scalars = {name: _scalar_section(name, document.get(name), keys) for name, keys in SCALARS.items()}
    tables = {name: _table(name, document.get(name), pending) for name in TABLES}
    _check_thresholds(scalars)
    _check_refs(tables, scalars)
    _check_rows(tables)
    ui_judge_contract.check(tables)
    return Contract(product, scalars, tables, pending)


def load(path):
    try:
        return loads(jsonio.read_bytes(path).decode("utf-8"))
    except UnicodeDecodeError as error:
        _fail("%s is not UTF-8: %s" % (path, error))
    except OSError as error:
        _fail("cannot read %s: %s" % (path, error))


def pending_finding(error):
    """The typed finding of a judge that asked for a pending value. Its severity is fixed: error."""
    return findings.finding("contract-pending", PENDING_SEVERITY, entry=error.path, question=error.question)


def incomplete(contract, timer_kinds=(), state_classes=(), roles=()):
    """Every timer kind, state class and role a product declares that the contract does not cover, and every role
    of the contract that has no role_min row (or, unless the table is pending, no importance level)."""
    wanted = (("timer-kind", timer_kinds, "timer"), ("state-class", state_classes, "state_class"),
              ("role", roles, "role"))
    found = []
    for what, declared, table in wanted:
        have = set(contract.ids(table))
        found.extend(findings.finding("contract-incomplete", what=what, name=name)
                     for name in sorted(set(declared) - have))
    own = contract.ids("role")
    found.extend(findings.finding("contract-incomplete", what="role-min", name=name)
                 for name in sorted(set(own) - set(contract.ids("role_min"))))
    if "importance" not in contract.pending_tables:
        leveled = {role for row in contract.rows("importance") for role in row["roles"]}
        found.extend(findings.finding("contract-incomplete", what="importance", name=name)
                     for name in sorted(set(own) - leveled))
    return found


def displayed_text(text, max_expansion=None):
    """The text as displayed: every `{placeholder}` replaced by its longest expansion. A placeholder without an
    expansion, or an expansion for a placeholder the text does not have, is an error."""
    expansion = {} if max_expansion is None else max_expansion
    if not isinstance(expansion, dict) or not all(_is_str(k) and _is_str(v) and not _PLACEHOLDER.search(v)
                                                  for k, v in expansion.items()):
        _fail("max_expansion must map each placeholder to a plain, non-empty text")
    names = set(_PLACEHOLDER.findall(text))
    if names - set(expansion):
        _fail("dwell: placeholder(s) %s have no max_expansion" % ", ".join(sorted(names - set(expansion))))
    if set(expansion) - names:
        _fail("dwell: max_expansion names %s, which the text does not contain" % ", ".join(sorted(set(expansion) - names)))
    return _PLACEHOLDER.sub(lambda found: expansion[found.group(0)], text)


def char_count(text):
    return len(unicodedata.normalize("NFC", text))


def reading_ms(chars, rate_wpm, chars_per_word):
    """chars / (rate * chars_per_word / 60) seconds, in whole ms rounded up, exactly (P004 3.10)."""
    per_minute = Fraction(str(rate_wpm)) * Fraction(str(chars_per_word))
    return -((-chars * 60000 * per_minute.denominator) // per_minute.numerator)


def _message(item):
    if not isinstance(item, dict) or not {"msgid", "lang", "kind", "text"} <= set(item) \
            or not set(item) <= {"msgid", "lang", "kind", "text", "max_expansion"}:
        _fail("dwell: a message is {msgid, lang, kind, text[, max_expansion]}, got %r" % (item,))
    for key in ("msgid", "lang", "kind", "text"):
        if not isinstance(item[key], str) or item[key].strip() == "":
            _fail("dwell: message %r has no usable %s" % (item.get("msgid"), key))
    return item


def dwell_table(contract, messages):
    """One row per (msgid, lang): characters as displayed, reading time, minimum dwell and the contract's timer.

    `messages` is an iterable of dicts {msgid, lang, kind, text, max_expansion}. Raises ContractPending while the
    reading rate is pending. A kind the contract has no timer for gets `lifetime_ms = None`.
    """
    rate = contract.get("reading", "rate_wpm")
    per_word = contract.get("thresholds", "dwell_chars_per_word")
    base = contract.get("thresholds", "dwell_base_ms")
    floor = contract.get("thresholds", "dwell_floor_ms")
    timers = {r["kind"]: r for r in contract.tables["timer"]}
    rows, seen = [], set()
    for item in sorted((_message(m) for m in messages), key=lambda m: (m["msgid"], m["lang"])):
        if (item["msgid"], item["lang"]) in seen:
            _fail("dwell: duplicate message %r in language %r" % (item["msgid"], item["lang"]))
        seen.add((item["msgid"], item["lang"]))
        chars = char_count(displayed_text(item["text"], item.get("max_expansion")))
        reading = reading_ms(chars, rate, per_word)
        timer = timers.get(item["kind"])
        rows.append(MappingProxyType({
            "msgid": item["msgid"], "lang": item["lang"], "kind": item["kind"], "chars": chars,
            "reading_ms": reading, "min_dwell_ms": max(floor, base + reading),
            "lifetime_ms": None if timer is None else timer["lifetime_ms"]}))
    return tuple(rows)


def dwell_findings(rows):
    """`dwell-below-reading-time` for a timed message shorter than its minimum (0 means untimed), and one
    `contract-incomplete` per timer kind the contract lacks."""
    found, missing = [], set()
    for row in rows:
        if row["lifetime_ms"] is None:
            missing.add(row["kind"])
        elif 0 < row["lifetime_ms"] < row["min_dwell_ms"]:
            found.append(findings.finding("dwell-below-reading-time", msgid=row["msgid"], lang=row["lang"],
                                          kind=row["kind"], lifetime_ms=row["lifetime_ms"],
                                          min_dwell_ms=row["min_dwell_ms"]))
    found.extend(findings.finding("contract-incomplete", what="timer-kind", name=kind) for kind in sorted(missing))
    return found
