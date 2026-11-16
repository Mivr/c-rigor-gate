"""U05e: state-scoped taps (`taps = { scope = "scene" }`), the layer policy of the tap judges under --contract, and
the cost model (a pre-run refusal of one impossible path only, the budget on measured wall time ending a bfs with
`depth-unsaturated` reason `budget`). Against the scene stub (gate/tests/data/ui_explore/stub_scene.py)."""

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_strategies as strategies
from rigor_lib.errors import InternalError
from tests import test_ui_explore_helpers as h

HERE = Path(__file__).resolve().parent
STUB = HERE / "data" / "ui_explore" / "stub_scene.py"
SCENE = HERE / "data" / "ui_explore" / "scene.events.toml"
CANARY = h.REPO / "selftest" / "ui_canary_product" / "canary.toml"
LOCKERS = h.REPO / "products" / "business-apps" / "ui" / "lockers.events.toml"
OPEN = "open 1000 7"
GO_WORDS = ["tap@go#%d" % i for i in range(9)]


def tearDownModule():
    h.assert_no_stubs()


def scene_stub(directory, mode):
    path = Path(directory) / ("scene-" + mode)
    path.write_text("#!/bin/sh\nUI_STUB_OWNER=%d exec %s -I %s %s\n" % (os.getpid(), sys.executable, STUB, mode))
    os.chmod(path, 0o755)
    return path


class SceneCase(h.ExploreCase):
    def run_scene(self, mode, *args, catalogue=SCENE, code=None):
        argv = ["ui-explore", "--probe", scene_stub(self.tmp, mode), "--catalogue", catalogue, "--out",
                self.tmp / "f.json", "--summary", self.tmp / "s.json"] + list(args)
        outcome = h.run_rigor(argv)
        if code is not None:
            self.assertExit(outcome, code)
        found = h.findings(self.tmp / "f.json") if (self.tmp / "f.json").exists() else None
        summary = json.loads((self.tmp / "s.json").read_text()) if (self.tmp / "s.json").exists() else None
        return outcome, found, summary

    def scene_replay(self, mode, paths, *args, contract=False, **kw):
        path = h.paths_file(self.tmp, paths, name="p%d.json" % time.monotonic_ns())
        extra = ["--contract", CANARY] if contract else []
        return self.run_scene(mode, "--strategy", "replay", "--paths", path, *extra, *args, **kw)

    def checks(self, found):
        return sorted((item["check"], item["path"][-1]) for item in found)


class SceneTapsTest(SceneCase):
    def test_the_bfs_derives_the_taps_of_each_state_from_its_scene(self):
        _, found, summary = self.run_scene("plain", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "1", "--max-states", "50")
        outcomes = summary["outcomes"]
        for word in GO_WORDS + ["tap@k1#0", "tap@k2#8", "tap@ok#4", "blank#0"]:
            self.assertIn(word, outcomes)
        self.assertNotIn("tap@off#0", outcomes)          # disabled: no u2 point, its centre is the first u3 point
        self.assertEqual(outcomes["blank#0"], {"pressed lv_button 120,10,219,49 untargeted": 1, "tap refused": 1})
        self.assertEqual(outcomes["tap@go#0"], {"pressed lv_button 10,10,109,49 aimed": 1, "tap ok": 1})
        self.assertEqual(summary["findings"]["taps-capped"], 0)

    def test_scene_words_replay_and_an_unknown_point_is_unbound(self):
        _, found, summary = self.scene_replay("plain", [[OPEN, "tap@go#4", "tap@go#9", "tap@nope#0", "blank#0"]],
                                              code=0)
        self.assertEqual(found, [])
        self.assertEqual(summary["outcomes"]["tap@go#9"], {"unbound": 1})
        self.assertEqual(summary["outcomes"]["tap@go#4"], {"pressed lv_button 10,10,109,49 aimed": 1, "tap ok": 1})

    def test_the_cap_per_state_is_an_info_finding(self):
        capped = self.catalogue("max_per_state = 64", "max_per_state = 5", base=SCENE)
        _, found, summary = self.run_scene("plain", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "1", "--max-states", "1", catalogue=capped)
        caps = h.by_check(found, "taps-capped")
        self.assertEqual(sorted(item["observed"]["class"] for item in caps), ["u2", "u3"])
        self.assertTrue(all(item["severity"] == "info" and item["path"] == [OPEN] for item in caps))
        self.assertEqual(caps[0]["id"], h.finding_id("taps-capped", ["taps-capped", caps[0]["state"]["key"],
                                                                     caps[0]["observed"]["class"]]))
        self.assertIn("tap@ok#0", summary["outcomes"])     # every centre first: go, k1, k2, ok, then go's point 1
        self.assertIn("tap@go#1", summary["outcomes"])
        self.assertNotIn("tap@k1#1", summary["outcomes"])

    def test_scene_words_need_a_scene_scoped_catalogue(self):
        fixed = self.catalogue('scope = "scene", max_per_state = 64, grid_pct = [20, 50, 80], ',
                               'scope = "fixed", ', base=SCENE)
        outcome, _, _ = self.scene_replay("plain", [[OPEN, "tap@go#0"]], catalogue=fixed, code=2)
        self.assertIn("is not a path word", outcome.stderr)


class LayerPolicyTest(SceneCase):
    PATHS = [[OPEN, "tap@go#0"], [OPEN, "tap-go"], [OPEN, "blank-right"], [OPEN, "go"]]

    def test_without_a_contract_taps_under_a_dialog_are_judged_as_before(self):
        _, found, _ = self.scene_replay("dialog", self.PATHS, code=1)
        self.assertEqual(self.checks(found), [("intent-missed", "go"), ("intent-missed", "tap-go"),
                                              ("intent-missed", "tap@go#0"), ("tap-misrouted", "tap-go"),
                                              ("tap-misrouted", "tap@go#0")])

    def test_a_tap_on_a_target_inert_under_a_modal_dialog_expects_no_effect(self):
        _, found, summary = self.scene_replay("dialog", self.PATHS, contract=True, code=0)
        self.assertEqual(found, [])
        self.assertEqual(summary["outcomes"]["tap-go"], {"layer inert dscrim": 1, "tap refused": 1,
                                                         "pressed lv_obj 0,0,319,239 other": 1})
        self.assertEqual(summary["outcomes"]["go"], {"apply missed": 1, "layer inert go": 1})
        _, found, _ = self.scene_replay("dialoglive", self.PATHS, contract=True, code=1)
        self.assertEqual(self.checks(found), [("blocked-target-live", "tap-go"), ("blocked-target-live", "tap@go#0")])
        self.assertEqual(found[0]["observed"]["layer"], "dscrim")

    def test_a_tap_outside_a_dismissing_layer_expects_exactly_its_dismiss(self):
        _, found, summary = self.scene_replay("snack", self.PATHS, contract=True, code=0)
        self.assertEqual(found, [])
        self.assertEqual(summary["outcomes"]["blank-right"]["tap dismissed"], 1)
        self.assertEqual(summary["events"]["blank-right"]["accepted_states"], 1)
        for mode in ("snackbad", "snackmore"):
            _, found, _ = self.scene_replay(mode, self.PATHS, contract=True, code=1)
            self.assertEqual(self.checks(found), [("tap-misrouted", "blank-right"), ("tap-misrouted", "tap-go"),
                                                  ("tap-misrouted", "tap@go#0")], mode)
            self.assertEqual(found[0]["observed"]["expected"], {"layer": "sscrim", "intent": "3:0"})

    def test_a_tap_that_only_removes_a_pass_through_layer_is_swallowed(self):
        _, found, _ = self.scene_replay("banner", self.PATHS, contract=True, code=1)
        self.assertEqual(self.checks(found), [("noop-tap-effect", "blank-right"), ("tap-swallowed-first", "tap-go"),
                                              ("tap-swallowed-first", "tap@go#0")])
        swallowed = h.by_check(found, "tap-swallowed-first")[0]
        self.assertEqual((swallowed["observed"]["layer"], swallowed["observed"]["below"]), ("bscrim", "go"))


class CostTest(SceneCase):
    def args(self, **kw):
        base = {"strategy": "bfs", "depth": 12, "max_states": 1000, "budget_s": 1200, "walk_length": None}
        base.update(kw)
        return SimpleNamespace(**base)

    def test_the_lockers_numbers_one_path_is_bounded_not_the_run(self):
        catalogue = catalogue_mod.load(LOCKERS)
        caps = ("hit-test", "tap")
        bound = strategies.check_cost(catalogue, self.args(), None, caps)
        self.assertEqual(bound, 2 * (12 * 300256 + 1024))
        with self.assertRaises(InternalError) as caught:
            strategies.check_cost(catalogue, self.args(depth=64), None, caps)
        self.assertIn("one path of this run could take", str(caught.exception))

    def test_a_replay_at_word_costs_its_offset_at_most(self):
        catalogue = catalogue_mod.load(SCENE)
        args = self.args(strategy="replay", budget_s=2)
        self.assertEqual(strategies.check_cost(catalogue, args, [[OPEN, "at 3200", "at 5200"]], ()), 2 * 8400)
        self.assertEqual(strategies.word_span(catalogue, "at 99999"), 10000)

    def test_the_budget_ends_a_bfs_cleanly_with_the_bound_finding(self):
        start = time.monotonic()
        _, found, summary = self.run_scene("slow", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "3", "--max-states", "50", "--budget-s", "3", code=1)
        self.assertLess(time.monotonic() - start, 30)
        bound = h.by_check(found, "depth-unsaturated")
        self.assertEqual(len(bound), 1)
        self.assertIn("budget", bound[0]["observed"]["reasons"])
        self.assertEqual(h.by_check(found, "ui-explore-timeout"), [])
        self.assertEqual((summary["budget_spent"], summary["evaluated"], summary["detail"]["budget_cut"]),
                         (True, [], True))
