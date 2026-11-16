"""U05e fix-up 2: scene taps never go vacuous in silence (the catalogue must require the frame facts and the tap
commands; an unreadable state and a bfs without one scene tap are errors), "dismissed" is exactly the layer leaving
(full change set, the declared ambient and countdown restart exempt), a dismissing layer comes before R7, an intent
shared by a live and an inert node is not excused, a covering control is recorded and must only dismiss its layer, the
disc points of P(n), the boot seeds' merged bound and the negatives (`intent_node = "key"`, a u1 accepted under a
modal layer, a pass-through tap whose control below acts). Against the scene stub."""

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_strategies import merge_bounds as _merge_bounds
from tests import test_ui_explore_helpers as h
from tests.test_ui_explore_scene import CANARY, OPEN, SCENE, SceneCase

AMBIENT = ('requires = ["frame-facts", "hit-test", "tap", "pointer"]\nambient = { trace = ["touch"], '
           'trace_provenance = "design:P004#4.3", countdown_restart_role = "countdown", '
           'countdown_restart_provenance = "design:P004#4.3" }\n')
REQUIRES = 'requires = ["frame-facts", "hit-test", "tap"]\n'


def tearDownModule():
    h.assert_no_stubs()


class LoaderTest(SceneCase):
    def test_scene_scope_needs_the_frame_facts_and_the_tap_commands_and_seeds_are_integers(self):
        text = SCENE.read_text()
        for old, new, why in ((REQUIRES, "", "needs `requires` to name frame-facts, hit-test, tap"),
                              (REQUIRES, 'requires = ["frame-facts", "tap"]\n', "needs `requires`"),
                              ("seeds = [7, 8]", "seeds = [[1]]", "1 to 256 distinct integers")):
            with self.subTest(why=why):
                with self.assertRaises(InternalError) as caught:
                    catalogue_mod.loads(text.replace(old, new, 1).encode())
                self.assertIn(why, str(caught.exception))


class VacuityTest(SceneCase):
    def test_an_unreadable_state_and_a_bfs_without_a_scene_tap_are_errors(self):
        _, found, summary = self.run_scene("badtree", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "1", "--max-states", "5", code=1)
        unread = h.by_check(found, "scene-unreadable")
        self.assertTrue(unread and all(item["severity"] == "error" for item in unread))
        self.assertEqual([item["observed"] for item in h.by_check(found, "scene-taps-vacuous")],
                         [{"sent": 0, "unbound": 0}])
        self.assertEqual(summary["scene_taps"], {"sent": 0, "unbound": 0})

    def test_a_bfs_that_sends_scene_taps_is_not_vacuous(self):
        _, found, summary = self.run_scene("plain", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "1", "--max-states", "5")
        self.assertEqual(h.by_check(found, "scene-taps-vacuous") + h.by_check(found, "scene-unreadable"), [])
        self.assertGreater(summary["scene_taps"]["sent"], 0)


class DismissTest(SceneCase):
    PATHS = [[OPEN, "blank-right"], [OPEN, "tap@go#0"]]

    def test_a_dismiss_with_another_trace_or_deadline_effect_is_misrouted(self):
        for mode, part in (("snacktwice", "trace"), ("snackdue", "due")):
            with self.subTest(mode=mode):
                _, found, _ = self.scene_replay(mode, self.PATHS, contract=True, code=1)
                self.assertEqual(self.checks(found), [("tap-misrouted", "blank-right"), ("tap-misrouted", "tap@go#0")])
                self.assertEqual(found[0]["observed"]["not_the_dismiss"], [part])

    def test_a_dismiss_over_a_countdown_the_touch_restarts_is_dismissed(self):
        catalogue = self.catalogue(REQUIRES, AMBIENT, base=SCENE)
        _, found, summary = self.scene_replay("snackcount", self.PATHS, contract=True, catalogue=catalogue, code=0)
        self.assertEqual(found, [])
        self.assertEqual(summary["outcomes"]["blank-right"]["tap dismissed"], 1)

    def test_a_dismiss_that_does_what_its_own_intent_does_is_dismissed_by_the_sibling_replay(self):
        catalogue = self.catalogue('  { id = "go", intent = 1', '  { id = "snack-dismiss", intent = 3, arg = 0, '
                                   'expect = "accept" },\n  { id = "go", intent = 1', base=SCENE)
        _, found, summary = self.scene_replay("snackfull", self.PATHS, "--judges", "ui-scene", "--today",
                                              "2026-11-16", contract=True, catalogue=catalogue)
        self.assertEqual([f for f in found if f["gate"] == "ui-explore"], [])
        self.assertEqual(summary["outcomes"]["blank-right"]["judged by sibling"], 1)
        # without the intent's event in the catalogue there is no sibling: the parts rule calls it misrouted
        _, found, _ = self.scene_replay("snackfull", self.PATHS, contract=True, code=1)
        self.assertEqual(found[0]["observed"]["not_the_dismiss"], ["semantic", "patches", "trace"])

    def test_a_layer_that_blocks_and_dismisses_dismisses_before_r7(self):
        contract = self.tmp / "modal.toml"
        text = CANARY.read_text()
        old = 'layer = "snackbar"\nblocks_input_below = false'
        self.assertIn(old, text)
        contract.write_text(text.replace(old, 'layer = "snackbar"\nblocks_input_below = true'))
        _, found, summary = self.scene_replay("snackmodal", [[OPEN, "tap@go#0"]], "--contract", contract, code=0)
        self.assertEqual(found, [])
        self.assertEqual(summary["outcomes"]["tap@go#0"]["tap dismissed"], 1)


class IntentTest(SceneCase):
    def test_an_intent_a_live_node_shares_keeps_its_intent_missed(self):
        _, found, _ = self.scene_replay("dialogdup", [[OPEN, "go"]], contract=True, code=1)
        self.assertEqual(self.checks(found), [("intent-missed", "go")])

    def test_intent_node_key_names_the_scene_key(self):
        catalogue = self.catalogue('intent_node = "intent"', 'intent_node = "key"', base=SCENE)
        catalogue.write_text(catalogue.read_text().replace(
            '  { id = "go", intent = 1', '  { id = "key-51", intent = 51, arg = 0, expect = "accept" },\n'
            '  { id = "go", intent = 1'))
        _, found, summary = self.scene_replay("dialog", [[OPEN, "key-51"]], contract=True, catalogue=catalogue,
                                              code=0)
        self.assertEqual((found, summary["outcomes"]["key-51"]), ([], {"apply missed": 1, "layer inert": 1}))
        _, found, summary = self.scene_replay("plain", [[OPEN, "key-51"]], contract=True, catalogue=catalogue, code=0)
        self.assertEqual(summary["outcomes"]["key-51"], {"apply ok": 1})


class CoveredTest(SceneCase):
    def test_a_covering_control_that_does_more_than_dismiss_is_misrouted(self):
        _, found, _ = self.scene_replay("dialoglive", [[OPEN, "tap@ok#0"]], contract=True, code=1)
        self.assertEqual(self.checks(found), [("tap-misrouted", "tap@ok#0")])
        expected = found[0]["observed"]["expected"]
        self.assertEqual((expected["control"], expected["aimed"], expected["layer"]), ("dclose", "ok", "dscrim"))


class PassTest(SceneCase):
    def test_a_pass_through_tap_whose_control_below_acts_is_not_swallowed(self):
        _, found, _ = self.scene_replay("bannerok", [[OPEN, "tap@go#0"]], contract=True)
        self.assertEqual(h.by_check(found, "tap-swallowed-first"), [])


class DiscTest(SceneCase):
    def test_with_the_ppi_and_radius_the_disc_points_follow_the_grid(self):
        _, found, summary = self.scene_replay("plain", [[OPEN, "tap@go#9"]], contract=True, code=0)
        self.assertEqual((found, summary["scene_taps"]), ([], {"sent": 1, "unbound": 0}))
        _, found, _ = self.scene_replay("plain", [[OPEN, "tap@go#9"]], code=1)     # no contract: grid only
        self.assertEqual(self.checks(found), [("scene-word-unbound", "tap@go#9")])


class BoundsTest(SceneCase):
    def test_a_later_seeds_budget_cut_keeps_the_earlier_seeds_bound(self):
        def bound(reasons):
            return {"id": "x", "check": "depth-unsaturated", "observed": {"reasons": reasons, "states_per_depth": [1],
                                                                         "dropped_states": 0}}
        merged = _merge_bounds([(7, bound(["state-bound"])), (8, bound(["budget"])), (8, {"id": "y", "check": "c"})])
        self.assertEqual([item["id"] for item in merged], ["x", "y"])
        self.assertEqual(merged[0]["observed"]["reasons"], ["state-bound", "budget"])
        self.assertEqual([p["seed"] for p in merged[0]["observed"]["per_seed"]], [7, 8])
        self.assertNotIn("states_per_depth", merged[0]["observed"])     # fix-up 3: per seed only
