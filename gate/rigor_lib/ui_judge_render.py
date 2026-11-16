"""The `ui-render` judge (U07, P004 3.3): what is painted. One step judge over the scene (O2), the rendered tree
(O3) and, on the first usable visit of each abstract state and frame checksum, the ink of its frame (O4 through
lvprobe's `ink`; the explorer's InkPlan, docs/ui-judges-render.md). Every threshold is the contract's; a value the owner
has not decided is `contract-pending` for exactly what needs it, a definition the contract lacks is
`contract-incomplete`. The judge fails closed: what a check needs and lvprobe did not measure is `ink-unmeasurable`.

Ink checks (only on a step that carries ink):
- `invisible-node`: a shown scene node that must paint (a text or countdown with a text, a button or key, a card:
  dialog, banner, snackbar) that changes no pixel: part `node` (its ink count is 0), `covered` (a later-painted,
  opaque, unrelated node contains its whole visible box, so no pixel of it can change; the cover is named), `text` (a
  button's or key's label, its text carrier, paints nothing although its text is not empty and lvprobe does not report
  it clipped, which is ui-fit's `text-clipped`). Not applicable (counted)
  to a node the scene marks inert (I) or that lies under a capture-modal-inert layer per R7 (the modal case).
- `contrast-low`: ui_judge_render_contrast.
- `ink-unmeasurable` (error): a node one of these checks needs whose ink lvprobe did not measure (`noink unstable`,
  `noink transformed`), every needed node of a state whose frame moved under the ink, and a text carrier that draws
  its own background where no sound verdict is possible (`own-background`); no other ink verdict on it.
Stage checks (every step, no ink): ui_judge_render_stage.
"""

from rigor_lib import ui_judge_render_contrast as contrast
from rigor_lib import ui_judge_render_stage as render_stage
from rigor_lib.ui_judge_render_common import cover_of, exempt, needs
from rigor_lib.ui_judge_render_ink import parse_ink
from rigor_lib.ui_judge_vocab import CARD_ROLES, PURE_TEXT

MUST_PAINT = frozenset(("button", "key")) | frozenset(CARD_ROLES)


def judge(ctx, report):
    render_stage.judge(ctx, report)
    if ctx.ink_records is None:
        return report.found                    # a later visit of a state already inked: no ink, no ink verdict
    ink = parse_ink(ctx.ink_records, ctx.frame)
    unmeasured = {}                            # key -> [(what, reason)]
    _invisible(ctx, report, ink, unmeasured)
    contrast.judge(ctx, report, ink, unmeasured)
    for node in ctx.scene:
        if node.key in unmeasured:
            report.add("ink-unmeasurable", [node.key], {"stage": "O4", "key": node.key, "role": node.role,
                                                        "unmeasured": unmeasured[node.key]},
                       target=node.key, records=[node.raw])
    return report.found


def _invisible(ctx, report, ink, unmeasured):
    for node, index in ctx.matched():
        must = node.role in MUST_PAINT or (node.role in PURE_TEXT and node.label != b"")
        if node.hidden or not must or ctx.frame.visible_box(index) is None:
            continue
        if exempt(ctx, node, index):
            report.not_applicable("invisible-node")
            continue
        found = _part(ctx, report, ink, unmeasured, node, index)
        if found is None:
            continue
        report.examined("invisible-node")
        part, at, extra = found
        if part is not None:
            records = [node.raw] + ctx.records(at) + ([ink[at].raw] if part != "covered" else [])
            report.add("invisible-node", [node.key, part],
                       dict({"stage": "O2+O4", "key": node.key, "role": node.role, "part": part}, **extra),
                       target=node.key, records=records)


def _part(ctx, report, ink, unmeasured, node, index):
    """(part or None for no finding, the rendered index it is about, extra observed), or None (no verdict)."""
    carrier = ctx.assoc.text.get(node.key)
    frame = ctx.frame
    fit = frame.fits.get(carrier) if carrier is not None else None
    # a label lvprobe reports clipped is ui-fit's `text-clipped` (one cause, one finding)
    text = carrier not in (None, index) and frame.shown(carrier) and not (fit and fit.clipped) \
        and frame.visible_box(carrier) is not None and frame.labels[carrier].text != b""
    checked = [index] + ([carrier] if text else [])
    for at, what in zip(checked, ("node", "text")):
        cover = cover_of(ctx, at)
        if cover is not None:
            return "covered", at, {"covered": what, "by": ctx.name_of(cover)}
        item = needs(ctx, report, ink, unmeasured, node, at, what)
        if item is None:
            return None
        if item.count == 0:
            return what, at, {}
    return None, index, {}
