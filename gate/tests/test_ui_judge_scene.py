"""The O2 checks of the ui-scene judge (U06, P004 3.1): touch-target-small, font-below-min, hierarchy-violated, raw-text,
wrap-policy-undeclared. Each: the positive case, the nearest negative case on each side of its threshold, the pending
case where the check reads a value that may be pending, exact ids."""

import unittest

from tests.test_ui_judge_helpers import Tree, base, checks, contract, expected_id, pending, run, sem


def with_ok(**changes):
    """The base scene with the ok button's scene record and rendered box changed (rect given as x, y, w, h)."""
    semantic, _tree = base()
    fields = dict(key="ok", role="key_label", label="OK", rect=(8, 100, 100, 50), intent="1:0", style="btn",
                  importance="2", wrap="single_line")
    fields.update(changes)
    semantic[2] = sem(fields.pop("key"), fields.pop("role"), fields.pop("label"), fields.pop("rect"), **fields)
    return semantic


def tree_with_button(rect, role_label="OK"):
    x, y, w, h = rect
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    tree.label(0, "Body text", (8, 40, 207, 63))
    button = tree.node(0, "lv_button", (x, y, x + w - 1, y + h - 1), clickable=1, bg=255)
    tree.label(button, role_label, (x + 2, y + 2, x + 21, y + 17))
    return tree


class TouchTargetTest(unittest.TestCase):
    def found(self, rect, the_contract=None, role="key_label"):
        label = "OK" if role == "key_label" else ""          # a node of a non-text role shows no text
        return [f for f in run(with_ok(rect=rect, role=role, label=label), tree_with_button(rect),
                               the_contract=the_contract)
                if f["check"] == "touch-target-small" or f["observed"].get("check") == "touch-target-small"]

    def test_one_below_the_dp_floor_on_either_side_is_a_finding_at_the_floor_none(self):
        self.assertEqual(self.found((8, 100, 100, 48)), [])
        self.assertEqual(self.found((8, 100, 48, 50)), [])
        for rect in ((8, 100, 100, 47), (8, 100, 47, 50)):
            found = self.found(rect)
            self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "touch-target-small", ["ok", "dp"])])
            self.assertEqual(found[0]["observed"]["limit"], 48)

    def test_the_role_minimum_wins_over_a_lower_floor(self):
        c = contract(lambda t: t.replace('touch_dp_min = 48\nprovenance = "spec:ui-look.md#4.1"',
                                         'touch_dp_min = 60\nprovenance = "spec:ui-look.md#4.1"'))
        self.assertEqual(self.found((8, 100, 100, 60), c), [])
        self.assertEqual([f["observed"]["limit"] for f in self.found((8, 100, 100, 59), c)], [60])

    def test_the_mm_floor_once_the_panel_is_sealed(self):
        # touch_min_mm 14 at 40 ppi is 22.047 px; a dp floor of 10 leaves only the mm floor
        c = contract(lambda t: t.replace("touch_min_dp                  = { value = 48",
                                         "touch_min_dp                  = { value = 10")
                     .replace("touch_dp_min = 48", "touch_dp_min = 10"))
        self.assertEqual(self.found((8, 100, 23, 60), c, role="panel"), [])
        found = self.found((8, 100, 22, 60), c, role="panel")
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "touch-target-small", ["ok", "mm"])])

    def test_a_pending_panel_reports_contract_pending_once_and_still_judges_dp(self):
        c = contract(lambda t: pending(t, "diagonal_in", 'diagonal_in = { pending = "9", provenance = "spec:P004#11-q9" }'))
        found = self.found((8, 100, 100, 47), c)
        self.assertEqual(sorted(f["id"] for f in found), sorted([
            expected_id("ui-scene", "touch-target-small", ["ok", "dp"]),
            expected_id("ui-scene", "contract-pending", ["touch-target-small", "panel.diagonal_in"], stateless=True)]))
        item = [f for f in found if f["check"] == "contract-pending"][0]
        self.assertEqual((item["severity"], item["state"], item["observed"]),
                         ("error", None, {"check": "touch-target-small", "entry": "panel.diagonal_in", "question": "9"}))

    def test_disabled_inert_hidden_or_intentless_nodes_are_not_targets(self):
        for change in ({"enabled": 0}, {"flags": "inert"}, {"flags": "hidden"}, {"intent": "-"}):
            semantic = with_ok(rect=(8, 100, 100, 40), **change)
            self.assertEqual([f for f in run(semantic, tree_with_button((8, 100, 100, 40)))
                              if f["check"] == "touch-target-small"], [], change)


class FontTest(unittest.TestCase):
    def body(self, style, the_contract=None):
        semantic, tree = base()
        semantic[1] = sem("body", "body", "Body text", (8, 40, 200, 24), style=style, importance="2", wrap="default")
        return [f for f in run(semantic, tree, the_contract=the_contract) if f["check"] == "font-below-min"]

    def test_a_style_one_px_below_the_role_minimum_is_a_finding_at_it_none(self):
        c13 = contract(lambda t: t.replace("caption  = { value = 10", "caption  = { value = 13"))
        c14 = contract(lambda t: t.replace("caption  = { value = 10", "caption  = { value = 14"))
        found = self.body("caption", c13)
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "font-below-min", ["body"])])
        self.assertEqual(found[0]["observed"], {"stage": "O2", "key": "body", "font_px": 13, "limit": 14})
        self.assertEqual(self.body("caption", c14), [])
        self.assertEqual(self.body("headline"), [])

    def test_a_role_without_a_minimum_is_contract_incomplete(self):
        c = contract(lambda t: t.replace('[[role_min]]\nrole = "body"\nfont_px_min = 14\ntouch_dp_min = 0\n'
                                         'provenance = "spec:ui-look.md#4.1"\n', ""))
        semantic, tree = base()
        found = run(semantic, tree, the_contract=c)
        self.assertIn(expected_id("ui-scene", "contract-incomplete", ["role-min", "body"], stateless=True),
                      [f["id"] for f in found])


class HierarchyTest(unittest.TestCase):
    def found(self, body_style="body", body_importance="2", the_contract=None, extra=()):
        semantic, tree = base()
        semantic[1] = sem("body", "body", "Body text", (8, 40, 200, 24), style=body_style, importance=body_importance,
                          wrap="default")
        return [f for f in run(semantic + list(extra), tree, the_contract=the_contract)
                if f["check"] in ("hierarchy-violated", "contract-pending", "contract-incomplete")]

    def test_the_ratio_k_at_equality_passes_and_one_px_more_fails(self):
        # title 20 px; level 2 at 16 px: 1.25 x 16 = 20 (equal: passes); at 17 px 21.25 > 20 fails
        at16 = contract(lambda t: t.replace("body     = { value = 14", "body     = { value = 16"))
        at17 = contract(lambda t: t.replace("body     = { value = 14", "body     = { value = 17"))
        self.assertEqual(self.found(the_contract=at16), [])
        found = self.found(the_contract=at17)
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "hierarchy-violated", ["ratio"])])
        self.assertEqual(found[0]["observed"]["k"], "5/4")

    def test_a_level_two_node_larger_than_level_one_breaks_the_rank(self):
        found = self.found(body_style="headline")
        self.assertEqual([(f["id"], f["observed"]["larger"]) for f in found],
                         [(expected_id("ui-scene", "hierarchy-violated", ["rank"]), ["body"])])

    def test_an_undeclared_or_wrong_level_is_a_finding(self):
        self.assertEqual([f["id"] for f in self.found(body_importance="-")],
                         [expected_id("ui-scene", "hierarchy-violated", ["body", "undeclared"])])
        found = self.found(body_importance="3")
        self.assertEqual([(f["id"], f["observed"]["declared"], f["observed"]["contract"]) for f in found],
                         [(expected_id("ui-scene", "hierarchy-violated", ["body", "level"]), 3, 2)])

    def test_two_roles_of_one_size_and_more_than_three_levels(self):
        semantic, tree = base()
        semantic[0] = sem("title", "title", "Title", (8, 8, 200, 24), style="body", importance="1", wrap="default")
        found = [f for f in run(semantic, tree) if f["check"] == "hierarchy-violated"]
        self.assertIn(expected_id("ui-scene", "hierarchy-violated", ["single-size"]), [f["id"] for f in found])
        c = contract(lambda t: t + '\n[[importance]]\nlevel = 4\nroles = ["extra"]\nprovenance = "owner:Q7"\n'
                     '[[role]]\nid = "extra"\nstyle = "caption"\nalign = "centre"\nprovenance = "spec:ui-look.md#4.1"\n')
        extra = [sem("cap", "caption", "c", (8, 70, 50, 16), style="caption", importance="3", wrap="default"),
                 sem("x", "extra", "x", (60, 70, 50, 16), style="caption", importance="4", wrap="default")]
        tree.label(0, "c", (8, 70, 57, 85))
        tree.label(0, "x", (60, 70, 109, 85))
        found = [f for f in run(semantic[:1] + base()[0][1:] + extra, tree, the_contract=c)
                 if f["check"] == "hierarchy-violated"]
        self.assertEqual([f["observed"] for f in found if f["observed"]["part"] == "levels"],
                         [{"stage": "O2", "part": "levels", "levels": [1, 2, 3, 4]}])

    def test_pending_importance_and_ratio_are_two_pending_findings_and_no_judgement(self):
        def edit(text):
            start = text.index("[[importance]]")
            end = text.index("[[toggle_group]]")
            text = text[:start] + text[end:]
            text = text.replace("[[style]]", '[pending_tables]\nimportance = { pending = "7", provenance = '
                                '"spec:P004#11-q7" }\n\n[[style]]', 1)
            return pending(text, "hierarchy_ratio_k", 'hierarchy_ratio_k = { pending = "5", provenance = '
                           '"design:P004#3.10-hierarchy_ratio_k" }')
        found = self.found(body_style="headline", the_contract=contract(edit))
        self.assertEqual(sorted(f["id"] for f in found), sorted([
            expected_id("ui-scene", "contract-pending", ["hierarchy-violated", "table:importance"], stateless=True),
            expected_id("ui-scene", "contract-pending", ["hierarchy-violated", "thresholds.hierarchy_ratio_k"],
                        stateless=True)]))


class TextTest(unittest.TestCase):
    def body(self, label, wrap="default", flags="-"):
        semantic, _tree = base()
        semantic[1] = sem("body", "body", label, (8, 40, 200, 24), style="body", importance="2", wrap=wrap,
                          flags=flags)
        tree = Tree()
        tree.label(0, "Title", (8, 8, 207, 31))
        tree.label(0, label, (8, 40, 207, 63))
        button = tree.node(0, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
        tree.label(button, "OK", (48, 117, 67, 132))
        return run(semantic, tree)

    def test_an_empty_text_node_is_raw_text_one_character_is_not(self):
        self.assertEqual([f["id"] for f in self.body("")], [expected_id("ui-scene", "raw-text", ["body", "empty"])])
        self.assertEqual(self.body("x"), [])
        self.assertEqual(self.body("", flags="hidden"), [])

    def test_an_undeclared_wrap_scope_is_wrap_policy_undeclared_and_unmeasurable_for_fit(self):
        found = self.body("Body text", wrap="-")
        self.assertEqual(sorted(f["id"] for f in found), sorted([
            expected_id("ui-scene", "wrap-policy-undeclared", ["body"]),
            expected_id("ui-fit", "fit-unmeasurable", ["body", "scope"])]))
        self.assertEqual(self.body("Body text", wrap="single_line"), [])
        self.assertEqual(checks(self.body("Body text", wrap="-", flags="hidden")), ["fit-unmeasurable"])


if __name__ == "__main__":
    unittest.main()
