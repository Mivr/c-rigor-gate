"""The time-probing mode of the `ui-time` judge (U09, docs/ui-judges-time.md "The time-probing mode"): the runs that
bracket when a timed element appears and when it goes, to one tick wherever the path allows it and further while a
lifetime rule is still undecided.

- The APPEARANCE: an element first shown at the end of a time step appeared somewhere in (the step before, now]. The
  path up to the step before, then `at` words inside that span, bisects it (an input step's appearance is exact).
- The DISAPPEARANCE: the path up to the appearance step, then `at` words: the plan's grid and deciding instants
  (ui_judge_time_checks.plan), then refinements inside the bracket.

Each run is a path of the explorer (`runner.probe`: run twice, with the explorer's run judges). A run that does not
reach the appearance as the path did is `probe-diverged`. At most MAX_PHASES runs per edge and MAX_AT `at` words per
run; a plan that needs more `at` words (a small `max_wait_ms`) is not run and its rules are `lifetime-undecided`.
"""

from dataclasses import dataclass, field

from rigor_lib.ui_judge_time_checks import MAX_AT, decisions, falling, plan, refine, rising
from rigor_lib.ui_judge_time_model import timeline

MAX_PHASES = 6         # probing runs per edge (16^5 > 600 000: a bracket of the longest advance down to one ms)


class Diverged(Exception):
    """A probing run did not show the element at the appearance step as the path did."""

    def __init__(self, words):
        Exception.__init__(self, "probing run diverged")
        self.words = words


@dataclass
class Probe:
    appear: tuple                     # (a_lo, a_hi): can have been shown from a_lo, shown at a_hi
    gone: tuple = (0, None)           # (t1_lo, t1_hi]
    samples: list = field(default_factory=list)
    seq: list = field(default_factory=list)       # the first disappearance run's facts from the appearance on
    run: tuple = ((), ())                          # (facts, words) of that run
    runs: int = 0
    why: object = None                # why nothing was run: `at-word-cap`, `no-plan`


class Prober:
    def __init__(self, runner, binding, tick):
        self.runner, self.binding, self.tick = runner, binding, tick
        self.max_wait = runner.catalogue.max_wait_ms

    def _run(self, words, before, instants, check):
        """The facts of `words` + `at` words at `instants`, and its samples (the steps after `before`); Diverged when
        the step `check` (an index) is not what `want` says."""
        origin = int(words[0].split(" ")[1])
        probe_words = words + ["at %d" % (at - origin) for at in instants]
        steps = self.runner.probe(probe_words)
        facts = timeline(steps, self.runner.catalogue, self.binding)
        if len(facts) <= check[0] or not check[1](facts[check[0]]):
            raise Diverged(probe_words)
        wanted = set(instants)
        samples = [f for f in facts[before + 1:] if f.now in wanted and f.word.startswith("at ")]
        return facts, [step.word for step in steps[:len(facts)]], samples

    def _appear(self, facts, words, index, kind, probe, until_tick):
        """Bisect the appearance inside the time step `index` (one run per call)."""
        lo, hi = probe.appear[0] - 1, probe.appear[1]
        instants = refine(lo, hi, self.max_wait)
        if not instants or (until_tick and hi - lo <= self.tick):
            return False
        before = facts[index - 1]
        _f, _w, samples = self._run(words[:index], index - 1, instants,
                                    (index - 1, lambda f: f.key == before.key))
        lo, hi = rising(samples, kind, lo, hi)
        probe.appear, probe.runs = (lo + 1, hi), probe.runs + 1
        return True

    def _gone(self, words, index, kind, appear_key, probe, instants):
        run_facts, run_words, samples = self._run(words[:index + 1], index, instants,
                                                  (index, lambda f: f.key == appear_key and kind in f.present))
        if not probe.seq:
            probe.seq, probe.run = run_facts[index:], (run_facts, run_words)
        probe.samples += samples
        probe.gone, probe.runs = falling(probe.samples, kind, run_facts[index].now), probe.runs + 1

    def _wide(self, bracket, until_tick):
        return bracket[1] is not None and bracket[1] - bracket[0] > (self.tick if until_tick else 1)

    def _inside(self, words, index, before_key, instants):
        return self._run(words[:index], index - 1, instants, (index - 1, lambda f: f.key == before_key))[2]

    def hidden(self, facts, words, index):
        """{kind: Probe} of the timed elements shown only INSIDE the time step `index` (gone again at its end; its
        patches create and remove a node): the path to the step before, then `at` words inside the step, refined
        until each element's two edges decide (or are one ms wide, or MAX_PHASES runs)."""
        before, step = facts[index - 1], facts[index]
        samples = self._inside(words, index, before.key, refine(before.now, step.now, self.max_wait))
        kinds = sorted({k for s in samples for k in s.present} - before.present - step.present)
        out = {}
        for kind in kinds:
            appear = rising(samples, kind, before.now, step.now)
            later = [s for s in samples if s.now > appear[1]]
            probe = Probe((appear[0] + 1, appear[1]), falling(later + [step], kind, appear[1]), samples, runs=1)
            out[kind] = probe
        return out, samples

    def refine_hidden(self, facts, words, index, kind, probe, decide):
        """Refine the edges of a hidden element while `decide(probe)` is undecided and an edge is wider than one ms."""
        before = facts[index - 1]
        for _phase in range(MAX_PHASES):
            if decide(probe) or (probe.appear[1] - probe.appear[0] < 1 and probe.gone[1] - probe.gone[0] <= 1):
                return probe
            instants = refine(probe.appear[0] - 1, probe.appear[1], self.max_wait) + \
                refine(probe.gone[0], probe.gone[1], self.max_wait)
            probe.samples += self._inside(words, index, before.key, sorted(set(instants)))
            lo, hi = rising(probe.samples, kind, before.now, facts[index].now)
            later = [s for s in probe.samples if s.now > hi]
            probe.appear, probe.gone = (lo + 1, hi), falling(later + [facts[index]], kind, hi)
            probe.runs += 1
        return probe

    def probe(self, facts, words, index, kind, timer, bounds):
        """The Probe of one appearance; `bounds` = (D or None, the floor or None). Raises Diverged."""
        appear = facts[index]
        probe = Probe((appear.appear_lo, appear.now), (appear.now, None))
        phases = {"appear": 0, "gone": 0}
        while phases["appear"] < MAX_PHASES and self._appear(facts, words, index, kind, probe, True):
            phases["appear"] += 1
        instants = plan(appear.now, probe.appear[1], timer["lifetime_ms"], bounds[0] if bounds[0] is not None
                        else bounds[1], self.tick, self.max_wait)
        if len(instants) > MAX_AT or not instants:
            probe.why = "at-word-cap" if instants else "no-plan"
            return probe
        self._gone(words, index, kind, appear.key, probe, instants)
        phases["gone"] = 1
        fine = timer["countdown_shown"]           # the last label before it goes: refine that edge to one ms
        while phases["gone"] < MAX_PHASES and self._wide(probe.gone, not fine):
            self._gone(words, index, kind, appear.key, probe, refine(probe.gone[0], probe.gone[1], self.max_wait))
            phases["gone"] += 1
        while None in decisions(probe.appear, probe.gone, timer["lifetime_ms"], bounds[0], bounds[1],
                                self.tick)[0].values():
            if self._wide(probe.gone, False) and phases["gone"] < MAX_PHASES:
                self._gone(words, index, kind, appear.key, probe, refine(probe.gone[0], probe.gone[1], self.max_wait))
                phases["gone"] += 1
            elif phases["appear"] < MAX_PHASES and self._appear(facts, words, index, kind, probe, False):
                phases["appear"] += 1
            else:
                break
        return probe
