"""The ui-time judge's probing (U09 fix-up 1): appearances bisected inside a time step, elements shown only inside a
step, undecided lifetimes reported (never silent, never counted), diverging probe runs, the probe cap, a screen under
a message, the clock-origin comparison of time and deadlines, dwell without a tick. Over the timed product simulated
in Python (test_ui_judge_time_helpers); no wall time."""

import unittest
from types import SimpleNamespace

from rigor_lib import ui_contract, ui_judge_time
from rigor_lib.ui_explore_grammar import parse_identity, parse_record
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet
from rigor_lib.ui_judge_time_model import Binding, Facts, appearances, timeline
from rigor_lib.ui_judge_time_origin import divergence

from tests.test_ui_judge_helpers import KEY, TODAY
from tests.test_ui_judge_time_helpers import Catalogue, Runner, Sim, contract

OPEN = "open 1000000000 7"


def judge_run(sim, paths, the_contract=None, max_wait_ms=600000):
    judges = JudgeSet(["ui-time"], the_contract or contract(), KEY, TODAY)
    judges.wants_identity(("frame-facts", "identity"))
    runner, found = Runner(sim, max_wait_ms), []
    for words in paths:
        found += judges.time.path(runner, sim.run(words))
    return found + judges.finish(paths[0][0]), runner


def checks_of(found, severity="error"):
    return sorted(f["check"] for f in found if f["severity"] == severity)


def examined(found):
    return [f for f in found if f["check"] == "checks-examined"][0]["observed"]


class AppearanceTest(unittest.TestCase):
    def test_an_appearance_inside_a_time_step_is_bisected_to_decide(self):
        found, _runner = judge_run(Sim(), [[OPEN, "later", "at 5000"]])
        row = examined(found)["lifetimes"][0]
        lo, hi = row["appeared"]
        self.assertTrue(lo <= OPEN_MS + 2000 <= hi and hi - lo <= 250, row["appeared"])     # one tick at most
        self.assertEqual(row["decided"], {"notice-lifetime-long": False, "notice-lifetime-short": False})
        self.assertNotIn("lifetime-undecided", checks_of(found))

    def test_a_one_second_notice_inside_a_five_second_step_is_short(self):
        found, _runner = judge_run(Sim(life=1000, count=lambda e, life: 4), [[OPEN, "later", "at 5000"]])
        short = [f for f in found if f["check"] == "notice-lifetime-short"]
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0]["path"], [OPEN, "later", "at 5000"])
        self.assertLess(short[0]["observed"]["shown_at_most_ms"], 4000 - 250)
        self.assertGreaterEqual(short[0]["observed"]["shown_at_most_ms"], 1000)

    def test_undecided_is_a_finding_and_not_examined(self):
        found, _runner = judge_run(Sim(), [[OPEN, "show"]], max_wait_ms=50)       # 85 `at` words: not run
        undecided = sorted(f["observed"]["check"] for f in found if f["check"] == "lifetime-undecided")
        self.assertEqual(undecided, ["notice-lifetime-long", "notice-lifetime-short"])
        self.assertEqual({f["observed"]["why"] for f in found if f["check"] == "lifetime-undecided"}, {"at-word-cap"})
        totals = examined(found)["totals"]
        self.assertEqual((totals["notice-lifetime-short"], totals["notice-lifetime-long"]), (0, 0))

    def test_a_diverging_probe_run_is_a_finding(self):
        found, _runner = judge_run(Sim(diverge=True), [[OPEN, "show"]])
        diverged = [f for f in found if f["check"] == "probe-diverged"]
        self.assertEqual(len(diverged), 1)
        self.assertEqual(diverged[0]["observed"]["path"], [OPEN, "show"])
        self.assertEqual(diverged[0]["observed"]["probe_path"][:2], [OPEN, "show"])

    def test_the_probe_cap_is_reported(self):
        saved = ui_judge_time.MAX_PROBES
        ui_judge_time.MAX_PROBES = 1
        try:
            found, _runner = judge_run(Sim(), [[OPEN, "show"], [OPEN, "other"]])
        finally:
            ui_judge_time.MAX_PROBES = saved
        capped = [f for f in found if f["check"] == "time-probes-capped"]
        self.assertEqual((len(capped), capped[0]["severity"], capped[0]["observed"]["capped"]), (1, "info", 1))
        self.assertEqual(len(examined(found)["lifetimes"]), 1)

    def test_dwell_is_judged_when_only_the_tick_is_pending(self):
        text = "A long notice that nobody can read in four seconds, not even a fast reader, surely not."
        real = contract()

        class NoTick:
            tables = real.tables

            def __getattr__(self, name):
                return getattr(real, name)

            def get(self, section, key):
                if (section, key) == ("clock", "tick_ms"):
                    raise ui_contract.ContractPending("clock.tick_ms", "0")
                return real.get(section, key)
        found, _runner = judge_run(Sim(text=text), [[OPEN, "show"]], NoTick())
        self.assertEqual(len([f for f in found if f["check"] == "dwell-below-reading-time"]), 1)


OPEN_MS = 1000000000


def step(index, word, now, cls, nodes):
    s = Step(index, word, origin=0, now=now)
    s.obs = {"semantic": tuple(parse_record("semantic", "\t".join([k, role, label, "0", "0", "1", "1", "1", "-", "-",
                                                                    "1", "-", "-", "-"])) for k, role, label in nodes),
             "frame": (), "patches": (), "trace": (), "due": None, "env": (),
             "identity": parse_identity(["state\t" + cls])}
    s.key, s.proj = "%s-%s" % (cls, "/".join(label for _k, _r, label in nodes)), {}
    return s


class PatchChainTest(unittest.TestCase):
    def test_patches_that_contradict_the_records_are_a_finding_and_judge_nothing(self):
        found, _runner = judge_run(Sim(lie=True), [[OPEN, "show", "at 500"]])
        lies = [f for f in found if f["check"] == "patches-inconsistent"]
        self.assertEqual(len(lies), 1)
        self.assertEqual(lies[0]["path"], [OPEN, "show", "at 500"])
        self.assertIn("did not show", lies[0]["observed"]["why"])


class ScreenUnderMessageTest(unittest.TestCase):
    def test_a_screen_continues_under_a_message(self):
        rows = [{"kind": "choose_size", "class": "screen", "lifetime_ms": 30000, "countdown_shown": True},
                {"kind": "dialog", "class": "message", "lifetime_ms": 8000, "countdown_shown": True}]
        binding = Binding(SimpleNamespace(rows=lambda name: rows), True)
        screen = [("3", "text", "Choose"), ("6", "countdown", "30 s")]
        steps = [step(0, "open", 0, "welcome", [("3", "text", "Hi")]),
                 step(1, "show", 0, "choose_size", screen),
                 step(2, "oops", 0, "dialog", screen + [("321", "dialog", ""), ("326", "countdown", "8 s")]),
                 step(3, "at 2000", 2000, "dialog", screen[:1] + [("6", "countdown", "28 s"), ("321", "dialog", ""),
                                                                    ("326", "countdown", "6 s")]),
                 step(4, "dismiss", 2000, "choose_size", screen[:1] + [("6", "countdown", "28 s")])]
        facts = timeline(steps, Catalogue(), binding)
        self.assertEqual(appearances(facts), [(1, "choose_size"), (2, "dialog")])
        self.assertEqual(facts[3].countdowns["choose_size"], (("6", 28),))       # the screen's own countdown


class RunnerTest(unittest.TestCase):
    def test_probing_runs_use_a_non_judging_scene(self):
        """U05e: the extra runs of ui-time judge no layer and start no sibling replay (as the sibling runs do)."""
        from pathlib import Path
        from rigor_lib import ui_explore_catalogue
        from rigor_lib.ui_explore_run import Config
        from rigor_lib.ui_explore_scene import Scene
        from rigor_lib.ui_explore_time import Runner as ExplorerRunner
        data = Path(__file__).resolve().parent / "data" / "ui_explore" / "scene.events.toml"
        catalogue = ui_explore_catalogue.load(str(data))
        scene = Scene(catalogue, None)
        config = Config(probe="p", deadline_s=1.0, catalogue=catalogue, budget=None, scene=scene)
        runner = ExplorerRunner(SimpleNamespace(config=config, contract=None))
        self.assertTrue(scene.judging)
        self.assertFalse(runner.config.scene.judging)
        self.assertIsNot(runner.config.scene, scene)


class OriginCompareTest(unittest.TestCase):
    def test_time_and_deadline_relative_to_the_origin(self):
        def fact(now, origin, due):
            return Facts(0, "w", "time", now, now, origin, "k", {}, due=due)
        self.assertIsNone(divergence([fact(1500, 1000, 250)], [fact(10**9 + 500, 10**9, 250)]))
        self.assertEqual(divergence([fact(1500, 1000, 250)], [fact(10**9 + 600, 10**9, 250)]), (0, "time"))
        self.assertEqual(divergence([fact(1500, 1000, 250)], [fact(10**9 + 500, 10**9, 251)]), (0, "due"))


if __name__ == "__main__":
    unittest.main()
