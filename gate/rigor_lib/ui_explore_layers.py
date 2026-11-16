"""The layer policy of the explorer's tap judges (U05e; P004 3.4; docs/ui-explore.md "Taps under a layer").

With `--contract`, a tap is judged in the layer context the ui-scene judge reads (ui_judge_context.Context: the scene,
the rendered tree, their association, each layer's sealed `[[input_layer]]` policy, inertness R7, and, with the
probe's `identity`, the elements), built from the state before the tap. Without a contract nothing here runs. One
verdict per tap, in this order:
  dismiss  the point is under a scrim (outside its card), the topmost layer there, whose sealed rows say a tap outside
           dismisses: the tap must do exactly that layer's dismiss (`dismissed`), else `tap-misrouted`. The dismiss
           intent is BOUND by the gate (fix-up 3 ruling): the intent of the one node inside the layer's card that is
           the `dismiss` element by scene identity (`ui_judge_identity.carries`: a button; with an `[[element]]` row,
           the node at its key); a scrim's own intent counts only when it equals it. Judged by a sibling replay of
           that intent (ui_explore_scene.Scene.sibling, `like_sibling`) when it is bound and the catalogue has its
           event, else by the strict parts rule (`layer_left`);
  inert    the tap's target is interactive and inert under R7: NO effect; an effect is `blocked-target-live`;
  covered  the same, but the tap pressed an interactive control of the modal layer's own card: it is that control's
           tap, judged against that control's own intent (sibling) or the parts rule;
  pass     under such a scrim whose layer neither blocks nor dismisses, over an interactive, not inert node below: a
           tap whose change is exactly the layer leaving is `tap-swallowed-first`; any other change is judged as
           without a contract (one that also posts trace records is then `tap-misrouted` or `noop-tap-effect`).
"""

from dataclasses import dataclass
from types import SimpleNamespace

from rigor_lib import ui_judge_identity
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
    intent: object     # dismiss: the BOUND dismiss intent (`intent:arg`) or None; covered: the control's intent
    removed: tuple     # the raw semantic records of the layer: the scrim, its card and the nodes inside the card
    aimed: object = None   # covered: the key of the inert node the tap aimed at
    bound: object = None   # dismiss: the key of the node that is the layer's `dismiss` element, or None
    card_role: object = None   # the role of the layer's card (`taps` `dismiss_trace` is per card role)
    scrim_intent: object = None   # dismiss: the scrim's own intent


def context(contract, snapshot, identity=None):
    """The judges' Context of the state of a snapshot (and its `identity` records, or None), or None when its records
    cannot be read as a scene and tree."""
    try:
        obs = {"semantic": tuple(parse_record("semantic", line) for line in snapshot["semantic"]),
               "frame": tuple(parse_typed_line(FRAME_FIELDS, line) for line in snapshot["frame"]),
               "identity": identity}
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


def bound_dismiss(ctx, scrim):
    """The node inside the scrim's card that IS its layer's `dismiss` element by scene identity (exactly one), or None
    without identity, without a card or without exactly one such node."""
    card = ctx.card_of(scrim)
    if ctx.identity is None or card is None:
        return None
    found = [n for n in ctx.scene[ctx.order[card.key] + 1:] if stage.inside(n.rect, card.rect)
             and ui_judge_identity.carries(ctx, n, "dismiss")]
    return found[0] if len(found) == 1 else None


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
            card = ctx.card_of(layer) if layer.role == "scrim" else layer
            return Verdict("covered", layer.key, control.key, control.intent, _layer_records(ctx, layer), node.key,
                           card_role=card.role if card is not None else None)
    return Verdict("inert", layer.key if layer else None, node.key, None, ())


def _below(ctx, shield, x, y):
    for node, index in reversed(ctx.matched()):
        if index < shield and node.interactive and not ctx.frame.related(index, shield) and _holds(ctx, index, x, y) \
                and not ctx.inert_target(node, index):
            return node
    return None


def verdict(contract, snapshot, x, y, aim, pressed=None, identity=None):
    """The Verdict of a tap at (x, y) aimed at rendered node `aim` (or None), which pressed rendered node `pressed` (or
    None), in the state of `snapshot` (and its identity records), or None."""
    ctx = context(contract, snapshot, identity)
    if ctx is None:
        return None
    try:
        top = _top(ctx, x, y)
        if top is None or top[0].role != "scrim" or (top[2] is not None and _holds(ctx, top[2], x, y)) \
                or ctx.card_of(top[0]) is None or ctx.card_of(top[0]).role not in CARD_ROLES:
            top = None
        outside = ctx.tap_outside(top[0]) if top is not None else None
        if outside:      # first: a layer that dismisses on a tap outside expects that, blocking or not
            bound = bound_dismiss(ctx, top[0])
            return Verdict("dismiss", top[0].key, None, bound.intent if bound else None, _layer_records(ctx, top[0]),
                           bound=bound.key if bound else None, card_role=ctx.card_of(top[0]).role,
                           scrim_intent=top[0].intent)
        found = _inert(ctx, aim, x, y, pressed)
        if found is not None or top is None:
            return found
        node, shield, _card, policy = top
        below = _below(ctx, shield, x, y) if outside is False and policy == "pass-through" else None
        return None if below is None else Verdict("pass", node.key, below.key, node.intent, _layer_records(ctx, node),
                                                  card_role=ctx.card_of(node).role)
    except ContractPending:
        return None


def _plain(lines, role):
    """Semantic lines with the label of every node of the declared countdown role blanked (its restart is exempt)."""
    out = []
    for line in lines:
        fields = line.split("\t")
        out.append("\t".join(fields[:2] + [""] + fields[3:]) if role is not None and fields[1] == role else line)
    return out


def _patch_exempt(fields, counts):
    return fields[0] == "update" and len(fields) > 2 and fields[2] == "text" and fields[1] in counts


def _counts(before, role):
    return {line.split("\t", 2)[0] for line in before["semantic"] if role is not None and line.split("\t")[1] == role}


def layer_left(verdict, before, after, patches, trace, role=None, restart=None, dismiss_trace=None):
    """The parts of a tap's change that are NOT exactly the layer leaving, strictly (empty: it is exactly that): the
    layer's semantic records leave and every other record stays (a node of the declared countdown `role` may change
    its label: the tap's own restart); the env inputs stay; every new patch names a key of the layer or is the
    countdown's `update <key> text`; no trace record besides the declared ambient ones, or, when the catalogue
    declares the dismiss's trace types for this card role (`dismiss_trace`), only those, each at most once; the next
    deadline is none or exactly the declared restart (any other deadline cannot be told from the layer's own timer
    by parts: not exactly the layer leaving)."""
    keys = {line.split("\t", 1)[0] for line in verdict.removed}
    counts = _counts(before, role)
    rest = [line for line in before["semantic"] if line not in verdict.removed]
    bad = []
    if len(rest) == len(before["semantic"]) or _plain(after["semantic"], role) != _plain(rest, role):
        bad.append("semantic")
    if after["env"] != before["env"]:
        bad.append("env")
    if any(p.fields[1] not in keys and not _patch_exempt(p.fields, counts) for p in patches):
        bad.append("patches")
    kinds = [record.fields[1] for record in trace]
    allowed = dismiss_trace or ()
    if any(kind not in allowed for kind in kinds) or len(set(kinds)) != len(kinds):
        bad.append("trace")
    if not (after["due"] is None or after["due"] == restart):
        bad.append("due")
    return bad


def like_sibling(sibling, before, after, patches, trace, role=None, restart=None):
    """The parts of a tap's change that differ from applying the layer's own intent from the same state (a sibling
    replay, ui_explore_scene.Scene.sibling), with the same exemptions on BOTH sides: a countdown-role node's label and
    its `update <key> text` patches, and the declared ambient events (set aside in the sibling by Scene.sibling, in
    the tap by the ambient rule); semantic, env, the next deadline (or the declared restart), patches, and the trace
    records' type and time."""
    counts = _counts(before, role)
    own = [p.raw for p in patches if not _patch_exempt(p.fields, counts)]
    theirs = [raw for raw in sibling["patches"] if not _patch_exempt(raw.split("\t"), counts)]
    bad = []
    if _plain(after["semantic"], role) != _plain(sibling["semantic"], role):
        bad.append("semantic")
    if after["env"] != sibling["env"]:
        bad.append("env")
    if own != theirs:
        bad.append("patches")
    if [(r.fields[1], r.fields[2]) for r in trace] != sibling["trace"]:
        bad.append("trace")
    if after["due"] != sibling["due"] and after["due"] != restart:
        bad.append("due")
    return bad
