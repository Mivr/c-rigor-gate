"""The time-probing mode of the `ui-time` judge (U09, docs/ui-judges-time.md "The time-probing mode"): the runs that
bracket when a timed element appears and when it goes, to one tick wherever the path allows it and further while a
lifetime rule is still undecided. An element is an INSTANCE (ui_judge_time_model.same_instance): a sample shows it only
while the instance is the one of the appearance.

- The APPEARANCE of an element first shown at the end of a time step: the path up to the step before, then `at` words
  inside the step AND at its end (the run must show the instance there, else `probe-diverged`); walking back from the
  end, a sample shows it while the instance stays the same.
- The DISAPPEARANCE: the path up to the appearance step, then `at` words; a sample shows it until the instance first
  changes or goes (ui_judge_time_model.alive).
- INSIDE a time step whose patches create and remove one key: the path to the step before, then `at` words inside the
  step, refined between consecutive samples until every such key has been seen; each element instance seen only inside
  is bracketed on both edges.

Every run is a path of the explorer (`runner.probe`: run twice, with the explorer's run judges). Samples of all runs
must change at most once in time (`monotone`; inside a step: one life, `unimodal`), else `probe-diverged`. At most
MAX_PHASES runs per edge (and per hidden step) and MAX_AT `at` words per run; a plan that needs more `at` words is not
run (`lifetime-undecided`).
"""

from dataclasses import dataclass, field

from rigor_lib.ui_judge_time_checks import GRID, MAX_AT, decisions, falling, monotone, plan, refine, rising
from rigor_lib.ui_judge_time_model import alive, same_instance, timeline

MAX_PHASES = 6         # probing runs per edge (16^5 > 600 000: a bracket of the longest advance down to one ms)


class Diverged(Exception):
    """A probing run did not show what the path showed, or two runs disagree."""

    def __init__(self, words):
        Exception.__init__(self, "probing run diverged")
        self.words = words


@dataclass
class Probe:
    appear: tuple                     # (a_lo, a_hi): can have been shown from a_lo, shown at a_hi
    gone: tuple = (0, None)           # (t1_lo, t1_hi]
    apoints: list = field(default_factory=list)   # (instant, shown) of the appearance runs
    gpoints: list = field(default_factory=list)   # (instant, shown) of the disappearance runs
    shown: list = field(default_factory=list)     # the samples that show the instance (their labels: `zero`)
    seq: list = field(default_factory=list)       # the first disappearance run's facts from the appearance on
    run: tuple = ((), (), 0)                       # (facts, words, the appearance index) of that run
    runs: int = 0
    why: object = None                # why nothing was run: `at-word-cap`, `no-plan`


class Prober:
    def __init__(self, runner, binding, tick):
        self.runner, self.binding, self.tick = runner, binding, tick
        self.max_wait = runner.catalogue.max_wait_ms

    def _run(self, words, instants, check):
        """(facts, words) of `words` + `at` words at `instants`; Diverged when `check(facts)` is false."""
        origin = int(words[0].split(" ")[1])
        probe_words = words + ["at %d" % (at - origin) for at in instants]
        steps = self.runner.probe(probe_words)
        facts = timeline(steps, self.runner.catalogue, self.binding)
        if not check(facts):
            raise Diverged(probe_words)
        return facts, [step.word for step in steps[:len(facts)]]

    # ---- the appearance at the end of a time step -------------------------------------------------------------------
    def _appear(self, facts, words, index, kind, probe):
        instants = refine(probe.appear[0] - 1, probe.appear[1], self.max_wait)
        if not instants:
            return False
        before, step = facts[index - 1], facts[index]
        run, run_words = self._run(words[:index], instants + [step.now], lambda f: len(f) > index and
                                   f[index - 1].key == before.key and f[-1].now == step.now and kind in f[-1].present
                                   and f[-1].roles.get(kind) == step.roles.get(kind))
        later = run[index:]
        iid = later[-1].tops.get(kind)               # the instance at the step's end, and where it was before
        flags = [(f.now, same_instance(f, f, kind, iid)) for f in later]
        probe.apoints += [(at, shown) for at, shown in flags if at in set(instants)]
        if not monotone(probe.apoints + [(before.now, False), (step.now, True)], True):
            raise Diverged(run_words)
        lo, hi = rising(probe.apoints, before.now, step.now)
        probe.appear, probe.runs = (lo + 1, hi), probe.runs + 1
        return True

    # ---- the disappearance ------------------------------------------------------------------------------------------
    def _gone(self, words, index, kind, appear, probe, instants):
        if probe.gpoints and probe.gone[0] > appear.now:
            instants = sorted(set(instants) | {probe.gone[0]})     # the last instant shown, again: runs must agree
        run, run_words = self._run(words[:index + 1], instants, lambda f: len(f) > index and f[index].key == appear.key
                                   and kind in f[index].present)
        wanted = set(instants)
        tracked = [(f, shown) for f, shown in alive(run, kind, index) if f.now in wanted and f.word.startswith("at ")]
        if not probe.seq:
            probe.seq, probe.run = run[index:], (run, run_words, index)
        probe.gpoints += [(f.now, shown) for f, shown in tracked]
        probe.shown += [f for f, shown in tracked if shown]
        if not monotone(probe.gpoints + [(appear.now, True)], False):
            raise Diverged(run_words)
        probe.gone, probe.runs = falling(probe.gpoints, appear.now), probe.runs + 1

    def _wide(self, bracket, until_tick):
        return bracket[1] is not None and bracket[1] - bracket[0] > (self.tick if until_tick else 1)

    def probe(self, facts, words, index, kind, timer, bounds):
        """The Probe of one appearance; `bounds` = (D or None, the floor or None). Raises Diverged."""
        appear = facts[index]
        probe = Probe((appear.appear_lo, appear.now), (appear.now, None))
        phases = {"appear": 0, "gone": 0}
        while phases["appear"] < MAX_PHASES and probe.appear[1] - probe.appear[0] >= self.tick \
                and self._appear(facts, words, index, kind, probe):
            phases["appear"] += 1
        instants = plan(appear.now, probe.appear[1], timer["lifetime_ms"], bounds[0] if bounds[0] is not None
                        else bounds[1], self.tick, self.max_wait)
        if len(instants) > MAX_AT or not instants:
            probe.why = "at-word-cap" if instants else "no-plan"
            return probe
        self._gone(words, index, kind, appear, probe, instants)
        phases["gone"] = 1
        fine = timer["countdown_shown"]           # the last label before it goes: refine that edge to one ms
        while phases["gone"] < MAX_PHASES and self._wide(probe.gone, not fine):
            self._gone(words, index, kind, appear, probe, refine(probe.gone[0], probe.gone[1], self.max_wait))
            phases["gone"] += 1
        limits = (timer["lifetime_ms"], bounds[0], bounds[1], self.tick)
        while None in decisions(probe.appear, probe.gone, *limits)[0].values():
            if self._wide(probe.gone, False) and phases["gone"] < MAX_PHASES:
                self._gone(words, index, kind, appear, probe, refine(probe.gone[0], probe.gone[1], self.max_wait))
                phases["gone"] += 1
            elif phases["appear"] < MAX_PHASES and self._appear(facts, words, index, kind, probe):
                phases["appear"] += 1
            else:
                break
        return probe

    # ---- what is shown only inside a time step ----------------------------------------------------------------------
    def inside(self, facts, words, index, pairs, wanted):
        """{instant: facts} sampled inside the time step `index`: first GRID - 1 even instants, then the midpoints of
        the widest gaps between consecutive samples while a key of `pairs` was never seen, then the instants
        `wanted(samples)` asks for (the edges still undecided), at most MAX_PHASES runs in all."""
        before, step = facts[index - 1], facts[index]
        samples, instants, keys = {}, refine(before.now, step.now, self.max_wait), [key for key, _role in pairs]
        for _phase in range(MAX_PHASES):
            if not instants:
                break
            anchor = min((at for at, f in samples.items() if any(k in f.labels for k in keys)), default=None)
            instants = sorted(set(instants) | ({anchor} if anchor is not None else set()))   # re-seen: must agree
            run, run_words = self._run(words[:index], instants, lambda f: len(f) >= index and
                                       f[index - 1].key == before.key)
            for f in run[index:]:
                if f.now in samples and [k in f.labels for k in keys] != [k in samples[f.now].labels for k in keys]:
                    raise Diverged(run_words)
                if f.now in set(instants) and f.word.startswith("at "):
                    samples[f.now] = f
            if not all(_unimodal(points) for points in keyed(samples, keys)):
                raise Diverged(run_words)
            unseen = [key for key, _role in pairs if not any(key in f.labels for f in samples.values())]
            instants = _gaps(sorted(set(samples) | {before.now, step.now})) if unseen else wanted(samples)
        return samples


def _gaps(points):
    """The midpoints of the GRID - 1 widest gaps between consecutive instants (ties: the earlier gap)."""
    gaps = sorted(((b - a, a, b) for a, b in zip(points, points[1:]) if b - a > 1), key=lambda g: (-g[0], g[1]))
    return sorted((a + b) // 2 for _w, a, b in gaps[:GRID - 1])


def keyed(samples, keys):
    """Per key, (instant, shown) over the samples."""
    return [[(at, key in f.labels) for at, f in sorted(samples.items())] for key in keys]


def _unimodal(points):
    """Not shown, then shown, then not shown again (at most): one node's life inside a step."""
    flags = [shown for _at, shown in sorted(points)]
    first = flags.index(True) if True in flags else len(flags)
    rest = flags[first:]
    last = rest.index(False) if False in rest else len(rest)
    return not any(rest[last:])


def edges(points, start, end):
    """((last instant not shown, first shown), (last shown, first not shown)) of one node or instance shown only
    inside (start, end), from (instant, shown) points; None when no point shows it."""
    shown = [at for at, flag in points if flag]
    if not shown:
        return None
    first, last = min(shown), max(shown)
    lo = max([start] + [at for at, flag in points if not flag and at < first])
    hi = min([end] + [at for at, flag in points if not flag and at > last])
    return (lo, first), (last, hi)
