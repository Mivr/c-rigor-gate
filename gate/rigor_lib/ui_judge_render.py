"""The `ui-render` judge (U07, P004 3.3): what is painted. One step judge over the scene (O2), the rendered tree
(O3) and, on the first visit of each abstract state, the ink of its frame (O4 through lvprobe's `ink`; the explorer
takes it once per state key, docs/ui-judges-render.md). Every threshold is the contract's; a value the owner has not
decided is `contract-pending` for exactly what needs it, a definition the contract lacks is `contract-incomplete`.

Ink checks (only on a step that carries ink):
- `invisible-node`: a shown scene node that must paint (a text or countdown with a text, a button or key, a card:
  dialog, banner, snackbar) whose associated rendered node changes no pixel, unless a later-painted opaque node covers
  its whole visible box (then no pixel of it can change: covered, which is `covered-node`'s, blocked).
- `contrast-low`: the worst-case contrast of a text node's ink (ui_judge_render_ink.worst_contrast) below
  `thresholds.contrast_large`: below the large-text floor the text fails at any size. Between `contrast_large` and
  `contrast_text` the verdict needs the contract's definition of large text, which the contract does not have: that
  node is no verdict and the role is `contract-incomplete` (`large-text`).
- `ink-unmeasurable` (info): a node one of these checks needs whose ink lvprobe did not measure (`noink unstable`,
  `noink transformed`), or every node of a state whose frame moved under the ink; no other ink verdict on it.
Stage checks (every step, no ink): ui_judge_render_stage.
"""

from rigor_lib import ui_judge_render_stage as render_stage
from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_judge_render_ink import parse_ink, worst_contrast
from rigor_lib.ui_judge_stage import inside
from rigor_lib.ui_judge_vocab import CARD_ROLES, PURE_TEXT

MUST_PAINT = frozenset(("button", "key")) | frozenset(CARD_ROLES)


def judge(ctx, report):
    render_stage.judge(ctx, report)
    if ctx.ink_records is None:
        return report.found                    # a later visit of a state already inked: no ink, no ink verdict
    ink = parse_ink(ctx.ink_records, ctx.frame)
    unmeasured = {}                            # key -> [(what, reason)]
    _invisible(ctx, report, ink, unmeasured)
    _contrast(ctx, report, ink, unmeasured)
    for node in ctx.scene:
        if node.key in unmeasured:
            report.add("ink-unmeasurable", [node.key], {"stage": "O4", "key": node.key, "role": node.role,
                                                        "unmeasured": unmeasured[node.key]},
                       target=node.key, severity="info", records=[node.raw])
    return report.found


def _needs(ctx, report, ink, unmeasured, node, index, what):
    """The ink of `index` for a check, or None (not measured: ink-unmeasurable, counted as its verdict)."""
    report.examined("ink-unmeasurable")
    reason = "frame-moved" if ctx.ink_moved else ink[index].reason
    if reason is not None:
        unmeasured.setdefault(node.key, []).append([what, reason])
        return None
    return ink[index]


def covered(ctx, index):
    """A later-painted, shown, unrelated node with an exactly opaque background contains the node's visible box: no
    pixel of the node can change when it is hidden (corner radii are not in the facts; such a cover is taken whole)."""
    frame = ctx.frame
    box = frame.visible_box(index)
    for other in frame.nodes[frame.end[index] + 1:]:
        if frame.related(index, other.index) or not frame.shown(other.index):
            continue
        cover = frame.visible_box(other.index)
        if other.bg_opa_exact and other.bg_opa_drawn >= 255 and cover is not None and inside(box, cover):
            return True
    return False


def _invisible(ctx, report, ink, unmeasured):
    for node, index in ctx.matched():
        must = node.role in MUST_PAINT or (node.role in PURE_TEXT and node.label != b"")
        if node.hidden or not must or ctx.frame.visible_box(index) is None or covered(ctx, index):
            continue
        item = _needs(ctx, report, ink, unmeasured, node, index, "node")
        if item is None:
            continue
        report.examined("invisible-node")
        if item.count == 0:
            report.add("invisible-node", [node.key], {"stage": "O2+O4", "key": node.key, "role": node.role},
                       target=node.key, records=[node.raw] + ctx.records(index) + [item.raw])


def _thresholds(ctx, report):
    try:
        return (ctx.contract.get("thresholds", "contrast_large"), ctx.contract.get("thresholds", "contrast_text"))
    except ContractPending as error:
        report.pending("contrast-low", error)
        return None


def _contrast(ctx, report, ink, unmeasured):
    texts = render_stage.texts(ctx)
    limits = _thresholds(ctx, report) if texts else None
    if limits is None:
        return
    large, text = limits
    for node, carrier in texts:
        item = _needs(ctx, report, ink, unmeasured, node, carrier, "text")
        if item is None or item.count == 0:
            continue                           # nothing painted: invisible-node's (or covered)
        worst = worst_contrast(item)
        if large <= worst < text:
            report.incomplete("large-text", ctx.role_of(node))
            continue
        report.examined("contrast-low")
        if worst < large:
            report.add("contrast-low", [node.key, "below-large"],
                       {"stage": "O2+O4", "key": node.key, "part": "below-large", "ratio": round(worst, 4),
                        "contrast_large": large, "contrast_text": text, "ink": [item.ink_lo, item.ink_hi],
                        "behind": [item.bg_lo, item.bg_hi]},
                       target=node.key, records=[node.raw] + ctx.records(carrier) + [item.raw])
