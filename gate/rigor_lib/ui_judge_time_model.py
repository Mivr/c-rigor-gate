"""The timeline of one path for the `ui-time` judge (U09, P004 3.5): per step, what the judge reads (docs/ui-judges-time.md).

A step is one `Facts`: its word's mode (`open`, `input`, `env`, `time`, `domain`), its virtual time and the time of the
step before, the state class of the probe's identity (None without it), the timed elements present, per element its
countdown values and its text, the comparable semantic and frame records, the parsed patches, whether those patches
agree with the semantic records (`chain`), and the keys of a declared countdown restart (U05d). Nothing here reads the
wall clock.

Binding a contract timer (`[[timer]]` kind) to what the scene shows:
- with the probe's identity: the kind is present iff the state class IS the kind (the class of the topmost message,
  else of the screen; docs/ui-judges-identity.md); a kind shown at the step before stays shown while another MESSAGE
  kind is the class and every node of its own scope at the step before is still in the scene with the same role and
  (but a countdown) the same label, and no patch of the step removed it (ui-rules: a message is drawn over what it
  covers, which stays visible behind it: a screen under a dialog, a banner under a snackbar; keys are reused across
  screens, so the keys alone do not tell);
- without it: only a message timer whose kind is a layer role of the scene vocabulary (`dialog`, `banner`, `snackbar`)
  is bindable, present iff a semantic record has that role; every other timer is `check-blocked` (needs identity).

An element is an INSTANCE, not a kind, followed by its own nodes: the nodes of its kind's scope when it first is the
topmost element of that kind. It stays shown while every one of those nodes is in the scene with the same role and
(a countdown aside) the same label and no patch of the step removed it (a countdown's own node made again is the same
element counting; a countdown node removed leaves it shown: `countdown-wrong` part `absent`), also under another
element of the same kind stacked over it; its presence ends when one changes
or goes. A new topmost scope (another text, other keys, a node made again) is a new instance: a new appearance
(`same_instance`, `appearances`). A countdown's changing label is the same instance. Instance ids are (the index of
the step it appeared at, kind): deterministic within a run.

The scope of an element (where its countdown and text are): the semantic records are in tree order and a message layer
is drawn above the screen, so a message's scope is the records from the LAST record of a message layer role
(`dialog`, `banner`, `snackbar`) to the end, and a screen's scope the records before the FIRST layer record (`scrim`
included). For a role-bound kind, the scope starts at the last record of that role.

A countdown's value (no contract or catalogue declares a countdown format): a label with exactly one run of 1 to 18
digits is that many seconds; a label whose only digits are `M:SS` is minutes and seconds; anything else is no value
and the judge's `contract-incomplete` (`countdown-format`).
"""

import re
from dataclasses import dataclass, field

LAYER_KINDS = ("dialog", "banner", "snackbar")   # message timer kinds bindable by scene role, without identity
LAYERS = ("scrim",) + LAYER_KINDS
_RUN = re.compile(rb"[0-9]+")
_SECONDS = re.compile(rb"[^0-9]*([0-9]{1,18})[^0-9]*")
_MINUTES = re.compile(rb"[^0-9]*([0-9]{1,16}):([0-5][0-9])[^0-9]*")
_AT = re.compile(r"at (0|[1-9][0-9]{0,15})")


def word_mode(word, catalogue):
    """`open`, `input` (a user input: u1..u5), `env` (an environment reply, e1: no user input), `time` or `domain`: what
    a path word does to the model (docs/ui-explore.md, "Paths and time")."""
    if word.startswith("open "):
        return "open"
    if word in ("settle", "wait-change") or _AT.fullmatch(word):
        return "time"
    if word.startswith("domain-at "):
        return "domain"
    event = catalogue.by_id(word)
    if event is not None and event.cls == "t1":
        return "time"
    return "env" if event is not None and event.cls == "e1" else "input"


def countdown_value(label):
    """The seconds a countdown label shows (one digit run: seconds; `M:SS`: minutes and seconds), or None."""
    found = _SECONDS.fullmatch(label)
    if found is not None:
        return int(found.group(1))
    found = _MINUTES.fullmatch(label)
    return None if found is None else int(found.group(1)) * 60 + int(found.group(2))


def masked_label(label):
    """A countdown label as clock-origin-divergence compares it: every digit run masked, the rest kept, and its value."""
    return _RUN.sub(b"#", label).decode("utf-8", "surrogateescape") + "=" + str(countdown_value(label))


@dataclass
class Facts:
    index: int
    word: str
    mode: str
    now: int
    prev_now: int
    origin: int
    key: object
    proj: object
    cls: object = None                                # the identity's state class, or None
    present: frozenset = frozenset()                  # the bound timer kinds shown
    countdowns: dict = field(default_factory=dict)    # kind -> ((key, value or None), ...)
    unparsed: tuple = ()                              # countdown labels with no value (contract-incomplete)
    texts: dict = field(default_factory=dict)         # kind -> the text of its scope (role `text`), joined by a space
    msgids: dict = field(default_factory=dict)        # kind -> the first msgid of a text node of its scope, or None
    scopes: dict = field(default_factory=dict)        # kind -> the keys of its scope at this step
    roles: dict = field(default_factory=dict)         # kind -> {key: (role, label or None for a countdown)}
    sigs: dict = field(default_factory=dict)          # kind -> (msgid, text) of its topmost scope
    removed: frozenset = frozenset()                  # the keys a `remove` patch of this step names
    rolemap: dict = field(default_factory=dict)       # key -> (role, label or None for a countdown), every record
    tracked: dict = field(default_factory=dict)       # kind -> ((instance id, its nodes' roles), ...) shown
    tops: dict = field(default_factory=dict)          # kind -> the id of its topmost instance
    semantic: tuple = ()
    labels: dict = field(default_factory=dict)        # key -> label bytes of the semantic records
    masked: tuple = ()                                # semantic raws, a countdown's label masked (origins)
    ident: tuple = ()                                 # the identity records' raws
    due: object = None                                # next-due relative to the origin, or None
    frame: tuple = ()
    patches: tuple = ()                               # (op, key, field, old bytes, new bytes)
    chain: object = None                              # None, or why the patches disagree with the semantic records
    restarts: frozenset = frozenset()                 # keys of a declared countdown restart (U05d) at this step

    @property
    def appear_lo(self):
        """The earliest instant something that is new at this step can have appeared: the step's own instant for an
        input (the clock does not move), else one ms after the step before."""
        return self.now if self.mode != "time" or self.now == self.prev_now else self.prev_now + 1


class Binding:
    """Which contract timers the run can bind, and how (identity or scene role)."""

    def __init__(self, contract, identity):
        self.timers = {row["kind"]: row for row in contract.rows("timer")}
        self.identity = bool(identity)

    def bound(self):
        return tuple(k for k in sorted(self.timers) if self.identity or (k in LAYER_KINDS and self.message(k)))

    def blocked(self):
        return tuple(k for k in sorted(self.timers) if k not in self.bound())

    def message(self, kind):
        return self.timers[kind]["class"] == "message"


def _scope(records, kind, binding, by_role):
    roles = [r.fields[1] for r in records]
    if by_role:
        start = max(i for i, role in enumerate(roles) if role == kind)
        return records[start:]
    layers = [i for i, role in enumerate(roles) if role in LAYERS]
    if binding.message(kind):
        cards = [i for i, role in enumerate(roles) if role in LAYER_KINDS]
        return records[cards[-1]:] if cards else ()
    return records[:layers[0]] if layers else records


def _identity_msgids(step):
    records = step.obs.get("identity")
    if not records:
        return None, {}
    msgids = {r.fields[1]: r.values[3] for r in records[1:] if r.fields[3] != "-"}
    return records[0].values[1].decode("utf-8", "surrogateescape"), msgids


def _role_label(record):
    return record.fields[1], None if record.fields[1] == "countdown" else record.values[2]


def _present(records, cls, binding, before, removed):
    """(the kinds shown, the kinds carried under another message with their scope's keys)."""
    if not binding.identity:
        roles = {r.fields[1] for r in records}
        return frozenset(k for k in binding.bound() if k in roles), {}
    now = {r.fields[0]: _role_label(r) for r in records}
    carried = {}
    if cls in binding.timers and binding.message(cls) and before is not None:
        carried = {k: before.scopes[k] for k in before.present
                   if k != cls and before.roles.get(k) and not before.scopes[k] & removed
                   and all(now.get(key) == shown for key, shown in before.roles[k].items())}
    return frozenset({k for k in binding.bound() if k == cls} | set(carried)), carried


def comparable_frame(frame):
    """The frame records but `life` and `taps` lines (they are in one frame only, docs/ui-model.md)."""
    return tuple(r.raw for r in frame if not r.raw.startswith(("life\t", "taps\t")))


def chain_error(before_labels, patches, labels):
    """None, or why the step's patches do not lead from the step before's semantic records to this step's: every
    `create` of a key not shown, `remove` of a key shown, `update text` whose old text is not the label shown, and at
    the end the same keys and, where a label is known, the same label (as the countdown-restart rule checks them)."""
    shown = dict(before_labels)
    for op, key, name, old, new in patches:
        if op == "create":
            if key in shown:
                return "create of a key already shown: %s" % key
            shown[key] = None                     # a created node's label is known only from a later text update
        elif op == "remove":
            if key not in shown:
                return "remove of a key not shown: %s" % key
            del shown[key]
        elif op == "update" and name == "text":
            if key not in shown or (shown[key] is not None and shown[key] != old):
                return "text update of %s from a label it did not show" % key
            shown[key] = new
    if set(shown) != set(labels):
        return "the patches end on other keys than the semantic records"
    wrong = sorted(k for k, label in shown.items() if label is not None and label != labels[k])
    return None if not wrong else "the patches end on another label than the semantic record of %s" % wrong[0]


def facts_of(step, before, catalogue, binding):
    """The Facts of one completed step (`before`: the Facts of the step before, or None)."""
    records = tuple(step.obs.get("semantic", ()))
    cls, msgids = _identity_msgids(step)
    patches = tuple((p.fields[0], p.fields[1], p.fields[2], p.values[3], p.values[4]) for p in step.obs.get("patches", ()))
    removed = frozenset(key for op, key, _f, _o, _n in patches if op == "remove")
    present, carried = _present(records, cls, binding, before, removed)
    due = step.obs.get("due")
    out = Facts(step.index, step.word, word_mode(step.word, catalogue), step.now,
                step.now if before is None else before.now, step.origin, step.key, step.proj, cls=cls,
                present=present, semantic=tuple(r.raw for r in records),
                labels={r.fields[0]: r.values[2] for r in records},
                masked=tuple("\t".join(r.fields[:2] + (masked_label(r.values[2]),) + r.fields[3:])
                             if r.fields[1] == "countdown" else r.raw for r in records),
                ident=tuple(r.raw for r in step.obs.get("identity") or ()),
                due=None if due is None else due - step.origin, frame=comparable_frame(step.obs.get("frame", ())),
                patches=patches, removed=removed, rolemap={r.fields[0]: _role_label(r) for r in records},
                restarts=frozenset(item["node"] for item in (step.restart or ())))
    # the open step's patches are the product's boot log, whatever it reports: the chain starts after it
    out.chain = None if before is None else chain_error(before.labels, out.patches, out.labels)
    for kind in present:
        scope = tuple(r for r in records if r.fields[0] in carried[kind]) if kind in carried else \
            _scope(records, kind, binding, not binding.identity)
        out.scopes[kind] = frozenset(r.fields[0] for r in scope)
        out.roles[kind] = {r.fields[0]: _role_label(r) for r in scope}
        counts = [(r.fields[0], countdown_value(r.values[2])) for r in scope if r.fields[1] == "countdown"]
        out.countdowns[kind] = tuple(counts)
        out.unparsed += tuple(r.values[2] for r in scope if r.fields[1] == "countdown"
                              and countdown_value(r.values[2]) is None)
        texts = [r for r in scope if r.fields[1] == "text" and r.values[2] != b""]
        out.texts[kind] = b" ".join(r.values[2] for r in texts).decode("utf-8", "replace")
        out.msgids[kind] = next((msgids[r.fields[0]] for r in texts if r.fields[0] in msgids), None)
        out.sigs[kind] = (out.msgids[kind], out.texts[kind])
    _instances(out, before)
    return out


def _holds(roles, fact):
    """Whether an instance's nodes all still hold: its countdown nodes aside (a countdown removed or made again leaves
    the element shown: `countdown-wrong` judges its countdown)."""
    held = {key: shown for key, shown in roles.items() if shown[0] != "countdown"}
    return not set(held) & fact.removed and all(fact.rolemap.get(key) == shown for key, shown in held.items())


def _plain(roles):
    return {key for key, shown in roles.items() if shown[0] != "countdown"}


def _instances(fact, before):
    """The instances of each kind shown at `fact`: those of the step before whose nodes all still hold, and its
    topmost scope as a new one when no held instance has exactly those keys."""
    for kind in sorted(fact.present):
        held = [(iid, roles) for iid, roles in (before.tracked.get(kind, ()) if before is not None else ())
                if _holds(roles, fact)]
        top = fact.roles.get(kind, {})
        match = next((iid for iid, roles in held if _plain(roles) == _plain(top)), None)
        if match is None and top:
            match = (fact.index, kind)
            held.append((match, dict(top)))
        fact.tracked[kind], fact.tops[kind] = tuple(held), match


def same_instance(before, fact, kind, iid=None):
    """Whether instance `iid` (by default the topmost of `kind` at `before`) is still shown at `fact`."""
    iid = before.tops.get(kind) if iid is None else iid
    return iid is not None and any(i == iid for i, _roles in fact.tracked.get(kind, ()))


def timeline(steps, catalogue, binding, before=None):
    """The Facts of every completed step of a run, up to the first that has no abstraction key (an error)."""
    out = []
    for step in steps:
        if step.key is None or step.error is not None:
            break
        out.append(facts_of(step, out[-1] if out else before, catalogue, binding))
    return out


def appearances(facts):
    """(index, kind) of every step where an instance of a bound timed element is shown that was not at the step before
    (a kind newly shown, or another instance of it)."""
    out = []
    for i, fact in enumerate(facts):
        for kind in sorted(fact.present):
            if fact.tops.get(kind) is not None and (i == 0 or not same_instance(facts[i - 1], facts[i - 1], kind,
                                                                                fact.tops[kind])):
                out.append((i, kind))
    return out


def alive(facts, kind, start):
    """Per fact after `start` (the appearance): whether the instance shown at `start` is still the one shown; once
    it is not, never again in that run (a later instance is another element)."""
    iid, out, going = facts[start].tops.get(kind), [], True
    for fact in facts[start + 1:]:
        going = going and same_instance(fact, fact, kind, iid)
        out.append((fact, going))
    return out
