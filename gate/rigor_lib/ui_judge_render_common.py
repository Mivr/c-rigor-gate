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
    """R7 for what is painted: the context's own inertness predicate (ui_judge_context.Context.inert) at the four
    corners of the node's visible box. Exact for a box: a rectangle contains a box exactly when it contains its four
    corners. A node with no visible box is exempt only when the scene marks it inert (I)."""
    box = ctx.frame.visible_box(index)
    corners = [] if box is None else [(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    return ctx.inert(node, index, corners)
