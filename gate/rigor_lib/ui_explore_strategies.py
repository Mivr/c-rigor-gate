"""The strategies of `rigor ui-explore` (U05, P004 4.3): sweep, bfs, walk and replay over one `Explorer`, which runs
every path twice, applies the judges and records what was reached and exercised. Iteration order is fixed everywhere:
catalogue order for events, discovery order for states, the argument order for seeds and paths."""

import hashlib

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_judges import (CoarseTable, coverage_c1, coverage_c8, make, pair_findings, run_step_judges,
                                         undeclared_env, views)
from rigor_lib.ui_explore_probe import ORIGIN_MAX_MS
from rigor_lib.ui_explore_run import run_twice

STRATEGIES = ("sweep", "bfs", "walk", "replay")
REQUIRED = {"sweep": ("C1",), "bfs": ("C8",), "walk": ()}   # replay: the criteria of its paths file
CRITERIA = ("C1", "C8")
WALK_ORIGIN_SPAN = 1 << 40


def open_word(origin_ms, seed):
    return "open %d %d" % (origin_ms, seed)


def domain_indices(count):
    """The domain entries a sweep visits: all of them."""
    return range(count)


class Explorer:
    def __init__(self, config, contract, judges, settle_bound):
        self.config = config
        self.key = config.catalogue.key
        self.contract = contract
        self.judges = judges
        self.settle_bound = settle_bound
        self.event_ids = [event.id for event in config.catalogue.events]
        self.declared_env = {(e.get("env"), e.get("arg"), e.get("hex")) for e in config.catalogue.events if e.cls == "e1"}
        self.reachable = {}          # abstraction key -> the first path that reached it
        self.reachable_env = {}      # (key, enabled env input) -> path
        self.exercised = set()       # (key, event id)
        self.domain_count = None
        self.domain_visited = set()
        self.coarse = CoarseTable(self.key)
        self.findings = []
        self.runs = 0

    def run(self, words, settle=True, explore=True):
        """Run `words` twice; returns the StepViews of the first run. Exploration facts come from the words given (not
        from the appended `settle` words, which are a check, not exploration)."""
        first, second = run_twice(self.config, words, self.settle_bound if settle else 0)
        self.runs += 1
        self.findings.extend(pair_findings(first, second, self.key))
        self.findings.extend(run_step_judges(self.judges, first, self.key, self.contract))
        steps = views(first, self.key)
        for view in steps:
            if view.key is not None:
                self.coarse.add(view, first.words[:view.index + 1])
        if "domain" in first.steps[0].obs and self.domain_count is None:
            self.domain_count = first.steps[0].obs["domain"]
        if explore:
            self._record(words, steps)
        return steps

    def _record(self, words, steps):
        for view in steps[:len(words)]:
            if view.index > 0 and view.word in self.event_ids:
                self.exercised.add((view.key_before, view.word))
            if view.key is None:
                break
            path = list(words[:view.index + 1])
            self.reachable.setdefault(view.key, path)
            for item in view.step.obs["env"]:
                self.reachable_env.setdefault((view.key, item), path)
            if view.word.startswith("domain-at "):
                self.domain_visited.add(int(view.word.split(" ")[1]))

    def coverage(self, criteria, word):
        out = []
        if "C1" in criteria:
            if self.domain_count is None:
                out.extend(coverage_c1_unknown(word))
            else:
                out.extend(coverage_c1(self.domain_count, self.domain_visited, word))
        if "C8" in criteria:
            origin = int(word.split(" ")[1])
            out.extend(coverage_c8(self.reachable, self.exercised, self.event_ids, origin))
            out.extend(undeclared_env(self.reachable_env, self.declared_env, origin))
        return out

    def all_findings(self):
        return self.findings + self.coarse.found


def coverage_c1_unknown(word):
    return [make("ui-coverage-gap", ["C1", None], None, int(word.split(" ")[1]), [word],
                 {"criterion": "C1", "domain_entry": None, "domain_count": None})]


def sweep(explorer, word):
    explorer.run([word])
    count = explorer.domain_count
    if count == 0:
        raise InternalError("sweep needs a model with a view domain (uim_domain_count() is 0)")
    for index in domain_indices(count or 0):
        explorer.run([word, "domain-at %d" % index])
    return {"domain_count": count, "domain_visited": len(explorer.domain_visited)}


def bfs(explorer, word, depth_bound, max_states):
    """BFS from `open` over (abstract state x catalogue event); every path is replayed from `open`. Returns the summary
    and the `depth-unsaturated` findings."""
    root = explorer.run([word])[0]
    if root.key is None:
        return {"states_per_depth": [0], "dropped_states": 0}, []
    per_depth, dropped, known, admitted, frontier = [1], 0, {root.key}, 1, [[word]]
    first_new = None                 # (key, path) of the first new state of the last depth that added any
    for _depth in range(1, depth_bound + 1):
        new, new_dropped, first = [], 0, None
        for path in frontier:
            for event in explorer.event_ids:
                steps = explorer.run(path + [event])
                last = steps[len(path)] if len(steps) > len(path) else None
                if last is None or last.key is None or last.key in known:
                    continue
                known.add(last.key)
                first = first or (last.key, path + [event])
                if admitted < max_states:
                    admitted += 1
                    new.append(path + [event])
                else:
                    new_dropped += 1
        per_depth.append(len(new) + new_dropped)
        dropped += new_dropped
        first_new = first or first_new
        frontier = new
        if not new:
            break
    summary = {"states_per_depth": per_depth, "dropped_states": dropped}
    return summary, _depth_findings(per_depth, depth_bound, max_states, dropped, first_new, word)


def _depth_findings(per_depth, depth_bound, max_states, dropped, first_new, word):
    """`depth-unsaturated`: the last depth still added abstract states, or the state bound dropped some."""
    reasons = []
    if len(per_depth) == depth_bound + 1 and per_depth[-1] > 0:
        reasons.append("last-depth-adds-states")
    if dropped:
        reasons.append("state-bound")
    if not reasons:
        return []
    observed = {"depth_bound": depth_bound, "max_states": max_states, "states_per_depth": per_depth,
                "dropped_states": dropped, "reasons": reasons}
    return [make("depth-unsaturated", [depth_bound, max_states], first_new[0], int(word.split(" ")[1]), first_new[1],
                 observed)]


def walk_events(seed, length, event_ids):
    """`length` catalogue events chosen by sha256 of the seed and the step: the same on every Python and platform."""
    out = []
    for index in range(length):
        digest = hashlib.sha256(b"ui-explore walk %d %d" % (seed, index)).digest()
        out.append(event_ids[int.from_bytes(digest[:8], "big") % len(event_ids)])
    return out


def walk_origins(base, seed, extra):
    out = [base]
    for index in range(1, extra + 1):
        digest = hashlib.sha256(b"ui-explore origin %d %d" % (seed, index)).digest()
        out.append(int.from_bytes(digest[:8], "big") % WALK_ORIGIN_SPAN)
    return out


def walk(explorer, origin, seed, walk_seeds, length, extra):
    if not explorer.event_ids:
        raise InternalError("walk needs at least one catalogue event")
    for walk_seed in walk_seeds:
        events = walk_events(walk_seed, length, explorer.event_ids)
        for start in walk_origins(origin, walk_seed, extra):
            if start > ORIGIN_MAX_MS:
                raise InternalError("walk origin out of range")
            explorer.run([open_word(start, seed)] + events)
    return {"walks": len(walk_seeds) * (extra + 1)}


def replay(explorer, paths):
    for path in paths:
        explorer.run(list(path), settle=False)
    return {"paths": len(paths)}

