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
from rigor_lib.ui_judge_time_model import Binding, Facts, chain_error, countdown_value, masked_label

from rigor_lib.ui_judge_time_probe import MAX_PHASES

from tests.test_ui_judge_helpers import KEY, TODAY, pending
from tests.test_ui_judge_time_helpers import Runner, Sim, contract

OPEN = "open 1000000000 7"
OPEN_MS = 1000000000
TIMER = {"kind": "dialog", "class": "message", "lifetime_ms": 4000, "countdown_shown": True}


def fact(now, prev=None, mode="time", present=("dialog",), countdown=None, patches=(), cls=None, index=0,
         semantic=("s",), frame=("f",)):
    out = Facts(index, "w", mode, now, now if prev is None else prev, 0, "k%d" % index, {}, cls=cls,
                present=frozenset(present), semantic=semantic, frame=frame, patches=tuple(patches))
    if countdown is not None:
        out.countdowns["dialog"] = (("7", countdown),)
    if "dialog" in out.present:            # one dialog instance throughout (instances: test_ui_judge_time_fixup2)
        out.tops["dialog"] = (0, "dialog")
        out.tracked["dialog"] = (((0, "dialog"), {}),)
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
    found += judges.time.fill()                   # the waiting origin replays (ui_explore_time.end)
    return found + judges.finish(paths[0][0]), runner


def by_check(found, check):
    return [f for f in found if f["check"] == check]


def errors(found):
    return sorted(f["check"] for f in found if f["severity"] == "error")


class RulesTest(unittest.TestCase):
    def test_plan_brackets_the_two_deciding_instants(self):
        instants = checks.plan(10000, 10000, 4000, 4000, 250, 600000)
        self.assertIn(10000 + 4000 - 250 - 1, instants)          # shown then: not short
        self.assertIn(10000 + 4000 + 250, instants)              # shown then: long
        self.assertEqual(max(instants), 14250)
        self.assertLessEqual(len(instants), checks.GRID + 2)
        self.assertEqual(checks.plan(10000, 10000, 0, None, 250, 600000), [])
        self.assertEqual(checks.plan(20000, 10000, 4000, 4000, 250, 600000), [])   # both instants behind

    def test_plan_never_jumps_more_than_max_wait(self):
        instants = checks.plan(0, 0, 300000, None, 250, 1000)
        gaps = [b - a for a, b in zip([0] + instants, instants)]
        self.assertLessEqual(max(gaps), 1000)
        self.assertGreater(len(instants), checks.MAX_AT)         # the judge does not run such a plan

    def test_refine_down_to_one_ms(self):
        self.assertEqual(checks.refine(3999, 4000, 600000), [])
        self.assertEqual(len(checks.refine(3749, 4000, 600000)), checks.GRID - 1)
        self.assertEqual(checks.refine(10, 12, 600000), [11])

    def test_rising_and_falling(self):
        points = [(500, True), (1000, False), (750, True), (1200, False)]
        self.assertEqual(checks.falling(points, 0), (750, 1000))
        self.assertEqual(checks.falling([(500, True)], 0), (500, None))
        self.assertEqual(checks.rising([(300, False), (600, True), (400, False)], 0, 1000), (400, 600))

    def test_monotone(self):
        self.assertTrue(checks.monotone([(1, False), (3, True), (2, False)], True))
        self.assertFalse(checks.monotone([(1, True), (3, True), (2, False)], True))          # shown, gone, shown
        self.assertFalse(checks.monotone([(1, True), (1, False)], False))                     # two runs disagree
        self.assertTrue(checks.monotone([(1, True), (2, False), (3, False)], False))

    def test_short_boundary(self):
        ok, _b = checks.decisions((0, 0), (3749, 3750), 4000, 4000, None, 250)
        short, _b = checks.decisions((0, 0), (3700, 3749), 4000, 4000, None, 250)
        self.assertEqual((ok["notice-lifetime-short"], short["notice-lifetime-short"]), (False, True))

    def test_a_wide_appearance_is_undecided_not_silent(self):
        found, bounds = checks.decisions((1, 1000), (4000, 4600), 4000, 4000, None, 250)
        self.assertEqual(found, {"notice-lifetime-short": None, "notice-lifetime-long": None})
        self.assertEqual(bounds, (3000, 4599))
        found, _b = checks.decisions((999, 1000), (4800, 4900), 4000, 4000, None, 250)
        self.assertEqual(found["notice-lifetime-short"], False)

    def test_long_boundary(self):
        ok, _b = checks.decisions((0, 0), (4249, 4250), 4000, None, None, 250)
        long_, _b = checks.decisions((0, 0), (4250, None), 4000, None, None, 250)
        self.assertEqual((ok["notice-lifetime-long"], long_["notice-lifetime-long"]), (False, True))

    def test_floor_approximation_only_without_dwell(self):
        found, _b = checks.decisions((0, 0), (500, 1000), 4000, None, 4000, 250)
        self.assertEqual(found, {"notice-lifetime-short-floor": True, "notice-lifetime-long": False})

    def test_countdown_formats(self):
        for label, value in ((b"29 s", 29), (b"0:29", 29), (b"1:05", 65), (b"\xd0\xb7 8 \xd1\x81", 8),
                             (b"step 1 of 3, 29 s", None), (b"soon", None), (b"1:5", None)):
            self.assertEqual(countdown_value(label), value, label)
        self.assertEqual(masked_label(b"0:29 left"), "#:# left=29")

    def test_patch_chain(self):
        before = {"1": b"Title", "7": b"4 s"}
        self.assertIsNone(chain_error(before, [update(4, 3)], {"1": b"Title", "7": b"3 s"}))
        self.assertIn("did not show", chain_error(before, [update(5, 3)], {"1": b"Title", "7": b"3 s"}))
        self.assertIn("another label", chain_error(before, [update(4, 3)], {"1": b"Title", "7": b"2 s"}))
        self.assertIn("other keys", chain_error(before, [], {"1": b"Title"}))

    def test_flash_within_one_input_step(self):
        steps = [fact(0, mode="open", present=()),
                 fact(0, mode="input", present=(), patches=[("create", "9", "node", b"-", b"panel"),
                                                            ("remove", "9", "node", b"panel", b"-")])]
        found, judged, _undecided, _inside = checks.flash_verdicts(steps, 500)
        self.assertEqual((judged, [v["identity"] for v in found]), (1, [["9", "panel"]]))

    def test_flash_needs_no_input_between_and_ignores_countdowns(self):
        create = ("create", "9", "node", b"-", b"panel")
        remove = ("remove", "9", "node", b"panel", b"-")
        quick = [fact(0, mode="input", present=(), patches=[create]), fact(300, prev=0, present=(), patches=[remove])]
        self.assertEqual(len(checks.flash_verdicts(quick, 500)[0]), 1)
        slow = [fact(0, mode="input", present=(), patches=[create]), fact(500, prev=0, present=(), patches=[remove])]
        self.assertEqual(checks.flash_verdicts(slow, 500)[0], [])
        # created at an input, removed by a 500 ms time step: shown for (0, 500]: undecided, not judged
        self.assertEqual([v["check"] for v in checks.flash_verdicts(slow, 500)[2]], ["lifetime-undecided"])
        self.assertEqual(checks.flash_verdicts(slow, 500)[1], 0)
        inside = [fact(0, mode="input", present=()),
                  fact(1100, prev=0, present=(), patches=[create, remove])]
        self.assertEqual(checks.flash_verdicts(inside, 500)[1:], (0, [], [(1, "9", "panel")]))   # left to the probe
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
        self.assertEqual(checks.countdown_verdicts("dialog", seq, TIMER, seq[0].now), [])

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
            self.assertEqual([v["identity"][1] for v in checks.countdown_verdicts("dialog", seq, TIMER, seq[0].now)], [part])

    def test_start_of_an_element_that_appeared_inside_a_time_step(self):
        inside = [fact(7000, prev=5000, countdown=6)]          # appeared in (5000, 7000]: up to 1999 ms counted
        self.assertEqual(checks.countdown_verdicts("dialog", inside, dict(TIMER, lifetime_ms=8000), 5001), [])
        late = [fact(7000, prev=5000, countdown=4)]
        self.assertEqual([v["observed"]["wanted"] for v in checks.countdown_verdicts(
            "dialog", late, dict(TIMER, lifetime_ms=8000), 5001)], [[7, 8]])   # 6 (= 7 - 1) is still accepted

    def test_start_accepts_one_second_either_way(self):
        for shown, parts in ((3, []), (4, []), (5, []), (2, ["start"]), (6, ["start"])):
            found = checks.countdown_verdicts("dialog", [fact(0, mode="input", countdown=shown)], TIMER, 0)
            self.assertEqual([v["identity"][1] for v in found], parts, shown)

    def test_zero_only_when_shown_at_a_step_end(self):
        gone = fact(4000, prev=3500, countdown=None, present=(), patches=[update(1, 0)])
        seq = [fact(3000, mode="input", countdown=1), fact(3500, prev=3000, countdown=1), gone]
        self.assertEqual(checks.countdown_verdicts("dialog", seq, TIMER, 0), [])         # never a step-end label
        brief = [fact(3000, mode="input", countdown=1), fact(3999, prev=3000, countdown=0, patches=[update(1, 0)])]
        self.assertEqual([v["identity"][1] for v in checks.countdown_verdicts("dialog", brief, TIMER, 0)],
                         ["zero"])                                                       # 0 for 1 ms, under a tick
        self.assertEqual(len(checks.zero_verdicts("dialog", [fact(3999, countdown=0)])), 1)

    def test_increase_on_input_steps_unless_a_declared_restart(self):
        tap = fact(900, prev=0, mode="input", countdown=4, patches=[update(3, 4)], index=1)
        found, judged = checks.increase_verdicts([fact(0, mode="input", countdown=3), tap])
        self.assertEqual(([v["identity"] for v in found], judged), ([["dialog", "increase"]], 1))
        tap.restarts = frozenset(("7",))
        self.assertEqual(checks.increase_verdicts([fact(0, mode="input", countdown=3), tap])[0], [])

    def test_invisible_auto_transition(self):
        same = [fact(0, mode="input", cls="main"), fact(1000, prev=0, cls="detail")]
        seen = [fact(0, mode="input", cls="main"), fact(1000, prev=0, cls="detail", semantic=("other",))]
        tapped = [fact(0, mode="input", cls="main"), fact(0, mode="input", cls="detail")]
        env = [fact(0, mode="input", cls="main"), fact(0, mode="env", cls="detail")]
        self.assertEqual(len(checks.invisible_verdicts(env)[0]), 1)       # an env reply is no user input
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
        self.assertEqual(row["appeared"], [OPEN_MS, OPEN_MS])           # an input: exact
        self.assertEqual(row["decided"], {"notice-lifetime-long": False, "notice-lifetime-short": False})
        self.assertEqual(examined["totals"]["clock-origin-divergence"], 4)
        self.assertEqual(runner.cost["origin_runs"], 4)
        self.assertLessEqual(runner.cost["probe_runs"], 2 * MAX_PHASES)

    def test_each_defect_gives_its_finding(self):
        cases = [
            (Sim(life=1000, count=lambda e, life: -(-(4000 - e) // 1000)), "notice-lifetime-short"),
            # it stalls too, and nothing is ever removed, so flash has no verdict
            (Sim(life=None, count=lambda e, life: 4), "notice-lifetime-long", "countdown-wrong", "check-vacuous"),
            # the countdown counts 4 3 4 3: an increase in a time step
            (Sim(count=lambda e, life: 4 - (e // 1000) % 2), "countdown-wrong"),
            (Sim(count=lambda e, life: 2 * -(-(life - e) // 2000)), "countdown-wrong"),
            (Sim(count=lambda e, life: -(-(life - e) // 1000) - 1), "countdown-wrong"),
            (Sim(count=lambda e, life: -(-(life - e) // 1000) + 5), "countdown-wrong"),
            (Sim(wrap32=True), "clock-origin-divergence"),
        ]
        for sim, *wanted in cases:
            found, _runner = judge_run(sim, [[OPEN, "show"]])
            self.assertEqual(errors(found), sorted(wanted), wanted)       # counts, not sets: one finding each

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
        _found, once = judge_run(Sim(), [[OPEN, "show"]])
        _found, runner = judge_run(Sim(), [[OPEN, "show"], [OPEN, "show"], [OPEN, "show", "at 100000"]])
        self.assertEqual(runner.cost["probe_runs"], once.cost["probe_runs"])
        self.assertEqual(runner.cost["origin_runs"], 8)        # the third path waits for the end of the run, then fills

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
