"""Path execution of `rigor ui-explore` (U05): runs path words in a fresh probe, records one observation per step, runs
every path twice and compares the two runs reply by reply. Nothing is retried. What each word does: ui_explore_words.

Path words (docs/ui-explore.md): `open <origin_ms> <seed>` (first, and only there), `domain-at <i>`, `settle` (fire
the next deadline), `wait-change` (fire deadlines until the abstraction key changes), `at <offset_ms>` (advance to
origin + offset), or a catalogue event id. After every word the explorer reads `frame`, `semantic`, `patches`, `trace`,
`next-due`, `env-inputs` (the open step reads `domain-count` first); patches and trace fetched during the word (drains,
snapshots) come first in the step's `patches` and `trace`.
"""

import re
from dataclasses import dataclass, field

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib import ui_explore_words as words_mod
from rigor_lib.ui_explore_key import key_hash, projection
from rigor_lib.ui_explore_probe import FRAME_MS, NOT_A_REPLY, ORIGIN_MAX_MS, TAP_CAPS, ProbeError, Session

_OPEN = re.compile(r"open (0|[1-9][0-9]{0,17}) (0|[1-9][0-9]{0,19})")
_DOMAIN = re.compile(r"domain-at (0|[1-9][0-9]{0,4})")
_AT = re.compile(r"at (0|[1-9][0-9]{0,15})")
SETTLE, WAIT_CHANGE = "settle", "wait-change"
# the parts of a step in the order the explorer reads them: run-twice names the first that differs
PARTS = ("domain", "outcome", "frame", "semantic", "patches", "trace", "due", "env", "ink", "ink_moved", "now", "error",
         "missing")


@dataclass(frozen=True)
class Config:
    probe: str
    deadline_s: float
    catalogue: object
    budget: object
    caps: object = None           # the capabilities of the first launch; every later launch must announce the same


@dataclass
class Step:
    """One executed path word. `outcome` says what it did; `applies` the results ("ok", "refused", "missed") of its
    inputs, the last of which is the word's `result`; `obs` the replies read after it; `unreachable` a wait it did not
    take; `starved` the window that made the run starve, on the step that crossed the limit; `images` evidence images
    (PNG bytes by file name) of a missed tap, never compared by run-twice. `error` is the ProbeError
    that ended the run here (then `obs` is partial and `key` None). `key`/`proj` are its abstraction key and
    projection, `key_before`/`proj_before` those of the step before."""
    index: int
    word: str
    outcome: list = field(default_factory=list)
    obs: dict = field(default_factory=dict)
    applies: list = field(default_factory=list)
    acc_patches: list = field(default_factory=list)
    acc_trace: list = field(default_factory=list)
    now: int = 0
    origin: int = 0
    unreachable: object = None
    starved: object = None
    error: object = None
    images: dict = field(default_factory=dict)
    misrouted: object = None      # a u2 tap pressed another non-root node than the one its target names
    noop: object = None           # a tap that must change nothing changed the model
    ambient: object = None        # a tap whose declared ambient events were missing or repeated (U05c)
    image_box: object = None      # (x, y, w, h) of the evidence image of the node a tap pressed
    key: object = None
    proj: object = None
    key_before: object = None
    proj_before: object = None

    @property
    def result(self):
        return self.applies[-1] if self.applies else None

    def parts(self):
        out = {"outcome": list(self.outcome), "now": self.now}
        if self.error is not None and self.error.detail == NOT_A_REPLY:
            # output nobody asked for is caught at one of two commands depending on timing: which one, and the
            # partial observation before it, are not compared
            out["error"] = [self.error.kind, None, self.error.detail]
            return out
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
    fire_log: list = field(default_factory=list)   # (virtual ms, step index) of every deadline fired
    fire_start: int = 0
    starved: bool = False
    commands: int = 0
    virtual_ms: int = 0


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
        if event is not None and event.cls in ("u2", "u3") and not all(cap in caps for cap in TAP_CAPS):
            raise InternalError("path word %r is a tap, and the probe does not announce the tap capability and "
                                "hit-test" % word)
    return origin, seed


def _do_word(session, step, run, catalogue, before):
    word = step.word
    if step.index == 0:
        step.obs["domain"] = session.domain_count()
        origin, seed = (int(x) for x in word.split(" ")[1:])
        session.open(origin, seed)
        step.outcome.append("open")
    elif word == SETTLE:
        words_mod.fire_due(session, step, run, catalogue, False)
    elif word == WAIT_CHANGE:
        words_mod.until_change(session, step, run, catalogue, step.key_before)
    elif _DOMAIN.fullmatch(word):
        session.domain_at(int(word.split(" ")[1]))
        step.outcome.append("domain-at")
    elif _AT.fullmatch(word):
        words_mod.advance_by(session, step, session.origin + int(word.split(" ")[1]), catalogue)
    else:
        event = catalogue.by_id(word)
        if event.cls == "t1":
            words_mod.time_event(session, step, run, event, catalogue, step.key_before)
        else:
            words_mod.inputs(session, step, words_mod.snapshot_of(before.obs), words_mod.input_sends(session, event),
                             catalogue)


def _observe(session, step):
    step.obs["frame"] = session.frame()
    step.obs["semantic"] = session.records("semantic")
    step.obs["patches"] = tuple(step.acc_patches) + session.records("patches")
    step.obs["trace"] = tuple(step.acc_trace) + session.records("trace")
    step.obs["due"] = session.next_due()
    step.obs["env"] = session.env_inputs()
    step.now = session.now


class InkPlan:
    """Which steps of a run take `ink` (U07, the ui-render judge): the first run of a path inks every step whose
    abstraction key no step of the exploration was inked at (`seen`, shared by every path), once per key; the second
    run inks exactly the same steps (`steps`), so run-twice compares the ink too."""

    def __init__(self, seen=None, steps=None):
        self.seen, self.steps = seen, steps

    def wants(self, step):
        if self.steps is not None:
            return step.index in self.steps
        if step.key in self.seen:
            return False
        self.seen.add(step.key)
        return True

    @staticmethod
    def again(run):
        return InkPlan(steps={step.index for step in run.steps if "ink" in step.obs})


def _comparable(frame):
    return [r.raw for r in frame if not r.raw.startswith(("life\t", "taps\t"))]


def _ink(session, run, step, plan):
    """`ink` of every node of the step's frame, then `frame` again: an ink whose retry settle flushed drops the probe's
    frame (docs/ui-model.md, "Statuses"), and the next word may need one. `ink_moved`: that frame is not the step's,
    so the ink does not describe it (the judge reads no ink of the step). An error ends the run in a pseudo step."""
    if plan is None or not plan.wants(step):
        return True
    try:
        step.obs["ink"] = session.ink()
        step.obs["ink_moved"] = _comparable(session.frame()) != _comparable(step.obs["frame"])
    except ProbeError as error:
        step.obs.pop("ink", None)
        run.steps.append(Step(len(run.steps), "ink", error=error, key_before=step.key, proj_before=step.proj,
                              origin=step.origin))
        run.error = (len(run.steps) - 1, error)
        return False
    return True


def _one(session, run, word, catalogue, plan=None):
    before = run.steps[-1] if run.steps else None
    step = Step(len(run.steps), word, origin=session.origin or 0)
    if before is not None:
        step.key_before, step.proj_before = before.key, before.proj
    run.steps.append(step)
    run.words.append(word)
    try:
        _do_word(session, step, run, catalogue, before)
        step.origin = session.origin
        _observe(session, step)
    except ProbeError as error:
        step.error = error
        run.error = (step.index, error)
        return False
    step.proj = projection(step.obs, step.now, catalogue.key)
    step.key = key_hash(step.proj)
    return _ink(session, run, step, plan) and _evidence(session, run, step)


def _evidence(session, run, step):
    """The image of the node a tap pressed, fetched after the step is complete, so that the step's own outcome and its
    findings stand when the evidence cannot be read: then a pseudo step `evidence` carries the error and the run ends."""
    if step.image_box is None:
        return True
    try:
        image = words_mod.box_image(session, step.image_box)
    except ProbeError as error:
        run.steps.append(Step(len(run.steps), "evidence", error=error, key_before=step.key, proj_before=step.proj,
                              origin=step.origin))
        run.error = (len(run.steps) - 1, error)
        return False
    if image is not None:
        step.images["tap-node.png"] = image
    return True


def _settle(session, run, catalogue, plan=None):
    """The starvation check after a path: fire deadlines for one starvation window of virtual time, until no deadline
    is left inside it, a wait is unreachable, or the run starves. At most `starve_firings` + 1 firings."""
    end = session.now + catalogue.starve_window_frames * FRAME_MS
    while not run.starved:
        due = run.steps[-1].obs["due"]
        if due is None or due > end:
            return True
        if not _one(session, run, SETTLE, catalogue, plan):
            return False
        if run.steps[-1].unreachable:
            return True
    return True


def execute(config, words, settle=False, ink=None):
    """One run of `words` in a fresh probe; with `settle`, the starvation check (`_settle`) follows the path; `ink`: the
    InkPlan of the steps that take ink, or None."""
    run = Run([], [])
    try:
        session = Session([config.probe], config.deadline_s, config.budget, config.caps)
    except ProbeError as error:
        return Run([words[0]], [Step(0, words[0], error=error)], (0, error))
    try:
        for word in words:
            if not _one(session, run, word, config.catalogue, ink):
                return run
        if settle and not _settle(session, run, config.catalogue, ink):
            return run
        try:
            session.quit()
        except ProbeError as error:
            run.steps.append(Step(len(run.steps), "quit", error=error, key_before=run.steps[-1].key,
                                  proj_before=run.steps[-1].proj, origin=run.steps[-1].origin))
            run.error = (len(run.steps) - 1, error)
        return run
    finally:
        run.commands, run.virtual_ms = session.commands, session.virtual_ms
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


def run_twice(config, words, settle=False, ink=None):
    """Both runs of a path: the first may append `settle` words, the second runs exactly the words of the first (and
    inks exactly the steps the first inked)."""
    first = execute(config, words, settle, ink)
    second = execute(config, list(first.words), False, InkPlan.again(first) if ink is not None else None)
    return first, second
