"""The checks of the `ui-time` judge (U09, P004 3.5) over timelines (ui_judge_time_model.Facts), pure: no probe, no clock.

Each check returns verdicts (`verdict`): the judge turns them into findings. Instants are virtual ms. An appearance is
known as a bracket (a_lo, a_hi): the element can have been shown from a_lo on and was shown at a_hi; a disappearance as
(t1_lo, t1_hi]. Every lifetime rule is decided on those bounds: yes, no, or None (undecided: the judge reports
`lifetime-undecided`), never guessed (docs/ui-judges-time.md, "The rules").
"""

from rigor_lib.ui_judge_time_model import countdown_value

GRID = 16            # samples per probing run inside a bracket
SECOND_MS = 1000     # the countdown's unit (P004 3.5: it changes at least once per virtual second)
MAX_AT = 64          # `at` words per probing run; a plan that needs more is not run (lifetime-undecided)


def verdict(check, identity, observed, target, state_at=None, path_at=None):
    """One verdict: the judge turns it into a finding (state and path of `state_at` and `path_at`, indexes into the
    timeline it judged; None: the appearance's)."""
    return {"check": check, "identity": identity, "observed": observed, "target": target, "state_at": state_at,
            "path_at": path_at}


def ceil_div(a, b):
    return -(-a // b)


def points(start, end, gap, max_wait):
    """Instants after `start` up to `end` included, `gap` apart, and never more than `max_wait` apart."""
    step = max(1, min(gap, max_wait))
    out, at = [], start
    while at < end:
        at = min(at + step, end)
        out.append(at)
    return out


def plan(now, a_hi, lifetime, dwell, tick, max_wait):
    """The instants of the first probing run after the appearance step (at `now`; the element shown since a_hi at the
    latest): the deciding instants a_hi + D - tick - 1 (shown then: not short) and a_hi + L + tick (shown then: long),
    and a grid of GRID instants up to the later one, in ticks, never more than `max_wait` apart. Empty when nothing can
    be decided (no limit, no known dwell) or both instants are already behind."""
    targets = set()
    if lifetime > 0:
        targets.add(a_hi + lifetime + tick)
    if dwell is not None:
        targets.add(a_hi + dwell - tick - 1)
    targets = {t for t in targets if t > now}
    if not targets:
        return []
    horizon = max(targets)
    gap = tick * max(1, ceil_div(horizon - now, GRID * tick))
    return sorted(set(points(now, horizon, gap, max_wait)) | targets)


def refine(lo, hi, max_wait):
    """At most GRID - 1 instants strictly inside (lo, hi), evenly apart; [] when the bracket is one ms."""
    if hi - lo <= 1:
        return []
    return [at for at in points(lo, hi, ceil_div(hi - lo, GRID), max_wait) if at < hi]


def rising(samples, kind, lo, hi):
    """The appearance bracket inside (lo, hi]: (the last instant not shown before the first shown, the first shown)."""
    first = min([s.now for s in samples if kind in s.present and lo < s.now <= hi] + [hi])
    return max([lo] + [s.now for s in samples if kind not in s.present and lo < s.now < first]), first


def falling(samples, kind, now):
    """(t1_lo, t1_hi): the disappearance after `now` lies in (t1_lo, t1_hi]; t1_hi None when shown at every sample."""
    gone = [s.now for s in samples if kind not in s.present and s.now > now]
    t1_hi = min(gone) if gone else None
    shown = [s.now for s in samples if kind in s.present and s.now > now and (t1_hi is None or s.now < t1_hi)]
    return max([now] + shown), t1_hi


def decisions(appear, gone, lifetime, dwell, floor, tick):
    """{check: True (defect) / False (none) / None (undecided)} of the lifetime rules, and the bounds (above,
    at_most): shown for more than `above` ms and at most `at_most` (None: still shown at the last sample).
    `appear` = (a_lo, a_hi), a_lo the first instant it can have been shown; `gone` = (t1_lo, t1_hi)."""
    above = gone[0] - appear[1]
    at_most = None if gone[1] is None else gone[1] - appear[0]
    out = {}
    for check, bound in (("notice-lifetime-short", dwell),
                         ("notice-lifetime-short-floor", floor if dwell is None else None)):
        if bound is not None:
            out[check] = True if at_most is not None and at_most < bound - tick else \
                (False if above + 1 >= bound - tick else None)
    if lifetime > 0:
        out["notice-lifetime-long"] = True if above >= lifetime + tick else \
            (False if at_most is not None and at_most <= lifetime + tick else None)
    return out, (above, at_most)


def _changes(fact, keys, shown):
    """(changes of the countdown keys' values in the step's patches, zero shown at a step end, increases): a patch
    value of 0 counts only on a node still shown, with a value, at the end of that step."""
    changes, zero, increases = 0, False, []
    for op, key, name, old, new in fact.patches:
        if op != "update" or name != "text" or key not in keys:
            continue
        before, after = countdown_value(old), countdown_value(new)
        zero = zero or (after == 0 and key in shown)
        if before is not None and after is not None and before != after:
            changes += 1
            if after > before and key not in fact.restarts:
                increases.append([before, after])
    return changes, zero, increases


def countdown_verdicts(kind, seq, timer, a_lo):
    """countdown-wrong over one run's consecutive observations `seq` from the appearance on (P004 3.5): `absent` (no
    countdown in the element's scope while shown), `start` (the first value outside ceil(L/1000) +-1; seen up to
    now - a_lo ms after the appearance, any value down to ceil((L - that)/1000) - 1), `zero` (0 as a step-end label, or
    a patch to 0 on a node still shown at the end of that step), `increase` (a value that grows but by a declared
    restart), `stalled` (no change for 1000 ms after the last instant a change can have happened, or one step of W ms
    with c changes and W >= 1000 (c + 1)). A step whose patches disagree with its records judges no change."""
    parts = {}
    want = ceil_div(timer["lifetime_ms"], SECOND_MS)
    low = ceil_div(timer["lifetime_ms"] - (seq[0].now - a_lo), SECOND_MS) if seq else want
    quiet = seq[0].now if seq else 0
    for m, fact in enumerate(seq):
        if kind not in fact.present:
            break
        shown = fact.countdowns.get(kind, ())
        if not shown:
            parts.setdefault("absent", {"step": fact.index})
            quiet = fact.now                      # no countdown: `absent`, not also `stalled`
            continue
        values = [v for _key, v in shown if v is not None]
        if m == 0 and values and timer["lifetime_ms"] > 0 and not low - 1 <= values[0] <= want + 1:
            parts.setdefault("start", {"step": fact.index, "shown": values[0], "wanted": [low, want]})
        keys = {key for key, _v in shown} | ({k for k, _v in seq[m - 1].countdowns.get(kind, ())} if m else set())
        changes, zero, increases = (0, False, []) if m == 0 or fact.chain else \
            _changes(fact, keys, {key for key, v in shown if v is not None})
        if 0 in values or zero:
            parts.setdefault("zero", {"step": fact.index})
        if increases:
            parts.setdefault("increase", {"step": fact.index, "values": increases[0]})
        if m == 0 or fact.mode != "time" or fact.chain:
            quiet = fact.now
            continue
        span = fact.now - seq[m - 1].now
        if changes:
            quiet = fact.now
        if span >= SECOND_MS * (changes + 1) or fact.now - quiet >= SECOND_MS:
            parts.setdefault("stalled", {"step": fact.index, "span_ms": max(span, fact.now - quiet),
                                         "changes": changes})
    return [verdict("countdown-wrong", [kind, part], dict(detail, kind=kind, part=part), kind)
            for part, detail in sorted(parts.items())]


def zero_verdicts(kind, samples):
    """countdown-wrong part `zero` from the step-end labels of every probing sample that shows the element."""
    for fact in samples:
        if kind in fact.present and 0 in [v for _k, v in fact.countdowns.get(kind, ())]:
            return [verdict("countdown-wrong", [kind, "zero"], {"step": fact.index, "kind": kind, "part": "zero"},
                            kind)]
    return []


def increase_verdicts(facts):
    """countdown-wrong part `increase` on a path, input steps included: a countdown whose value grows while its
    element stays shown, unless it is a declared countdown restart on a tap (U05d). Returns (verdicts, steps judged)."""
    out, judged = [], 0
    for m in range(1, len(facts)):
        fact, before = facts[m], facts[m - 1]
        for kind in sorted(fact.present & before.present):
            keys = {k for k, _v in fact.countdowns.get(kind, ())} & {k for k, _v in before.countdowns.get(kind, ())}
            if not keys or fact.chain:
                continue
            judged += 1
            increases = _changes(fact, keys, keys)[2]
            if increases:
                out.append(verdict("countdown-wrong", [kind, "increase"], {
                    "step": fact.index, "kind": kind, "part": "increase", "values": increases[0]}, kind, m, m))
    return out, judged


def flash_verdicts(facts, threshold):
    """flash: a scene node (not a countdown) created and removed with no user input (u1..u5, a domain move or open)
    after its creation, within less than the flash threshold, measured on the patches (`create`/`remove`) of steps
    whose patches agree with their records; a node created and removed within ONE step is judged by that step's span
    (0 for an input). Returns (verdicts, the number of removals judged)."""
    born, out, judged = {}, [], 0
    for at, fact in enumerate(facts):
        if fact.mode not in ("time", "env") or fact.chain:
            born = {}
        if fact.chain:
            continue
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
    """invisible-auto-transition: a time or env step (no user input) that changes the identity's state class while the
    semantic records and the frame (but its life and taps lines) are unchanged. Returns (verdicts, the steps judged)."""
    out, judged = [], 0
    for m in range(1, len(facts)):
        before, fact = facts[m - 1], facts[m]
        if fact.mode not in ("time", "env") or before.cls is None or fact.cls is None:
            continue
        judged += 1
        if before.cls != fact.cls and before.semantic == fact.semantic and before.frame == fact.frame:
            out.append(verdict("invisible-auto-transition", [before.cls, fact.cls],
                               {"from": before.cls, "to": fact.cls, "word": fact.word, "step": fact.index},
                               "%s/%s" % (before.cls, fact.cls), m - 1, m))
    return out, judged


def chain_verdicts(facts):
    """patches-inconsistent: a step whose patches do not lead from the records before it to its own (patches are the
    product's claim; flash and the countdown's changes read them). Returns (verdicts, steps judged)."""
    out = [verdict("patches-inconsistent", [fact.word, fact.chain], {"step": fact.index, "word": fact.word,
                                                                     "why": fact.chain}, fact.word, m - 1, m)
           for m, fact in enumerate(facts) if m > 0 and fact.chain]
    return out, max(0, len(facts) - 1)
