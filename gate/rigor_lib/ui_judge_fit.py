"""The `ui-fit` judge (U06, P004 3.2): text fit from the rendered facts of every label of the frame (O3, lvprobe's `label`
and `fit` records), with the scene's rect and wrap scope (O2) where a scene node owns the label (ui_judge_stage).

Per label, fail closed: a label lvprobe could not measure (`unsupported`, or no `fit` record) is `fit-unmeasurable`
and nothing else is judged on it; placeholder glyphs are `glyph-missing`. Then `text-clipped` (lvprobe's `clipped`),
`full-string-shown` (LVGL's dots), and, for an owned label, `text-overflow` against the owner's rect and wrap scope.
A label no scene node owns is judged on everything but text-overflow (it has no declared rect or scope) and is
`stage-unmatched` (ui_judge_context). `font-shrunk` is blocked (docs/ui-judges.md): lvprobe maps no font.
"""


def judge(ctx, report):
    scopes = {row["scope"]: row for row in ctx.contract.rows("wrap")}
    for index in sorted(ctx.frame.labels):
        _label(ctx, report, index, scopes)
    return report.found


def _who(ctx, index):
    """(identity, observed part, exception target) of a label: its owner's key, or its walk index."""
    key = ctx.assoc.owner.get(index)
    if key is not None:
        return [key], {"key": key}, key
    return ["index", index], {"index": index}, None


def _label(ctx, report, index, scopes):
    frame = ctx.frame
    label, fit = frame.labels[index], frame.fits.get(index)
    identity, who, target = _who(ctx, index)
    owner = ctx.by_key.get(who.get("key"))
    scope = scopes.get(owner.wrap_policy) if owner is not None else None
    records = ctx.records(index) + ([owner.raw] if owner is not None else [])
    base = dict(who, stage="O3" if owner is None else "O2+O3")
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
    if owner is not None and frame.shown(index) and label.own_text != b"":
        _overflow(report, identity, base, target, records, owner, scope, label)


def _overflow(report, identity, base, target, records, owner, scope, label):
    """At the font the label is rendered with: single-line scope (`wrap = none`): the natural width above the owner's
    width; a wrapping scope: the laid-out height above the owner's height, or more lines than `max_lines` (0: no cap).
    A scope that declares an ellipsis or a clip makes the excess intended. No scope: fit-unmeasurable."""
    if scope is None:
        report.add("fit-unmeasurable", identity + ["scope"], dict(base, reason="no-wrap-scope"), target=target,
                   records=records)
        return
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
