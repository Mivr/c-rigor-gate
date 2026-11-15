"""The strategies of `rigor ui-explore` (U05, P004 4.3): sweep, bfs, walk and replay over one `Explorer`, which runs
every path twice, applies the step and run judges and records the exploration. Iteration order is fixed everywhere:
catalogue order for events, discovery order for states, argument order for seeds and paths."""

import hashlib

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_coverage import Exploration
from rigor_lib.ui_explore_judges import (CoarseTable, make, probe_error_judge, run_step_judges, run_twice_judge,
                                         starvation_judge, state_of, unreachable_judge)
from rigor_lib.ui_explore_probe import ORIGIN_MAX_MS, BudgetSpent
from rigor_lib.ui_explore_run import run_twice

STRATEGIES = ("sweep", "bfs", "walk", "replay")
REQUIRED = {"sweep": ("C1",), "bfs": ("C8",), "walk": ()}   # replay: the criteria of its paths file
WALK_ORIGIN_SPAN = 1 << 40


def open_word(origin_ms, seed):
    return "open %d %d" % (origin_ms, seed)


def domain_indices(count):
    """The domain entries a sweep visits: all of them."""
    return range(count)


class Explorer:
    def __init__(self, config, contract, settle_bound, word, caps=(), step_judges=(), run_judges=()):
        catalogue = config.catalogue
        self.config, self.contract, self.settle_bound = config, contract, settle_bound
        self.step_judges = [starvation_judge(settle_bound, catalogue.key), unreachable_judge(catalogue.key)]
        self.step_judges += list(step_judges)
        self.run_judges = [probe_error_judge(catalogue.key), run_twice_judge(catalogue.key)] + list(run_judges)
        self.sendable = [e.id for e in catalogue.events if e.cls not in ("u2", "u3") or "tap" in caps]
        self.exploration = Exploration(catalogue, word)
        self.coarse = CoarseTable(catalogue.key)
        self.findings = []
        self.runs = 0

    def run(self, words, settle=True, explore=True):
        """Run `words` twice; returns the steps of the first run."""
        if self.config.budget.spent():
            raise BudgetSpent()
        first, second = run_twice(self.config, words, settle)
        self.runs += 1
        for judge in self.run_judges:
            self.findings.extend(judge(first, second, self.contract))
        self.findings.extend(run_step_judges(self.step_judges, first, self.contract))
        for step in first.steps:
            if step.key is not None:
                self.coarse.add(step, first.words)
        if "domain" in first.steps[0].obs and self.exploration.domain_count is None:
            self.exploration.domain_count = first.steps[0].obs["domain"]
        if explore:
            self.exploration.record(words, first.steps)
        return first.steps

    def all_findings(self):
        return self.findings + self.coarse.found


def sweep(explorer, word):
    explorer.run([word])
    count = explorer.exploration.domain_count
    if count == 0:
        raise InternalError("sweep needs a model with a view domain (uim_domain_count() is 0)")
    for index in domain_indices(count or 0):
        explorer.run([word, "domain-at %d" % index])
    return {"domain_count": count, "domain_visited": len(explorer.exploration.domain_visited)}


def bfs(explorer, word, depth_bound, max_states):
    """BFS from `open` over (abstract state x sendable catalogue event); every path is replayed from `open`."""
    if not explorer.sendable:
        raise InternalError("bfs needs at least one catalogue event this probe can be sent")
    root = explorer.run([word])[0]
    if root.key is None:
        return {"states_per_depth": [0], "dropped_states": 0}, []
    per_depth, dropped, known, admitted, frontier = [1], 0, {root.key}, 1, [[word]]
    first_new = None
    for _depth in range(1, depth_bound + 1):
        new, new_dropped, first = [], 0, None
        for path in frontier:
            for event in explorer.sendable:
                steps = explorer.run(path + [event])
                last = steps[len(path)] if len(steps) > len(path) else None
                if last is None or last.key is None or last.key in known:
                    continue
                known.add(last.key)
                first = first or (last, path + [event])
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
    return summary, _depth_findings(explorer, per_depth, depth_bound, max_states, dropped, first_new)


def _depth_findings(explorer, per_depth, depth_bound, max_states, dropped, first_new):
    reasons = []
    if len(per_depth) == depth_bound + 1 and per_depth[-1] > 0:
        reasons.append("last-depth-adds-states")
    if dropped:
        reasons.append("state-bound")
    if not reasons:
        return []
    step, path = first_new
    catalogue = explorer.config.catalogue
    observed = {"depth_bound": depth_bound, "max_states": max_states, "states_per_depth": per_depth,
                "dropped_states": dropped, "reasons": reasons}
    return [make("depth-unsaturated", ["depth", catalogue.sha256, depth_bound, max_states],
                 state_of(step.key, step.proj, catalogue.key, step.origin), path, observed)]


def walk_events(seed, length, event_ids):
    """`length` events chosen by sha256 of the seed and the step: the same on every Python and platform."""
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
    if not explorer.sendable:
        raise InternalError("walk needs at least one catalogue event this probe can be sent")
    for walk_seed in walk_seeds:
        events = walk_events(walk_seed, length, explorer.sendable)
        for start in walk_origins(origin, walk_seed, extra):
            if start > ORIGIN_MAX_MS:
                raise InternalError("walk origin out of range")
            explorer.run([open_word(start, seed)] + events)
    return {"walks": len(walk_seeds) * (extra + 1)}


def replay(explorer, paths):
    for path in paths:
        explorer.run(list(path), settle=False)
    return {"paths": len(paths)}
