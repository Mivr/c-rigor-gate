"""Path execution of `rigor ui-explore` (U05): turns path words into probe commands, records one observation per step,
runs every path twice in fresh probe processes and compares the two runs reply by reply. Nothing is retried.

Path words (docs/ui-explore.md): `open <origin_ms> <seed>` (first, and only there), `domain-at <i>`, `settle` (fire
the next deadline), `wait-change` (fire deadlines until the abstraction key changes), `at <offset_ms>` (advance to
origin + offset), or a catalogue event id. Every virtual-time word is bounded by the catalogue's `max_wait_ms`: a longer
wait is not taken, the step records it (`timer-unreachable`). Advances are split on the frame grid into spans of at
most `SPAN_FRAMES` frames, so the per-command deadline holds on a slow product; the probe's own loop steps at every grid
boundary and deadline anyway, so the split calls `uim_step` with exactly the same lengths as one long advance.
After every word the explorer reads `frame`, `semantic`, `patches`, `trace`, `next-due`, `env-inputs` (the open step
reads `domain-count` first).
"""

import re
from dataclasses import dataclass, field

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_key import key_hash, projection
from rigor_lib.ui_explore_probe import FRAME_MS, ORIGIN_MAX_MS, TIME_MAX_MS, ProbeError, Session

_OPEN = re.compile(r"open (0|[1-9][0-9]{0,17}) (0|[1-9][0-9]{0,19})")
_DOMAIN = re.compile(r"domain-at (0|[1-9][0-9]{0,4})")
_AT = re.compile(r"at (0|[1-9][0-9]{0,15})")
SETTLE, WAIT_CHANGE = "settle", "wait-change"
SPAN_FRAMES = 64
# the parts of a step in the order the explorer reads them: run-twice names the first that differs
PARTS = ("domain", "outcome", "frame", "semantic", "patches", "trace", "due", "env", "now", "error", "missing")


@dataclass(frozen=True)
class Config:
    probe: str
    deadline_s: float
    catalogue: object
    budget: object
    starvation_steps: int


@dataclass
class Step:
    """One executed path word. `outcome` says what the word did, `obs` holds the replies read after it, `applies` the
    results of its `apply`/`tap` commands, `unreachable` a wait it did not take. `error` is the ProbeError that ended the
    run here (then `obs` is partial and `key` None). `key`/`proj` are its abstraction key and projection, `key_before`/
    `proj_before` those of the step before; `streak` counts consecutive firings that left a deadline within a frame."""
    index: int
    word: str
    outcome: list = field(default_factory=list)
    obs: dict = field(default_factory=dict)
    applies: list = field(default_factory=list)
    now: int = 0
    origin: int = 0
    unreachable: object = None
    error: object = None
    key: object = None
    proj: object = None
    key_before: object = None
    proj_before: object = None
    streak: int = 0
    starved: bool = False
    firings: list = field(default_factory=list)

    def parts(self):
        out = {"outcome": list(self.outcome), "now": self.now}
        for name, value in self.obs.items():
            out[name] = _plain(value)
        if self.error is not None:
            out["error"] = [self.error.kind, self.error.command, self.error.detail]
        return out


@dataclass
class Run:
    words: list
    steps: list
    error: object = None          # (step index, ProbeError) or None


def _plain(value):
    if isinstance(value, tuple) and value and hasattr(value[0], "raw"):
        return [record.raw for record in value]
    if isinstance(value, tuple):
        return [list(item) if isinstance(item, tuple) else item for item in value]
    return value


def check_words(words, catalogue, caps=()):
    """Refuse a path that is not well formed (a bad path file is the gate's input error, exit 2)."""
    if type(words) is not list or not words or type(words[0]) is not str or not _OPEN.fullmatch(words[0]):
        raise InternalError("a path must start with `open <origin_ms> <seed>`: %r" % (words[:1],))
    origin, seed = (int(x) for x in words[0].split(" ")[1:])
    if origin > ORIGIN_MAX_MS or seed >= 2**64:
        raise InternalError("path: origin or seed out of range in %r" % words[0])
    for word in words[1:]:
        if type(word) is not str:
            raise InternalError("path word %r is not a string" % (word,))
        event = catalogue.by_id(word)
        if not (word in (SETTLE, WAIT_CHANGE) or _DOMAIN.fullmatch(word) or _AT.fullmatch(word) or event):
            raise InternalError("path word %r is not a path word or a catalogue event id" % word)
        if event is not None and event.cls in ("u2", "u3") and "tap" not in caps:
            raise InternalError("path word %r is a tap, and the probe does not announce the tap capability" % word)
    return origin, seed


# ---- time -----------------------------------------------------------------------------------------------------
def _reachable(session, step, target, start, limit):
    """False (and the step records why) when `target` is past the protocol's clock or more than `limit` after `start`."""
    reason = "protocol-limit" if target > TIME_MAX_MS else "max-wait" if target - start > limit else None
    if reason:
        step.unreachable = {"target_ms": target, "now_ms": session.now, "max_wait_ms": limit, "reason": reason}
        step.outcome.append("unreachable")
    return reason is None


def advance_to(session, target):
    """Advance in spans of at most SPAN_FRAMES frames, every span ending on the frame grid (or at the target)."""
    while session.now < target:
        frames = (session.now - session.origin) // FRAME_MS + SPAN_FRAMES
        session.advance(min(target, session.origin + frames * FRAME_MS))


def _fire_due(session, step, before, limit):
    due = session.next_due()
    if due is None:
        step.outcome.append("no-deadline")
        return
    target = due - FRAME_MS if before else due
    if target <= session.now:
        step.outcome.append("deadline-within-a-frame")
        return
    if _reachable(session, step, target, session.now, limit):
        advance_to(session, target)
        step.outcome.append(("now %d" if before else "fired %d") % session.now)


def _advance_by(session, step, target, limit):
    if target <= session.now:
        step.outcome.append("past")
    elif _reachable(session, step, target, session.now, limit):
        advance_to(session, target)
        step.outcome.append("now %d" % session.now)


def _until_change(session, step, base, catalogue, bound):
    """Fire deadlines until the abstraction key differs from `base`. Ends with `no-deadline`, `no-change` (the next
    deadline is past `max_wait_ms` from the start: a quiet state of a product with a perpetual tick, not a finding), or
    `starving` after `bound` consecutive firings that each left the next deadline within a frame (timer-starvation)."""
    start, limit, streak = session.now, catalogue.max_wait_ms, 0
    while True:
        due = session.next_due()
        if due is None:
            step.outcome.append("no-deadline")
            return
        if due > TIME_MAX_MS or due - start > limit:
            step.outcome.append("no-change")
            return
        advance_to(session, due)
        obs = {"semantic": session.records("semantic"), "due": session.next_due(), "env": session.env_inputs()}
        if key_hash(projection(obs, session.now, catalogue.key)) != base:
            step.outcome.append("changed %d" % session.now)
            return
        streak = streak + 1 if obs["due"] is not None and obs["due"] - session.now <= FRAME_MS else 0
        step.firings = (step.firings + [[session.now, obs["due"]]])[-bound:]
        if streak >= bound:
            step.outcome.append("starving")
            step.starved = True
            return


# ---- words ----------------------------------------------------------------------------------------------------
def _apply(session, step, kind, ident, arg, hex_text):
    step.applies.append("ok" if session.apply(kind, ident, arg, hex_text) else "refused")
    step.outcome.append("apply " + step.applies[-1])


def _catalogue_event(session, step, event, catalogue, base, bound):
    cls, limit = event.cls, catalogue.max_wait_ms
    if cls in ("u1", "u5"):
        _apply(session, step, 3, event.get("intent"), event.get("arg"), "")
    elif cls == "e1":
        _apply(session, step, 1, event.get("env"), event.get("arg"), event.get("hex"))
    elif cls == "u4" and event.get("via") == "wedge":
        _apply(session, step, 2, 0, 0, event.get("hex"))
    elif cls == "u4":
        for digit in event.get("digits"):
            _apply(session, step, 3, event.get("digit_intent"), int(digit), "")
        _apply(session, step, 3, event.get("enter_intent"), 0, "")
    elif cls in ("u2", "u3"):
        step.applies.append("ok" if session.tap(event.get("x"), event.get("y")) else "refused")
        step.outcome.append("tap " + step.applies[-1])
    else:
        _time_event(session, step, event, catalogue, base, limit, bound)


def _time_event(session, step, event, catalogue, base, limit, bound):
    kind = event.get("kind")
    if kind in ("fire-due", "before-due"):
        _fire_due(session, step, kind == "before-due", limit)
    elif kind == "advance":
        _advance_by(session, step, session.now + event.get("ms"), limit)
    elif kind == "at":
        _advance_by(session, step, session.origin + event.get("offset_ms"), limit)
    else:
        _until_change(session, step, base, catalogue, bound)


def _do_word(session, step, catalogue, base, bound):
    word = step.word
    if step.index == 0:
        step.obs["domain"] = session.domain_count()
        origin, seed = (int(x) for x in word.split(" ")[1:])
        session.open(origin, seed)
        step.outcome.append("open")
    elif word == SETTLE:
        _fire_due(session, step, False, catalogue.max_wait_ms)
    elif word == WAIT_CHANGE:
        _until_change(session, step, base, catalogue, bound)
    elif _DOMAIN.fullmatch(word):
        session.domain_at(int(word.split(" ")[1]))
        step.outcome.append("domain-at")
    elif _AT.fullmatch(word):
        _advance_by(session, step, session.origin + int(word.split(" ")[1]), catalogue.max_wait_ms)
    else:
        _catalogue_event(session, step, catalogue.by_id(word), catalogue, base, bound)


def _observe(session, step):
    step.obs["frame"] = session.frame()
    for name in ("semantic", "patches", "trace"):
        step.obs[name] = session.records(name)
    step.obs["due"] = session.next_due()
    step.obs["env"] = session.env_inputs()
    step.now = session.now


def _check_refusal(step, before):
    """A refused input must change nothing (model.h); only the gate can see it."""
    if not step.applies or any(item != "refused" for item in step.applies):
        return
    changed = [name for name in ("patches", "trace") if step.obs[name]]
    changed += [name for name in ("semantic", "due", "env") if _plain(step.obs[name]) != _plain(before.obs[name])]
    if changed:
        raise ProbeError("contract", "apply", "a refused input changed the model: " + ", ".join(changed))


def starving(step):
    """The step fired a deadline and the next one is again at most one frame away."""
    due = step.obs.get("due")
    fired = any(item.startswith("fired ") for item in step.outcome)
    return step.error is None and fired and due is not None and due - step.now <= FRAME_MS


def _one(session, run, word, catalogue, bound):
    before = run.steps[-1] if run.steps else None
    step = Step(len(run.steps), word, origin=session.origin or 0)
    if before is not None:
        step.key_before, step.proj_before = before.key, before.proj
    run.steps.append(step)
    run.words.append(word)
    try:
        _do_word(session, step, catalogue, step.key_before, bound)
        step.origin = session.origin
        _observe(session, step)
        if before is not None:
            _check_refusal(step, before)
    except ProbeError as error:
        step.error = error
        run.error = (step.index, error)
        return False
    step.proj = projection(step.obs, step.now, catalogue.key)
    step.key = key_hash(step.proj)
    if step.starved:
        step.streak = bound
    else:
        step.streak = (before.streak + 1 if before is not None else 1) if starving(step) else 0
    return True


def execute(config, words, settle=False):
    """One run of `words` in a fresh probe. With `settle`, `settle` words are appended while a deadline is pending,
    until none is, a firing leaves the next one more than a frame away, a wait is unreachable, or
    `starvation_steps` consecutive firings left a deadline within a frame (`timer-starvation`)."""
    run = Run([], [])
    try:
        session = Session([config.probe], config.deadline_s, config.budget)
    except ProbeError as error:
        return Run([words[0]], [Step(0, words[0], error=error)], (0, error))
    try:
        for word in words:
            if not _one(session, run, word, config.catalogue, config.starvation_steps):
                return run
        bound = config.starvation_steps
        while settle and run.steps[-1].obs["due"] is not None and run.steps[-1].streak < bound:
            if not _one(session, run, SETTLE, config.catalogue, config.starvation_steps):
                return run
            last = run.steps[-1]
            if last.unreachable or not starving(last):
                break
        try:
            session.quit()
        except ProbeError as error:
            run.steps.append(Step(len(run.steps), "quit", error=error, key_before=run.steps[-1].key,
                                  proj_before=run.steps[-1].proj, origin=run.steps[-1].origin))
            run.error = (len(run.steps) - 1, error)
        return run
    finally:
        session.close()


def first_difference(first, second):
    """(index of the first step whose trace differs, or None; (index, part) of the first other difference in read
    order, or None)."""
    trace_at = other = None
    for index in range(max(len(first.steps), len(second.steps))):
        a = first.steps[index].parts() if index < len(first.steps) else {"missing": True}
        b = second.steps[index].parts() if index < len(second.steps) else {"missing": True}
        if trace_at is None and "trace" in a and "trace" in b and a["trace"] != b["trace"]:
            trace_at = index
        if other is None:
            names = [name for name in PARTS if name in a or name in b]
            if "trace" in a and "trace" in b:
                names.remove("trace")
            differing = [n for n in names if jsonio.canonical_dumps(a.get(n)) != jsonio.canonical_dumps(b.get(n))]
            if differing:
                other = (index, differing[0])
    return trace_at, other


def run_twice(config, words, settle=False):
    """Both runs of a path: the first may append `settle` words, the second runs exactly the words of the first."""
    first = execute(config, words, settle)
    second = execute(config, list(first.words), False)
    return first, second
