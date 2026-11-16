"""The consistency checks of the UI contract loader (docs/ui-contract.md, "Consistency the loader enforces"): orderings of
the thresholds, references between tables, alignment and role minimums, timers and wrap rows. Split out of ui_contract
(U06 fix-up 3, the series' 500-line limit); no behaviour changed, and `ui_contract` re-exports the public names.
"""

from rigor_lib.errors import InternalError

EXTRA_ELEMENTS = frozenset(("countdown", "dismiss", "done", "cancel", "numpad", "language_switch",
                            "size_buttons"))

# Orderings P004 3.10 implies: the first value may not exceed the second (checked unless one is pending).
ORDER = (("touch_min_mm", "button_floor_mm"), ("button_floor_mm", "button_recommended_mm"),
         ("button_recommended_mm", "keypad_key_min_mm"), ("spacing_hard_mm", "spacing_recommended_mm"),
         ("feedback_target_frames", "feedback_rendered_frames_max"),
         ("busy_indicator_ms", "busy_progress_cancel_ms"), ("dwell_base_ms", "dwell_floor_ms"),
         ("contrast_large", "contrast_text"))


def _fail(why):
    raise InternalError("ui-contract: %s" % why)


def check_consistency(tables, scalars, pending):
    """Every check of this module; `pending` is the loader's Pending type."""
    _check_thresholds(scalars, pending)
    _check_refs(tables, scalars)
    _check_rows(tables)


def _check_thresholds(scalars, pending):
    values = {k: e.value for k, e in scalars["thresholds"].items()}
    for low, high in ORDER:
        if not isinstance(values[low], pending) and not isinstance(values[high], pending) and values[low] > values[high]:
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
