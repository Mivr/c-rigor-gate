"""The `ui-fit` judge (U06, P004 3.2): text fit from the rendered facts of every label of the frame (O3, lvprobe's `label`
and `fit` records), with the owner's rect (O2) and the wrap scope (its element's, else its typographic role's) and the
line-height baseline the contract gives its style, where a scene node owns the label (ui_judge_vocab).

Per label, fail closed: a label lvprobe could not measure (`unsupported`, or no `fit` record) is `fit-unmeasurable`
and nothing else is judged on it; placeholder glyphs are `glyph-missing`. Then `text-clipped` (lvprobe's `clipped`),
`full-string-shown` (LVGL's dots), and, for an owned label, `text-overflow` (against the owner's rect and scope) and
`font-shrunk` (its line height against the `[[style_line]]` regression baseline of its style). A label no scene node
owns is judged by class, box and text hash, on everything but text-overflow and font-shrunk; it is `stage-unmatched`.
"""


def judge(ctx, report):
    lines = {row["style"]: (row["line_height_px"], row["provenance"]) for row in ctx.contract.rows("style_line")}
    for index in sorted(ctx.frame.labels):
        _label(ctx, report, index, lines)
    return report.found


def _who(ctx, index):
    """(identity, observed part, exception target, owner node) of a label."""
    key = ctx.assoc.owner.get(index)
    if key is not None:
        return [key], {"key": key}, key, ctx.by_key[key]
    name = ctx.rendered_name(index)
    return ["label", name["target"]], {"label": name}, name["target"], None


def _label(ctx, report, index, lines):
    frame = ctx.frame
    label, fit = frame.labels[index], frame.fits.get(index)
    if label.own_text == b"" or not frame.shown(index):
        return
    identity, who, target, owner = _who(ctx, index)
    scope = ctx.scope_of(owner) if owner is not None else None   # None: contract-incomplete (the stage's)
    records = ctx.records(index) + ([owner.raw] if owner is not None else [])
    base = dict(who, stage="O3" if owner is None else "O2+O3")
    report.examined("fit-unmeasurable")
    if fit is None or fit.unsupported:
        report.add("fit-unmeasurable", identity + ["facts"], dict(base, reason="unsupported" if fit else "no-fit"),
                   target=target, records=records)
        return
    for check in ("glyph-missing", "text-clipped", "full-string-shown"):
        report.examined(check)
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
    """The label's line height below the `[[style_line]]` line height of the owner's style: a REGRESSION BASELINE read
    from the product (provenance `product-baseline:<commit>`), not a spec value; the finding says so."""
    style = ctx.style_of(owner)
    if style not in lines:
        report.incomplete("style-line", style)
        return
    report.examined("font-shrunk")
    height, provenance = lines[style]
    if label.line_h < height:
        report.add("font-shrunk", identity, dict(base, line_h=label.line_h, baseline_line_h=height,
                                                 basis=provenance), target=target, records=records)


def _overflow(report, identity, base, target, records, owner, scope, label):
    """At the font the label is rendered with: single-line scope (`wrap = none`): the natural width above the owner's
    width; a wrapping scope: the laid-out height above the owner's height, or more lines than `max_lines` (0: no cap).
    A scope that declares an ellipsis or a clip makes the excess intended."""
    if scope["ellipsis"] or scope["clip"]:
        return                        # the excess is intended: no comparison, no verdict counted
    report.examined("text-overflow")
    if scope["wrap"] == "none":
        if label.natural[0] > owner.w:
            report.add("text-overflow", identity, dict(base, part="width", natural_w=label.natural[0],
                                                       rect_w=owner.w), target=target, records=records)
        return
    if label.laid[1] > owner.h or (scope["max_lines"] and label.lines > scope["max_lines"]):
        report.add("text-overflow", identity, dict(base, part="height", laid_h=label.laid[1], lines=label.lines,
                                                   rect_h=owner.h, max_lines=scope["max_lines"]),
                   target=target, records=records)
