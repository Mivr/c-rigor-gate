"""What one path word does through the probe (U05; docs/ui-explore.md "Paths and time"): inputs with the gate's own
"a refusal changes nothing" check, virtual time bounded by `max_wait_ms`, advances split on the frame grid with the
logs drained every `drain_ms`, and the firing count of `timer-starvation`.

Inputs: every `apply` (and `tap`) of a word is checked on its own. Before it the explorer holds a snapshot of the model
(semantic records, next deadline, env inputs, frame lines; the step before's observation for the first input of a word,
a fresh one otherwise); after a refused input it takes another, and drains patches and trace: anything new, or any
difference, is `probe-internal-error` kind `contract`. A word's outcome is the outcome of its LAST input (a pad macro is
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
    return {"semantic": raws(obs["semantic"]), "due": obs["due"], "env": [list(i) for i in obs["env"]],
            "frame": raws(obs["frame"])}


def collect(session, step):
    """Fetch patches and trace into the step (they are logs: what is read is gone from the model)."""
    step.acc_patches.extend(session.records("patches"))
    step.acc_trace.extend(session.records("trace"))


def observe(session, step):
    """Patches and trace into the step, then the model's state (semantic, deadline, env inputs, frame records)."""
    collect(session, step)
    return {"semantic": session.records("semantic"), "due": session.next_due(), "env": session.env_inputs(),
            "frame": session.frame()}


def snapshot(session, step):
    return snapshot_of(observe(session, step))


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
    changed = [name for name, mark in zip(("patches", "trace"), marks)
               if len(getattr(step, "acc_" + name)) > mark]
    changed += [name for name in ("semantic", "due", "env", "frame") if after[name] != before[name]]
    if changed:
        raise ProbeError("contract", label, "a refused input changed the model: " + ", ".join(changed))
    return after


def inputs(session, step, before, sends):
    """Send `sends` = [(label, callable)] in order, each checked against a snapshot taken before it."""
    for label, send in sends:
        if before is None:
            before = snapshot(session, step)
        before = tap_input(session, step, before, send) if label == "tap" else \
            _input(session, step, before, send, label)


# ---- catalogue taps (u2, u3): docs/ui-explore.md "Taps" ---------------------------------------------------------
def node_box(frame, node):
    """(x, y, w, h) of walk node `node` cut to the display, from the frame's `frame` and `node` records; None if empty."""
    size = next((r for r in frame if r.fields[0] == "frame"), None)
    record = next((r for r in frame if r.fields[0] == "node" and r.fields[1] == str(node)), None)
    if size is None or record is None:
        return None
    width, height = int(size.fields[1]), int(size.fields[2])
    x1, y1, x2, y2 = (int(v) for v in record.fields[5:9])
    x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, width - 1), min(y2, height - 1)
    return None if x2 < x1 or y2 < y1 else (x1, y1, x2 - x1 + 1, y2 - y1 + 1)


def node_image(session, frame, node):
    """PNG bytes of walk node `node`'s box in the current frame, fetched in row bands that each fit one `crop` reply;
    None from a probe without frame facts or crop, or for an empty box."""
    if not all(cap in session.caps for cap in ("frame-facts", "crop")):
        return None
    box = node_box(frame, node)
    if box is None:
        return None
    x, y, w, h = box
    rows = (BUF_MAX - 1) // (8 * w + 1)
    data = b"".join(session.crop(x, top, w, min(rows, y + h - top)) for top in range(y, y + h, rows))
    return write_png(w, h, data)


def _tap_result(event, expect, got, changed):
    """The outcome of a catalogue tap, or a ProbeError when the probe contradicts itself or a tap that must change
    nothing changed the model."""
    if (expect == "blocked") != (got == "blocked"):
        raise ProbeError("contract", "tap", "the hit query and the tap disagree on whether a tap is processed")
    pressed = None if got == "blocked" else got[0]
    if got != "blocked" and pressed != expect:
        raise ProbeError("contract", "tap", "the tap pressed another node than the hit query found")
    if event.cls == "u3" or pressed is None:
        if changed:
            what = "a complement tap" if event.cls == "u3" else "a tap that pressed nothing"
            raise ProbeError("contract", "tap", "%s changed the model: %s" % (what, ", ".join(changed)))
        return "refused"
    return "ok" if changed else "missed"


def tap_input(session, step, before, event):
    """`hit-test x y`, then `tap x y`, then a snapshot. u2: `ok` when the tap pressed a node and changed the model,
    `missed` when it pressed one and changed nothing (with the node's image), `refused` when it was blocked or pressed
    nothing (and then nothing may change). u3: `refused`, and nothing may change."""
    x, y = event.get("x"), event.get("y")
    expect = session.hit_test(x, y)
    got = session.tap(x, y)
    marks = (len(step.acc_patches), len(step.acc_trace))
    obs = observe(session, step)
    after = snapshot_of(obs)
    changed = [name for name, mark in zip(("patches", "trace"), marks) if len(getattr(step, "acc_" + name)) > mark]
    changed += [name for name in ("semantic", "due", "env") if after[name] != before[name]]
    result = _tap_result(event, expect, got, changed)
    if result == "refused" and after["frame"] != before["frame"]:
        raise ProbeError("contract", "tap", "a tap that must change nothing changed the frame")
    if result == "missed":
        image = node_image(session, obs["frame"], got[0])
        if image is not None:
            step.images["tap-node.png"] = image
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
