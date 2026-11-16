"""`clock-origin-divergence` of the `ui-time` judge (U09, P004 3.5; docs/ui-judges-time.md): a path replayed from the
other clock origins must give, step by step, the same semantic records (a countdown's label with its digit runs masked
and its value kept), the same identity, the same time since the origin and the same next deadline relative to the
origin (an unstamped deadline fires at another relative instant even when the scene looks the same).

Selection, bounded: first every path that shows a (state key at its appearance, timer kind) pair no selected path has
shown, in run order; the paths that show only pairs already covered wait, and fill the quota at the end of the run, in
run order. The quota is ORIGIN_PATHS paths per boot seed (the seed of the `open` word).
"""

from rigor_lib.ui_judge_time_model import Binding, appearances, timeline

ORIGINS = (1, 1000, 10**9, 2**32 + 7, 2**40)     # P004 3.5, ms
ORIGIN_PATHS = 8


def divergence(facts, other):
    """(step, part) of the first step that differs, or where the replay ended; None when none does."""
    for at, fact in enumerate(facts):
        if at >= len(other):
            return at, "ended"
        theirs = other[at]
        for part, mine, them in (("semantic", fact.masked, theirs.masked), ("identity", fact.ident, theirs.ident),
                                 ("time", fact.now - fact.origin, theirs.now - theirs.origin),
                                 ("due", fact.due, theirs.due)):
            if mine != them:
                return at, part
    return None


class Origins:
    def __init__(self, contract):
        self.contract = contract
        self.covered, self.done, self.waiting, self.per_seed = set(), set(), [], {}
        self.runs = 0

    def offer(self, facts, words):
        """Whether to replay this path now; a path whose pairs are all covered waits for the end of the run."""
        pairs = {(facts[i].key, kind) for i, kind in appearances(facts)}
        seed = words[0].split(" ")[2]
        if not pairs or tuple(words) in self.done or self.per_seed.get(seed, 0) >= ORIGIN_PATHS:
            return False
        if pairs <= self.covered:
            if all(tuple(w) != tuple(words) for w, _f in self.waiting):
                self.waiting.append((list(words), facts))
            return False
        self.covered |= pairs
        return True

    def take(self, words):
        seed = words[0].split(" ")[2]
        self.done.add(tuple(words))
        self.per_seed[seed] = self.per_seed.get(seed, 0) + 1

    def fill(self):
        """The waiting paths that still fit the quota, in run order."""
        out = []
        for words, facts in self.waiting:
            seed = words[0].split(" ")[2]
            if tuple(words) not in self.done and self.per_seed.get(seed, 0) < ORIGIN_PATHS:
                self.take(words)
                out.append((words, facts))
        return out

    def replay(self, runner, identity, facts, words):
        """[(step, part, origin)] of every other origin whose replay diverges."""
        seed, diverged = words[0].split(" ")[2], []
        for origin in ORIGINS:
            if origin == facts[0].origin:
                continue
            steps = runner.once(["open %d %s" % (origin, seed)] + words[1:])
            self.runs += 1
            found = divergence(facts, timeline(steps, runner.catalogue, Binding(self.contract, identity)))
            if found is not None:
                diverged.append((found[0], found[1], origin))
        return diverged
