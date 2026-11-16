"""The `ui-fit` judge (U06, P004 3.2): text fit from the rendered facts of every label of the frame (O3, lvprobe's `label`
and `fit` records), with the owner's rect (O2) and the wrap scope and line height the contract gives its typographic
role and style, where a scene node owns the label (ui_judge_vocab).

Per label, fail closed: a label lvprobe could not measure (`unsupported`, or no `fit` record) is `fit-unmeasurable`
and nothing else is judged on it; placeholder glyphs are `glyph-missing`. Then `text-clipped` (lvprobe's `clipped`),
`full-string-shown` (LVGL's dots), and, for an owned label, `text-overflow` (against the owner's rect and its role's
scope) and `font-shrunk` (its line height against the contract's `[[style_line]]` for its style). A label no scene node
owns is judged by class, box and text hash, on everything but text-overflow and font-shrunk; it is `stage-unmatched`.
"""

from rigor_lib.ui_contract import ContractPending


def judge(ctx, report):
    scopes = {row["scope"]: row for row in ctx.contract.rows("wrap")}
    lines = {row["style"]: row["line_height_px"] for row in ctx.contract.rows("style_line")}
    for index in sorted(ctx.frame.labels):
        _label(ctx, report, index, scopes, lines)
    return report.found


def _who(ctx, index):
    """(identity, observed part, exception target, owner node) of a label."""
    key = ctx.assoc.owner.get(index)
    if key is not None:
        return [key], {"key": key}, key, ctx.by_key[key]
    name = ctx.rendered_name(index)
    return ["label", name["target"]], {"label": name}, name["target"], None


def _scope(ctx, report, owner, scopes):
    """The wrap scope row of the owner's typographic role; None (reported) when it cannot be had."""
    role = ctx.role_of(owner) if owner is not None else None
    if role is None:
        return None
    rows = [row for row in ctx.contract.rows("role_wrap") if row["role"] == role]
    if not rows:
        report.incomplete("role-wrap", role)      # ui-scene reports it as wrap-policy-undeclared too
        return None
    try:
        return scopes[ctx.contract.row_value("role_wrap", role, "scope")]
    except ContractPending as error:
        report.pending("text-overflow", error, whole=False)
        return None


def _label(ctx, report, index, scopes, lines):
    frame = ctx.frame
    label, fit = frame.labels[index], frame.fits.get(index)
    if label.own_text == b"" or not frame.shown(index):
        return
    identity, who, target, owner = _who(ctx, index)
    scope = _scope(ctx, report, owner, scopes)
    records = ctx.records(index) + ([owner.raw] if owner is not None else [])
    base = dict(who, stage="O3" if owner is None else "O2+O3")
    for check in ("fit-unmeasurable", "glyph-missing", "text-clipped", "full-string-shown"):
        report.examined(check)
    if fit is None or fit.unsupported:
        report.add("fit-unmeasurable", identity + ["facts"], dict(base, reason="unsupported" if fit else "no-fit"),
                   target=target, records=records)
        return
    if fit.missing > 0:
        report.add("glyph-missing", identity, dict(base, missing=fit.missing), target=target, records=records)
    if fit.clipped and not (scope is not None and scope["clip"]):
        report.add("text-clipped", identity, dict(base, drawn=fit.drawn), target=target, records=records)
    if label.dotted and not (scope is not None and scope["ellipsis"]):
        report.add("full-string-shown", identity, dict(base, part="dotted"), target=target, records=records)
    if owner is not None and ctx.role_of(owner) is not None:
        _font(ctx, report, identity, base, target, records, owner, label, lines)
        if scope is not None:
            _overflow(report, identity, base, target, records, owner, scope, label)


def _font(ctx, report, identity, base, target, records, owner, label, lines):
    """The label's line height below the contract's line height of the owner's style (`[[style_line]]`)."""
    style = ctx.style_of(owner)
    if style not in lines:
        report.incomplete("style-line", style)
        return
    report.examined("font-shrunk")
    if label.line_h < lines[style]:
        report.add("font-shrunk", identity, dict(base, line_h=label.line_h, contract_line_h=lines[style]),
                   target=target, records=records)


def _overflow(report, identity, base, target, records, owner, scope, label):
    """At the font the label is rendered with: single-line scope (`wrap = none`): the natural width above the owner's
    width; a wrapping scope: the laid-out height above the owner's height, or more lines than `max_lines` (0: no cap).
    A scope that declares an ellipsis or a clip makes the excess intended."""
    report.examined("text-overflow")
    if scope["ellipsis"] or scope["clip"]:
        return
    if scope["wrap"] == "none":
        if label.natural[0] > owner.w:
            report.add("text-overflow", identity, dict(base, part="width", natural_w=label.natural[0],
                                                       rect_w=owner.w), target=target, records=records)
        return
    if label.laid[1] > owner.h or (scope["max_lines"] and label.lines > scope["max_lines"]):
        report.add("text-overflow", identity, dict(base, part="height", laid_h=label.laid[1], lines=label.lines,
                                                   rect_h=owner.h, max_lines=scope["max_lines"]),
                   target=target, records=records)
