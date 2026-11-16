"""The geometric checks of the `ui-scene` judge (U06, P004 3.1, 3.10). They read the scene (O2) for what a node is
(structural role, intent, flags, the sealed policies) and the associated rendered nodes (O3) for where it is: the box
(equal to the scene rect by the association), the paint order (lvprobe's walk order), ancestry and the clip chain. A
scene node without an association takes part in none of them; it is `stage-unmatched` (ui_judge_context).

Probe points P(n) (P004 3.10): the centre and the grid `thresholds.probe_grid_pct` x the same, inside n's box; and the
disc of `thresholds.probe_disc_radius_mm` around the centre, clipped to n, which needs the panel's ppi
(`panel.diagonal_in`): while that is pending the disc is `contract-pending` and the grid points are still judged.

One cause, one finding: a layer that takes the taps meant for a control is `overlay-policy`'s (it runs first and records
the capture); `occluded-target` then does not count that layer's nodes over that control.
"""

from fractions import Fraction

from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_judge_stage import inside, intersect
from rigor_lib.ui_judge_vocab import LAYER_ROLES


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


def free_square(box, obstacles, side):
    """Whether an axis-aligned square of `side` pixels fits in the inclusive `box` without meeting any obstacle box.
    Exact: a free square can be slid left and then up until it touches the box or an obstacle, so its top left corner
    is one of the candidates below."""
    if side <= 0:
        return True
    xs = {box[0]} | {o[2] + 1 for o in obstacles}
    ys = {box[1]} | {o[3] + 1 for o in obstacles}
    for x in sorted(xs):
        for y in sorted(ys):
            square = (x, y, x + side - 1, y + side - 1)
            if inside(square, box) and all(intersect(square, o) is None for o in obstacles):
                return True
    return False


def _cover_region(frame, index):
    """Where rendered node `index` stops a visitor seeing or pressing what is below it, or None: its visible box when it
    is clickable, draws a background opacity above 0 (`bg_opa_drawn`; a gradient alone is not counted) or has a
    background image; a label's drawn glyph box. Borders, outlines, shadows, images and other widgets' own drawing
    are not facts of lvprobe and are not counted (docs/ui-judges.md, honesty table)."""
    node = frame.nodes[index]
    if not frame.shown(index):
        return None
    region = frame.visible_box(index)
    if node.clickable or node.bg_opa_drawn > 0 or node.bg_image:
        return region
    fit = frame.fits.get(index)
    if fit is not None and fit.drawn and fit.glyphs is not None:
        return intersect(region, intersect(fit.glyphs, fit.visible))
    return None


class Probe:
    """The probe region of one node: grid points, centre, disc radius (or None while the ppi is pending)."""

    def __init__(self, box, grid, radius):
        self.box, self.points, self.mid, self.radius = box, probe_points(box, grid), centre(box), radius

    def inert_points(self):
        """The grid points, and with the ppi the corners of the disc's bounding box inside the node (R7)."""
        if self.radius is None or not self.points:
            return self.points
        r = int(self.radius) + 1
        disc = intersect(self.box, (self.mid[0] - r, self.mid[1] - r, self.mid[0] + r, self.mid[1] + r))
        return self.points + [(disc[0], disc[1]), (disc[2], disc[3])]

    def disc_meets(self, region):
        return self.radius is not None and region is not None and \
            _distance2(self.mid, region) <= self.radius * self.radius


def _radius(ctx, report, check):
    try:
        return ctx.contract.mm_to_px(ctx.contract.get("thresholds", "probe_disc_radius_mm"))
    except ContractPending as error:
        report.pending(check, error)
        return None


def _probe(ctx, index, radius):
    return Probe(ctx.frame.nodes[index].box, ctx.contract.get("thresholds", "probe_grid_pct"), radius)


def _covering(ctx, node, index):
    """Rendered nodes that may cover a target: painted later, not its ancestor, not part of it (a descendant counts
    only when another scene node is associated with it: a layer's card over the layer's scrim), and not part of a
    layer whose capture of this target overlay-policy reported."""
    frame, own = ctx.frame, {ctx.assoc.text.get(node.key)}
    others = {i for key, i in ctx.assoc.match.items() if key != node.key}
    owned = ctx.captured.get(node.key, ())
    for other in range(index + 1, len(frame.nodes)):
        if frame.descends(other, index) and (other not in others or other in own):
            continue
        if any(frame.descends(other, part) for part in owned):
            continue
        yield other


def occluded_target(ctx, report):
    """O2 + O3: an interactive, not inert node (R7) one of whose probe points lies under a covering node; for a scrim
    with an intent (its tap area is what its card leaves free), no free square of the touch floor
    (`thresholds.touch_min_dp`) in its visible box once the covering nodes are taken out (part `layer-unreachable`)."""
    frame, radius = ctx.frame, _radius(ctx, report, "occluded-target")
    floor = ctx.contract.get("thresholds", "touch_min_dp")
    for node, index in ctx.matched():
        probe = _probe(ctx, index, radius)
        if not node.interactive or not probe.points or ctx.inert(node, index, probe.inert_points()):
            continue
        report.examined("occluded-target")
        regions = [(o, _cover_region(frame, o)) for o in _covering(ctx, node, index)]
        regions = [(o, intersect(r, probe.box)) for o, r in regions if r is not None]
        regions = [(o, r) for o, r in regions if r is not None]
        if node.role in LAYER_ROLES:
            visible = frame.visible_box(index)
            if visible is not None and not free_square(visible, [r for _o, r in regions], floor):
                _occluded(ctx, report, node, index, "layer-unreachable", [o for o, _r in regions], len(probe.points))
            continue
        covering = [o for o, r in regions if probe.disc_meets(r)
                    or any(inside((x, y, x, y), r) for x, y in probe.points)]
        if covering:
            hits = sum(1 for x, y in probe.points if any(inside((x, y, x, y), r) for _o, r in regions))
            _occluded(ctx, report, node, index, "covered", covering, hits)


def _occluded(ctx, report, node, index, part, covering, hits):
    report.add("occluded-target", [node.key], {
        "stage": "O2+O3", "key": node.key, "part": part, "covered_by": [ctx.name_of(o) for o in covering],
        "grid_points_covered": hits}, target=node.key, records=[node.raw] + ctx.records(index, *covering))


def overlay_policy(ctx, report):
    """O2 + O3, per layer with a sealed policy: (a) capture-modal-inert over an enabled control with an intent painted
    below it, unless the control is inert (R7): part `captures`, basis `sealed`; (b) pass-through, but the layer's
    rendered node or card is clickable over an interactive, not inert control: part `captures`, basis `rendered`;
    (c) a policy the scene states that is not the sealed one: part `contradicts`; (d) a clickable rendered node in no
    layer and not part of any scene node over an interactive node: part `undeclared`; (e) a scrim the scene does not
    follow with a card, so that no policy applies: part `no-card`."""
    frame, radius = ctx.frame, _radius(ctx, report, "overlay-policy")
    candidates = [(n, i) for n, i in ctx.matched() if n.intent != "-" and n.enabled and "D" not in n.flags]
    for layer_node, layer, parts, policy in ctx.layers():
        if policy is None and layer_node.role == "scrim" and ctx.card_of(layer_node) is None:
            report.add("overlay-policy", [layer_node.key, "no-card"],
                       {"stage": "O2", "layer": layer_node.key, "part": "no-card"}, target=layer_node.key,
                       records=[layer_node.raw])
        if policy is None:
            continue
        report.examined("overlay-policy")
        if layer_node.input_policy not in ("-", policy):
            report.add("overlay-policy", [layer_node.key, "contradicts"],
                       {"stage": "O2", "layer": layer_node.key, "part": "contradicts", "scene": layer_node.input_policy,
                        "contract": policy}, target=layer_node.key, records=[layer_node.raw])
        for node, index in candidates:
            if index in parts:                  # the layer's own scrim or card
                continue
            area = [p for p in parts if p > index and not frame.related(index, p)
                    and intersect(frame.visible_box(p), frame.nodes[index].box) is not None
                    and (policy != "pass-through" or frame.nodes[p].clickable)]
            if not area or ctx.inert(node, index, _probe(ctx, index, radius).inert_points()):
                continue
            if policy == "pass-through" and not node.interactive:
                continue
            ctx.captured.setdefault(node.key, []).extend(parts)
            report.add("overlay-policy", [layer_node.key, node.key, "captures"],
                       {"stage": "O2+O3", "layer": layer_node.key, "policy": policy, "key": node.key,
                        "part": "captures", "basis": "sealed" if policy != "pass-through" else "rendered"},
                       target="%s/%s" % (layer_node.key, node.key),
                       records=[layer_node.raw, node.raw] + ctx.records(*area, index))
    _undeclared(ctx, report)


def _undeclared(ctx, report):
    frame = ctx.frame
    targets = [(node, index) for node, index in ctx.matched() if node.interactive]
    associated = set(ctx.assoc.match.values())
    for other in range(len(frame.nodes)):
        if frame.is_root(other) or not frame.nodes[other].clickable or not frame.shown(other) \
                or ctx.layer_of(other) != -1 or any(a in associated for a in [other] + frame.ancestors(other)):
            continue
        region = frame.visible_box(other)
        name = ctx.rendered_name(other)
        for node, index in targets:
            if other > index and not frame.related(other, index) \
                    and intersect(region, frame.nodes[index].box) is not None:
                report.add("overlay-policy", ["undeclared", name["target"], node.key],
                           {"stage": "O2+O3", "capturing": name, "key": node.key, "part": "undeclared"},
                           target="%s/%s" % (name["target"], node.key), records=[node.raw] + ctx.records(other, index))


def target_spacing(ctx, report):
    """O2 + O3: two interactive, not inert nodes with distinct intents that are not layers (a scrim's overlap is the
    layer's, judged by overlay-policy and occluded-target) whose boxes share a pixel, unless
    `thresholds.hit_overlap_allowed`; once the panel is sealed, an edge-to-edge gap below `spacing_hard_mm` (error) or
    `spacing_recommended_mm` (info)."""
    contract = ctx.contract
    overlap_allowed = contract.get("thresholds", "hit_overlap_allowed")
    radius = _radius(ctx, report, "target-spacing")
    try:
        hard = contract.mm_to_px(contract.get("thresholds", "spacing_hard_mm"))
        soft = contract.mm_to_px(contract.get("thresholds", "spacing_recommended_mm"))
    except ContractPending as error:
        report.pending("target-spacing", error)
        hard = soft = None
    targets = sorted(((n, i) for n, i in ctx.matched() if n.interactive and n.role not in LAYER_ROLES
                      and not ctx.inert(n, i, _probe(ctx, i, radius).inert_points())), key=lambda p: p[0].key)
    report.examined("target-spacing", len(targets))
    for k, (a, ia) in enumerate(targets):
        for b, ib in targets[k + 1:]:
            if a.intent != b.intent:
                _spacing_pair(ctx, report, (a, ia), (b, ib), overlap_allowed, hard, soft)


def _spacing_pair(ctx, report, first, second, overlap_allowed, hard, soft):
    (a, ia), (b, ib) = first, second
    ba, bb = ctx.frame.nodes[ia].box, ctx.frame.nodes[ib].box
    pair = {"stage": "O2+O3", "keys": [a.key, b.key]}
    target, records = "%s/%s" % (a.key, b.key), [a.raw, b.raw] + ctx.records(ia, ib)
    if intersect(ba, bb) is not None:
        if not overlap_allowed:
            report.add("target-spacing", [a.key, b.key, "overlap"], dict(pair, part="overlap"), target=target,
                       records=records)
        return
    if hard is None:
        return
    dx = max(0, bb[0] - ba[2] - 1, ba[0] - bb[2] - 1)
    dy = max(0, bb[1] - ba[3] - 1, ba[1] - bb[3] - 1)
    gap2 = dx * dx + dy * dy
    if gap2 < hard * hard:
        report.add("target-spacing", [a.key, b.key, "hard"], dict(pair, part="hard", gap2_px=gap2, limit_px=hard),
                   target=target, records=records)
    elif gap2 < soft * soft:
        report.add("target-spacing", [a.key, b.key, "recommended"],
                   dict(pair, part="recommended", gap2_px=gap2, limit_px=soft), target=target, severity="info",
                   records=records)


def _in_viewport(ctx, index):
    """The node lies in a scrolling viewport: an ancestor that is a scroll context (lvprobe's `scroll`) other than a
    screen or layer root, or an ancestor whose scene node declares scrolling (flag S)."""
    frame = ctx.frame
    scroll = frame.nodes[index].scroll
    if scroll != -1 and not frame.is_root(scroll):
        return True
    scrolling = {i for n, i in ctx.matched() if "S" in n.flags}
    return any(a in scrolling for a in frame.ancestors(index))


def node_out_of_bounds(ctx, report):
    """O2 + O3: a shown node with an area, not in a scrolling viewport, whose box is not inside the contract's window,
    or not inside its parent when the parent is not a screen or layer root."""
    frame = ctx.frame
    window = (0, 0, ctx.contract.get("window", "width_px") - 1, ctx.contract.get("window", "height_px") - 1)
    for node, index in ctx.matched():
        box = frame.nodes[index].box
        if box[2] < box[0] or box[3] < box[1] or _in_viewport(ctx, index):
            continue
        report.examined("node-out-of-bounds")
        if not inside(box, window):
            report.add("node-out-of-bounds", [node.key, "window"],
                       {"stage": "O2+O3", "key": node.key, "part": "window", "box": list(box)},
                       target=node.key, records=[node.raw] + ctx.records(index))
        parent = frame.nodes[index].parent
        if not frame.is_root(parent) and not inside(box, frame.nodes[parent].box):
            report.add("node-out-of-bounds", [node.key, "parent"],
                       {"stage": "O2+O3", "key": node.key, "part": "parent", "box": list(box),
                        "parent": ctx.name_of(parent)},
                       target=node.key, records=[node.raw] + ctx.records(index, parent))


def text_overlap(ctx, report):
    """O2 + O3: two shown text nodes with a text, in the same layer, neither an ancestor of the other, whose boxes share
    a pixel."""
    frame = ctx.frame
    texts = sorted(((n, i) for n, i in ctx.matched() if ctx.role_of(n) is not None and n.label != b""),
                   key=lambda p: p[0].key)
    report.examined("text-overlap", len(texts))
    for k, (a, ia) in enumerate(texts):
        for b, ib in texts[k + 1:]:
            if ctx.layer_of(ia) != ctx.layer_of(ib) or frame.related(ia, ib):
                continue
            if intersect(frame.nodes[ia].box, frame.nodes[ib].box) is not None:
                report.add("text-overlap", [a.key, b.key], {"stage": "O2+O3", "keys": [a.key, b.key]},
                           target="%s/%s" % (a.key, b.key), records=[a.raw, b.raw] + ctx.records(ia, ib))
