"""The ui-time judge (U09, P004 3.5) on recorded timelines: the rules on hand-built Facts, and the judge with its
time-probing mode and clock-origin replays over a timed product simulated in Python (test_ui_judge_time_helpers).
No test reads the wall clock or sleeps."""

import hashlib
import json
import unittest
from types import SimpleNamespace

from rigor_lib import ui_judge_time_checks as checks
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet
from rigor_lib.ui_judge_time_model import Binding, Facts

from tests.test_ui_judge_helpers import KEY, TODAY, pending
from tests.test_ui_judge_time_helpers import Runner, Sim, contract

OPEN = "open 1000000000 7"
TIMER = {"kind": "dialog", "class": "message", "lifetime_ms": 4000, "countdown_shown": True}


def fact(now, prev=None, mode="time", present=("dialog",), countdown=None, patches=(), cls=None, index=0,
         semantic=("s",), frame=("f",)):
    out = Facts(index, "w", mode, now, now if prev is None else prev, 0, "k%d" % index, {}, cls=cls,
                present=frozenset(present), semantic=semantic, frame=frame, patches=tuple(patches))
    if countdown is not None:
        out.countdowns["dialog"] = (("7", countdown),)
    return out


def update(old, new, key="7"):
    return ("update", key, "text", b"%d s" % old, b"%d s" % new)


def judge_run(sim, paths, the_contract=None, identity=True, gates=("ui-time",)):
    """The findings of the judge set over `paths` (each the steps of a first run), then its end of the run."""
    judges = JudgeSet(list(gates), the_contract or contract(), KEY, TODAY)
    judges.wants_identity(("frame-facts", "identity") if identity else ("frame-facts",))
    runner, found = Runner(sim), []
    for words in paths:
        found += judges.time.path(runner, sim.run(words))
    return found + judges.finish(paths[0][0]), runner


def by_check(found, check):
    return [f for f in found if f["check"] == check]


def errors(found):
    return sorted(f["check"] for f in found if f["severity"] == "error")


class RulesTest(unittest.TestCase):
    def test_plan_brackets_the_two_deciding_instants(self):
        appear = fact(10000, mode="input")
        instants = checks.plan(appear, 4000, 4000, 250, 600000)
        self.assertIn(10000 + 4000 - 250 - 1, instants)          # the last instant a short element is gone by
        self.assertIn(10000 + 4000 + 250, instants)              # the first instant a long one is still shown at
        self.assertEqual(max(instants), 14250)
        self.assertLessEqual(len(instants), checks.GRID + 2)
        self.assertEqual(checks.plan(appear, 0, None, 250, 600000), [])

    def test_plan_never_jumps_more_than_max_wait(self):
        instants = checks.plan(fact(0, mode="input"), 300000, None, 250, 1000)
        gaps = [b - a for a, b in zip([0] + instants, instants)]
        self.assertLessEqual(max(gaps), 1000)

    def test_refine_stops_within_one_tick(self):
        self.assertEqual(checks.refine(3749, 3999, 250, 600000), [])
        self.assertEqual(checks.refine(3749, 4000, 250, 600000), [3999])
        many = checks.refine(0, 300000, 250, 600000)
        self.assertLessEqual(len(many), checks.GRID)

    def test_bracket(self):
        appear = fact(0, mode="input")
        samples = [fact(500), fact(1000, present=()), fact(750)]
        self.assertEqual(checks.bracket(appear, samples, "dialog"), (750, 1000))
        self.assertEqual(checks.bracket(appear, [fact(500)], "dialog"), (500, None))

    def test_short_boundary(self):
        appear = fact(0, mode="input")
        _m, ok = checks.lifetime_verdicts("dialog", appear, (3700, 3750), TIMER, 4000, None, 250)
        _m, short = checks.lifetime_verdicts("dialog", appear, (3700, 3749), TIMER, 4000, None, 250)
        self.assertEqual([v["check"] for v in ok], [])
        self.assertEqual([v["check"] for v in short], ["notice-lifetime-short"])

    def test_short_uses_the_earliest_appearance_of_a_time_step(self):
        appear = fact(1000, prev=0)                          # appeared somewhere in (0, 1000]
        _m, found = checks.lifetime_verdicts("dialog", appear, (4000, 4600), TIMER, 4000, None, 250)
        self.assertEqual(found, [])                          # at most 4599 ms: not certainly under 3750

    def test_long_boundary(self):
        appear = fact(0, mode="input")
        _m, ok = checks.lifetime_verdicts("dialog", appear, (4249, None), TIMER, 4000, None, 250)
        _m, long_ = checks.lifetime_verdicts("dialog", appear, (4250, None), TIMER, 4000, None, 250)
        self.assertEqual(ok, [])
        self.assertEqual([v["check"] for v in long_], ["notice-lifetime-long"])

    def test_floor_approximation_only_without_dwell(self):
        appear = fact(0, mode="input")
        _m, found = checks.lifetime_verdicts("dialog", appear, (500, 1000), TIMER, None, 4000, 250)
        self.assertEqual([v["check"] for v in found], ["notice-lifetime-short-floor"])

    def test_flash_within_one_input_step(self):
        steps = [fact(0, mode="open", present=()),
                 fact(0, mode="input", present=(), patches=[("create", "9", "node", b"-", b"panel"),
                                                            ("remove", "9", "node", b"panel", b"-")])]
        found, judged = checks.flash_verdicts(steps, 500)
        self.assertEqual((judged, [v["identity"] for v in found]), (1, [["9", "panel"]]))

    def test_flash_needs_no_input_between_and_ignores_countdowns(self):
        create = ("create", "9", "node", b"-", b"panel")
        remove = ("remove", "9", "node", b"panel", b"-")
        quick = [fact(0, mode="input", present=(), patches=[create]), fact(300, prev=0, present=(), patches=[remove])]
        self.assertEqual(len(checks.flash_verdicts(quick, 500)[0]), 1)
        slow = [fact(0, mode="input", present=(), patches=[create]), fact(500, prev=0, present=(), patches=[remove])]
        self.assertEqual(checks.flash_verdicts(slow, 500)[0], [])
        tapped = [fact(0, mode="input", present=(), patches=[create]),
                  fact(0, mode="input", present=(), patches=[remove])]
        self.assertEqual(checks.flash_verdicts(tapped, 500)[0], [])
        countdown = [fact(0, mode="input", present=(), patches=[("create", "7", "node", b"-", b"countdown"),
                                                                ("remove", "7", "node", b"countdown", b"-")])]
        self.assertEqual(checks.flash_verdicts(countdown, 500)[0], [])

    def test_countdown_clean(self):
        seq = [fact(0, mode="input", countdown=4)] + [fact(t, prev=t - 500, countdown=4 - t // 1000,
                                                           patches=[update(5 - t // 1000, 4 - t // 1000)]
                                                           if t % 1000 == 0 else [])
                                                      for t in range(500, 4000, 500)]
        self.assertEqual(checks.countdown_verdicts("dialog", seq, TIMER), [])

    def test_countdown_parts(self):
        start = [fact(0, mode="input", countdown=9)]
        zero = [fact(0, mode="input", countdown=4), fact(900, prev=0, countdown=0, patches=[update(4, 0)])]
        up = [fact(0, mode="input", countdown=3), fact(900, prev=0, countdown=4, patches=[update(3, 4)])]
        stalled = [fact(0, mode="input", countdown=4), fact(500, prev=0, countdown=4),
                   fact(1000, prev=500, countdown=4)]
        jump = [fact(0, mode="input", countdown=4), fact(2000, prev=0, countdown=3, patches=[update(4, 3)])]
        absent = [fact(0, mode="input")]
        for seq, part in ((start, "start"), (zero, "zero"), (up, "increase"), (stalled, "stalled"),
                          (jump, "stalled"), (absent, "absent")):
            self.assertEqual([v["identity"][1] for v in checks.countdown_verdicts("dialog", seq, TIMER)], [part])

    def test_start_of_an_element_that_appeared_inside_a_time_step(self):
        inside = [fact(7000, prev=5000, countdown=6)]          # appeared in (5000, 7000]: up to 1999 ms counted
        self.assertEqual(checks.countdown_verdicts("dialog", inside, dict(TIMER, lifetime_ms=8000)), [])
        late = [fact(7000, prev=5000, countdown=4)]
        self.assertEqual([v["observed"]["wanted"] for v in checks.countdown_verdicts(
            "dialog", late, dict(TIMER, lifetime_ms=8000))], [[7, 8]])   # 6 (= 7 - 1) is still accepted

    def test_increase_of_a_declared_restart_or_an_input_is_not_judged(self):
        restart = fact(900, prev=0, countdown=4, patches=[update(3, 4)])
        restart.restarts = frozenset(("7",))
        self.assertEqual(checks.countdown_verdicts("dialog", [fact(0, mode="input", countdown=3), restart], TIMER), [])
        tap = fact(0, mode="input", countdown=4, patches=[update(3, 4)])
        self.assertEqual(checks.countdown_verdicts("dialog", [fact(0, mode="input", countdown=3), tap], TIMER), [])

    def test_invisible_auto_transition(self):
        same = [fact(0, mode="input", cls="main"), fact(1000, prev=0, cls="detail")]
        seen = [fact(0, mode="input", cls="main"), fact(1000, prev=0, cls="detail", semantic=("other",))]
        tapped = [fact(0, mode="input", cls="main"), fact(0, mode="input", cls="detail")]
        self.assertEqual([v["identity"] for v in checks.invisible_verdicts(same)[0]], [["main", "detail"]])
        self.assertEqual(checks.invisible_verdicts(seen)[0], [])
        self.assertEqual(checks.invisible_verdicts(tapped), ([], 0))

    def test_binding_without_identity(self):
        rows = [dict(TIMER), dict(TIMER, kind="report", **{"class": "screen"})]
        fake = SimpleNamespace(rows=lambda name: rows)
        self.assertEqual((Binding(fake, False).bound(), Binding(fake, False).blocked()), (("dialog",), ("report",)))
        self.assertEqual(Binding(fake, True).bound(), ("dialog", "report"))


def expected_id(check, identity, state_key=None):
    """The id from docs/ui-judges-time.md, recomputed with hashlib and json only."""
    data = [identity, state_key] if state_key is not None else identity
    text = json.dumps(["ui-time", check, data], sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    return "ui-time.%s/%s" % (check, hashlib.sha256(text.encode("ascii")).hexdigest()[:12])


class JudgeTest(unittest.TestCase):
    def test_clean_dialog_gives_only_the_examined_line(self):
        found, runner = judge_run(Sim(), [[OPEN, "show"]])
        self.assertEqual(errors(found), [])
        examined = by_check(found, "checks-examined")[0]["observed"]
        row = examined["lifetimes"][0]
        self.assertEqual((row["kind"], row["shown_more_than_ms"], row["shown_at_most_ms"]), ("dialog", 3999, 4000))
        self.assertEqual(row["phases"], 2)
        self.assertEqual(examined["totals"]["clock-origin-divergence"], 4)
        self.assertEqual(runner.cost, {"probe_runs": 2, "origin_runs": 4, "probe_commands": 0, "virtual_ms": 0})

    def test_each_defect_gives_its_finding(self):
        cases = [
            (Sim(life=1000, count=lambda e, life: -(-(4000 - e) // 1000)), "notice-lifetime-short"),
            # it stalls too, and nothing is ever removed, so flash has no verdict
            (Sim(life=None, count=lambda e, life: 4), "notice-lifetime-long", "countdown-wrong", "check-vacuous"),
            (Sim(count=lambda e, life: 2 * -(-(life - e) // 2000)), "countdown-wrong"),
            (Sim(count=lambda e, life: -(-(life - e) // 1000) - 1), "countdown-wrong"),
            (Sim(count=lambda e, life: -(-(life - e) // 1000) + 5), "countdown-wrong"),
            (Sim(wrap32=True), "clock-origin-divergence"),
        ]
        for sim, *wanted in cases:
            found, _runner = judge_run(sim, [[OPEN, "show"]])
            self.assertEqual(set(errors(found)), set(wanted), wanted)

    def test_countdown_parts_end_to_end(self):
        parts = {}
        for name, count in (("stalled", lambda e, life: 2 * -(-(life - e) // 2000)),
                            ("zero", lambda e, life: -(-(life - e) // 1000) - 1),
                            ("start", lambda e, life: -(-(life - e) // 1000) + 5)):
            found, _runner = judge_run(Sim(count=count), [[OPEN, "show"]])
            parts[name] = [f["observed"]["part"] for f in by_check(found, "countdown-wrong")]
        self.assertEqual(parts, {"stalled": ["stalled"], "zero": ["zero"], "start": ["start"]})

    def test_flash_silent_transition_and_their_paths(self):
        found, _runner = judge_run(Sim(), [[OPEN, "flash"], [OPEN, "blink", "at 300"], [OPEN, "silent", "fire-due"]])
        self.assertEqual([c for c in errors(found) if c != "check-vacuous"], ["flash", "flash",
                                                                            "invisible-auto-transition"])
        silent = by_check(found, "invisible-auto-transition")[0]
        self.assertEqual(silent["path"], [OPEN, "silent", "fire-due"])
        self.assertEqual(silent["observed"]["from"], "main")
        slow, _runner = judge_run(Sim(), [[OPEN, "blink", "at 600"], [OPEN, "show"]])
        self.assertEqual(by_check(slow, "flash"), [])

    def test_ids_are_keyed_by_the_state_of_the_first_appearance(self):
        sim = Sim(life=1000)
        found, _runner = judge_run(sim, [[OPEN, "show"]])
        short = by_check(found, "notice-lifetime-short")[0]
        appear = sim.run([OPEN, "show"])[1]
        self.assertEqual(short["id"], expected_id("notice-lifetime-short", ["dialog"], appear.key))
        self.assertEqual(short["path"], [OPEN, "show"])
        self.assertEqual(short["state"]["key"], appear.key)

    def test_replaying_a_finding_path_gives_the_same_id(self):
        for sim in (Sim(life=1000), Sim(wrap32=True), Sim(life=None)):
            found, _runner = judge_run(sim, [[OPEN, "show"]])
            again, _runner = judge_run(sim, [f["path"] for f in found if f["severity"] == "error"])
            self.assertEqual({f["id"] for f in found if f["severity"] == "error"},
                             {f["id"] for f in again if f["severity"] == "error"})

    def test_one_probe_per_state_and_kind(self):
        sim = Sim()
        _found, runner = judge_run(sim, [[OPEN, "show"], [OPEN, "show"], [OPEN, "show", "at 100000"]])
        self.assertEqual(runner.cost["probe_runs"], 2)
        self.assertEqual(runner.cost["origin_runs"], 8)        # two distinct paths show the dialog

    def test_without_identity_screen_timers_are_blocked(self):
        edit = lambda text: text.replace('kind = "banner"\nclass = "message"', 'kind = "banner"\nclass = "screen"')
        found, _runner = judge_run(Sim(identity=False), [[OPEN, "show"]], contract(edit), identity=False)
        blocked = sorted(tuple(f["observed"].get(k) for k in ("check", "kind")) for f in by_check(found, "check-blocked"))
        self.assertEqual(blocked, [("invisible-auto-transition", None), ("notice-lifetime-short", "banner")])
        self.assertEqual(set(errors(found)), {"check-blocked"})     # invisible: blocked, so not vacuous
        self.assertEqual(by_check(found, "checks-examined")[0]["observed"]["lifetimes"][0]["kind"], "dialog")

    def test_pending_rate_gives_contract_pending_and_the_floor_check(self):
        edit = lambda text: pending(text, "rate_wpm", 'rate_wpm = { pending = "11", provenance = "spec:P004#11-q11" }')
        found, _runner = judge_run(Sim(life=1000), [[OPEN, "show"]], contract(edit))
        self.assertEqual(sorted({f["observed"]["check"] for f in by_check(found, "contract-pending")}),
                         ["dwell-below-reading-time", "notice-lifetime-short"])
        self.assertEqual(len(by_check(found, "notice-lifetime-short-floor")), 1)
        self.assertEqual(by_check(found, "notice-lifetime-short"), [])

    def test_dwell_below_reading_time_from_the_text_seen(self):
        sim = Sim(text="A long notice that nobody can read in four seconds, not even a fast reader, surely not.")
        found, _runner = judge_run(sim, [[OPEN, "show"]])
        dwell = by_check(found, "dwell-below-reading-time")
        self.assertEqual(len(dwell), 1)
        self.assertGreater(dwell[0]["observed"]["min_dwell_ms"], 4000)
        self.assertIn("notice-lifetime-short", errors(found))    # D is now the reading time: 4 s is short of it

    def test_vacuous_when_nothing_timed_appears(self):
        found, _runner = judge_run(Sim(), [[OPEN]])
        vacuous = sorted(f["observed"]["check"] for f in by_check(found, "check-vacuous"))
        self.assertEqual(vacuous, ["clock-origin-divergence", "countdown-wrong", "dwell-below-reading-time", "flash",
                                   "invisible-auto-transition", "notice-lifetime-long", "notice-lifetime-short"])


class JudgeSetTest(unittest.TestCase):
    def test_ui_time_alone_judges_no_step(self):
        judges = JudgeSet(["ui-time"], contract(), KEY, TODAY)
        self.assertEqual(judges.gates, ())
        self.assertEqual(judges.step_judge(Step(1, "show"), PathSoFar([Step(0, OPEN)], 1), None), [])

    def test_identity_is_read_for_ui_time_only_when_announced(self):
        judges = JudgeSet(["ui-time"], contract(), KEY, TODAY)
        self.assertTrue(judges.wants_identity(("frame-facts", "identity")))
        self.assertIsNone(judges.identity)                       # ui-scene's own flag stays unset
        self.assertFalse(JudgeSet(["ui-time"], contract(), KEY, TODAY).wants_identity(("frame-facts",)))
        both = JudgeSet(["ui-fit", "ui-time"], contract(), KEY, TODAY)
        self.assertTrue(both.wants_identity(("frame-facts", "identity")))

    def test_unknown_judge(self):
        with self.assertRaisesRegex(InternalError, "ui-time"):
            JudgeSet(["ui-nope"], contract(), KEY, TODAY)


if __name__ == "__main__":
    unittest.main()
