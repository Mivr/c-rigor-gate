"""The ui-time judge, U09 fix-up 2: an element is an instance (a replacement is a new appearance, a countdown's ticking
is not), what is shown only inside a step is sampled until every created-and-removed key was seen, the carry rule
checks roles and labels, diverging and non-monotone probes are `probe-diverged`, increases between step-end values,
and the origin fill runs inside the explorer's budget. Over a scripted product simulated in Python; no wall time."""

import unittest
from types import SimpleNamespace

from rigor_lib.ui_explore_grammar import parse_record
from rigor_lib.ui_explore_probe import BudgetSpent
from rigor_lib.ui_explore_time import end
from rigor_lib.ui_judge_findings import JudgeSet
from rigor_lib.ui_judge_time_checks import absent_verdicts, increase_verdicts
from rigor_lib.ui_judge_time_model import Binding, appearances, timeline

from tests.test_ui_judge_helpers import KEY, TODAY
from tests.test_ui_judge_time_helpers import Catalogue, Runner, Sim, contract
from tests.test_ui_judge_time_probe import step as made_step

OPEN = "open 1000000000 7"
T0 = 1000000000


class ScriptSim(Sim):
    """`go` starts a script of elements (key, role, text, start ms, end ms or None, countdown) relative to its instant;
    the class is the role of the last message shown, else `main`."""

    def __init__(self, script, flip=False, flip_after=2, **kw):
        Sim.__init__(self, **kw)
        self.script, self.flip, self.flip_after = script, flip, flip_after

    def _input(self, word, now, st):
        if word == "go":
            st["go"] = now
        return []

    def scene(self, t, st):
        nodes, cls = {"1": ("text", "Title")}, "main"
        go = st.get("go")
        flip = self.flip and len(self.runs) > self.flip_after       # a product that differs on later runs
        for key, role, text, start, stop, counts in self.script if go is not None else ():
            if go + start <= t and (stop is None or t < go + stop) and not flip:
                nodes[key] = (role, "")
                nodes[key + "t"] = ("text", text)
                if counts:
                    nodes[key + "c"] = ("countdown", "%d s" % -(-(go + start + 4000 - t) // 1000))
                cls = role
        return nodes, cls


def judge_run(sim, paths):
    judges = JudgeSet(["ui-time"], contract(), KEY, TODAY)
    judges.wants_identity(("frame-facts", "identity"))
    runner, found = Runner(sim), []
    for words in paths:
        found += judges.time.path(runner, sim.run(words))
    found += judges.time.fill()
    return found + judges.finish(paths[0][0]), runner, judges


def errors(found):
    return sorted(f["check"] for f in found if f["severity"] == "error")


def examined(found):
    return [f for f in found if f["check"] == "checks-examined"][0]["observed"]


class InstanceTest(unittest.TestCase):
    def test_a_replacement_across_steps_is_a_new_appearance(self):
        sim = ScriptSim([("50", "banner", "Not saved", 0, 200, False), ("60", "banner", "Saved", 200, None, False)])
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 100", "at 5000"]])
        rows = sorted((r["appeared"][1] - T0, r["shown_at_most_ms"]) for r in examined(found)["lifetimes"])
        self.assertEqual(rows[0][0], 0)                            # A: from the input
        self.assertTrue(200 <= rows[0][1] <= 250, rows)            # gone at 200, within a tick
        self.assertEqual(rows[1][0], 200)                          # B: from 200, not from A's appearance
        self.assertEqual(errors(found).count("notice-lifetime-short"), 1)

    def test_a_replacement_inside_a_step(self):
        sim = ScriptSim([("50", "banner", "Not saved", 100, 300, False), ("60", "banner", "Saved", 300, None, False)])
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 1100"]])
        short = [f for f in found if f["check"] == "notice-lifetime-short"]
        self.assertEqual(len(short), 1)                            # A, seen only inside the step
        self.assertEqual(short[0]["observed"]["element"], "banner#0")
        later = [r for r in examined(found)["lifetimes"] if r["path"] == [OPEN, "go", "at 1100"]]
        self.assertTrue(any(abs(r["appeared"][1] - (T0 + 300)) <= 70 for r in later), later)   # B from about 300

    def test_a_banner_covered_by_another_banner_lives_on(self):
        # the kiosk at boot: a second banner stacked over the first, whose nodes do not change
        sim = ScriptSim([("50", "banner", "Codes offline", 0, None, False), ("60", "banner", "Self-test", 300, None,
                                                                             False)])
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 1100"]])
        rows = sorted((r["appeared"][1] - T0, r["shown_at_most_ms"]) for r in examined(found)["lifetimes"])
        self.assertEqual([at_most for _at, at_most in rows], [None, None])     # both still shown at the last sample
        self.assertEqual(rows[0][0], 0)
        self.assertNotIn("notice-lifetime-short", errors(found))

    def test_a_ticking_countdown_is_one_instance(self):
        found, _runner, _j = judge_run(Sim(), [[OPEN, "show", "at 1500", "at 2500"]])
        self.assertEqual(len(examined(found)["lifetimes"]), 1)
        self.assertEqual(errors(found), [])


class InsideTest(unittest.TestCase):
    def test_a_50_ms_banner_inside_an_1100_ms_step(self):
        sim = ScriptSim([("50", "banner", "Not saved", 400, 450, False)])
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 1100"]])
        short = [f for f in found if f["check"] == "notice-lifetime-short"]
        flash = [f for f in found if f["check"] == "flash"]
        self.assertEqual((len(short), len(flash)), (1, 1))
        self.assertLessEqual(short[0]["observed"]["shown_at_most_ms"], 200)

    def test_a_key_never_sampled_is_undecided(self):
        sim = ScriptSim([("50", "banner", "Blip", 333, 334, False)])     # one ms inside a 100 000 ms step
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 100000"]])
        unsampled = [f for f in found if f["check"] == "lifetime-undecided" and f["observed"].get("why")
                     == "hidden-unsampled"]
        self.assertEqual(sorted(f["observed"]["key"] for f in unsampled), ["50", "50t"])
        self.assertEqual(examined(found)["totals"]["flash"], 0)

    def test_a_diverging_inside_run(self):
        # 500 ms: flash is undecided after the first samples, so a second run comes, and re-sees an instant
        sim = ScriptSim([("50", "banner", "Not saved", 400, 900, False)], flip=True)
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 1100"]])
        self.assertIn("probe-diverged", errors(found))

    def test_an_appearance_the_probing_run_does_not_reproduce(self):
        sim = ScriptSim([("50", "banner", "Saved", 400, None, False)], flip=True, flip_after=1)
        found, _runner, _j = judge_run(sim, [[OPEN, "go", "at 1100"]])
        diverged = [f for f in found if f["check"] == "probe-diverged"]
        self.assertEqual(len(diverged), 1)
        self.assertEqual(examined(found)["totals"]["notice-lifetime-short"], 0)     # no lifetime decided from it

    def test_hidden_steps_count_against_the_probe_cap(self):
        import rigor_lib.ui_judge_time as judge_mod
        saved, judge_mod.MAX_PROBES = judge_mod.MAX_PROBES, 0
        try:
            found, _runner, _j = judge_run(ScriptSim([("50", "banner", "x", 400, 450, False)]), [[OPEN, "go", "at 1100"]])
        finally:
            judge_mod.MAX_PROBES = saved
        capped = [f for f in found if f["check"] == "time-probes-capped"]
        self.assertEqual(capped[0]["observed"]["first"][1], "inside at 1100")


class CarryTest(unittest.TestCase):
    def test_no_carry_to_a_successor_screen_with_a_superset_of_keys(self):
        rows = [{"kind": "choose_size", "class": "screen", "lifetime_ms": 30000, "countdown_shown": False},
                {"kind": "banner", "class": "message", "lifetime_ms": 0, "countdown_shown": False}]
        binding = Binding(SimpleNamespace(rows=lambda name: rows), True)
        choose = [("3", "text", "Choose a size")]
        welcome = [("3", "text", "Welcome"), ("14", "panel", ""), ("297", "banner", "")]
        steps = [made_step(0, "show", 0, "choose_size", choose),
                 made_step(1, "at 30000", 30000, "banner", welcome)]
        facts = timeline(steps, Catalogue(), binding)
        self.assertEqual(sorted(facts[1].present), ["banner"])      # key 3 is reused, its label is not


class CountdownNodeTest(unittest.TestCase):
    def test_a_removed_countdown_leaves_the_screen_shown_and_is_absent(self):
        # the kiosk after a size choice: Choose size stays, only its countdown node is removed
        rows = [{"kind": "choose_size", "class": "screen", "lifetime_ms": 30000, "countdown_shown": True}]
        binding = Binding(SimpleNamespace(rows=lambda name: rows), True)
        screen = [("3", "text", "Choose a size"), ("48", "button", "Small")]
        steps = [made_step(0, "pick", 0, "choose_size", screen + [("6", "countdown", "30 s")]),
                 made_step(1, "small", 0, "choose_size", screen)]
        steps[1].obs["patches"] = (parse_record("patches", "remove\t6\tnode\tcountdown\t-"),)
        facts = timeline(steps, Catalogue(), binding)
        self.assertEqual(appearances(facts), [(0, "choose_size")])
        found, judged = absent_verdicts(facts, {"choose_size": rows[0]})
        self.assertEqual(([v["observed"]["step"] for v in found], judged), ([1], 2))


class MoreTest(unittest.TestCase):
    def test_increase_by_a_node_made_again(self):
        rows = [{"kind": "dialog", "class": "message", "lifetime_ms": 8000, "countdown_shown": True}]
        binding = Binding(SimpleNamespace(rows=lambda name: rows), True)
        nodes = [("321", "dialog", ""), ("322", "text", "No")]
        steps = [made_step(0, "go", 0, "dialog", nodes + [("326", "countdown", "3 s")]),
                 made_step(1, "at 900", 900, "dialog", nodes + [("326", "countdown", "5 s")])]
        steps[1].obs["patches"] = tuple(parse_record("patches", line) for line in (   # the node made again
            "remove\t326\tnode\tcountdown\t-", "create\t326\tnode\t-\tcountdown"))
        facts = timeline(steps, Catalogue(), binding)
        found, judged = increase_verdicts(facts)
        self.assertEqual(([v["observed"]["values"] for v in found], judged), ([[3, 5]], 1))

    def test_a_cut_during_the_origin_fill_is_a_cut_run(self):
        judge = SimpleNamespace(runner=object(), fill=lambda: (_ for _ in ()).throw(BudgetSpent()))
        with self.assertRaises(BudgetSpent):
            end(SimpleNamespace(time_judge=judge), {}, [])
        self.assertEqual(end(SimpleNamespace(time_judge=judge), {"budget_cut": True}, ["x"]), ({"budget_cut": True},
                                                                                           ["x"]))
        self.assertEqual(end(SimpleNamespace(), {}, ["x"]), ({}, ["x"]))


if __name__ == "__main__":
    unittest.main()
