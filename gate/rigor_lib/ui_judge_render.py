"""The `ui-render` judge (U07, P004 3.3): what is painted. One step judge over the scene (O2), the rendered tree
(O3) and, on the first usable visit of each abstract state and frame checksum, the ink of its frame (O4 through
lvprobe's `ink`; the explorer's InkPlan, docs/ui-judges-render.md). Every threshold is the contract's; a value the owner
has not decided is `contract-pending` for exactly what needs it, a definition the contract lacks is
`contract-incomplete`. The judge fails closed: what a check needs and lvprobe did not measure is `ink-unmeasurable`.

Ink checks (only on a step that carries ink):
- `invisible-node`: a shown scene node that must paint (a text or countdown with a text, a button or key, a card:
  dialog, banner, snackbar) that changes no pixel, decided by the ink: count 0 is part `node`, or `covered` when a
  later-painted, opaque, unrelated node contains its whole visible box (the cover named as the cause); a button's or
  key's text carrier with count 0 and a non-empty drawn text is part `text`. A count above 0 is no finding. A label
  lvprobe reports clipped (`observed.clipped`) is left to ui-fit only when ui-fit is selected and reports its
  `text-clipped` (no `clip` scope); then it is a counted not-applicable. Not applicable (counted) too: a node the
  scene marks inert (I) or that lies under a capture-modal-inert layer per R7 (the modal case).
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
        outside = ctx.frame.visible_box(index) is None and index not in ctx.frame.labels   # node-out-of-bounds'
        if node.hidden or not must or outside:
            continue
        if exempt(ctx, node, index):
            report.not_applicable("invisible-node")
            continue
        found = _part(ctx, report, ink, unmeasured, node, index)
        if found is None:
            continue
        if found == "fit":
            report.not_applicable("invisible-node")     # ui-fit reports this label's text-clipped
            continue
        report.examined("invisible-node")
        part, at, extra = found
        if part is not None:
            report.add("invisible-node", [node.key, part],
                       dict({"stage": "O2+O4", "key": node.key, "role": node.role, "part": part}, **extra),
                       target=node.key, records=[node.raw] + ctx.records(at) + [ink[at].raw])


def fit_reports_clipped(ctx, index):
    """ui-fit is selected and reports `text-clipped` on this label (ui_judge_fit: lvprobe's `clipped`, unless the
    owner's scope declares `clip`): then a label that paints nothing because it is clipped is that finding's cause."""
    fit = ctx.frame.fits.get(index)
    if "ui-fit" not in ctx.gates or fit is None or fit.unsupported or not fit.clipped:
        return False
    owner = ctx.assoc.owner.get(index)
    scope = ctx.scope_of(ctx.by_key[owner]) if owner is not None else None
    return not (scope is not None and scope["clip"])


def _part(ctx, report, ink, unmeasured, node, index):
    """(part or None for no finding, the rendered index it is about, extra observed), "fit" (ui-fit's text-clipped is
    the cause), or None (no verdict: not measured). The ink decides: a count above 0 is no finding whatever covers it
    (a rounded or transformed cover may not hide it); a count of 0 is `covered` when an opaque cover explains it."""
    frame = ctx.frame
    carrier = ctx.assoc.text.get(node.key)
    text = carrier not in (None, index) and frame.shown(carrier) and frame.labels[carrier].text != b""
    for at, what in zip([index] + ([carrier] if text else []), ("node", "text")):
        item = needs(ctx, report, ink, unmeasured, node, at, what)
        if item is None:
            return None
        if item.count > 0:
            continue
        if fit_reports_clipped(ctx, at):
            return "fit"
        extra = {"clipped": True} if at in frame.fits and frame.fits[at].clipped else {}
        cover = cover_of(ctx, at)
        if cover is not None:
            return "covered", at, dict(extra, covered=what, by=ctx.name_of(cover))
        return what, at, extra
    return None, index, {}
