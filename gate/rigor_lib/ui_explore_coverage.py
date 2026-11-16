"""The exploration of `rigor ui-explore` and its exploration-level judges (U05, P004 4.3 coverage criteria).

`Exploration` is the visited graph the explorer builds from the exploration words of every first run (never from the
appended `settle` words, which are a check). An exploration judge is `judge(exploration, contract) -> (evaluated,
findings)`; `evaluated` is False when the criterion could not be judged (then it is not reported as evaluated, and
`--require` turns that into a finding). The coverage criteria are registered in `CRITERIA`.
"""

from dataclasses import dataclass, field

from rigor_lib.ui_explore_judges import make, state_of
from rigor_lib.ui_explore_key import derived_matched
from rigor_lib.ui_explore_words import outcome_kind


@dataclass
class EventCount:
    """The abstract states in which an input event's outcome (its last input's) was accepted, refused or missed, and
    for each outcome the first send that had it: (path, (key, projection, origin) before the send)."""
    accepted: set = field(default_factory=set)
    refused: set = field(default_factory=set)
    missed: set = field(default_factory=set)
    first: dict = field(default_factory=dict)       # outcome -> (path, state before)


@dataclass
class Exploration:
    catalogue: object
    open_word: str
    domain_count: object = None
    domain_visited: set = field(default_factory=set)
    reachable: dict = field(default_factory=dict)      # key -> (path, projection, origin)
    edges: set = field(default_factory=set)            # (key before, word, key after or None)
    env: dict = field(default_factory=dict)            # (key, enabled env input) -> path
    events: dict = field(default_factory=dict)         # event id -> EventCount
    outcomes: dict = field(default_factory=dict)       # path word or event id -> {outcome type: count}
    derived_matched: set = field(default_factory=set)  # derived facts whose selector matched in some visited state
    visited: bool = False

    def record(self, words, steps):
        """Add the exploration steps of one first run (steps of `words`, not the appended ones)."""
        ids = self.catalogue.event_ids
        for step in steps[:len(words)]:
            self._outcomes(step)
            if step.index > 0 and step.word in ids:
                self.edges.add((step.key_before, step.word, step.key))
                self._count(step, words)
            if step.key is None:
                break
            self.visited = True
            for fact in self.catalogue.key.derived:
                if fact.name not in self.derived_matched and derived_matched(fact, step.obs):
                    self.derived_matched.add(fact.name)
            if step.key not in self.reachable:
                self.reachable[step.key] = (list(words[:step.index + 1]), step.proj, step.origin)
            for item in step.obs["env"]:
                if (step.key, item) not in self.env:
                    self.env[(step.key, item)] = list(words[:step.index + 1])
            if step.word.startswith("domain-at "):
                self.domain_visited.add(int(step.word.split(" ")[1]))

    def _count(self, step, words):
        if step.result is None:
            return
        count = self.events.setdefault(step.word, EventCount())
        outcome = {"ok": "accepted", "refused": "refused", "missed": "missed", "dismissed": "accepted",
                   "inert": "refused"}[step.result]
        getattr(count, outcome).add(step.key_before)
        if outcome not in count.first:
            count.first[outcome] = (list(words[:step.index + 1]), (step.key_before, step.proj_before, step.origin))

    def _outcomes(self, step):
        word = "settle" if step.word == "settle" else step.word.split(" ")[0] if step.index else "open"
        counts = self.outcomes.setdefault(word, {})
        for item in step.outcome:
            kind = outcome_kind(item)
            counts[kind] = counts.get(kind, 0) + 1

    def exercised(self):
        return {(before, word) for before, word, _after in self.edges}


def c1_judge(exploration, contract):
    """C1: every domain entry visited. Not evaluated when the model has no view domain or its count is unknown."""
    del contract
    count, sha = exploration.domain_count, exploration.catalogue.sha256
    if not count:
        return False, []
    return True, [make("ui-coverage-gap", ["C1", sha, index], None, [exploration.open_word],
                       {"criterion": "C1", "domain_entry": index, "domain_count": count})
                  for index in range(count) if index not in exploration.domain_visited]


def c8_judge(exploration, contract):
    """C8: every reachable (abstract state, catalogue event) pair exercised; every enabled env input declared; every
    event declared `accept` accepted somewhere, every event declared `refuse` never accepted."""
    del contract
    if not exploration.reachable:
        return False, []
    catalogue, key = exploration.catalogue, exploration.catalogue.key
    exercised, out = exploration.exercised(), []
    for state in sorted(exploration.reachable):
        path, proj, origin = exploration.reachable[state]
        for event in catalogue.events:
            if (state, event.id) not in exercised:
                out.append(make("ui-coverage-gap", ["C8", state, event.id], state_of(state, proj, key, origin), path,
                                {"criterion": "C8", "event": event.id}))
    declared = {(e.get("env"), e.get("arg"), e.get("hex")) for e in catalogue.events if e.cls == "e1"}
    for (state, item), path in sorted(exploration.env.items()):
        if item not in declared:
            proj, origin = exploration.reachable[state][1:]
            out.append(make("ui-coverage-gap", ["C8-env", state, list(item)], state_of(state, proj, key, origin), path,
                            {"criterion": "C8", "undeclared_env_input": [item[0], item[1]]},
                            {"env-input.json": {"input": list(item)}}))
    out.extend(_acceptance(exploration))
    return True, out


def _acceptance(exploration):
    out = []
    key, sha = exploration.catalogue.key, exploration.catalogue.sha256
    for event in exploration.catalogue.events:
        count = exploration.events.get(event.id)
        if count is None or event.cls in ("u2", "u3"):     # taps declare no expectation (yet)
            continue
        expect = event.get("expect")
        bad = (expect == "accept" and not count.accepted) or (expect == "refuse" and count.accepted)
        if bad:
            # the witness is the first send with the offending outcome: replaying it gives the same finding
            check = "event-never-accepted" if expect == "accept" else "event-accepted"
            witness = count.first["accepted"] if expect == "refuse" else count.first.get("refused", count.first.get("missed"))
            path, before = witness
            out.append(make(check, [sha, event.id], state_of(before[0], before[1], key, before[2]), path,
                            {"event": event.id, "expect": expect, "accepted_states": len(count.accepted),
                             "refused_states": len(count.refused), "missed_states": len(count.missed)}))
    return out


def key_facts_judge(exploration):
    """`key-fact-unmatched`: a derived fact whose node/role selector matched no record in any visited state is a
    constant, not a fact; every strategy runs this once some state was visited."""
    sha = exploration.catalogue.sha256
    return [make("key-fact-unmatched", [sha, fact.name], None, [exploration.open_word],
                 {"fact": fact.name, "node": fact.node, "role": fact.role})
            for fact in exploration.catalogue.key.derived
            if exploration.visited and fact.model is None and fact.name not in exploration.derived_matched]


CRITERIA = {"C1": c1_judge, "C8": c8_judge}


def not_evaluated(criterion, exploration):
    """The finding `--require` gives for a required criterion that no judge evaluated."""
    return make("ui-coverage-gap", ["not-evaluated", criterion, exploration.catalogue.sha256], None,
                [exploration.open_word], {"criterion": criterion, "evaluated": False})
