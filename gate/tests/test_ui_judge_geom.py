"""The O2 + O3 checks of the ui-scene judge (U06, P004 3.1, 3.10): occluded-target, overlay-policy, target-spacing,
node-out-of-bounds, text-overlap. The base button is the box 8,100..107,149: its grid points (20/50/80 %) are x 28, 58,
88 and y 110, 125, 140; its centre 58,125; the probe disc of 7.5 mm at 40 ppi has a radius of 11.81 px."""

import unittest

from rigor_lib.ui_judge_geom import probe_points
from tests.test_ui_judge_helpers import base, checks, contract, expected_id, pending, run, sem

PANEL_PENDING = lambda t: pending(t, "diagonal_in", 'diagonal_in = { pending = "9", provenance = "spec:P004#11-q9" }')


def only(found, check):
    return [f for f in found if f["check"] == check]


class ProbePointTest(unittest.TestCase):
    def test_the_grid_and_the_centre_inside_the_box(self):
        self.assertEqual(probe_points((8, 100, 107, 149), [20, 50, 80]),
                         [(x, y) for x in (28, 58, 88) for y in (110, 125, 140)])
        self.assertEqual(probe_points((0, 0, 0, 0), [20, 50, 80, 100]), [(0, 0)])
        self.assertEqual(probe_points((0, 0, -1, 9), [50]), [])
        self.assertEqual(len(probe_points((0, 0, 99, 99), [20, 80])), 9)      # the centre is added


class OccludedTest(unittest.TestCase):
    def cover(self, box, the_contract=None, clickable=0, bg=255, parent=0, flags="-", hidden=0, tree_edit=None):
        semantic, tree = base()
        tree.node(parent, "lv_obj", box, clickable=clickable, bg=bg, hidden=hidden)
        semantic[2] = sem("ok", "key_label", "OK", (8, 100, 100, 50), intent="1:0", style="btn", importance="2",
                          wrap="single_line", flags=flags)
        if tree_edit:
            tree_edit(tree)
        return run(semantic, tree, the_contract=the_contract)

    def test_a_cover_on_the_last_grid_column_is_a_finding_one_pixel_right_none(self):
        found = only(self.cover((88, 90, 139, 159)), "occluded-target")
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "occluded-target", ["ok"])])
        self.assertEqual((found[0]["observed"]["grid_points_covered"], found[0]["observed"]["covered_by"]),
                         (3, [{"index": 5, "class": "lv_obj"}]))
        self.assertEqual(self.cover((89, 90, 139, 159)), [])

    def test_the_disc_inside_its_radius_is_a_finding_just_outside_none(self):
        # no grid point in either; the centre 58,125 is 11.18 px from the first box and 12.17 px from the second
        self.assertEqual(checks(self.cover((60, 112, 62, 114))), ["occluded-target"])
        self.assertEqual(self.cover((60, 111, 62, 113)), [])

    def test_with_a_pending_panel_the_disc_is_pending_and_the_grid_still_judged(self):
        c = contract(PANEL_PENDING)
        pend = expected_id("ui-scene", "contract-pending", ["occluded-target", "panel.diagonal_in"], stateless=True)
        found = self.cover((60, 112, 62, 114), the_contract=c)
        self.assertEqual([f["id"] for f in found if f["observed"].get("check") == "occluded-target"], [pend])
        self.assertEqual(only(found, "occluded-target"), [])
        self.assertEqual(len(only(self.cover((88, 90, 139, 159), the_contract=c), "occluded-target")), 1)

    def test_what_does_not_cover(self):
        self.assertEqual(self.cover((88, 90, 139, 159), bg=0), [])                   # transparent, not clickable
        self.assertEqual(self.cover((88, 90, 139, 159), hidden=1), [])
        self.assertEqual(self.cover((88, 90, 139, 159), flags="inert"), [])           # not a target
        self.assertEqual(self.cover((88, 102, 100, 140), parent=3), [])               # its own descendant
        self.assertEqual(checks(self.cover((88, 90, 139, 159), bg=0, clickable=1)),
                         ["occluded-target", "overlay-policy"])                       # takes taps: an undeclared layer

    def test_an_earlier_sibling_does_not_cover(self):
        semantic, tree = base()
        tree.nodes.insert(3, dict(tree.nodes[1], label=None, fit=None, box=(88, 90, 139, 159), bg=255))
        for node in tree.nodes[4:]:
            node["parent"] = node["parent"] + 1 if node["parent"] >= 3 else node["parent"]
        self.assertEqual(only(run(semantic, tree), "occluded-target"), [])

    def test_a_later_label_covers_with_its_drawn_glyphs_only(self):
        semantic, tree = base()
        tree.label(0, "x", (80, 120, 99, 135), glyphs="86,122,90,130")     # glyphs on 88,125
        self.assertEqual(checks(only(run(semantic, tree), "occluded-target")), ["occluded-target"])
        semantic, tree = base()
        tree.label(0, "x", (80, 120, 99, 135), glyphs="89,122,90,123")    # neither the grid nor the disc
        self.assertEqual(only(run(semantic, tree), "occluded-target"), [])

    def test_behind_a_declared_modal_blocker_is_not_occluded_but_must_be_inert(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 90, 159, 159), clickable=1)
        semantic.append(sem("veil", "layer", "", (0, 90, 160, 70), policy="modal"))
        found = run(semantic, tree)
        self.assertEqual([f["id"] for f in found],
                         [expected_id("ui-scene", "overlay-policy", ["veil", "ok", "captures"])])


class OverlayTest(unittest.TestCase):
    def layer(self, policy, flags="-", box=(0, 90, 159, 159), before=False):
        semantic, tree = base()
        semantic[2] = sem("ok", "key_label", "OK", (8, 100, 100, 50), intent="1:0", style="btn", importance="2",
                          wrap="single_line", flags=flags)
        x1, y1, x2, y2 = box
        semantic.append(sem("veil", "layer", "", (x1, y1, x2 - x1 + 1, y2 - y1 + 1), policy=policy))
        if before:
            tree.nodes.insert(1, {"parent": 0, "depth": 1, "cls": "lv_obj", "box": box, "hidden": 0, "clickable": 1,
                                  "clip": -1, "scroll": -1, "bg": 0, "exact": 1, "grad": 0, "image": 0, "label": None,
                                  "fit": None})
            for node in tree.nodes[2:]:
                node["parent"] = node["parent"] + 1 if node["parent"] >= 1 else node["parent"]
        else:
            tree.node(0, "lv_obj", box, clickable=1)
        return run(semantic, tree)

    def test_a_capturing_layer_over_an_enabled_node(self):
        self.assertEqual([f["id"] for f in self.layer("modal")],
                         [expected_id("ui-scene", "overlay-policy", ["veil", "ok", "captures"])])
        found = self.layer("dismissable")
        self.assertEqual(sorted(checks(found)), ["occluded-target", "overlay-policy"])
        self.assertEqual(only(found, "overlay-policy")[0]["observed"],
                         {"stage": "O2+O3", "layer": "veil", "policy": "dismissable", "key": "ok", "inert": False})

    def test_inert_under_a_modal_passes_inert_under_a_dismissing_layer_does_not(self):
        self.assertEqual(self.layer("modal", flags="inert"), [])
        self.assertEqual(checks(self.layer("dismissable", flags="inert")), ["overlay-policy"])

    def test_a_pass_through_layer_a_layer_below_or_beside_is_no_finding(self):
        self.assertEqual(checks(self.layer("screen")), ["occluded-target"])          # covers, captures nothing
        self.assertEqual(self.layer("modal", before=True), [])
        self.assertEqual(self.layer("modal", box=(108, 90, 159, 159)), [])           # one pixel right of the box

    def test_an_undeclared_capturing_node_has_no_target_for_an_exception(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 0, 319, 239), clickable=1)
        found = only(run(semantic, tree), "overlay-policy")
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "overlay-policy", ["undeclared", 5, "ok"])])
        self.assertEqual(found[0]["observed"]["capturing"], {"index": 5, "class": "lv_obj"})


class SpacingTest(unittest.TestCase):
    def second(self, x, intent="2:0", the_contract=None):
        semantic, tree = base()
        button = tree.node(0, "lv_button", (x, 100, x + 99, 149), clickable=1, bg=255)
        tree.label(button, "No", (x + 40, 117, x + 59, 132))
        semantic.append(sem("no", "key_label", "No", (x, 100, 100, 50), intent=intent, style="btn", importance="2",
                            wrap="single_line"))
        return [f for f in run(semantic, tree, the_contract=the_contract)
                if f["check"] == "target-spacing" or f["observed"].get("check") == "target-spacing"]

    def test_the_gap_against_one_and_three_mm(self):
        # hard 1 mm = 1.57 px, recommended 3 mm = 4.72 px; the ok button ends at x 107
        self.assertEqual([(f["id"], f["severity"]) for f in self.second(109)],
                         [(expected_id("ui-scene", "target-spacing", ["no", "ok", "hard"]), "error")])
        self.assertEqual([(f["id"], f["severity"]) for f in self.second(110)],
                         [(expected_id("ui-scene", "target-spacing", ["no", "ok", "recommended"]), "info")])
        self.assertEqual([f["severity"] for f in self.second(112)], ["info"])
        self.assertEqual(self.second(113), [])

    def test_an_overlap_is_hard_unless_allowed_and_one_intent_is_never_compared(self):
        found = self.second(100)
        self.assertEqual([f["id"] for f in only(found, "target-spacing")],
                         [expected_id("ui-scene", "target-spacing", ["no", "ok", "overlap"])])
        allowed = contract(lambda t: t.replace("hit_overlap_allowed           = { value = false",
                                               "hit_overlap_allowed           = { value = true"))
        self.assertEqual(self.second(100, the_contract=allowed), [])
        self.assertEqual(self.second(109, intent="1:0"), [])

    def test_pending_mm_spacing_still_judges_the_overlap(self):
        c = contract(PANEL_PENDING)
        pend = expected_id("ui-scene", "contract-pending", ["target-spacing", "panel.diagonal_in"], stateless=True)
        self.assertEqual([f["id"] for f in self.second(109, the_contract=c)], [pend])
        self.assertEqual(sorted(f["id"] for f in self.second(100, the_contract=c)),
                         sorted([pend, expected_id("ui-scene", "target-spacing", ["no", "ok", "overlap"])]))


class BoundsTest(unittest.TestCase):
    def panel(self, box, parent=0):
        semantic, tree = base()
        tree.node(parent, "lv_obj", box)
        x1, y1, x2, y2 = box
        semantic.append(sem("edge", "panel", "", (x1, y1, x2 - x1 + 1, y2 - y1 + 1)))
        return only(run(semantic, tree), "node-out-of-bounds")

    def test_the_window_edge_inside_passes_one_pixel_out_fails(self):
        self.assertEqual(self.panel((280, 200, 319, 239)), [])
        self.assertEqual([f["id"] for f in self.panel((280, 200, 320, 239))],
                         [expected_id("ui-scene", "node-out-of-bounds", ["edge", "window"])])
        self.assertEqual(len(self.panel((-1, 200, 10, 239))), 1)
        self.assertEqual(self.panel((330, 200, 329, 239)), [])                   # no area

    def test_a_child_one_pixel_outside_its_parent(self):
        self.assertEqual(self.panel((10, 100, 107, 149), parent=3), [])
        found = self.panel((10, 100, 108, 149), parent=3)
        self.assertEqual([(f["id"], f["observed"]["parent"]) for f in found],
                         [(expected_id("ui-scene", "node-out-of-bounds", ["edge", "parent"]), {"key": "ok"})])


class OverlapTest(unittest.TestCase):
    def second_text(self, y, layer=False):
        semantic, tree = base()
        parent = 0
        if layer:
            parent = tree.node(0, "lv_obj", (0, 0, 319, 239))
            semantic.append(sem("sheet", "layer", "", (0, 0, 320, 240), policy="screen"))
        tree.label(parent, "More", (8, y, 207, y + 23))
        semantic.append(sem("more", "body", "More", (8, y, 200, 24), style="body", importance="2", wrap="default"))
        return only(run(semantic, tree), "text-overlap")

    def test_touching_rows_pass_one_shared_row_fails(self):
        self.assertEqual(self.second_text(64), [])
        self.assertEqual([f["id"] for f in self.second_text(63)],
                         [expected_id("ui-scene", "text-overlap", ["body", "more"])])

    def test_texts_in_different_layers_are_not_compared(self):
        self.assertEqual(self.second_text(63, layer=True), [])


if __name__ == "__main__":
    unittest.main()
