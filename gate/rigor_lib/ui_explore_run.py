"""Path execution of `rigor ui-explore` (U05): turns a path (a list of path words) into probe commands, records one
observation per step, runs every path twice in fresh probe processes and compares the two runs reply by reply.

Path words (docs/ui-explore.md): `open <origin_ms> <seed>` (always the first word, and only there), `domain-at <i>`,
`settle` (fire the next deadline, the gate's own time event), or the id of a catalogue event. After every word the
explorer reads, in this order: `frame`, `semantic`, `patches`, `trace`, `next-due`, `env-inputs`; the `open` step also
reads `domain-count` first. Nothing is retried.
"""

import re
from dataclasses import dataclass, field

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_probe import ADVANCE_MAX_MS, FRAME_MS, ORIGIN_MAX_MS, ProbeError, Session

_OPEN = re.compile(r"open (0|[1-9][0-9]{0,17}) (0|[1-9][0-9]{0,19})")
_DOMAIN = re.compile(r"domain-at (0|[1-9][0-9]{0,4})")
SETTLE = "settle"
OBSERVED = ("frame", "semantic", "patches", "trace", "due", "env")


@dataclass(frozen=True)
class Config:
    probe: str
    deadline_s: float
    catalogue: object


@dataclass
class Step:
    """One executed path word: `outcome` says what the word did, `obs` holds every reply read after it.
    `error` is the ProbeError that ended the run at this step (then `obs` is partial)."""
    index: int
    word: str
    outcome: list = field(default_factory=list)
    obs: dict = field(default_factory=dict)
    now: int = 0
    error: object = None

    def parts(self):
        """The comparable parts of the step, as plain data (what run-twice compares)."""
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

    @property
    def complete(self):
        return self.error is None


def _plain(value):
    if isinstance(value, tuple) and value and hasattr(value[0], "raw"):
        return [record.raw for record in value]
    if isinstance(value, tuple):
        return [list(item) if isinstance(item, tuple) else item for item in value]
    return value


def check_words(words, catalogue):
    """Refuse a path that is not well formed (a bad path file is the gate's input error, exit 2)."""
    if type(words) is not list or not words or type(words[0]) is not str or not _OPEN.fullmatch(words[0]):
        raise InternalError("a path must start with `open <origin_ms> <seed>`: %r" % (words[:1],))
    origin, seed = (int(x) for x in words[0].split(" ")[1:])
    if origin > ORIGIN_MAX_MS or seed >= 2**64:
        raise InternalError("path: origin or seed out of range in %r" % words[0])
    for word in words[1:]:
        if type(word) is not str or not (word == SETTLE or _DOMAIN.fullmatch(word) or catalogue.by_id(word)):
            raise InternalError("path word %r is not domain-at, settle or a catalogue event id" % (word,))
        if catalogue.by_id(word) is not None and catalogue.by_id(word).cls in ("u2", "u3"):
            raise InternalError("path word %r is a tap, which ui-probe/1 cannot send" % word)
    return origin, seed


def _advance_to(session, step, target):
    while session.now < target:
        session.advance(min(target, session.now + ADVANCE_MAX_MS))
    step.outcome.append("now %d" % session.now)


def _fire_due(session, step, before):
    due = session.next_due()
    if due is None:
        step.outcome.append("no-deadline")
        return
    target = due - FRAME_MS if before else due
    if target <= session.now:
        step.outcome.append("deadline-within-a-frame")
        return
    _advance_to(session, step, target)
    if not before:
        step.outcome[-1] = "fired %d" % session.now


def _apply(session, step, kind, ident, arg, hex_text):
    step.outcome.append("apply %s" % ("ok" if session.apply(kind, ident, arg, hex_text) else "refused"))


def _catalogue_event(session, step, event):
    cls = event.cls
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
    elif cls == "t1" and event.get("kind") == "advance":
        _advance_to(session, step, session.now + event.get("ms"))
    elif cls == "t1":
        _fire_due(session, step, event.get("kind") == "before-due")
    else:   # u2, u3: refused before any run (ui-probe/1 has no tap command)
        raise InternalError("event %s of class %s cannot be sent through ui-probe/1" % (event.id, cls))


def _do_word(session, step, catalogue):
    word = step.word
    if step.index == 0:
        if not _OPEN.fullmatch(word):
            raise InternalError("path word 0 must be open: %r" % word)
        step.obs["domain"] = session.domain_count()
        origin, seed = (int(x) for x in word.split(" ")[1:])
        session.open(origin, seed)
        step.outcome.append("open")
    elif word == SETTLE:
        _fire_due(session, step, False)
    elif _DOMAIN.fullmatch(word):
        session.domain_at(int(word.split(" ")[1]))
        step.outcome.append("domain-at")
    else:
        event = catalogue.by_id(word)
        if event is None:
            raise InternalError("path word %r is not open, domain-at, settle or a catalogue event id" % word)
        _catalogue_event(session, step, event)


def _observe(session, step):
    step.obs["frame"] = session.frame()
    for name in ("semantic", "patches", "trace"):
        step.obs[name] = session.records(name)
    step.obs["due"] = session.next_due()
    step.obs["env"] = session.env_inputs()
    step.now = session.now


def _one(session, run, word, catalogue):
    step = Step(len(run.steps), word)
    run.steps.append(step)
    run.words.append(word)
    try:
        _do_word(session, step, catalogue)
        _observe(session, step)
    except ProbeError as error:
        step.error = error
        run.error = (step.index, error)
        return False
    return True


def starving(step):
    """True when the step fired a deadline and the next one is again at most one frame away (0-delay rescheduling)."""
    fired = any(item.startswith("fired ") for item in step.outcome)
    due = step.obs.get("due")
    return step.error is None and fired and due is not None and due - step.now <= FRAME_MS


def execute(config, words, settle_bound=0):
    """One run of `words` in a fresh probe. With `settle_bound` > 0, `settle` words are appended while a deadline is
    pending, until none is, the next one is more than a frame away after a firing, or `settle_bound` consecutive
    firings left a deadline within a frame (`timer-starvation`)."""
    run = Run([], [])
    session = None
    try:
        session = Session([config.probe], config.deadline_s)
    except ProbeError as error:
        step = Step(0, words[0], error=error)
        return Run([words[0]], [step], (0, error))
    try:
        for word in words:
            if not _one(session, run, word, config.catalogue):
                return run
        streak = 0
        while settle_bound and streak < settle_bound and run.steps[-1].obs.get("due") is not None:
            if not _one(session, run, SETTLE, config.catalogue):
                return run
            if not starving(run.steps[-1]):
                break
            streak += 1
        try:
            session.quit()
        except ProbeError as error:
            quit_step = Step(len(run.steps), "quit", error=error)
            run.steps.append(quit_step)
            run.error = (quit_step.index, error)
        return run
    finally:
        session.close()


def first_difference(first, second):
    """(index of the first step where the trace differs or None, (index, part) of the first other difference or None)."""
    trace_at = other = None
    for index in range(max(len(first.steps), len(second.steps))):
        a = first.steps[index].parts() if index < len(first.steps) else {"missing": True}
        b = second.steps[index].parts() if index < len(second.steps) else {"missing": True}
        if trace_at is None and "trace" in a and "trace" in b and a["trace"] != b["trace"]:
            trace_at = index
        if other is None:
            names = sorted(set(a) | set(b))
            if "trace" in a and "trace" in b:
                names.remove("trace")
            differing = [name for name in names if jsonio.canonical_dumps(a.get(name)) != jsonio.canonical_dumps(b.get(name))]
            if differing:
                other = (index, differing[0])
    return trace_at, other


def run_twice(config, words, settle_bound=0):
    """Both runs of a path: the first may append `settle` words, the second runs exactly the words of the first."""
    first = execute(config, words, settle_bound)
    second = execute(config, list(first.words), 0)
    return first, second
