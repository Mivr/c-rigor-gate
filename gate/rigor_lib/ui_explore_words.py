"""What one path word does through the probe (U05; docs/ui-explore.md "Paths and time"): inputs with the gate's own
"a refusal changes nothing" check, virtual time bounded by `max_wait_ms`, advances split on the frame grid with the
logs drained every `drain_ms`, and the firing count of `timer-starvation`.

Inputs: every `apply` (and `tap`) of a word is checked on its own. Before it the explorer holds a snapshot of the model
(frame records without `life` lines, semantic records, next deadline, env inputs; the step before's observation for the
first input of a word, a fresh one otherwise, read frame first); after a refused input it takes another, and drains
patches and trace: anything new, any difference or a `life` line in the after frame is `probe-internal-error` kind
`contract`. A word's outcome is the outcome of its LAST input (a pad macro is
accepted only when its enter is). `missed` (a probe with apply-missed) is not a refusal and is not checked.

Advances: spans of at most min(SPAN_FRAMES, drain_ms / 16) frames, every span ending on the grid `origin + k * 16` (or
at the target), with patches and trace fetched after every span that does not end the advance. The probe's loop
ends every `uim_step` at each grid boundary and each deadline anyway, so the split calls the model with exactly the
same step lengths as one long advance; it only bounds the work per command and the log volume between drains.
"""

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import BUF_MAX
from rigor_lib.ui_explore_key import key_hash, projection
from rigor_lib.ui_explore_png import write_png
from rigor_lib.ui_explore_probe import FRAME_MS, TIME_MAX_MS, ProbeError

SPAN_FRAMES = 64


def raws(records):
    return [record.raw for record in records]


def snapshot_of(obs):
    """What "nothing changed" compares: semantic, deadline, env inputs and the frame records, the frame without its
    `life` lines (a `life` line is in the first frame after its event only, so it is kept apart: `life`)."""
    frame = raws(obs["frame"])
    return {"semantic": raws(obs["semantic"]), "due": obs["due"], "env": [list(i) for i in obs["env"]],
            "frame": [line for line in frame if not line.startswith("life\t")],
            "life": [line for line in frame if line.startswith("life\t")]}


def collect(session, step):
    """Fetch patches and trace into the step (they are logs: what is read is gone from the model)."""
    step.acc_patches.extend(session.records("patches"))
    step.acc_trace.extend(session.records("trace"))


def observe(session, step):
    """The model's state in the order of the step's own observation: `frame` FIRST (it runs the product's due work and
    may retake the snapshot), then semantic, patches and trace (into the step), the deadline and the env inputs."""
    frame = session.frame()
    semantic = session.records("semantic")
    collect(session, step)
    return {"frame": frame, "semantic": semantic, "due": session.next_due(), "env": session.env_inputs()}


def snapshot(session, step):
    return snapshot_of(observe(session, step))


def changes(step, marks, before, after, frame=True):
    """What changed between two snapshots: new patches or trace since `marks`, semantic, due, env; with `frame`, the
    frame records too, and any `life` line in the after frame (an object was created or deleted)."""
    changed = [name for name, mark in zip(("patches", "trace"), marks) if len(getattr(step, "acc_" + name)) > mark]
    changed += [name for name in ("semantic", "due", "env") if after[name] != before[name]]
    if frame and (after["frame"] != before["frame"] or after["life"]):
        changed.append("frame")
    return changed


# ---- inputs ---------------------------------------------------------------------------------------------------
def _input(session, step, before, send, label):
    """Send one input; returns the snapshot after it when it was refused (checked against `before`), else None."""
    result = send()
    step.applies.append(result)
    step.outcome.append("%s %s" % (label, result))
    if result != "refused":
        return None
    marks = (len(step.acc_patches), len(step.acc_trace))
    after = snapshot(session, step)
    changed = changes(step, marks, before, after)
    if changed:
        raise ProbeError("contract", label, "a refused input changed the model: " + ", ".join(changed))
    return after


def inputs(session, step, before, sends):
    """Send `sends` = [(label, callable or tap event)] in order, each checked against a snapshot taken before it."""
    for label, send in sends:
        if before is None:
            before = snapshot(session, step)
        before = tap_input(session, step, before, send) if label == "tap" else \
            _input(session, step, before, send, label)


# ---- catalogue taps (u2, u3): docs/ui-explore.md "Taps" ---------------------------------------------------------
IMAGE_SIDE = 256     # evidence images show at most the top-left 256 x 256 pixels of a node's box


def frame_nodes(frame_lines):
    """{walk index: (parent, depth, class, (x1, y1, x2, y2))} of the `node` records, and the display size, from frame
    lines (escaped raws; the grammar checked the numbers)."""
    nodes, size = {}, None
    for line in frame_lines:
        fields = line.split("\t")
        if fields[0] == "node":
            nodes[int(fields[1])] = (int(fields[2]), int(fields[3]), fields[4], tuple(int(v) for v in fields[5:9]))
        elif fields[0] == "frame":
            size = (int(fields[1]), int(fields[2]))
    return nodes, size


def aimed_node(nodes, event):
    """The node a u2 event aims at: the deepest (then the last drawn) node of its declared `target` class whose box
    holds the point, in the frame before the tap; None without a target or without such a node."""
    target, x, y = dict(event.spec).get("target"), event.get("x"), event.get("y")
    found = [(depth, index) for index, (parent, depth, cls, (x1, y1, x2, y2)) in nodes.items()
             if target is not None and cls == target and x1 <= x <= x2 and y1 <= y <= y2]
    return max(found)[1] if found else None


def image_box(box, size):
    """(x, y, w, h) of the evidence image of a node box: cut to the display and to IMAGE_SIDE; None if empty."""
    if size is None:
        return None
    x1, y1, x2, y2 = max(box[0], 0), max(box[1], 0), min(box[2], size[0] - 1), min(box[3], size[1] - 1)
    if x2 < x1 or y2 < y1:
        return None
    return x1, y1, min(x2 - x1 + 1, IMAGE_SIDE), min(y2 - y1 + 1, IMAGE_SIDE)


def box_image(session, box):
    """PNG bytes of `box` (x, y, w <= IMAGE_SIDE, h) of the current frame, read with `crop` in row bands that each fit one
    reply; None from a probe without crop."""
    if "crop" not in session.caps:
        return None
    x, y, w, h = box
    rows = (BUF_MAX - 1) // (8 * w + 1)
    data = b"".join(session.crop(x, top, w, min(rows, y + h - top)) for top in range(y, y + h, rows))
    return write_png(w, h, data)


def _pressed(step, nodes, expect, got, event):
    """The node the tap pressed, or None when it pressed nothing or a screen or layer root (a node with no parent); the
    step's outcome records the pressed node (index, class, box) and whether it is the node the event aimed at. A probe
    that contradicts itself is a ProbeError kind contract."""
    if (expect == "blocked") != (got == "blocked"):
        raise ProbeError("contract", "tap", "the hit query and the tap disagree on whether a tap is processed")
    if got == "blocked":
        step.outcome.append("pressed blocked")
        return None
    if got[0] != expect:
        raise ProbeError("contract", "tap", "the tap pressed another node than the hit query found")
    if got[0] is None:
        step.outcome.append("pressed none")
        return None
    if got[0] not in nodes:
        raise ProbeError("contract", "tap", "the tap pressed a node that is not in the frame")
    parent, _, cls, box = nodes[got[0]]
    aimed = aimed_node(nodes, event)
    how = "root" if parent == -1 else "aimed" if aimed == got[0] else "other" if aimed is not None else "untargeted"
    step.outcome.append("pressed %d %s %s %s" % (got[0], cls, ",".join(str(v) for v in box), how))
    if how == "other":
        step.misrouted = {"pressed": {"index": got[0], "class": cls, "box": list(box)},
                          "aimed": {"index": aimed, "class": nodes[aimed][2], "box": list(nodes[aimed][3])}}
    return None if parent == -1 else got[0]


def tap_input(session, step, before, event):
    """`hit-test x y`, `tap x y`, then a snapshot (frame first). A u2 tap that pressed a node (not a root): `ok` when the
    model changed, `missed` when it did not (the node's box becomes the evidence image); one that was blocked or pressed
    nothing or a root, and every u3 tap: `refused` when nothing changed, else `ok` and the finding `noop-tap-effect`."""
    x, y = event.get("x"), event.get("y")
    nodes, size = frame_nodes(before["frame"])
    expect = session.hit_test(x, y)
    got = session.tap(x, y)
    marks = (len(step.acc_patches), len(step.acc_trace))
    after = snapshot(session, step)
    node = _pressed(step, nodes, expect, got, event)
    if event.cls == "u2" and node is not None:
        result = "ok" if changes(step, marks, before, after, frame=False) else "missed"
        if result == "missed" or step.misrouted:
            step.image_box = image_box(nodes[node][3], size)
    else:
        changed = changes(step, marks, before, after)
        result = "ok" if changed else "refused"
        if changed:
            step.noop = {"changed": changed}
    step.applies.append(result)
    step.outcome.append("tap %s" % result)
    return after


def input_sends(session, event):
    cls = event.cls
    apply = session.apply
    if cls in ("u1", "u5"):
        return [("apply", lambda: apply(3, event.get("intent"), event.get("arg"), ""))]
    if cls == "e1":
        return [("apply", lambda: apply(1, event.get("env"), event.get("arg"), event.get("hex")))]
    if cls == "u4" and event.get("via") == "wedge":
        return [("apply", lambda: apply(2, 0, 0, event.get("hex")))]
    if cls == "u4":
        digits = [("apply", lambda d=int(d): apply(3, event.get("digit_intent"), d, "")) for d in event.get("digits")]
        return digits + [("apply", lambda: apply(3, event.get("enter_intent"), 0, ""))]
    if cls in ("u2", "u3"):
        return [("tap", event)]
    raise InternalError("event %s is not an input" % event.id)


# ---- time -----------------------------------------------------------------------------------------------------
def reachable(session, step, target, start, limit):
    """False (and the step records why: `timer-unreachable`) when `target` is past the protocol's clock or more than
    `limit` after `start`."""
    reason = "protocol-limit" if target > TIME_MAX_MS else "max-wait" if target - start > limit else None
    if reason:
        step.unreachable = {"target_ms": target, "now_ms": session.now, "max_wait_ms": limit, "reason": reason}
        step.outcome.append("unreachable")
    return reason is None


def advance_to(session, step, target, catalogue):
    frames = min(SPAN_FRAMES, catalogue.drain_ms // FRAME_MS)
    while session.now < target:
        end = session.origin + ((session.now - session.origin) // FRAME_MS + frames) * FRAME_MS
        session.advance(min(target, end))
        if session.now < target:
            collect(session, step)


def fired(session, step, run, catalogue):
    """Count one deadline firing; True when the run is now starving: more than `starve_firings` firings within the
    last `starve_window_frames` frames of virtual time (reported once per run)."""
    run.fire_log.append((session.now, step.index))
    window = catalogue.starve_window_frames * FRAME_MS
    while run.fire_log[run.fire_start][0] <= session.now - window:
        run.fire_start += 1
    count = len(run.fire_log) - run.fire_start
    if count <= catalogue.starve_firings or run.starved:
        return False
    first_ms, first_step = run.fire_log[run.fire_start]
    start = run.steps[first_step]
    step.starved = {"firings": count, "limit": catalogue.starve_firings, "window_ms": window, "first_ms": first_ms,
                    "last_ms": session.now, "start_key": start.key_before, "start_proj": start.proj_before}
    run.starved = True
    return True


def fire_due(session, step, run, catalogue, before):
    due = session.next_due()
    if due is None:
        step.outcome.append("no-deadline")
        return
    target = due - FRAME_MS if before else due
    if target <= session.now:
        step.outcome.append("deadline-within-a-frame")
        return
    if not reachable(session, step, target, session.now, catalogue.max_wait_ms):
        return
    advance_to(session, step, target, catalogue)
    if before:
        step.outcome.append("now %d" % session.now)
    else:
        step.outcome.append("fired %d" % session.now)
        fired(session, step, run, catalogue)


def advance_by(session, step, target, catalogue):
    if target <= session.now:
        step.outcome.append("past")
    elif reachable(session, step, target, session.now, catalogue.max_wait_ms):
        advance_to(session, step, target, catalogue)
        step.outcome.append("now %d" % session.now)


def until_change(session, step, run, catalogue, base):
    """Fire deadlines until the abstraction key differs from `base`. A first deadline past `max_wait_ms` or the clock
    limit is `timer-unreachable`, as for fire-due; a later one ends the word with `no-change` (a quiet state of a product
    with a perpetual tick); `starving` when the firings starve."""
    start, first = session.now, True
    while True:
        due = session.next_due()
        if due is None:
            step.outcome.append("no-deadline")
            return
        if first and not reachable(session, step, due, start, catalogue.max_wait_ms):
            return
        if due > TIME_MAX_MS or due - start > catalogue.max_wait_ms:
            step.outcome.append("no-change")
            return
        advance_to(session, step, due, catalogue)
        if fired(session, step, run, catalogue):
            step.outcome.append("starving")
            return
        obs = {"semantic": session.records("semantic"), "due": session.next_due(), "env": session.env_inputs()}
        if key_hash(projection(obs, session.now, catalogue.key)) != base:
            step.outcome.append("changed %d" % session.now)
            return
        first = False


def time_event(session, step, run, event, catalogue, base):
    kind = event.get("kind")
    if kind in ("fire-due", "before-due"):
        fire_due(session, step, run, catalogue, kind == "before-due")
    elif kind == "advance":
        advance_by(session, step, session.now + event.get("ms"), catalogue)
    elif kind == "at":
        advance_by(session, step, session.origin + event.get("offset_ms"), catalogue)
    else:
        until_change(session, step, run, catalogue, base)


def outcome_kind(item):
    """The type of one outcome (its words without the numbers), as the summary counts them."""
    return " ".join(word for word in item.split(" ") if not word.isdigit())
