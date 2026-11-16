"""`contrast-low` of the `ui-render` judge (U07, P004 3.3; docs/ui-judges-render.md, "contrast-low").

For a shown text-bearing node with a typographic role and a drawn text, the ink of the label that carries its text:
- a carrier without a background of its own: ui_judge_render_ink.worst_contrast (the ink extreme farther from the
  background against the nearest point of the background interval);
- a carrier with an exactly opaque, single-colour background (`bg_opa_exact`, `bg_opa_drawn` 255, no gradient, no
  image): ui_judge_render_ink.against_fill, an upper bound, so only a finding is sound; when it does not fail, the
  node is `ink-unmeasurable` (`own-background`), as is every other carrier with a background of its own;
- not applicable (counted) to a text the scene marks inert or that lies under a capture-modal-inert layer per R7.
Thresholds, each read on its own: below `contrast_large` is a finding (the text fails at any size); at or above
`contrast_text` it passes; in between the contract's missing definition of large text is `contract-incomplete`
(`large-text`, the role). A pending threshold is `contract-pending`; the other one still decides what it can.
"""

from rigor_lib import ui_judge_render_stage as render_stage
from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_judge_render_common import exempt, needs
from rigor_lib.ui_judge_render_ink import against_fill, worst_contrast


def thresholds(ctx, report):
    """(contrast_large, contrast_text), each None while pending (then contract-pending)."""
    out = []
    for key in ("contrast_large", "contrast_text"):
        try:
            out.append(ctx.contract.get("thresholds", key))
        except ContractPending as error:
            report.pending("contrast-low", error)
            out.append(None)
    return tuple(out)


def decide(worst, large, text):
    """"fail" below the large-text floor, "pass" at or above the text threshold, "between" in between, or None when
    the threshold that would decide is pending. Both comparisons are strict below: a ratio equal to a threshold meets
    it."""
    if large is not None and worst < large:
        return "fail"
    if text is not None and worst >= text:
        return "pass"
    if large is None or text is None:
        return None
    return "between"


def own_fill(rendered):
    """None (the carrier draws no background of its own), its fill colour (exactly opaque, one colour), or
    "unsound"."""
    if rendered.bg_opa_drawn <= 0 and not rendered.bg_grad and not rendered.bg_image:
        return None
    if rendered.bg_opa_exact and rendered.bg_opa_drawn >= 255 and not rendered.bg_grad and not rendered.bg_image:
        return rendered.bg
    return "unsound"


def judge(ctx, report, ink, unmeasured):
    texts = render_stage.texts(ctx)
    if not texts:
        return
    large, text = thresholds(ctx, report)
    for node, carrier in texts:
        if exempt(ctx, node, carrier):
            report.not_applicable("contrast-low")
            continue
        item = needs(ctx, report, ink, unmeasured, node, carrier, "text")
        if item is None or item.count == 0:
            continue                           # nothing painted: invisible-node's
        _one(ctx, report, unmeasured, node, carrier, item, (large, text))


def _one(ctx, report, unmeasured, node, carrier, item, limits):
    fill = own_fill(ctx.frame.nodes[carrier])
    if fill == "unsound":
        unmeasured.setdefault(node.key, []).append(["text", "own-background"])
        return
    worst = against_fill(item, fill) if fill is not None else worst_contrast(item)
    verdict = decide(worst, *limits)
    if verdict is None:
        return                                 # the deciding threshold is pending (contract-pending)
    if fill is not None and verdict != "fail":
        unmeasured.setdefault(node.key, []).append(["text", "own-background"])
        return
    if verdict == "between":
        report.incomplete("large-text", ctx.role_of(node))
        return
    report.examined("contrast-low")
    if verdict == "fail":
        large, text = limits
        report.add("contrast-low", [node.key, "below-large"],
                   {"stage": "O2+O4", "key": node.key, "part": "below-large", "ratio": round(worst, 4),
                    "against": "own-fill" if fill is not None else "behind", "contrast_large": large,
                    "contrast_text": text, "ink": [item.ink_lo, item.ink_hi],
                    "behind": [fill] if fill is not None else [item.bg_lo, item.bg_hi]},
                   target=node.key, records=[node.raw] + ctx.records(carrier) + [item.raw])
