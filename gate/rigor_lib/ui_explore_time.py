"""The explorer's side of the `ui-time` judge (U09, P004 3.5; docs/ui-judges-time.md): with `--judges` naming
`ui-time`, every path the strategy runs is handed, with the steps of its first run, to the judge
(ui_judge_time.TimeJudge.path), which may run more paths through the `Runner` below:

- the time-probing runs: the path up to the step where a timed element appears, then `at` words that bracket its
  disappearance (each run twice, as every path, with the explorer's run judges);
- the clock-origin replays: the same path from other origins, run once each (the metamorphic comparison is against
  the path's own first run, which run-twice already checked).

Neither is a strategy path: no step judge of another gate sees them and the exploration (coverage) does not record
them. Both spend the run's wall budget (`--budget-s`; a spent budget ends the run with the explorer's budget timeout)
and are added to the summary's `cost`; the judge reports its own share in its `checks-examined`. Without `ui-time`
nothing here runs and the explorer is unchanged.
"""

from rigor_lib.ui_explore_judges import probe_error_judge
from rigor_lib.ui_explore_run import execute, run_twice


class Runner:
    """Runs the judge's extra paths with the explorer's configuration and counts them."""

    def __init__(self, explorer):
        self.explorer = explorer
        self.catalogue = explorer.config.catalogue
        self.cost = {"probe_runs": 0, "origin_runs": 0, "probe_commands": 0, "virtual_ms": 0}

    def _count(self, runs, name):
        self.cost[name] += 1
        for run in runs:
            self.cost["probe_commands"] += run.commands
            self.cost["virtual_ms"] += run.virtual_ms
            self.explorer.commands += run.commands
            self.explorer.virtual_ms += run.virtual_ms

    def probe(self, words):
        """A probing path, run twice; the steps of its first run."""
        first, second = run_twice(self.explorer.config, words, False, None)
        self._count((first, second), "probe_runs")
        for judge in self.explorer.run_judges:
            self.explorer.findings.extend(judge(first, second, self.explorer.contract))
        return first.steps

    def once(self, words):
        """A clock-origin replay, run once; its steps. A run that ended in a probe error is reported as such."""
        run = execute(self.explorer.config, words, False, None)
        self._count((run,), "origin_runs")
        self.explorer.findings.extend(probe_error_judge(self.catalogue.key)(run, run, None)[:1])
        return run.steps


def attach(explorer, judges):
    """Hands every path the explorer runs to the ui-time judge; nothing when it is not selected. Returns `explorer`."""
    if judges is None or judges.time is None:
        return explorer
    runner, plain = Runner(explorer), explorer.run

    def run(words, settle=True, explore=True):
        steps = plain(words, settle, explore)
        explorer.findings.extend(judges.time.path(runner, steps))
        return steps
    explorer.run = run
    return explorer
