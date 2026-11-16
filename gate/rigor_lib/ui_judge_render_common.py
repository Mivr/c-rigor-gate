"""What the ink checks of the `ui-render` judge share (U07): the ink a check needs (or `ink-unmeasurable`), the
opaque cover of a node, and R7 for what is painted (docs/ui-judges-render.md)."""

from rigor_lib.ui_judge_stage import inside


def needs(ctx, report, ink, unmeasured, node, index, what):
    """The ink of `index` for a check, or None (not measured: ink-unmeasurable, counted as its verdict)."""
    report.examined("ink-unmeasurable")
    reason = "frame-moved" if ctx.ink_moved else ink[index].reason
    if reason is not None:
        unmeasured.setdefault(node.key, []).append([what, reason])
        return None
    return ink[index]


def cover_of(ctx, index):
    """The first later-painted, shown, unrelated node with an exactly opaque background that contains the node's
    visible box (no pixel of the node can change when it is hidden; corner radii are not in the facts, such a cover is
    taken whole), or None."""
    frame = ctx.frame
    box = frame.visible_box(index)
    if box is None:
        return None
    for other in frame.nodes[frame.end[index] + 1:]:
        if frame.related(index, other.index) or not frame.shown(other.index):
            continue
        cover = frame.visible_box(other.index)
        if other.bg_opa_exact and other.bg_opa_drawn >= 255 and cover is not None and inside(box, cover):
            return other.index
    return None


def exempt(ctx, node, index):
    """R7 for what is painted: the scene marks the node inert, or a capture-modal-inert layer's rendered scrim (or card
    without one), painted later, clickable and drawn with a background opacity above 0, contains its visible box."""
    if "I" in node.flags:
        return True
    frame, box = ctx.frame, ctx.frame.visible_box(index)
    for _layer, shield, _parts, policy in ctx.layers():
        rendered = frame.nodes[shield]
        if policy != "capture-modal-inert" or shield <= index or frame.related(index, shield) \
                or not rendered.clickable or rendered.bg_opa_drawn <= 0 or not frame.shown(shield):
            continue
        cover = frame.visible_box(shield)
        if box is not None and cover is not None and inside(box, cover):
            return True
    return False
