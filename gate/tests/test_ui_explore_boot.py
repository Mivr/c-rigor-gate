"""U05e: the pad macro's `digit_map`, the catalogue's `[boot]` seeds (`--boot-seeds catalogue`), `[[prefix]]` rows
(`--prefix NAME`) and the strict loader of the new tables. Against the scene stub."""

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib.errors import InternalError
from tests import test_ui_explore_helpers as h
from tests.test_ui_explore_scene import OPEN, SCENE, SceneCase


def tearDownModule():
    h.assert_no_stubs()


class PadMapTest(SceneCase):
    def test_a_digit_map_sends_each_digit_as_its_own_intent(self):
        _, found, summary = self.scene_replay("keyed", [[OPEN, "pad-map-12"], [OPEN, "pad-12"]], code=0)
        self.assertEqual(found, [])
        self.assertEqual(summary["outcomes"]["pad-map-12"], {"apply ok": 3})
        # without the map the digit is the arg of digit_intent: this adapter refuses `apply 3 5 2`
        self.assertEqual(summary["outcomes"]["pad-12"], {"apply ok": 2, "apply refused": 1})

    def test_the_loader_wants_every_digit_mapped_and_one_of_map_and_digit_intent(self):
        text = SCENE.read_text()
        for old, new, why in ((', "2" = { intent = 5, arg = 1 }', '', "does not map the digit(s) 2"),
                              ('digit_map = {', 'digit_intent = 5, digit_map = {', "unknown key(s) digit_intent"),
                              ('"1" = { intent = 5, arg = 0 }', '"1" = { intent = 5 }', "missing key(s) arg"),
                              ('"1" = { intent', '"x" = { intent', "single digits")):
            with self.subTest(why=why):
                self.assertIn(old, text)
                with self.assertRaises(InternalError) as caught:
                    catalogue_mod.loads(text.replace(old, new, 1).encode())
                self.assertIn(why, str(caught.exception))


class BootSeedsTest(SceneCase):
    def bfs(self, mode, *extra, **kw):
        return self.run_scene(mode, "--strategy", "bfs", "--origin-ms", "1000", "--depth", "1", "--max-states", "3",
                              *extra, **kw)

    def test_the_strategy_runs_once_per_boot_seed_and_the_findings_merge(self):
        _, found, summary = self.bfs("seeded", "--boot-seeds", "catalogue")
        self.assertEqual([item["seed"] for item in summary["detail"]["boot_seeds"]], [7, 8])
        self.assertTrue(found)
        self.assertEqual(sorted({item["path"][0] for item in found if item["path"]}),
                         ["open 1000 7", "open 1000 8"])
        self.assertEqual(len({item["id"] for item in found}), len(found))
        _, single, _ = self.bfs("seeded", "--seed", "8")
        ids = {item["id"] for item in found}
        self.assertTrue({item["id"] for item in single if item["check"] != "depth-unsaturated"} <= ids)

    def test_a_prefix_starts_the_bfs_after_its_words(self):
        _, found, summary = self.bfs("snack", "--seed", "7", "--prefix", "shown")
        self.assertTrue(found)
        self.assertTrue(all(item["path"][:2] == [OPEN, "show"] for item in found if len(item["path"]) > 1))
        self.assertEqual(list(summary["outcomes"]["show"]), ["apply refused"])       # in every path, once

    def test_bad_requests_are_the_gates_input_errors(self):
        for extra, why in ((["--boot-seeds", "catalogue", "--seed", "7"], "--seed is not allowed with --boot-seeds"),
                           (["--seed", "7", "--prefix", "nope"], "no [[prefix]] row of that name")):
            with self.subTest(why=why):
                outcome, _, _ = self.bfs("plain", *extra, code=2)
                self.assertIn(why, outcome.stderr)
        no_boot = self.catalogue('[boot]\nseeds = [7, 8]\nprovenance = "design:P004#4.3"\n', '', base=SCENE)
        outcome, _, _ = self.bfs("plain", "--boot-seeds", "catalogue", catalogue=no_boot, code=2)
        self.assertIn("has no [boot] seeds", outcome.stderr)
        bad_prefix = self.catalogue('words = ["show"]', 'words = ["nope"]', base=SCENE)
        outcome, _, _ = self.bfs("plain", "--seed", "7", "--prefix", "shown", catalogue=bad_prefix, code=2)
        self.assertIn("is not a path word", outcome.stderr)


class LoaderTest(SceneCase):
    def test_the_new_tables_are_strict(self):
        text = SCENE.read_text()
        cases = (('max_per_state = 64, ', '', "required with scope"),
                 ('scope = "scene"', 'scope = "wide"', "taps.scope"),
                 ('grid_pct = [20, 50, 80]', 'grid_pct = [50, 20]', "strictly increasing"),
                 ('intent_node = "intent"', 'intent_node = "label"', "taps.intent_node"),
                 ('provenance = "design:P004#4.3" }', 'provenance = "trust me" }', "provenance"),
                 ('seeds = [7, 8]', 'seeds = [7, 7]', "distinct"),
                 ('words = ["show"]', 'words = []', "path words"),
                 ('name = "shown"', 'name = "Shown"', "prefix[0].name"))
        for old, new, why in cases:
            with self.subTest(why=why):
                self.assertIn(old, text)
                with self.assertRaises(InternalError) as caught:
                    catalogue_mod.loads(text.replace(old, new, 1).encode())
                self.assertIn(why, str(caught.exception))
        loaded = catalogue_mod.loads(text.encode())
        self.assertEqual((loaded.boot_seeds, loaded.prefix("shown"), loaded.taps.max_per_state),
                         ((7, 8), ("show",), 64))
