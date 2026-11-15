"""The exploration of `rigor ui-explore` and its exploration-level judges (U05, P004 4.3 coverage criteria).

`Exploration` is the visited graph the explorer builds from the exploration words of every first run (never from the
appended `settle` words, which are a check). An exploration judge is `judge(exploration, contract) -> (evaluated,
findings)`; `evaluated` is False when the criterion could not be judged (then it is not reported as evaluated, and
`--require` turns that into a finding). The coverage criteria are registered in `CRITERIA`.
"""

from dataclasses import dataclass, field

from rigor_lib.ui_explore_judges import make, state_of


@dataclass
class EventCount:
    """The abstract states in which an event was accepted and refused (a state may be in both: refusal in one run
    of a state and acceptance in another is the run-twice judge's business)."""
    accepted: set = field(default_factory=set)
    refused: set = field(default_factory=set)
    first_path: object = None      # the first path that sent it
    first_state: object = None     # (key, projection, origin) before that send


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

    def record(self, words, steps):
        """Add the exploration steps of one first run (steps of `words`, not the appended ones)."""
        ids = self.catalogue.event_ids
        for step in steps[:len(words)]:
            if step.index > 0 and step.word in ids:
                self.edges.add((step.key_before, step.word, step.key))
                self._count(step, words)
            if step.key is None:
                break
            if step.key not in self.reachable:
                self.reachable[step.key] = (list(words[:step.index + 1]), step.proj, step.origin)
            for item in step.obs["env"]:
                if (step.key, item) not in self.env:
                    self.env[(step.key, item)] = list(words[:step.index + 1])
            if step.word.startswith("domain-at "):
                self.domain_visited.add(int(step.word.split(" ")[1]))

    def _count(self, step, words):
        if not step.applies:
            return
        count = self.events.setdefault(step.word, EventCount())
        if count.first_path is None:
            count.first_path = list(words[:step.index + 1])
            count.first_state = (step.key_before, step.proj_before, step.origin)
        (count.accepted if "ok" in step.applies else count.refused).add(step.key_before)

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
            check = "event-never-accepted" if expect == "accept" else "event-accepted"
            before = count.first_state
            out.append(make(check, [sha, event.id], state_of(before[0], before[1], key, before[2]), count.first_path,
                            {"event": event.id, "expect": expect, "accepted_states": len(count.accepted),
                             "refused_states": len(count.refused)}))
    return out


CRITERIA = {"C1": c1_judge, "C8": c8_judge}


def not_evaluated(criterion, exploration):
    """The finding `--require` gives for a required criterion that no judge evaluated."""
    return make("ui-coverage-gap", ["not-evaluated", criterion, exploration.catalogue.sha256], None,
                [exploration.open_word], {"criterion": criterion, "evaluated": False})
