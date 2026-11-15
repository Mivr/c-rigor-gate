"""The `ui-scene` judge (U06, P004 3.1): one step judge over the scene (O2) and, where the scene lacks the tree, the rendered
tree it is associated with (O3). Every threshold is read from the UI contract at the step; a value the owner has not
decided is `contract-pending` for that check (or that part), never a default.

Checks on O2 alone: touch-target-small, font-below-min, hierarchy-violated, raw-text, wrap-policy-undeclared.
Checks on O2 + O3 (geometry, paint order and ancestry come from the associated rendered nodes, ui_judge_geom):
occluded-target, overlay-policy, target-spacing, node-out-of-bounds, text-overlap.
Blocked (docs/ui-judges.md, "Honesty table"): value-split, required-element-missing, toggle-group-indistinct.
"""

from fractions import Fraction

from rigor_lib import ui_judge_geom as geom
from rigor_lib.ui_contract import ContractPending


def judge(ctx, report):
    for check in (touch_target_small, font_below_min, hierarchy_violated, raw_text, wrap_policy_undeclared,
                  geom.occluded_target, geom.overlay_policy, geom.target_spacing, geom.node_out_of_bounds,
                  geom.text_overlap):
        check(ctx, report)
    return report.found


def _shown_texts(ctx):
    return [node for node in ctx.scene if ctx.is_text(node) and not node.hidden]


def touch_target_small(ctx, report):
    """O2: an interactive node (intent, enabled, not inert, not hidden) narrower or lower than the larger of
    `thresholds.touch_min_dp` and its role's `role_min.touch_dp_min` (scene px = dp); and, once the panel is sealed,
    than `thresholds.touch_min_mm`."""
    contract = ctx.contract
    floor = contract.get("thresholds", "touch_min_dp")
    minimum = {row["role"]: row["touch_dp_min"] for row in contract.rows("role_min")}
    try:
        mm_px = contract.mm_to_px(contract.get("thresholds", "touch_min_mm"))
    except ContractPending as error:
        report.pending("touch-target-small", error)
        mm_px = None
    for node in ctx.scene:
        if node.hidden or not node.interactive:
            continue
        need = max(floor, minimum.get(node.role, 0))
        if node.w < need or node.h < need:
            report.add("touch-target-small", [node.key, "dp"],
                       {"stage": "O2", "key": node.key, "unit": "dp", "w": node.w, "h": node.h, "limit": need},
                       target=node.key, records=[node.raw])
        if mm_px is not None and (node.w < mm_px or node.h < mm_px):
            report.add("touch-target-small", [node.key, "mm"],
                       {"stage": "O2", "key": node.key, "unit": "mm", "w": node.w, "h": node.h, "limit_px": mm_px},
                       target=node.key, records=[node.raw])


def font_below_min(ctx, report):
    """O2: a shown text node whose style's font size (`type_scale` of the style's `scale`) is below its role's
    `role_min.font_px_min`. A role with no role_min row is `contract-incomplete`."""
    minimum = {row["role"]: row["font_px_min"] for row in ctx.contract.rows("role_min")}
    for node in _shown_texts(ctx):
        if node.role not in minimum:
            report.add("contract-incomplete", ["role-min", node.role], {"what": "role-min", "name": node.role},
                       stateless=True)
            continue
        size = ctx.contract.style_px(node.style)
        if size < minimum[node.role]:
            report.add("font-below-min", [node.key], {"stage": "O2", "key": node.key, "font_px": size,
                                                      "limit": minimum[node.role]},
                       target=node.key, records=[node.raw])


def _hierarchy_inputs(ctx, report):
    levels = k = None
    try:
        levels = {role: row["level"] for row in ctx.contract.rows("importance") for role in row["roles"]}
    except ContractPending as error:
        report.pending("hierarchy-violated", error)
    try:
        k = Fraction(str(ctx.contract.get("thresholds", "hierarchy_ratio_k")))
    except ContractPending as error:
        report.pending("hierarchy-violated", error)
    return levels, k


def hierarchy_violated(ctx, report):
    """O2, per state: every shown text node declares the importance level the contract gives its role; at most 3
    levels; the smallest level-1 font is the largest of all and at least k times the largest level-2 font; text nodes
    of two or more roles show at least two font sizes."""
    levels, k = _hierarchy_inputs(ctx, report)
    if levels is None or k is None:
        return
    texts = _shown_texts(ctx)
    declared = []
    for node in texts:
        if node.importance is None:
            report.add("hierarchy-violated", [node.key, "undeclared"], {"stage": "O2", "key": node.key,
                                                                        "part": "undeclared"},
                       target=node.key, records=[node.raw])
        elif node.role not in levels:
            report.add("contract-incomplete", ["importance", node.role], {"what": "importance", "name": node.role},
                       stateless=True)
        elif node.importance != levels[node.role]:
            report.add("hierarchy-violated", [node.key, "level"], {"stage": "O2", "key": node.key, "part": "level",
                                                                   "declared": node.importance,
                                                                   "contract": levels[node.role]},
                       target=node.key, records=[node.raw])
        else:
            declared.append(node)
    _ranks(ctx, report, declared, k)
    sizes = {ctx.contract.style_px(node.style) for node in texts}
    if len({node.role for node in texts}) >= 2 and len(sizes) < 2:
        report.add("hierarchy-violated", ["single-size"], {"stage": "O2", "part": "single-size",
                                                           "roles": len({n.role for n in texts})},
                   records=[node.raw for node in texts])


def _ranks(ctx, report, declared, k):
    size = {node.key: ctx.contract.style_px(node.style) for node in declared}
    distinct = sorted({node.importance for node in declared})
    if len(distinct) > 3:
        report.add("hierarchy-violated", ["levels"], {"stage": "O2", "part": "levels", "levels": distinct},
                   records=[node.raw for node in declared])
    first = [node for node in declared if node.importance == 1]
    if not first:
        return
    top = min(size[node.key] for node in first)
    others = [node for node in declared if node.importance != 1]
    over = sorted(node.key for node in others if size[node.key] > top)
    second = [size[node.key] for node in others if node.importance == 2]
    if over:
        report.add("hierarchy-violated", ["rank"], {"stage": "O2", "part": "rank", "level1_px": top, "larger": over},
                   records=[node.raw for node in declared])
    elif second and Fraction(top) < k * max(second):
        report.add("hierarchy-violated", ["ratio"], {"stage": "O2", "part": "ratio", "level1_px": top,
                                                     "level2_px": max(second), "k": str(k)},
                   records=[node.raw for node in declared])


def raw_text(ctx, report):
    """O2: a shown text node whose formatted string is empty. (The raw-msgid half is blocked: O2 has no msgid.)"""
    for node in _shown_texts(ctx):
        if node.label == b"":
            report.add("raw-text", [node.key, "empty"], {"stage": "O2", "key": node.key, "part": "empty"},
                       target=node.key, records=[node.raw])


def wrap_policy_undeclared(ctx, report):
    """O2: a shown text node that declares no wrap scope of the contract (`wrap_policy` is `-`)."""
    for node in _shown_texts(ctx):
        if node.wrap_policy == "-":
            report.add("wrap-policy-undeclared", [node.key], {"stage": "O2", "key": node.key},
                       target=node.key, records=[node.raw])
