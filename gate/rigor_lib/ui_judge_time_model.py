"""The timeline of one path for the `ui-time` judge (U09, P004 3.5): per step, what the judge reads (docs/ui-judges-time.md).

A step is one `Facts`: its word's mode (`open`, `input`, `time`, `domain`), its virtual time and the time of the step
before, the state class of the probe's identity (None without it), the timed elements present, per element its
countdown values and its text, the comparable semantic and frame records, the parsed patches and the keys of a declared
countdown restart (U05d). Nothing here reads the wall clock.

Binding a contract timer (`[[timer]]` kind) to what the scene shows:
- with the probe's identity: the kind is present iff the state class IS the kind (the class of the topmost message,
  else of the screen; docs/ui-judges-identity.md);
- without it: only a message timer whose kind is a layer role of the scene vocabulary (`dialog`, `banner`, `snackbar`)
  is bindable, present iff a semantic record has that role; every other timer is `check-blocked` (needs identity).

The scope of an element (where its countdown and text are): the semantic records are in tree order and a message layer
is drawn above the screen, so a message's scope is the records from the LAST record of a message layer role
(`dialog`, `banner`, `snackbar`) to the end, and a screen's scope the records before the FIRST layer record (`scrim`
included). For a role-bound kind, the scope starts at the last record of that role.
"""

import re
from dataclasses import dataclass, field

LAYER_KINDS = ("dialog", "banner", "snackbar")   # message timer kinds bindable by scene role, without identity
LAYERS = ("scrim",) + LAYER_KINDS
_DIGITS = re.compile(rb"[0-9]{1,18}")
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
    """The value a countdown label shows: its first run of 1 to 18 digits, or None."""
    found = _DIGITS.search(label)
    return None if found is None else int(found.group(0))


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
    texts: dict = field(default_factory=dict)         # kind -> the text of its scope (role `text`), joined by a space
    msgids: dict = field(default_factory=dict)        # kind -> the first msgid of a text node of its scope, or None
    semantic: tuple = ()
    masked: tuple = ()                                # semantic raws, a countdown's label as its value (origins)
    ident: tuple = ()                                 # the identity records' raws
    frame: tuple = ()
    patches: tuple = ()                               # (op, key, field, old bytes, new bytes)
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


def _present(records, cls, binding):
    if binding.identity:
        return frozenset(k for k in binding.bound() if k == cls)
    roles = {r.fields[1] for r in records}
    return frozenset(k for k in binding.bound() if k in roles)


def masked(records):
    """The semantic records with absolute times masked as clock-origin-divergence compares them: a countdown's label
    is its value (P004 3.5: countdowns compared as values)."""
    out = []
    for r in records:
        if r.fields[1] == "countdown":
            out.append("\t".join(r.fields[:2] + (str(countdown_value(r.values[2])),) + r.fields[3:]))
        else:
            out.append(r.raw)
    return tuple(out)


def comparable_frame(frame):
    """The frame records but `life` and `taps` lines (they are in one frame only, docs/ui-model.md)."""
    return tuple(r.raw for r in frame if not r.raw.startswith(("life\t", "taps\t")))


def facts_of(step, before, catalogue, binding):
    """The Facts of one completed step (`before`: the step before, or None)."""
    records = tuple(step.obs.get("semantic", ()))
    cls, msgids = _identity_msgids(step)
    present = _present(records, cls, binding)
    out = Facts(step.index, step.word, word_mode(step.word, catalogue), step.now,
                step.now if before is None else before.now, step.origin, step.key, step.proj, cls=cls,
                present=present, semantic=tuple(r.raw for r in records), masked=masked(records),
                ident=tuple(r.raw for r in step.obs.get("identity") or ()),
                frame=comparable_frame(step.obs.get("frame", ())),
                patches=tuple((p.fields[0], p.fields[1], p.fields[2], p.values[3], p.values[4])
                              for p in step.obs.get("patches", ())),
                restarts=frozenset(item["node"] for item in (step.restart or ())))
    for kind in present:
        scope = _scope(records, kind, binding, not binding.identity)
        out.countdowns[kind] = tuple((r.fields[0], countdown_value(r.values[2])) for r in scope
                                     if r.fields[1] == "countdown")
        texts = [r for r in scope if r.fields[1] == "text" and r.values[2] != b""]
        out.texts[kind] = b" ".join(r.values[2] for r in texts).decode("utf-8", "replace")
        out.msgids[kind] = next((msgids[r.fields[0]] for r in texts if r.fields[0] in msgids), None)
    return out


def timeline(steps, catalogue, binding):
    """The Facts of every completed step of a run, up to the first that has no abstraction key (an error)."""
    out = []
    for step in steps:
        if step.key is None or step.error is not None:
            break
        out.append(facts_of(step, out[-1] if out else None, catalogue, binding))
    return out


def appearances(facts):
    """(index, kind) of every step where a bound timed element is shown and was not at the step before."""
    out = []
    for i, fact in enumerate(facts):
        for kind in sorted(fact.present):
            if i == 0 or kind not in facts[i - 1].present:
                out.append((i, kind))
    return out
