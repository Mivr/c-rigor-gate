"""U05e fix-up 3: the bound dismiss intent (scene identity) and the sibling replay's acceptance (an accepted event that
removes the layer), the strict parts rule (`dismiss_trace`), per-state vacuity (`scene-controls-untapped`), an
unreadable state in a replay, the sibling's memo and cost, and the signal mask around a probe's start. Against the
scene stub."""

import signal

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_probe as up
from rigor_lib.errors import InternalError
from tests import test_ui_explore_helpers as h
from tests.test_ui_explore_scene import OPEN, SCENE, SceneCase, scene_stub

JUDGE = ("--judges", "ui-scene", "--today", "2026-11-16")
EVENTS = '  { id = "snack-dismiss", intent = 3, arg = 0, expect = "accept" },\n' \
         '  { id = "open-it", intent = 7, arg = 0, expect = "accept" },\n  { id = "go", intent = 1'


def tearDownModule():
    h.assert_no_stubs()


def own(found):
    return sorted((f["check"], f["path"][-1]) for f in found if f["gate"] == "ui-explore")


class BoundDismissTest(SceneCase):
    PATHS = [[OPEN, "blank-right"], [OPEN, "tap@go#0"]]

    def run_bound(self, mode, code=1):
        catalogue = self.catalogue('  { id = "go", intent = 1', EVENTS, base=SCENE)
        return self.scene_replay(mode, self.PATHS, *JUDGE, contract=True, catalogue=catalogue, code=code)

    def test_a_sibling_that_is_refused_or_leaves_the_layer_decides_nothing(self):
        for mode, why in (("snacknoop", "sibling failed refused"), ("snackstay", "sibling failed layer-stays")):
            with self.subTest(mode=mode):
                _, found, summary = self.run_bound(mode)
                self.assertEqual(own(found), [("tap-misrouted", "blank-right"), ("tap-misrouted", "tap@go#0")])
                self.assertEqual(summary["outcomes"]["blank-right"][why], 1)
                self.assertEqual(summary["outcomes"]["blank-right"]["judged by parts"], 1)

    def test_a_scrim_carrying_an_unrelated_intent_is_judged_against_the_bound_dismiss(self):
        _, found, summary = self.run_bound("snackopen")
        self.assertEqual(own(found), [("tap-misrouted", "blank-right"), ("tap-misrouted", "tap@go#0")])
        misrouted = [f for f in found if f["check"] == "tap-misrouted"][0]
        self.assertEqual(misrouted["observed"]["expected"], {"layer": "sscrim", "intent": "3:0"})
        self.assertEqual(summary["outcomes"]["blank-right"]["judged by sibling"], 1)

    def test_the_sibling_is_memoised_and_its_cost_counted(self):
        _, found, summary = self.run_bound("snackfull", code=None)
        self.assertEqual(own(found), [])
        self.assertEqual(summary["sibling_cost"]["runs"], 1)       # one state, one event: both paths, both runs
        self.assertGreater(summary["sibling_cost"]["probe_commands"], 0)


class StrictPartsTest(SceneCase):
    def test_dismiss_trace_is_strict(self):
        text = SCENE.read_text()
        old = ', dismiss_trace = { snackbar = ["dismiss"], banner = ["dismiss"] }, dismiss_trace_provenance = ' \
              '"design:P004#4.3"'
        self.assertIn(old, text)
        for new, why in ((', dismiss_trace = { snackbar = ["dismiss"] }', "go together"),
                         (', dismiss_trace = { panel = ["dismiss"] }, dismiss_trace_provenance = "design:P004#4.3"',
                          "card roles"),
                         (', dismiss_trace = { snackbar = [] }, dismiss_trace_provenance = "design:P004#4.3"',
                          "non-empty list")):
            with self.subTest(why=why):
                with self.assertRaises(InternalError) as caught:
                    catalogue_mod.loads(text.replace(old, new).encode())
                self.assertIn(why, str(caught.exception))
        # without the declaration a dismiss that posts its own trace event is not exactly the layer leaving
        _, found, _ = self.scene_replay("snack", [[OPEN, "blank-right"]], contract=True,
                                        catalogue=self.catalogue(old, "", base=SCENE), code=1)
        self.assertEqual(own(found), [("tap-misrouted", "blank-right")])
        self.assertEqual(found[0]["observed"]["not_the_dismiss"], ["trace"])


class UntappedTest(SceneCase):
    def test_a_state_whose_controls_cannot_be_tapped_is_an_error(self):
        _, found, summary = self.run_scene("unassoc", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "1", "--max-states", "3", code=1)
        untapped = h.by_check(found, "scene-controls-untapped")
        self.assertTrue(untapped)
        self.assertEqual(sorted((n["key"], n["why"]) for n in untapped[0]["observed"]["nodes"]),
                         [("51", "unassociated"), ("dup", "duplicate key"), ("dup", "duplicate key"),
                          ("go", "unassociated"), ("k2", "unassociated"), ("ok", "unassociated")])
        self.assertEqual(len(h.by_check(found, "scene-taps-vacuous")), 1)    # blank taps alone do not count
        self.assertEqual(summary["scene_taps"]["sent"], 0)

    def test_a_replayed_scene_word_in_an_unreadable_state_is_scene_unreadable(self):
        _, found, summary = self.scene_replay("badtree", [[OPEN, "tap@go#0"]], code=1)
        self.assertEqual(own(found), [("scene-unreadable", "tap@go#0")])
        self.assertEqual(summary["outcomes"]["tap@go#0"], {"unreadable": 1})


class SignalMaskTest(SceneCase):
    def test_a_probe_starts_with_the_callers_mask_and_the_caller_keeps_it(self):
        before = signal.pthread_sigmask(signal.SIG_BLOCK, [])
        session = up.Session([str(scene_stub(self.tmp, "plain"))], 5.0, up.Budget(60))
        try:
            with open("/proc/%d/status" % session._proc.pid) as stream:
                blocked = int(next(l for l in stream if l.startswith("SigBlk:")).split()[1], 16)
            self.assertFalse(blocked & (1 << (signal.SIGTERM - 1)))
            self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, []), before)
            self.assertIn(session, up.LIVE)
        finally:
            session.close()
