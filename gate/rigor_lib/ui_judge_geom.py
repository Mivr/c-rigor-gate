"""The geometric checks of the `ui-scene` judge (U06, P004 3.1, 3.10). They read the scene (O2) for what a node is (intent,
enabled, inert, layer policy, text) and the associated rendered nodes (O3) for where it is: the box (equal to the scene
rect by the association), the paint order (lvprobe's walk order), ancestry and the clip chain. A scene node without an
association takes part in none of them; it is `stage-unmatched` (ui_judge_context).

Probe points P(n) (P004 3.10): the centre and the grid `thresholds.probe_grid_pct` x the same, inside n's box; and the
disc of `thresholds.probe_disc_radius_mm` around the centre, clipped to n, which needs the panel's ppi
(`panel.diagonal_in`): while that is pending the disc is `contract-pending` and the grid points are still judged.
"""

from fractions import Fraction

from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_judge_stage import inside, intersect


def _cut(box, cut):
    return intersect(box, cut)


def probe_points(box, grid):
    """Grid points of an inclusive box: x1 + floor(w * p / 100) for p in grid and 50, at most x2."""
    w, h = box[2] - box[0] + 1, box[3] - box[1] + 1
    if w <= 0 or h <= 0:
        return []
    pcts = sorted({Fraction(str(p)) for p in grid} | {Fraction(50)})
    xs = [box[0] + min(w - 1, int(w * p / 100)) for p in pcts]
    ys = [box[1] + min(h - 1, int(h * p / 100)) for p in pcts]
    return sorted({(x, y) for x in xs for y in ys})


def centre(box):
    w, h = box[2] - box[0] + 1, box[3] - box[1] + 1
    return box[0] + min(w - 1, w // 2), box[1] + min(h - 1, h // 2)


def _distance2(point, box):
    dx = max(box[0] - point[0], 0, point[0] - box[2])
    dy = max(box[1] - point[1], 0, point[1] - box[3])
    return dx * dx + dy * dy


def _cover_region(frame, index):
    """Where rendered node `index` stops a visitor seeing or pressing what is below it, or None: its visible box when it
    is clickable or paints a background (drawn opacity above 0, a gradient or an image); a label's drawn glyphs."""
    node = frame.nodes[index]
    if not frame.shown(index):
        return None
    region = frame.visible_box(index)
    if node.clickable or node.bg_opa_drawn > 0 or node.bg_image:
        return region
    fit = frame.fits.get(index)
    if fit is not None and fit.drawn and fit.glyphs is not None:
        return _cut(region, intersect(fit.glyphs, fit.visible))
    return None


def _disc_radius(ctx, report):
    try:
        return ctx.contract.mm_to_px(ctx.contract.get("thresholds", "probe_disc_radius_mm"))
    except ContractPending as error:
        report.pending("occluded-target", error)
        return None


def _targets(ctx):
    return [(node, index) for node, index in ctx.matched() if node.interactive and not ctx.behind_modal(index)]


def occluded_target(ctx, report):
    """O2 + O3: an interactive node not behind a declared modal blocker, one of whose probe points lies under a
    later-painted rendered node that is not its ancestor or descendant and covers that point (_cover_region)."""
    frame, grid = ctx.frame, ctx.contract.get("thresholds", "probe_grid_pct")
    radius = _disc_radius(ctx, report)
    for node, index in _targets(ctx):
        box = frame.nodes[index].box
        points = probe_points(box, grid)
        if not points:
            continue
        mid = centre(box)
        covering, hits = [], 0
        for other in range(index + 1, len(frame.nodes)):
            if frame.descends(other, index):
                continue
            region = _cut(_cover_region(frame, other), box)
            if region is None:
                continue
            grid_hits = sum(1 for p in points if inside((p[0], p[1], p[0], p[1]), region))
            disc_hit = radius is not None and _distance2(mid, region) <= radius * radius
            if grid_hits or disc_hit:
                covering.append(other)
                hits += grid_hits
        if covering:
            names = [_name(ctx, other) for other in covering]
            report.add("occluded-target", [node.key], {"stage": "O2+O3", "key": node.key, "covered_by": names,
                                                       "grid_points_covered": hits, "grid_points": len(points)},
                       target=node.key, records=[node.raw] + ctx.records(index, *covering))


def _name(ctx, index):
    """A rendered node in a finding: the key of the scene node associated with it, or its walk index."""
    keys = [key for key, i in ctx.assoc.match.items() if i == index]
    return {"key": keys[0]} if keys else {"index": index, "class": ctx.frame.nodes[index].cls}


def overlay_policy(ctx, report):
    """O2 + O3: a declared layer whose contract row captures input (`blocks_input_below` or `tap_outside_dismisses`)
    over an enabled node with an intent painted below it, unless the layer is modal (`blocks_input_below`) and the node
    is declared `inert`; and a clickable rendered node in no declared layer, not part of an interactive node, painted
    over an interactive node (a layer that declares no policy)."""
    frame = ctx.frame
    candidates = [(node, index) for node, index in ctx.matched() if node.intent != "-" and node.enabled]
    for layer_node, layer, row in ctx.layers():
        if not (row["blocks_input_below"] or row["tap_outside_dismisses"]):
            continue
        for node, index in candidates:
            if index > layer or frame.related(index, layer) \
                    or intersect(frame.nodes[index].box, frame.nodes[layer].box) is None:
                continue
            if "inert" in node.flags and row["blocks_input_below"]:
                continue
            report.add("overlay-policy", [layer_node.key, node.key, "captures"],
                       {"stage": "O2+O3", "layer": layer_node.key, "policy": layer_node.input_policy, "key": node.key,
                        "inert": "inert" in node.flags}, target="%s/%s" % (layer_node.key, node.key),
                       records=[layer_node.raw, node.raw] + ctx.records(layer, index))
    _undeclared(ctx, report)


def _undeclared(ctx, report):
    frame = ctx.frame
    targets = [(node, index) for node, index in ctx.matched() if node.interactive]
    parts = {index for _node, index in targets}
    for other in range(len(frame.nodes)):
        if frame.is_root(other) or not frame.nodes[other].clickable or not frame.shown(other) \
                or ctx.layer_of(other) != -1 or any(a in parts for a in [other] + frame.ancestors(other)):
            continue
        region = frame.visible_box(other)
        for node, index in targets:
            if other > index and not frame.related(other, index) \
                    and intersect(region, frame.nodes[index].box) is not None:
                report.add("overlay-policy", ["undeclared", other, node.key],
                           {"stage": "O2+O3", "capturing": _name(ctx, other), "key": node.key, "policy": None},
                           records=[node.raw] + ctx.records(other, index))


def target_spacing(ctx, report):
    """O2 + O3: two interactive nodes with distinct intents (neither behind a modal blocker) whose boxes overlap, unless
    `thresholds.hit_overlap_allowed`; once the panel is sealed, an edge-to-edge gap below `spacing_hard_mm` (error) or
    `spacing_recommended_mm` (info)."""
    contract, frame = ctx.contract, ctx.frame
    overlap_allowed = contract.get("thresholds", "hit_overlap_allowed")
    try:
        hard = contract.mm_to_px(contract.get("thresholds", "spacing_hard_mm"))
        soft = contract.mm_to_px(contract.get("thresholds", "spacing_recommended_mm"))
    except ContractPending as error:
        report.pending("target-spacing", error)
        hard = soft = None
    targets = sorted(_targets(ctx), key=lambda pair: pair[0].key)
    for i, (a, ia) in enumerate(targets):
        for b, ib in targets[i + 1:]:
            if a.intent == b.intent:
                continue
            ba, bb = frame.nodes[ia].box, frame.nodes[ib].box
            pair = {"stage": "O2+O3", "keys": [a.key, b.key]}
            target, records = "%s/%s" % (a.key, b.key), [a.raw, b.raw] + ctx.records(ia, ib)
            if intersect(ba, bb) is not None:
                if not overlap_allowed:
                    report.add("target-spacing", [a.key, b.key, "overlap"], dict(pair, part="overlap"),
                               target=target, records=records)
                continue
            if hard is None:
                continue
            gap2 = _gap2(ba, bb)
            if gap2 < hard * hard:
                report.add("target-spacing", [a.key, b.key, "hard"], dict(pair, part="hard", gap2_px=gap2,
                                                                          limit_px=hard),
                           target=target, records=records)
            elif gap2 < soft * soft:
                report.add("target-spacing", [a.key, b.key, "recommended"],
                           dict(pair, part="recommended", gap2_px=gap2, limit_px=soft),
                           target=target, severity="info", records=records)


def _gap2(a, b):
    """Squared edge-to-edge distance in px of two disjoint inclusive boxes (pixels between them)."""
    dx = max(0, b[0] - a[2] - 1, a[0] - b[2] - 1)
    dy = max(0, b[1] - a[3] - 1, a[1] - b[3] - 1)
    return dx * dx + dy * dy


def node_out_of_bounds(ctx, report):
    """O2 + O3: a shown node with an area whose box is not inside the contract's window, or not inside its parent when
    the parent is not a screen or layer root."""
    frame = ctx.frame
    window = (0, 0, ctx.contract.get("window", "width_px") - 1, ctx.contract.get("window", "height_px") - 1)
    for node, index in ctx.matched():
        box = frame.nodes[index].box
        if box[2] < box[0] or box[3] < box[1]:
            continue
        if not inside(box, window):
            report.add("node-out-of-bounds", [node.key, "window"],
                       {"stage": "O2+O3", "key": node.key, "part": "window", "box": list(box)},
                       target=node.key, records=[node.raw] + ctx.records(index))
        parent = frame.nodes[index].parent
        if not frame.is_root(parent) and not inside(box, frame.nodes[parent].box):
            report.add("node-out-of-bounds", [node.key, "parent"],
                       {"stage": "O2+O3", "key": node.key, "part": "parent", "box": list(box),
                        "parent": _name(ctx, parent)},
                       target=node.key, records=[node.raw] + ctx.records(index, parent))


def text_overlap(ctx, report):
    """O2 + O3: two shown text nodes with a text, in the same declared layer, neither an ancestor of the other, whose
    boxes share a pixel."""
    frame = ctx.frame
    texts = sorted(((n, i) for n, i in ctx.matched() if ctx.is_text(n) and n.label != b""), key=lambda p: p[0].key)
    for k, (a, ia) in enumerate(texts):
        for b, ib in texts[k + 1:]:
            if ctx.layer_of(ia) != ctx.layer_of(ib) or frame.related(ia, ib):
                continue
            if intersect(frame.nodes[ia].box, frame.nodes[ib].box) is not None:
                report.add("text-overlap", [a.key, b.key], {"stage": "O2+O3", "keys": [a.key, b.key]},
                           target="%s/%s" % (a.key, b.key), records=[a.raw, b.raw] + ctx.records(ia, ib))
