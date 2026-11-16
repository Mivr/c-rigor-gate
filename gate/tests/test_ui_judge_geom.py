"""The O2 + O3 checks of the ui-scene judge (U06, P004 3.1, 3.10): occluded-target, overlay-policy, target-spacing,
node-out-of-bounds, text-overlap. The base button is the box 8,100..107,149: its grid points (20/50/80 %) are x 28, 58,
88 and y 110, 125, 140; its centre 58,125; the probe disc of 7.5 mm at 40 ppi has a radius of 11.81 px."""

import unittest

from rigor_lib.ui_judge_geom import probe_points
from tests.test_ui_judge_helpers import base, checks, contract, expected_id, pending, run, sem

PANEL_PENDING = lambda t: pending(t, "diagonal_in", 'diagonal_in = { pending = "9", provenance = "spec:P004#11-q9" }')


def only(found, check):
    return [f for f in found if f["check"] == check]


def with_node(box, role="panel", parent=0, flags="-", intent="-", enabled=1, key="x", **facts):
    """The base scene and one more node (scene and rendered) at the inclusive `box`."""
    semantic, tree = base()
    tree.node(parent, facts.pop("cls", "lv_obj"), box, **facts)
    x1, y1, x2, y2 = box
    semantic.append(sem(key, role, "", (x1, y1, x2 - x1 + 1, y2 - y1 + 1), flags=flags, intent=intent,
                        enabled=enabled))
    return semantic, tree


class ProbePointTest(unittest.TestCase):
    def test_the_grid_and_the_centre_inside_the_box(self):
        self.assertEqual(probe_points((8, 100, 107, 149), [20, 50, 80]),
                         [(x, y) for x in (28, 58, 88) for y in (110, 125, 140)])
        self.assertEqual(probe_points((0, 0, 0, 0), [20, 50, 80, 100]), [(0, 0)])
        self.assertEqual(probe_points((0, 0, -1, 9), [50]), [])
        self.assertEqual(len(probe_points((0, 0, 99, 99), [20, 80])), 9)      # the centre is added


class OccludedTest(unittest.TestCase):
    def cover(self, box, the_contract=None, ok_flags="-", **facts):
        semantic, tree = with_node(box, **dict({"bg": 255}, **facts))
        semantic[2] = sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn", flags=ok_flags)
        return run(semantic, tree, the_contract=the_contract)

    def test_a_cover_on_the_last_grid_column_is_a_finding_one_pixel_right_none(self):
        found = only(self.cover((88, 90, 139, 159)), "occluded-target")
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "occluded-target", ["ok"])])
        self.assertEqual((found[0]["observed"]["grid_points_covered"], found[0]["observed"]["covered_by"],
                          found[0]["observed"]["part"]), (3, [{"key": "x"}], "covered"))
        self.assertEqual(self.cover((89, 90, 139, 159)), [])

    def test_the_disc_inside_its_radius_is_a_finding_just_outside_none(self):
        # no grid point in either; the centre 58,125 is 11.18 px from the first box and 12.17 px from the second
        self.assertEqual(checks(self.cover((60, 112, 62, 114))), ["occluded-target"])
        self.assertEqual(self.cover((60, 111, 62, 113)), [])

    def test_with_a_pending_panel_the_disc_is_pending_and_the_grid_still_judged(self):
        c = contract(PANEL_PENDING)
        pend = expected_id("ui-scene", "contract-pending", ["occluded-target", "panel.diagonal_in"], stateless=True)
        found = self.cover((60, 112, 62, 114), the_contract=c)
        self.assertIn(pend, [f["id"] for f in found])
        self.assertEqual(only(found, "occluded-target"), [])
        self.assertEqual(len(only(self.cover((88, 90, 139, 159), the_contract=c), "occluded-target")), 1)

    def test_what_does_not_cover(self):
        self.assertEqual(self.cover((88, 90, 139, 159), bg=0), [])                     # transparent, not clickable
        self.assertEqual(self.cover((88, 90, 139, 159), hidden=1), [])
        self.assertEqual(self.cover((88, 90, 139, 159), ok_flags="I"), [])             # declared inert
        self.assertEqual(checks(self.cover((88, 90, 139, 159), bg=0, clickable=1)), ["occluded-target"])

    def test_a_scene_node_inside_the_target_covers_it_its_own_label_does_not(self):
        semantic, tree = with_node((88, 102, 100, 140), parent=3, bg=255)
        self.assertEqual(checks(only(run(semantic, tree), "occluded-target")), ["occluded-target"])
        semantic, tree = base()
        tree.nodes[4]["fit"]["glyphs"] = "50,120,90,130"                             # the OK label's glyphs on 88,125
        self.assertEqual(only(run(semantic, tree), "occluded-target"), [])

    def test_a_later_label_covers_with_its_drawn_glyphs_only(self):
        semantic, tree = base()
        tree.label(0, "x", (80, 120, 99, 135), glyphs="86,122,90,130")
        semantic.append(sem("x", "text", "x", (80, 120, 20, 16), style="body"))
        self.assertEqual(checks(only(run(semantic, tree), "occluded-target")), ["occluded-target"])
        semantic, tree = base()
        tree.label(0, "x", (80, 120, 99, 135), glyphs="89,122,90,123")
        semantic.append(sem("x", "text", "x", (80, 120, 20, 16), style="body"))
        self.assertEqual(only(run(semantic, tree), "occluded-target"), [])

    def test_a_dimmed_clickable_modal_scrim_over_every_probe_point_makes_the_target_inert(self):
        # R7: a scrim before a dialog card (capture-modal-inert), clickable, background opacity above 0
        def modal(scrim_box=(0, 0, 319, 239), bg=82, clickable=1):
            semantic, tree = base()
            tree.node(0, "lv_obj", scrim_box, clickable=clickable, bg=bg)
            tree.node(0, "lv_obj", (60, 160, 259, 229), clickable=1, bg=255)
            x1, y1, x2, y2 = scrim_box
            semantic += [sem("sc", "scrim", "", (x1, y1, x2 - x1 + 1, y2 - y1 + 1)),
                         sem("card", "dialog", "", (60, 160, 200, 70))]
            return run(semantic, tree)
        self.assertEqual(modal(), [])
        for broken in (dict(bg=0), dict(clickable=0), dict(scrim_box=(0, 0, 87, 239))):
            found = modal(**broken)
            self.assertEqual(checks(found), ["overlay-policy"], broken)       # one cause, one finding (overlay owns it)
            self.assertEqual(found[0]["observed"]["basis"], "sealed")

    def test_a_bare_inert_panel_grants_nothing(self):
        # the reviewer's case: one transparent panel with I painted over everything silences no occlusion
        semantic, tree = with_node((88, 90, 139, 159), bg=255)
        tree.node(0, "lv_obj", (0, 0, 319, 239))
        semantic.append(sem("p", "panel", "", (0, 0, 320, 240), flags="I", enabled=0))
        self.assertEqual([f["id"] for f in run(semantic, tree)], [expected_id("ui-scene", "occluded-target", ["ok"])])

    def test_a_layer_is_unreachable_without_a_free_square_of_the_touch_floor(self):
        # the kiosk's persistent banner: a scrim with an intent whose card has its rectangle
        def scrim(card_box):
            semantic, tree = base()
            node = tree.node(0, "lv_obj", (120, 160, 319, 239), clickable=1)
            tree.node(node, "lv_obj", card_box, clickable=1, bg=255)
            x1, y1, x2, y2 = card_box
            semantic += [sem("s", "scrim", "", (120, 160, 200, 80), intent="9:0"),
                         sem("c", "banner", "", (x1, y1, x2 - x1 + 1, y2 - y1 + 1))]
            return only(run(semantic, tree), "occluded-target")
        found = scrim((120, 160, 319, 239))
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in found],
                         [(expected_id("ui-scene", "occluded-target", ["s"]), "layer-unreachable")])
        self.assertEqual(len(scrim((120, 160, 272, 239))), 1)                  # a free band 47 px wide: too narrow
        self.assertEqual(scrim((120, 160, 271, 239)), [])                      # 48 px: one touch target fits
        self.assertEqual(scrim((230, 200, 289, 229)), [])                      # the card moved: a wide free band


class OverlayTest(unittest.TestCase):
    def layer(self, role, flags="-", box=(0, 90, 159, 159), before=False, clickable=0, policy="-", scrim=False,
              bg=0, ok=None):
        semantic, tree = base()
        semantic[2] = ok or sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn", flags=flags)
        x1, y1, x2, y2 = box
        rect = (x1, y1, x2 - x1 + 1, y2 - y1 + 1)
        added = ([sem("sc", "scrim", "", rect)] if scrim else []) + [sem("veil", role, "", rect, policy=policy)]
        card_bg = 255 if role in ("dialog", "banner", "snackbar") else bg
        if before:
            tree.nodes.insert(1, {"parent": 0, "depth": 1, "cls": "lv_obj", "box": box, "hidden": 0, "clickable": 0,
                                  "clip": -1, "scroll": -1, "bg": card_bg, "exact": 1, "grad": 0, "image": 0,
                                  "label": None, "fit": None, "colour": "ffffff"})
            for node in tree.nodes[2:]:
                node["parent"] = node["parent"] + 1 if node["parent"] >= 1 else node["parent"]
            semantic = added + semantic
        else:
            if scrim:
                tree.node(0, "lv_obj", box, clickable=clickable, bg=bg)
            tree.node(0, "lv_obj", box, clickable=clickable, bg=card_bg)
            semantic = semantic + added
        return run(semantic, tree)

    def test_a_sealed_modal_layer_over_an_enabled_control(self):
        found = self.layer("dialog")
        self.assertEqual([(f["id"], f["observed"]["basis"]) for f in found],
                         [(expected_id("ui-scene", "overlay-policy", ["veil", "ok", "captures"]), "sealed")])

    def test_a_pass_through_layer_captures_only_where_it_is_rendered_clickable(self):
        # not clickable: it takes no tap, it only hides the control (occluded-target's)
        self.assertEqual(checks(self.layer("snackbar")), ["occluded-target"])
        found = self.layer("snackbar", clickable=1)
        self.assertEqual([(f["id"], f["observed"]["policy"], f["observed"]["basis"]) for f in found],
                         [(expected_id("ui-scene", "overlay-policy", ["veil", "ok", "captures"]), "pass-through",
                           "rendered")])
        self.assertEqual(checks(self.layer("banner", scrim=True, clickable=1)), ["overlay-policy"])

    def test_an_inert_control_passes_under_a_modal_only_a_flagged_one_passes_under_any(self):
        self.assertEqual(self.layer("dialog", flags="I"), [])
        self.assertEqual(checks(self.layer("snackbar", flags="I", clickable=1)), [])

    def test_a_layer_below_or_beside_is_no_finding(self):
        self.assertEqual(self.layer("dialog", before=True), [])
        self.assertEqual(self.layer("dialog", box=(108, 90, 159, 159)), [])           # one pixel right of the box

    def test_a_scrim_takes_its_cards_policy_and_the_pair_is_judged_once(self):
        self.assertEqual([f["id"] for f in self.layer("dialog", scrim=True)],
                         [expected_id("ui-scene", "overlay-policy", ["sc", "ok", "captures"])])
        self.assertEqual(checks(self.layer("banner", scrim=True)), ["occluded-target"])   # the opaque card hides it

    def test_a_scrim_without_a_card_and_a_policy_in_the_scene_that_is_not_the_sealed_one(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 180, 319, 239), clickable=1)
        semantic.append(sem("sc", "scrim", "", (0, 180, 320, 60)))
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in run(semantic, tree)],
                         [(expected_id("ui-scene", "overlay-policy", ["sc", "no-card"]), "no-card")])
        self.assertEqual(only(self.layer("banner", policy="pass-through"), "overlay-policy"), [])
        self.assertEqual([f["id"] for f in only(self.layer("banner", policy="capture-modal-inert"), "overlay-policy")],
                         [expected_id("ui-scene", "overlay-policy", ["veil", "contradicts"])])

    def test_a_layer_role_without_sealed_rows_or_with_disagreeing_rows_is_contract_incomplete(self):
        def edit(text, rows):
            return text.replace('[[input_layer]]\nlayer = "banner"', rows + '[[input_layer]]\nlayer = "banner_x"')
        both = contract(lambda t: edit(t, '[[input_layer]]\nlayer = "banner_y"\nblocks_input_below = true\n'
                                       'tap_outside_dismisses = false\naccepts_input = true\n'
                                       'provenance = "spec:ui-rules.md#presentation"\n'))
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 180, 319, 239), bg=255)
        semantic.append(sem("b", "banner", "", (0, 180, 320, 60)))
        self.assertEqual([f["id"] for f in run(semantic, tree, the_contract=both)],
                         [expected_id("ui-scene", "contract-incomplete", ["input-layer", "banner"], stateless=True)])
        none = contract(lambda t: t.replace('layer = "banner"', 'layer = "notice"'))
        self.assertEqual([f["id"] for f in run(semantic, tree, the_contract=none)],
                         [expected_id("ui-scene", "contract-incomplete", ["input-layer", "banner"], stateless=True)])

    def test_an_undeclared_capturing_node_is_named_by_class_and_box(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 0, 319, 239), clickable=1)
        found = only(run(semantic, tree), "overlay-policy")
        name = "node/lv_obj/0/0/319/239"
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "overlay-policy", ["undeclared", name, "ok"])])
        self.assertEqual(found[0]["observed"]["capturing"], {"class": "lv_obj", "box": [0, 0, 319, 239], "target": name})


class SpacingTest(unittest.TestCase):
    def second(self, x, intent="2:0", the_contract=None, role="button"):
        semantic, tree = base()
        button = tree.node(0, "lv_button", (x, 100, x + 99, 149), clickable=1, bg=255)
        tree.label(button, "No", (x + 40, 117, x + 59, 132))
        semantic.append(sem("no", role, "No" if role == "button" else "", (x, 100, 100, 50), intent=intent,
                            style="btn" if role == "button" else 0))
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

    def test_an_overlap_is_hard_unless_allowed_one_intent_and_a_layer_are_never_compared(self):
        self.assertEqual([f["id"] for f in self.second(100)],
                         [expected_id("ui-scene", "target-spacing", ["no", "ok", "overlap"])])
        allowed = contract(lambda t: t.replace("hit_overlap_allowed           = { value = false",
                                               "hit_overlap_allowed           = { value = true"))
        self.assertEqual(self.second(100, the_contract=allowed), [])
        self.assertEqual(self.second(109, intent="1:0"), [])
        self.assertEqual(self.second(100, role="scrim"), [])

    def test_pending_mm_spacing_still_judges_the_overlap(self):
        c = contract(PANEL_PENDING)
        pend = expected_id("ui-scene", "contract-pending", ["target-spacing", "panel.diagonal_in"], stateless=True)
        self.assertEqual([f["id"] for f in self.second(109, the_contract=c)], [pend])
        self.assertEqual(sorted(f["id"] for f in self.second(100, the_contract=c)),
                         sorted([pend, expected_id("ui-scene", "target-spacing", ["no", "ok", "overlap"])]))


class BoundsTest(unittest.TestCase):
    def panel(self, box, parent=0, **facts):
        semantic, tree = with_node(box, key="edge", parent=parent, **facts)
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

    def test_a_scrolling_viewport_excuses_its_children_a_scrolling_screen_does_not(self):
        semantic, tree = base()
        view = tree.node(0, "lv_obj", (0, 160, 159, 199))
        tree.node(view, "lv_obj", (0, 190, 159, 259), scroll=view)
        semantic += [sem("view", "panel", "", (0, 160, 160, 40)), sem("item", "panel", "", (0, 190, 160, 70))]
        self.assertEqual(only(run(semantic, tree), "node-out-of-bounds"), [])
        self.assertEqual(len(self.panel((280, 200, 320, 239), scroll=0)), 1)
        semantic, tree = base()
        view = tree.node(0, "lv_obj", (0, 160, 159, 199))
        tree.node(view, "lv_obj", (0, 190, 159, 259))
        semantic += [sem("view", "panel", "", (0, 160, 160, 40), flags="S"), sem("item", "panel", "", (0, 190, 160, 70))]
        self.assertEqual(only(run(semantic, tree), "node-out-of-bounds"), [])
        semantic[-2] = sem("view", "panel", "", (0, 160, 160, 40))
        self.assertEqual(sorted(f["observed"]["part"] for f in only(run(semantic, tree), "node-out-of-bounds")),
                         ["parent", "window"])


class OverlapTest(unittest.TestCase):
    def second_text(self, y, layer=False):
        semantic, tree = base()
        parent = 0
        if layer:
            parent = tree.node(0, "lv_obj", (0, 0, 319, 239), bg=255)
            semantic.append(sem("sheet", "banner", "", (0, 0, 320, 240)))
        tree.label(parent, "More", (8, y, 207, y + 23))
        semantic.append(sem("more", "text", "More", (8, y, 200, 24), style="body"))
        return only(run(semantic, tree), "text-overlap")

    def test_touching_rows_pass_one_shared_row_fails(self):
        self.assertEqual(self.second_text(64), [])
        self.assertEqual([f["id"] for f in self.second_text(63)],
                         [expected_id("ui-scene", "text-overlap", ["body", "more"])])

    def test_texts_in_different_layers_are_not_compared(self):
        self.assertEqual(self.second_text(63, layer=True), [])


if __name__ == "__main__":
    unittest.main()
