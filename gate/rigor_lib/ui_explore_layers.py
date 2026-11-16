"""The layer policy of the explorer's tap judges (U05e; P004 3.4; docs/ui-explore.md "Taps under a layer").

With `--contract`, a tap is judged in the layer context the ui-scene judge reads (ui_judge_context.Context: the scene,
the rendered tree, their association, each layer's sealed `[[input_layer]]` policy, inertness R7), built from the
state before the tap. Without a contract nothing here runs. One verdict per tap, in this order:
  inert    the tap's target (a u2 tap's aimed node, a scene tap's node) is interactive and inert under R7: the tap
           must have NO effect; an effect is `blocked-target-live`; neither `intent-missed` nor `tap-misrouted`;
  covered  the same, but the tap pressed an interactive control of the modal layer's own card (its Dismiss drawn over
           the target's point; pressing the card itself stays `inert`):
           the tap is that control's, judged as a tap on it (`intent-missed` when nothing changed), never misrouted;
  dismiss  the point is under a scrim (outside its card), the topmost layer there, whose sealed rows say a tap outside
           dismisses: the tap must do exactly that layer's dismiss: the layer's records leave the scene and nothing
           else of the scene changes (outcome `dismissed`); anything else is `tap-misrouted` naming both;
  pass     the point is under such a scrim whose layer does not block and does not dismiss, over an interactive, not
           inert node below it: a tap that only removes the layer is `tap-swallowed-first` (the first tap is
           swallowed); any other outcome is judged as without a contract.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from rigor_lib import ui_judge_stage as stage
from rigor_lib.errors import InternalError
from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_record, parse_typed_line
from rigor_lib.ui_judge_context import Context
from rigor_lib.ui_judge_vocab import CARD_ROLES


@dataclass(frozen=True)
class Verdict:
    kind: str          # inert, dismiss or pass
    layer: object      # the layer's node key (a scrim, or a card without one), or None (a node flagged I)
    target: object     # the aimed scene node's key (inert), the node below (pass), or None
    intent: object     # the layer's dismiss intent (`intent:arg`, `-` when the scrim has none)
    removed: tuple     # the raw semantic records of the layer: the scrim, its card and the nodes inside the card
    aimed: object = None   # covered: the key of the inert node the tap aimed at


def context(contract, snapshot):
    """The judges' Context of the state of a snapshot, or None when its records cannot be read as a scene and tree."""
    try:
        obs = {"semantic": tuple(parse_record("semantic", line) for line in snapshot["semantic"]),
               "frame": tuple(parse_typed_line(FRAME_FIELDS, line) for line in snapshot["frame"])}
        return Context(SimpleNamespace(contract=contract, gates=()), SimpleNamespace(obs=obs))
    except (InternalError, ValueError, KeyError):
        return None


def _holds(ctx, index, x, y):
    box = ctx.frame.visible_box(index)
    return box is not None and stage.inside((x, y, x, y), box)


def _layer_records(ctx, scrim):
    """The scrim, its card and the scene nodes after the card whose rects lie inside the card's rect."""
    start = ctx.order[scrim.key]
    out = [scrim.raw]
    card = ctx.card_of(scrim)
    if card is not None:
        out.append(card.raw)
        for node in ctx.scene[start + 2:]:
            if not stage.inside(node.rect, card.rect):
                break
            out.append(node.raw)
    return tuple(out)


def _top(ctx, x, y):
    """(layer node, its scrim's rendered index, the card's rendered index or None, policy) of the latest painted shown
    layer whose rendered parts hold the point, or None."""
    found = [(shield, node, parts, policy) for node, shield, parts, policy in ctx.layers()
             if any(_holds(ctx, part, x, y) for part in parts)]
    if not found:
        return None
    shield, node, parts, policy = max(found, key=lambda item: item[0])
    return node, shield, (parts[1] if len(parts) > 1 else None), policy


def _inert(ctx, aim, x, y, pressed):
    key = ctx.name_of(aim).get("key") if aim is not None and aim < len(ctx.frame.nodes) else None
    node = ctx.by_key.get(key)
    if node is None or not node.interactive or not ctx.inert_target(node, aim):
        return None
    shields = [(n, parts) for n, shield, parts, policy in ctx.layers()
               if policy == "capture-modal-inert" and shield > aim and _holds(ctx, shield, x, y)]
    layer = shields[-1][0] if shields else None
    cards = [part for _, parts in shields for part in parts[1:]]
    if pressed is not None and pressed < len(ctx.frame.nodes):
        control = next((n for n, i in ctx.matched() if n.interactive and ctx.frame.descends(pressed, i)
                        and any(ctx.frame.descends(i, card) for card in cards)), None)
        if control is not None:      # a control of the layer's own card took the tap: it is that control's
            return Verdict("covered", layer.key, control.key, control.intent, _layer_records(ctx, layer), node.key)
    return Verdict("inert", layer.key if layer else None, node.key, None, ())


def _below(ctx, shield, x, y):
    for node, index in reversed(ctx.matched()):
        if index < shield and node.interactive and not ctx.frame.related(index, shield) and _holds(ctx, index, x, y) \
                and not ctx.inert_target(node, index):
            return node
    return None


def verdict(contract, snapshot, x, y, aim, pressed=None):
    """The Verdict of a tap at (x, y) aimed at rendered node `aim` (or None), which pressed rendered node `pressed` (or
    None), in the state of `snapshot`, or None."""
    ctx = context(contract, snapshot)
    if ctx is None:
        return None
    try:
        top = _top(ctx, x, y)
        if top is None or top[0].role != "scrim" or (top[2] is not None and _holds(ctx, top[2], x, y)) \
                or ctx.card_of(top[0]) is None or ctx.card_of(top[0]).role not in CARD_ROLES:
            top = None
        outside = ctx.tap_outside(top[0]) if top is not None else None
        if outside:      # first: a layer that dismisses on a tap outside expects that, blocking or not
            return Verdict("dismiss", top[0].key, None, top[0].intent, _layer_records(ctx, top[0]))
        found = _inert(ctx, aim, x, y, pressed)
        if found is not None or top is None:
            return found
        node, shield, _card, policy = top
        below = _below(ctx, shield, x, y) if outside is False and policy == "pass-through" else None
        return None if below is None else Verdict("pass", node.key, below.key, node.intent, _layer_records(ctx, node))
    except ContractPending:
        return None


def _plain(lines, role):
    """Semantic lines with the label of every node of the declared countdown role blanked (its restart is exempt)."""
    out = []
    for line in lines:
        fields = line.split("\t")
        out.append("\t".join(fields[:2] + [""] + fields[3:]) if role is not None and fields[1] == role else line)
    return out


def layer_left(verdict, before, after, patches, trace, role=None, restart=None):
    """The parts of a tap's change that are NOT exactly the layer leaving (empty: it is exactly that). Allowed, and
    nothing else: the layer's semantic records leave and every other record stays (a node of the declared countdown
    `role` may change its label: the tap's own restart); the env inputs stay; every new patch names a key of the layer,
    or is an `update <key> text` of a countdown-role node; at most one trace record besides the declared ambient ones
    (the dismiss's own); the next deadline is gone, later than before (the layer's timer cancelled) or the declared
    restart. The explorer cannot replay the dismiss intent itself (an adapter may not take it), hence these parts."""
    keys = {line.split("\t", 1)[0] for line in verdict.removed}
    counts = {line.split("\t", 2)[0] for line in before["semantic"] if role is not None and line.split("\t")[1] == role}
    rest = [line for line in before["semantic"] if line not in verdict.removed]
    bad = []
    if len(rest) == len(before["semantic"]) or _plain(after["semantic"], role) != _plain(rest, role):
        bad.append("semantic")
    if after["env"] != before["env"]:
        bad.append("env")
    if any(p.fields[1] not in keys and not (p.fields[0] == "update" and p.fields[2] == "text" and p.fields[1] in counts)
           for p in patches):
        bad.append("patches")
    if len(trace) > 1:
        bad.append("trace")
    due, old = after["due"], before["due"]
    if not (due is None or (old is not None and due >= old) or due == restart):
        bad.append("due")
    return bad


def like_sibling(sibling, before, after, patches, trace, role=None, restart=None):
    """The parts of a tap's change that differ from applying the layer's own intent from the same state (a sibling
    replay, ui_explore_scene.Scene.sibling): semantic (a countdown-role node's label exempt), env, the next deadline (or
    the declared restart), the patches (a countdown-role node's `update <key> text` exempt) and the trace records' type
    and time (besides the declared ambient ones, set aside on both sides)."""
    counts = {line.split("\t", 2)[0] for line in before["semantic"] if role is not None and line.split("\t")[1] == role}
    own = [p.raw for p in patches if not (p.fields[0] == "update" and p.fields[2] == "text" and p.fields[1] in counts)]
    bad = []
    if _plain(after["semantic"], role) != _plain(sibling["semantic"], role):
        bad.append("semantic")
    if after["env"] != sibling["env"]:
        bad.append("env")
    if own != sibling["patches"]:
        bad.append("patches")
    if [(r.fields[1], r.fields[2]) for r in trace] != sibling["trace"]:
        bad.append("trace")
    if after["due"] != sibling["due"] and after["due"] != restart:
        bad.append("due")
    return bad
