"""The L3 (stage conformance) checks of the `ui-render` judge (U07, P004 3.3) that read the rendered tree (O3: lvprobe's
`node` and `label` records) against the scene (O2) and the sealed contract; no ink. docs/ui-judges-render.md.

- `flag-mismatch`: LVGL's `hidden` against the scene's H (parts `hidden`, `shown`); `clickable` against what the scene
  says the node is: a disabled node (`enabled` 0 or D) or an inert one (I) that is clickable (`disabled-clickable`,
  `inert-clickable`); a node without an intent that is clickable (`clickable`), except a layer (scrim, dialog, banner,
  snackbar: whether its clickable scrim or card takes the taps is overlay-policy's); the long mode of the label that
  carries a text node's text against its wrap scope (`long-mode`). The other direction, an intent whose rendered node is
  not clickable, is already ui-scene's `stage-unmatched` (the association pairs a node with an intent only with a
  clickable object).
- `align-mismatch`: the text alignment LVGL draws (`align_drawn`) against the `[[role]]` alignment of the node's
  typographic role (`align_banner` inside a banner when the role has one).
- `line-height-mismatch` (an APPROXIMATION of P004's `font-size-mismatch`, under its own id): the line height of the
  label above the `[[style_line]]` baseline of the owner's style; below it is ui-fit's `font-shrunk`.
"""

from rigor_lib.ui_judge_vocab import LAYER_ROLES

LONG_WRAP, LONG_DOTS, LONG_SCROLL, LONG_SCROLL_CIRCULAR, LONG_CLIP = range(5)   # lv_label_long_mode_t (LVGL 9)
LONG_NAMES = ("wrap", "dots", "scroll", "scroll_circular", "clip")
ALIGN_CODES = {"left": 1, "centre": 2}                                       # lv_text_align_t: LEFT 1, CENTER 2
ALIGN_NAMES = ("auto", "left", "centre", "right")


def judge(ctx, report):
    for node in ctx.scene:
        if node.key in ctx.assoc.match:
            _flags(ctx, report, node, ctx.assoc.match[node.key])
    for node, carrier in texts(ctx):
        _long_mode(ctx, report, node, carrier)
        _align(ctx, report, node, carrier)
        _line_height(ctx, report, node, carrier)


def texts(ctx):
    """(scene node, the rendered label carrying its text) of every shown text-bearing node with a typographic role whose
    text is drawn (non-empty) by an associated, shown label."""
    out = []
    for node in ctx.scene:
        carrier = ctx.assoc.text.get(node.key)
        if node.hidden or carrier is None or ctx.role_of(node) is None or not ctx.frame.shown(carrier):
            continue
        if ctx.frame.labels[carrier].own_text != b"":
            out.append((node, carrier))
    return out


def _who(ctx, node, index, carrier=None):
    records = [node.raw] + ctx.records(index) + (ctx.records(carrier) if carrier not in (None, index) else [])
    return {"stage": "O2+O3", "key": node.key, "role": node.role}, records


def _flags(ctx, report, node, index):
    rendered, shown = ctx.frame.nodes[index], ctx.frame.shown(index)
    report.examined("flag-mismatch")
    base, records = _who(ctx, node, index)
    if node.hidden == shown:
        part = "shown" if node.hidden else "hidden"
        report.add("flag-mismatch", [node.key, part], dict(base, part=part, scene_hidden=node.hidden,
                                                             rendered_shown=shown), target=node.key, records=records)
    if node.hidden or not shown or not rendered.clickable:
        return
    if not node.enabled or "D" in node.flags:
        part = "disabled-clickable"
    elif "I" in node.flags:
        part = "inert-clickable"
    elif node.intent == "-" and node.role not in LAYER_ROLES:
        part = "clickable"
    else:
        return
    report.add("flag-mismatch", [node.key, part], dict(base, part=part, intent=node.intent != "-",
                                                         enabled=node.enabled, flags="".join(sorted(node.flags))),
               target=node.key, records=records)


def expected_long_mode(scope):
    """The LVGL long mode a `[[wrap]]` scope needs: an ellipsis is DOTS, a clip CLIP, any other scope WRAP (a `none`
    scope included: LVGL has no non-wrapping mode that does not cut the text; a single line that does not fit its rect
    is ui-fit's `text-overflow`)."""
    if scope["ellipsis"]:
        return LONG_DOTS
    if scope["clip"]:
        return LONG_CLIP
    return LONG_WRAP


def _long_mode(ctx, report, node, carrier):
    scope = ctx.scope_of(node)
    if scope is None:
        return                                  # contract-incomplete (role-wrap): the stage's
    report.examined("flag-mismatch")
    label, want = ctx.frame.labels[carrier], expected_long_mode(scope)
    if label.long_mode != want:
        base, records = _who(ctx, node, ctx.assoc.match[node.key], carrier)
        got = LONG_NAMES[label.long_mode] if 0 <= label.long_mode < len(LONG_NAMES) else str(label.long_mode)
        report.add("flag-mismatch", [node.key, "long-mode"],
                   dict(base, part="long-mode", scope=scope["scope"], long=got, expected=LONG_NAMES[want]),
                   target=node.key, records=records)


def in_banner(ctx, index):
    """Whether a rendered node lies inside (or is) the rendered node of a scene node of role banner."""
    banners = {i for key, i in ctx.assoc.match.items() if ctx.by_key[key].role == "banner"}
    return any(i in banners for i in [index] + ctx.frame.ancestors(index))


def _align(ctx, report, node, carrier):
    fit = ctx.frame.fits.get(carrier)
    if fit is None or fit.unsupported or not fit.drawn:
        return                                  # no draw task: lvprobe knows no drawn alignment
    row = ctx.contract.row("role", ctx.role_of(node))
    banner = in_banner(ctx, carrier)
    want = row["align_banner"] if banner and "align_banner" in row else row["align"]
    label = ctx.frame.labels[carrier]
    report.examined("align-mismatch")
    if label.align_drawn != ALIGN_CODES[want]:
        base, records = _who(ctx, node, ctx.assoc.match[node.key], carrier)
        name = ALIGN_NAMES[label.align_drawn] if 0 <= label.align_drawn < 4 else str(label.align_drawn)
        report.add("align-mismatch", [node.key], dict(base, align_drawn=name, expected=want, in_banner=banner,
                                                      typographic_role=ctx.role_of(node)),
                   target=node.key, records=records)


def _line_height(ctx, report, node, carrier):
    style = ctx.style_of(node)
    row = next((r for r in ctx.contract.rows("style_line") if r["style"] == style), None)
    if row is None:
        report.incomplete("style-line", style)
        return
    report.examined("line-height-mismatch")
    label = ctx.frame.labels[carrier]
    if label.line_h > row["line_height_px"]:
        base, records = _who(ctx, node, ctx.assoc.match[node.key], carrier)
        report.add("line-height-mismatch", [node.key], dict(base, part="above", line_h=label.line_h,
                                                            baseline_line_h=row["line_height_px"],
                                                            basis=row["provenance"]),
                   target=node.key, records=records)
