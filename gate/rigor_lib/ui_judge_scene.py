"""The `ui-scene` judge (U06, P004 3.1): one step judge over the scene (O2) and, where the scene lacks the tree, the rendered
tree it is associated with (O3). Every threshold and every judgement entry (typographic role, importance, wrap scope,
layer policy) is read from the UI contract at the step; a value the owner has not decided is `contract-pending` for
exactly what needs it, never a default.

Checks on O2 alone: touch-target-small, font-below-min, hierarchy-violated, raw-text, wrap-policy-undeclared.
Checks on O2 + O3: occluded-target, overlay-policy, target-spacing, node-out-of-bounds, text-overlap (ui_judge_geom),
toggle-group-indistinct (the members' rendered facts within one state).
Blocked (docs/ui-judges.md, "Honesty table"): value-split, required-element-missing.
"""

from fractions import Fraction

from rigor_lib import ui_judge_geom as geom
from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_judge_vocab import PURE_TEXT


def judge(ctx, report):
    for check in (touch_target_small, font_below_min, hierarchy_violated, raw_text, wrap_policy_undeclared,
                  toggle_group_indistinct, geom.occluded_target, geom.overlay_policy, geom.target_spacing,
                  geom.node_out_of_bounds, geom.text_overlap):
        check(ctx, report)
    return report.found


def _texts(ctx):
    """(node, typographic role) of every shown text-bearing node whose role the contract gives."""
    return [(node, ctx.role_of(node)) for node in ctx.scene if not node.hidden and ctx.role_of(node) is not None]


def touch_target_small(ctx, report):
    """O2: an interactive, shown node narrower or lower than the larger of `thresholds.touch_min_dp` and its typographic
    role's `role_min.touch_dp_min` (scene px = dp); and, once the panel is sealed, than `thresholds.touch_min_mm`."""
    contract = ctx.contract
    floor = contract.get("thresholds", "touch_min_dp")
    minimum = {row["role"]: row["touch_dp_min"] for row in contract.rows("role_min")}
    try:
        mm_px = contract.mm_to_px(contract.get("thresholds", "touch_min_mm"))
    except ContractPending as error:
        report.pending("touch-target-small", error, whole=False)
        mm_px = None
    for node in ctx.scene:
        if node.hidden or not node.interactive:
            continue
        report.examined("touch-target-small")
        need = max(floor, minimum.get(ctx.role_of(node), 0))
        if node.w < need or node.h < need:
            report.add("touch-target-small", [node.key, "dp"],
                       {"stage": "O2", "key": node.key, "unit": "dp", "w": node.w, "h": node.h, "limit": need},
                       target=node.key, records=[node.raw])
        if mm_px is not None and (node.w < mm_px or node.h < mm_px):
            report.add("touch-target-small", [node.key, "mm"],
                       {"stage": "O2", "key": node.key, "unit": "mm", "w": node.w, "h": node.h, "limit_px": mm_px},
                       target=node.key, records=[node.raw])


def font_below_min(ctx, report):
    """O2: a shown text node whose style's font size (`type_scale` of the style's `scale`) is below its typographic
    role's `role_min.font_px_min`. A role with no role_min row is `contract-incomplete`."""
    minimum = {row["role"]: row["font_px_min"] for row in ctx.contract.rows("role_min")}
    for node, role in _texts(ctx):
        if role not in minimum:
            report.incomplete("role-min", role)
            continue
        report.examined("font-below-min")
        size = ctx.contract.style_px(ctx.style_of(node))
        if size < minimum[role]:
            report.add("font-below-min", [node.key], {"stage": "O2", "key": node.key, "font_px": size,
                                                      "limit": minimum[role]},
                       target=node.key, records=[node.raw])


def hierarchy_violated(ctx, report):
    """O2, per state, over the shown text nodes. Without the contract's importance table or ratio: the part that needs
    neither, `single-size` (text of two or more roles in one font size). With the table: `level` (a level in the scene
    that is not the contract's), `levels` (more than 3), `rank` (another level larger than the smallest level-1 text);
    with the ratio too: `ratio` (the smallest level-1 size below k times the largest level-2 size)."""
    texts = _texts(ctx)
    report.examined("hierarchy-violated", len(texts))
    sizes = {ctx.contract.style_px(ctx.style_of(node)) for node, _role in texts}
    if len({role for _node, role in texts}) >= 2 and len(sizes) < 2:
        report.add("hierarchy-violated", ["single-size"], {"stage": "O2", "part": "single-size",
                                                           "roles": len({role for _n, role in texts})},
                   records=[node.raw for node, _role in texts])
    try:
        levels = {role: row["level"] for row in ctx.contract.rows("importance") for role in row["roles"]}
    except ContractPending as error:
        report.pending("hierarchy-violated", error, whole=False)
        return
    leveled = []
    for node, role in texts:
        if role not in levels:
            report.incomplete("importance", role)
        elif node.importance != "-" and int(node.importance) != levels[role]:
            report.add("hierarchy-violated", [node.key, "level"],
                       {"stage": "O2", "key": node.key, "part": "level", "declared": int(node.importance),
                        "contract": levels[role]}, target=node.key, records=[node.raw])
        else:
            leveled.append((node, levels[role]))
    _ranks(ctx, report, leveled)


def _ranks(ctx, report, leveled):
    size = {node.key: ctx.contract.style_px(ctx.style_of(node)) for node, _level in leveled}
    distinct = sorted({level for _node, level in leveled})
    records = [node.raw for node, _level in leveled]
    if len(distinct) > 3:
        report.add("hierarchy-violated", ["levels"], {"stage": "O2", "part": "levels", "levels": distinct},
                   records=records)
    first = [node for node, level in leveled if level == 1]
    if not first:
        return
    top = min(size[node.key] for node in first)
    over = sorted(node.key for node, level in leveled if level != 1 and size[node.key] > top)
    if over:
        report.add("hierarchy-violated", ["rank"], {"stage": "O2", "part": "rank", "level1_px": top, "larger": over},
                   records=records)
        return
    second = [size[node.key] for node, level in leveled if level == 2]
    if not second:
        return
    try:
        k = Fraction(str(ctx.contract.get("thresholds", "hierarchy_ratio_k")))
    except ContractPending as error:
        report.pending("hierarchy-violated", error, whole=False)
        return
    if Fraction(top) < k * max(second):
        report.add("hierarchy-violated", ["ratio"], {"stage": "O2", "part": "ratio", "level1_px": top,
                                                     "level2_px": max(second), "k": str(k)}, records=records)


def raw_text(ctx, report):
    """O2: a shown node of role `text` or `countdown` whose formatted string is empty. (The raw-msgid half is blocked:
    the scene has no msgid.)"""
    for node in ctx.scene:
        if node.role in PURE_TEXT and not node.hidden:
            report.examined("raw-text")
            if node.label == b"":
                report.add("raw-text", [node.key, "empty"], {"stage": "O2", "key": node.key, "part": "empty"},
                           target=node.key, records=[node.raw])


def wrap_policy_undeclared(ctx, report):
    """O2 + contract: a shown text node whose typographic role the contract gives no wrap scope (`[[role_wrap]]`); a
    pending row is `contract-pending`. A scope the scene states that is not the contract's is the part `contradicts`."""
    for node, role in _texts(ctx):
        report.examined("wrap-policy-undeclared")
        rows = [row for row in ctx.contract.rows("role_wrap") if row["role"] == role]
        if not rows:
            report.add("wrap-policy-undeclared", ["role", role], {"stage": "O2", "role": role, "part": "undeclared"},
                       stateless=True)
            continue
        try:
            scope = ctx.contract.row_value("role_wrap", role, "scope")
        except ContractPending as error:
            report.pending("wrap-policy-undeclared", error, whole=False)
            continue
        if node.wrap_policy not in ("-", scope):
            report.add("wrap-policy-undeclared", [node.key, "contradicts"],
                       {"stage": "O2", "key": node.key, "part": "contradicts", "scene": node.wrap_policy,
                        "contract": scope}, target=node.key, records=[node.raw])


def _mark(ctx, node, index, mark):
    if mark == "bg":
        return ctx.frame.nodes[index].bg
    if mark == "bg_opa":
        return ctx.frame.nodes[index].bg_opa_drawn
    return node.token


def toggle_group_indistinct(ctx, report):
    """O2 + O3, within one state: the members of a contract toggle group (its [[element]] keys) present in the scene
    must be all present, shown and associated, and for every mark the group declares (rendered `bg` colour, drawn
    `bg_opa`, the scene's `style` token) exactly one member differs from the others, which are all equal."""
    keys = {row["id"]: row["key"] for row in ctx.contract.rows("element")}
    for group in ctx.contract.rows("toggle_group"):
        members = [keys[m] for m in group["members"]]
        present = [ctx.by_key[k] for k in members if k in ctx.by_key and not ctx.by_key[k].hidden]
        if not present:
            continue
        report.examined("toggle-group-indistinct", len(present))
        indexes = {n.key: ctx.assoc.match[n.key] for n in present if n.key in ctx.assoc.match}
        if len(present) != len(members) or len(indexes) != len(members) \
                or not all(ctx.frame.shown(i) for i in indexes.values()):
            report.add("toggle-group-indistinct", [group["id"], "members"],
                       {"stage": "O2+O3", "group": group["id"], "part": "members",
                        "present": sorted(n.key for n in present), "associated": sorted(indexes)},
                       records=[n.raw for n in present])
            continue
        for mark in group["marks"]:
            values = [_mark(ctx, ctx.by_key[k], indexes[k], mark) for k in members]
            odd = [v for v in values if values.count(v) == 1]
            if len(set(values)) != 2 or (len(values) > 2 and len(odd) != 1):
                report.add("toggle-group-indistinct", [group["id"], mark],
                           {"stage": "O2+O3", "group": group["id"], "part": mark, "distinct": len(set(values))},
                           target=group["id"], records=[ctx.by_key[k].raw for k in members]
                           + ctx.records(*indexes.values()))
