"""U05e fix-up 4: `scene-controls-untapped` in every readable state where a tap target derived no u2 word (H is no tap
target; a duplicated key once), a dismiss sibling whose own intent does more than make the layer leave, the BOUND key's
event replayed in `intent_node = "key"` mode, no bound intent from a disabled or intent-less dismiss button, and two
stacked layers (the topmost is the one that must leave). Against the scene stub."""

from tests import test_ui_explore_helpers as h
from tests.test_ui_explore_fixup3 import EVENTS, JUDGE, own
from tests.test_ui_explore_scene import OPEN, SCENE, SceneCase

PATHS = [[OPEN, "blank-right"], [OPEN, "tap@go#0"]]


def tearDownModule():
    h.assert_no_stubs()


class UntappedTest(SceneCase):
    def test_every_state_with_an_untapped_target_is_reported(self):
        _, found, summary = self.run_scene("half", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "1", "--max-states", "2", code=1)
        untapped = h.by_check(found, "scene-controls-untapped")
        self.assertTrue(untapped)
        for item in untapped:      # go, 51 and k2 are tapped; `hid` (H) is no tap target; `dup` once
            self.assertEqual(sorted((n["key"], n["why"]) for n in item["observed"]["nodes"]),
                             [("dup", "duplicate key"), ("ok", "unassociated")])
        self.assertIn("tap@go#0", summary["outcomes"])
        self.assertNotIn("tap@hid#0", summary["outcomes"])
        self.assertEqual(h.by_check(found, "scene-taps-vacuous"), [])


class SiblingTest(SceneCase):
    def run_bound(self, mode, catalogue=None, code=None):
        catalogue = catalogue or self.catalogue('  { id = "go", intent = 1', EVENTS, base=SCENE)
        return self.scene_replay(mode, PATHS, *JUDGE, contract=True, catalogue=catalogue, code=code)

    def test_a_dismiss_whose_own_intent_does_more_is_misrouted(self):
        for mode in ("snacktag", "snackfull"):
            with self.subTest(mode=mode):
                _, found, summary = self.run_bound(mode, code=1)
                self.assertEqual(own(found), [("tap-misrouted", "blank-right"), ("tap-misrouted", "tap@go#0")])
                self.assertEqual(summary["outcomes"]["blank-right"]["sibling failed more-than-dismiss"], 1)

    def test_key_mode_replays_the_bound_keys_event_not_the_scrims(self):
        catalogue = self.catalogue('intent_node = "intent"', 'intent_node = "key"', base=SCENE)
        catalogue.write_text(catalogue.read_text().replace(
            '  { id = "go", intent = 1', '  { id = "scrim-key", intent = 60, arg = 0, expect = "accept" },\n'
            '  { id = "dismiss-key", intent = 62, arg = 0, expect = "accept" },\n  { id = "go", intent = 1'))
        _, found, summary = self.run_bound("snackkeys", catalogue)
        self.assertEqual(own(found), [])
        self.assertEqual(summary["outcomes"]["blank-right"]["judged by sibling"], 1)
        self.assertEqual(summary["outcomes"]["blank-right"]["tap dismissed"], 1)

    def test_a_disabled_dismiss_button_binds_no_intent(self):
        _, found, summary = self.run_bound("snackdead", code=None)
        self.assertEqual(own(found), [])                  # judged by parts: the declared `dismiss` trace, no deadline
        self.assertEqual(summary["outcomes"]["blank-right"]["judged by parts"], 1)
        self.assertNotIn("judged by sibling", summary["outcomes"]["blank-right"])


class StackTest(SceneCase):
    def test_the_topmost_layer_is_the_one_that_must_leave(self):
        _, found, summary = self.scene_replay("stack", [[OPEN, "blank-right"]], contract=True, code=0)
        self.assertEqual(found, [])          # the snackbar left, the banner below stayed (judged by parts)
        self.assertEqual(summary["outcomes"]["blank-right"]["layer dismiss sscrim"], 1)
        self.assertEqual(summary["outcomes"]["blank-right"]["tap dismissed"], 1)
        _, found, _ = self.scene_replay("stackwrong", [[OPEN, "blank-right"]], contract=True, code=1)
        self.assertEqual(own(found), [("tap-misrouted", "blank-right")])
