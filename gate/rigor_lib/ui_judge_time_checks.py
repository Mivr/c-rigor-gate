"""The checks of the `ui-time` judge (U09, P004 3.5) over timelines (ui_judge_time_model.Facts), pure: no probe, no clock.

Each check returns verdicts `(check, identity, observed, at, target)`: `at` the index of the step whose state and path
the finding takes, `target` what an `[[exception]]` names. Instants are virtual ms; a disappearance is known only
between two observations, so every rule is decided on bounds and gives a finding only when the bound decides it
(docs/ui-judges-time.md, "The rules").
"""

from rigor_lib.ui_judge_time_model import countdown_value

GRID = 16            # samples per probing run (the time-probing mode)
SECOND_MS = 1000     # the countdown's unit (P004 3.5: it changes at least once per virtual second)


def verdict(check, identity, observed, target, state_at=None, path_at=None):
    """One verdict: the judge turns it into a finding (state and path of `state_at` and `path_at`, indexes into the
    timeline it judged; None: the appearance's)."""
    return {"check": check, "identity": identity, "observed": observed, "target": target, "state_at": state_at,
            "path_at": path_at}


def ceil_div(a, b):
    return -(-a // b)


def _points(start, end, gap, max_wait):
    """Instants after `start` up to `end` included, `gap` apart, and never more than `max_wait` apart."""
    step = max(1, min(gap, max_wait))
    out, at = [], start
    while at < end:
        at = min(at + step, end)
        out.append(at)
    return out


def plan(appear, lifetime, dwell, tick, max_wait):
    """The instants of the first probing run after the appearance step `appear`: the two deciding instants (the last
    instant at which a short element is already gone, appear_lo + D - tick - 1, and the first at which a long one is
    still shown, appear + L + tick) and a grid of at most GRID instants up to the later one. Empty when nothing can be
    decided (no limit and no known dwell)."""
    targets = set()
    if lifetime > 0:
        targets.add(appear.now + lifetime + tick)
    if dwell is not None and appear.appear_lo + dwell - tick - 1 > appear.now:
        targets.add(appear.appear_lo + dwell - tick - 1)
    if not targets:
        return []
    horizon = max(targets)
    gap = tick * max(1, ceil_div(horizon - appear.now, GRID * tick))
    return sorted(set(_points(appear.now, horizon, gap, max_wait)) | targets)


def refine(lo, hi, tick, max_wait):
    """The instants of a refining run inside the bracket (lo, hi] of a disappearance, or [] when it is within a tick."""
    if hi - lo <= tick:
        return []
    gap = tick * max(1, ceil_div(hi - lo, GRID * tick))
    return [at for at in _points(lo, hi, gap, max_wait) if at < hi]


def bracket(appear, samples, kind):
    """(t1_lo, t1_hi): the disappearance lies in (t1_lo, t1_hi]; t1_hi None when it was shown at every sample."""
    gone = [s.now for s in samples if kind not in s.present]
    t1_hi = min(gone) if gone else None
    shown = [s.now for s in samples if kind in s.present and (t1_hi is None or s.now < t1_hi)]
    return max([appear.now] + shown), t1_hi


def lifetime_verdicts(kind, appear, lo_hi, timer, dwell, floor, tick):
    """notice-lifetime-short (D known), its floor approximation (D unknown, `floor` = max(L, dwell_floor_ms)) and
    notice-lifetime-long; and the measured lifetime bounds `(above, at_most)` (at_most None: still shown)."""
    t1_lo, t1_hi = lo_hi
    above = t1_lo - appear.now
    at_most = None if t1_hi is None else t1_hi - appear.appear_lo
    lifetime, out = timer["lifetime_ms"], []
    observed = {"kind": kind, "lifetime_ms": lifetime, "tick_ms": tick, "shown_more_than_ms": above,
                "shown_at_most_ms": at_most}
    if dwell is not None and at_most is not None and at_most < dwell - tick:
        out.append(verdict("notice-lifetime-short", [kind], dict(observed, dwell_ms=dwell), kind))
    if dwell is None and floor is not None and at_most is not None and at_most < floor - tick:
        out.append(verdict("notice-lifetime-short-floor", [kind], dict(observed, floor_ms=floor), kind))
    if lifetime > 0 and above >= lifetime + tick:
        out.append(verdict("notice-lifetime-long", [kind], observed, kind))
    return (above, at_most), out


def _changes(fact, keys):
    """(number of changes of the countdown keys' values in the step's patches, values shown, increases)."""
    changes, values, increases = 0, [], []
    for op, key, name, old, new in fact.patches:
        if op != "update" or name != "text" or key not in keys:
            continue
        before, after = countdown_value(old), countdown_value(new)
        values += [v for v in (before, after) if v is not None]
        if before is not None and after is not None and before != after:
            changes += 1
            if after > before and key not in fact.restarts:
                increases.append([before, after])
    return changes, values, increases


def countdown_verdicts(kind, seq, timer):
    """countdown-wrong over one run's consecutive observations `seq` from the appearance on (P004 3.5): the countdown
    is present while the element is shown (`absent`), starts at ceil(L/1000) +-1 (`start`), never shows 0 (`zero`),
    never increases in a time step but by a declared restart (`increase`), and changes at least once per virtual second
    (`stalled`: no change for 1000 ms or more after the last instant a change can have happened, or one step of W ms
    with c changes and W >= 1000 (c + 1))."""
    parts = {}
    want = ceil_div(timer["lifetime_ms"], SECOND_MS)
    quiet = seq[0].now if seq else 0
    for m, fact in enumerate(seq):
        if kind not in fact.present:
            break
        shown = fact.countdowns.get(kind, ())
        if not shown:
            parts.setdefault("absent", {"step": fact.index})
        values = [v for _key, v in shown if v is not None]
        if m == 0 and values and timer["lifetime_ms"] > 0 and abs(values[0] - want) > 1:
            parts.setdefault("start", {"step": fact.index, "shown": values[0], "wanted": want})
        keys = {key for key, _v in shown} | ({k for k, _v in seq[m - 1].countdowns.get(kind, ())} if m else set())
        changes, seen, increases = (0, [], []) if m == 0 else _changes(fact, keys)
        if 0 in values + seen:
            parts.setdefault("zero", {"step": fact.index})
        if m == 0 or fact.mode != "time":
            quiet = fact.now
            continue
        if increases:
            parts.setdefault("increase", {"step": fact.index, "values": increases[0]})
        span = fact.now - seq[m - 1].now
        if changes:
            quiet = fact.now
        if span >= SECOND_MS * (changes + 1) or fact.now - quiet >= SECOND_MS:
            parts.setdefault("stalled", {"step": fact.index, "span_ms": max(span, fact.now - quiet),
                                         "changes": changes})
    return [verdict("countdown-wrong", [kind, part], dict(detail, kind=kind, part=part), kind)
            for part, detail in sorted(parts.items())]


def flash_verdicts(facts, threshold):
    """flash: a scene node (not a countdown) created and removed with no input after its creation, within less than
    the flash threshold, measured on the patches (`create`/`remove`); a node created and removed within ONE step is
    judged by that step's span (0 for an input). Returns (verdicts, the number of removals judged)."""
    born, out, judged = {}, [], 0
    for at, fact in enumerate(facts):
        if fact.mode != "time":
            born = {}
        for op, key, _name, old, new in fact.patches:
            role = (new if op == "create" else old).decode("ascii", "replace")
            if op == "create" and role != "countdown":
                born[key] = (at, fact.appear_lo, role)
            elif op == "remove" and key in born:
                created, lo, role = born.pop(key)
                judged += 1
                if fact.now - lo < threshold:
                    out.append(verdict("flash", [key, role], {
                        "key": key, "role": role, "shown_at_most_ms": fact.now - lo, "threshold_ms": threshold,
                        "steps": [facts[created].index, fact.index]}, key, created, at))
    return out, judged


def invisible_verdicts(facts):
    """invisible-auto-transition: a time step that changes the identity's state class while the semantic records and
    the frame (but its life and taps lines) are unchanged. Returns (verdicts, the time steps judged)."""
    out, judged = [], 0
    for m in range(1, len(facts)):
        before, fact = facts[m - 1], facts[m]
        if fact.mode != "time" or before.cls is None or fact.cls is None:
            continue
        judged += 1
        if before.cls != fact.cls and before.semantic == fact.semantic and before.frame == fact.frame:
            out.append(verdict("invisible-auto-transition", [before.cls, fact.cls],
                               {"from": before.cls, "to": fact.cls, "word": fact.word, "step": fact.index},
                               "%s/%s" % (before.cls, fact.cls), m - 1, m))
    return out, judged
