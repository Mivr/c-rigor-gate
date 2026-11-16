"""The O2 checks of the ui-scene judge (U06, P004 3.1): touch-target-small, font-below-min, hierarchy-violated, raw-text,
wrap-policy-undeclared, and toggle-group-indistinct (O2 + O3, one state). Each: the positive case, the nearest negative
case on each side of its threshold, the pending case where the check reads a value that may be pending, exact ids."""

import unittest

from tests.test_ui_judge_helpers import Tree, add_lang, base, checks, contract, expected_id, pending, run, sem

PANEL_PENDING = lambda t: pending(t, "diagonal_in", 'diagonal_in = { pending = "9", provenance = "spec:P004#11-q9" }')


def with_ok(rect, **changes):
    """The base scene with the ok button's scene record and rendered box at `rect` (x, y, w, h)."""
    semantic, _tree = base()
    fields = dict(intent="1:0", style="btn")
    fields.update(changes)
    semantic[2] = sem("ok", fields.pop("role", "button"), fields.pop("label", "OK"), rect, **fields)
    x, y, w, h = rect
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    tree.label(0, "Body text", (8, 40, 207, 63))
    button = tree.node(0, "lv_button", (x, y, x + w - 1, y + h - 1), clickable=1, bg=255)
    tree.label(button, "OK", (x + 2, y + 2, x + 21, y + 17))
    return semantic, tree


def only(found, check):
    return [f for f in found if f["check"] == check or f["observed"].get("check") == check]


class TouchTargetTest(unittest.TestCase):
    def found(self, rect, the_contract=None, **changes):
        return only(run(*with_ok(rect, **changes), the_contract=the_contract), "touch-target-small")

    def test_one_below_the_dp_floor_on_either_side_is_a_finding_at_the_floor_none(self):
        self.assertEqual(self.found((8, 100, 100, 48)), [])
        self.assertEqual(self.found((8, 100, 48, 50)), [])
        for rect in ((8, 100, 100, 47), (8, 100, 47, 50)):
            found = self.found(rect)
            self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "touch-target-small", ["ok", "dp"])])
            self.assertEqual(found[0]["observed"]["limit"], 48)

    def test_the_typographic_roles_minimum_wins_over_a_lower_floor(self):
        c = contract(lambda t: t.replace('role = "key_label"\nfont_px_min = 14\ntouch_dp_min = 48',
                                         'role = "key_label"\nfont_px_min = 14\ntouch_dp_min = 60'))
        self.assertEqual(self.found((8, 100, 100, 60), c), [])
        self.assertEqual([f["observed"]["limit"] for f in self.found((8, 100, 100, 59), c)], [60])

    def test_the_mm_floor_once_the_panel_is_sealed(self):
        # touch_min_mm 14 at 40 ppi is 22.047 px; a dp floor of 10 leaves only the mm floor (a panel has no role)
        c = contract(lambda t: t.replace("touch_min_dp                  = { value = 48",
                                         "touch_min_dp                  = { value = 10")
                     .replace("touch_dp_min = 48", "touch_dp_min = 10"))
        self.assertEqual(self.found((8, 100, 23, 60), c, role="panel", label=""), [])
        found = self.found((8, 100, 22, 60), c, role="panel", label="")
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "touch-target-small", ["ok", "mm"])])

    def test_a_pending_panel_reports_contract_pending_once_and_still_judges_dp(self):
        found = self.found((8, 100, 100, 47), contract(PANEL_PENDING))
        self.assertEqual(sorted(f["id"] for f in found), sorted([
            expected_id("ui-scene", "touch-target-small", ["ok", "dp"]),
            expected_id("ui-scene", "contract-pending", ["touch-target-small", "panel.diagonal_in"], stateless=True)]))
        item = [f for f in found if f["check"] == "contract-pending"][0]
        self.assertEqual((item["severity"], item["state"], item["observed"]),
                         ("error", None, {"check": "touch-target-small", "entry": "panel.diagonal_in", "question": "9"}))

    def test_disabled_inert_hidden_or_intentless_nodes_are_not_targets(self):
        for change in ({"enabled": 0}, {"flags": "I"}, {"flags": "D"}, {"flags": "H"}, {"intent": "-"}):
            self.assertEqual(self.found((8, 100, 100, 40), **change), [], change)


class FontTest(unittest.TestCase):
    def body(self, style, the_contract=None):
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style=style)
        return only(run(semantic, tree, the_contract=the_contract), "font-below-min")

    def test_a_variant_style_one_px_below_its_roles_minimum_is_a_finding_at_it_none(self):
        # small_body (scale caption) is a [[style_role]] variant of the role body, whose minimum is 14 px
        c13 = contract(lambda t: t.replace("caption  = { value = 10", "caption  = { value = 13"))
        c14 = contract(lambda t: t.replace("caption  = { value = 10", "caption  = { value = 14"))
        found = self.body("small_body", c13)
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "font-below-min", ["body"])])
        self.assertEqual(found[0]["observed"], {"stage": "O2", "key": "body", "font_px": 13, "limit": 14})
        self.assertEqual(self.body("small_body", c14), [])
        self.assertEqual(self.body("big_body"), [])

    def test_a_role_without_a_minimum_is_contract_incomplete(self):
        c = contract(lambda t: t.replace('[[role_min]]\nrole = "body"\nfont_px_min = 14\ntouch_dp_min = 0\n'
                                         'provenance = "spec:ui-look.md#4.1"\n', ""))
        self.assertIn(expected_id("ui-scene", "contract-incomplete", ["role-min", "body"], stateless=True),
                      [f["id"] for f in run(*base(), the_contract=c)])


def importance_pending(text):
    start, end = text.index("[[importance]]"), text.index("[[toggle_group]]")
    text = text[:start] + text[end:]
    return text.replace("[[style]]", '[pending_tables]\nimportance = { pending = "7", provenance = "spec:P004#11-q7" }'
                        '\n\n[[style]]', 1)


def ratio_pending(text):
    return pending(text, "hierarchy_ratio_k", 'hierarchy_ratio_k = { pending = "5", provenance = '
                   '"design:P004#3.10-hierarchy_ratio_k" }')


class HierarchyTest(unittest.TestCase):
    def found(self, body_style="body", importance="-", the_contract=None, semantic=None):
        base_semantic, tree = base()
        semantic = semantic or base_semantic
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style=body_style, importance=importance)
        return only(run(semantic, tree, the_contract=the_contract), "hierarchy-violated") + \
            [f for f in run(semantic, tree, the_contract=the_contract) if f["check"] == "contract-incomplete"]

    def test_the_ratio_k_at_equality_passes_and_one_px_more_fails(self):
        # title 20 px; level 2 at 16 px: 1.25 x 16 = 20 (equal: passes); at 17 px 21.25 > 20 fails
        at16 = contract(lambda t: t.replace("body     = { value = 14", "body     = { value = 16"))
        at17 = contract(lambda t: t.replace("body     = { value = 14", "body     = { value = 17"))
        self.assertEqual(self.found(the_contract=at16), [])
        found = self.found(the_contract=at17)
        self.assertEqual([f["id"] for f in found], [expected_id("ui-scene", "hierarchy-violated", ["ratio"])])
        self.assertEqual(found[0]["observed"]["k"], "5/4")

    def test_a_level_two_text_larger_than_level_one_breaks_the_rank(self):
        found = self.found(body_style="big_body")
        self.assertEqual([(f["id"], f["observed"]["larger"]) for f in found],
                         [(expected_id("ui-scene", "hierarchy-violated", ["rank"]), ["body"])])

    def test_a_level_in_the_scene_is_normal_as_the_contracts_and_a_finding_otherwise(self):
        self.assertEqual(self.found(importance="2"), [])
        found = self.found(importance="3")
        self.assertEqual([(f["id"], f["observed"]["declared"], f["observed"]["contract"]) for f in found],
                         [(expected_id("ui-scene", "hierarchy-violated", ["body", "level"]), 3, 2)])

    def test_two_roles_of_one_size_and_more_than_three_levels(self):
        semantic, tree = base()
        semantic[0] = sem("title", "text", "Title", (8, 8, 200, 24), style="btn")    # key_label: 14 px like body
        semantic[2] = sem("ok", "panel", "", (8, 100, 100, 50))
        self.assertEqual([f["id"] for f in only(run(semantic, tree), "hierarchy-violated")],
                         [expected_id("ui-scene", "hierarchy-violated", ["single-size"])])
        c = contract(lambda t: t + '\n[[importance]]\nlevel = 4\nroles = ["extra"]\nprovenance = "owner:Q7"\n'
                     '[[style]]\nid = "extra"\ntoken = 12\nscale = "staff"\nweight = 400\nusage = "text"\n'
                     'provenance = "spec:ui-look.md#4.2"\n[[role]]\nid = "extra"\nstyle = "extra"\nalign = "centre"\n'
                     'provenance = "spec:ui-look.md#4.1"\n[[role_min]]\nrole = "extra"\nfont_px_min = 12\n'
                     'touch_dp_min = 0\nprovenance = "spec:ui-look.md#4.1"\n[[role_wrap]]\nrole = "extra"\n'
                     'scope = "default"\nprovenance = "spec:ui-look.md#5"\n[[role_wrap]]\nrole = "caption"\n'
                     'scope = "default"\nprovenance = "spec:ui-look.md#5"\n'
                     '[[style_line]]\nstyle = "extra"\nline_height_px = 16\nprovenance = "product-baseline:abd8895"\n')
        semantic, tree = base()
        semantic += [sem("cap", "text", "c", (8, 70, 50, 16), style="caption"),
                     sem("x", "text", "x", (60, 70, 50, 16), style=12)]
        tree.label(0, "c", (8, 70, 57, 85))
        tree.label(0, "x", (60, 70, 109, 85))
        found = only(run(semantic, tree, the_contract=c), "hierarchy-violated")
        self.assertEqual([f["observed"] for f in found], [{"stage": "O2", "part": "levels", "levels": [1, 2, 3, 4]}])

    def test_pending_importance_or_ratio_skips_only_the_parts_that_need_them(self):
        both = contract(lambda t: ratio_pending(importance_pending(t)))
        found = self.found(body_style="big_body", the_contract=both)
        self.assertEqual(sorted(f["id"] for f in found), [
            expected_id("ui-scene", "contract-pending", ["hierarchy-violated", "table:importance"], stateless=True)])
        semantic, _tree = base()
        semantic[0] = sem("title", "text", "Title", (8, 8, 200, 24), style="btn")
        semantic[2] = sem("ok", "panel", "", (8, 100, 100, 50))
        found = self.found(the_contract=both, semantic=semantic)
        self.assertIn(expected_id("ui-scene", "hierarchy-violated", ["single-size"]), [f["id"] for f in found])
        ratio = contract(ratio_pending)
        self.assertEqual([f["id"] for f in self.found(body_style="big_body", the_contract=ratio)],
                         [expected_id("ui-scene", "hierarchy-violated", ["rank"])])
        at17 = contract(lambda t: ratio_pending(t).replace("body     = { value = 14", "body     = { value = 17"))
        self.assertEqual([f["id"] for f in self.found(the_contract=at17)], [
            expected_id("ui-scene", "contract-pending", ["hierarchy-violated", "thresholds.hierarchy_ratio_k"],
                        stateless=True)])


class TextTest(unittest.TestCase):
    def body(self, label, style="body", flags="-", role="text", wrap="-"):
        semantic, _tree = base()
        semantic[1] = sem("body", role, label, (8, 40, 200, 24), style=style, flags=flags, wrap=wrap)
        tree = Tree()
        tree.label(0, "Title", (8, 8, 207, 31))
        tree.label(0, label, (8, 40, 207, 63))
        button = tree.node(0, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
        tree.label(button, "OK", (48, 117, 67, 132))
        return run(semantic, tree)

    def test_an_empty_text_or_countdown_is_raw_text_one_character_is_not(self):
        for role in ("text", "countdown"):
            self.assertEqual([f["id"] for f in self.body("", role=role)],
                             [expected_id("ui-scene", "raw-text", ["body", "empty"])])
        self.assertEqual(self.body("x"), [])
        self.assertEqual(self.body("", flags="H"), [])

    def test_a_role_without_a_wrap_scope_is_contract_incomplete_once_per_role(self):
        found = self.body("Body text", style="caption")
        self.assertEqual([(f["id"], f["state"]) for f in found],
                         [(expected_id("ui-scene", "contract-incomplete", ["role-wrap", "caption"], stateless=True), None)])
        self.assertEqual(self.body("Body text", wrap="default"), [])

    def test_an_element_scope_wins_over_the_roles_and_gives_one_to_a_role_without_one(self):
        c = contract(lambda t: t + '[[element]]\nid = "the_body"\nkey = "body"\nwrap = "single_line"\n'
                     'provenance = "spec:ui-look.md#L296"\n')
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="caption", wrap="single_line")
        self.assertEqual(run(semantic, tree, the_contract=c), [])
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="body", wrap="default")
        self.assertEqual([f["observed"]["contract"] for f in run(semantic, tree, the_contract=c)], ["single_line"])

    def test_a_scope_in_the_scene_that_is_not_the_contracts_contradicts(self):
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in self.body("Body text", wrap="single_line")],
                         [(expected_id("ui-scene", "wrap-policy-undeclared", ["body", "contradicts"]), "contradicts")])


class ToggleTest(unittest.TestCase):
    def lang(self, en_colour="282a2f", en_style="lang_off", drop=None, hidden=False):
        semantic, tree = base()
        add_lang(tree)
        tree.nodes[-2]["colour"] = en_colour
        semantic += [sem("lang_bg", "button", "BG", (216, 8, 48, 48), intent="8:0", style="lang_on"),
                     sem("lang_en", "button", "EN", (272, 8, 48, 48), intent="8:1", style=en_style,
                         flags="H" if hidden else "-")]
        if drop is not None:
            del semantic[drop]
        return only(run(semantic, tree), "toggle-group-indistinct")

    def test_the_members_differ_in_every_declared_mark(self):
        self.assertEqual(self.lang(), [])

    def test_one_mark_alike_is_a_finding_of_that_mark(self):
        self.assertEqual([f["id"] for f in self.lang(en_colour="2b4678")],
                         [expected_id("ui-scene", "toggle-group-indistinct", ["language", "bg"])])
        self.assertEqual([f["id"] for f in self.lang(en_style="lang_on")],
                         [expected_id("ui-scene", "toggle-group-indistinct", ["language", "style"])])

    def test_a_member_missing_while_another_shows_is_a_finding_none_shown_is_none(self):
        self.assertEqual([f["observed"]["part"] for f in self.lang(drop=-1)], ["members"])
        semantic, tree = base()
        self.assertEqual(only(run(semantic, tree), "toggle-group-indistinct"), [])

    def test_three_members_need_exactly_one_odd_one(self):
        c = contract(lambda t: t.replace('members = ["lang_bg", "lang_en"]', 'members = ["lang_bg", "lang_en", "x"]')
                     + '[[element]]\nid = "x"\nkey = "x"\nprovenance = "spec:ui-look.md#4.2"\n')
        semantic, tree = base()
        add_lang(tree)
        button = tree.node(0, "lv_button", (160, 180, 207, 227), clickable=1, bg=255, colour="282a2f")
        tree.label(button, "X", (170, 190, 189, 205))
        semantic += [sem("lang_bg", "button", "BG", (216, 8, 48, 48), intent="8:0", style="lang_on"),
                     sem("lang_en", "button", "EN", (272, 8, 48, 48), intent="8:1", style="lang_off"),
                     sem("x", "button", "X", (160, 180, 48, 48), intent="8:2", style="lang_off")]
        self.assertEqual(only(run(semantic, tree, the_contract=c), "toggle-group-indistinct"), [])
        tree.nodes[button]["colour"] = "000000"
        self.assertEqual([f["observed"]["part"] for f in only(run(semantic, tree, the_contract=c),
                                                               "toggle-group-indistinct")], ["bg"])


if __name__ == "__main__":
    unittest.main()
