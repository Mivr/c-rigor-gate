"""The `ui-render` judge (U07, docs/ui-judges-render.md) on hand-built observations: the ink checks (`invisible-node`,
`contrast-low`, `ink-unmeasurable`), the stage checks (`flag-mismatch`, `align-mismatch`, `line-height-mismatch`), the
WCAG arithmetic, the ink records' format, R7 for paint and the exception rules (the explorer's side:
test_ui_judge_render_explore.py)."""

import copy
import unittest

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import INK_FIELDS, parse_typed_line
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet
from rigor_lib.ui_judge_render_contrast import decide
from rigor_lib.ui_judge_render_ink import Ink, luminance, ratio, worst_contrast
from tests.test_ui_judge_helpers import (CANARY_CONTRACT, KEY, OPEN, TODAY, base, contract, expected_id, pending,
                                         sem, step)

BLACK_ON_WHITE = ("000000", "f0f0f0", "ffffff", "ffffff")


def modal():
    """(semantic, tree) of the base state under a correct modal: a full-window dimmed, clickable scrim with an intent
    and its opaque dialog card (the canary contract seals `dialog` capture-modal-inert)."""
    semantic, tree = base()
    tree.node(0, "lv_obj", (0, 0, 319, 239), clickable=1, bg=82, colour="000000")
    tree.node(0, "lv_obj", (200, 160, 299, 219), clickable=1, bg=255)
    semantic += [sem("scrim", "scrim", "", (0, 0, 320, 240), intent="9:0"),
                 sem("card", "dialog", "", (200, 160, 100, 60))]
    return semantic, tree


def ink_lines(tree, override=None):
    """One `ink` record per non-root node: 100 pixels of black text on white, unless `override` gives the node's own
    (a full record line without its `ink\\t<i>` head, or a `noink` reason)."""
    out = []
    for i, node in enumerate(tree.nodes):
        if node["parent"] == -1:
            continue
        given = (override or {}).get(i)
        if given in ("unstable", "transformed"):
            out.append("noink\t%d\t%s" % (i, given))
            continue
        x1, y1, x2, y2 = node["box"]
        count, colours = given if given is not None else (100, BLACK_ON_WHITE)
        box = "-" if count == 0 else "%d,%d,%d,%d" % (x1, y1, x2, y2)
        out.append("\t".join(["ink", str(i), str(count), box] + list(colours)))
    return out


def judged(semantic, tree, ink=None, gates=("ui-render",), the_contract=None, moved=False, finish=False):
    """The findings of one step with its ink (`ink`: an override dict, or False for a step without ink)."""
    tree.align_drawn = 2 if tree.align_drawn == 1 else tree.align_drawn     # the canary roles are centred
    judges = JudgeSet(list(gates), the_contract or contract(), KEY, TODAY)
    s = step(semantic, tree)
    if ink is not False:
        s.obs["ink"] = tuple(parse_typed_line(INK_FIELDS, line) for line in ink_lines(tree, ink))
        s.obs["ink_moved"] = moved
    found = judges.step_judge(s, PathSoFar([Step(0, OPEN)], 1), None)
    if finish:
        found = found + judges.finish(OPEN)
    return [{k: v for k, v in copy.deepcopy(f).items() if k != "_evidence"} for f in found]


def render(found, check=None):
    return sorted((f["check"], f["observed"].get("key"), f["observed"].get("part"), f["severity"])
                  for f in found if f["gate"] == "ui-render" and (check is None or f["check"] == check)
                  and f["check"] != "checks-examined")


class ContrastArithmeticTest(unittest.TestCase):
    def test_the_wcag_formula(self):
        self.assertEqual(luminance("000000"), 0.0)
        self.assertEqual(luminance("ffffff"), 1.0)
        self.assertAlmostEqual(ratio(luminance("ffffff"), luminance("000000")), 21.0)
        self.assertAlmostEqual(luminance("777777"), 0.18447, places=4)    # #777 on white is 4.48:1
        self.assertAlmostEqual(ratio(1.0, luminance("777777")), 4.478, places=3)

    def test_the_bounds_are_combined_text_extreme_against_the_nearest_background(self):
        def ink(lo, hi, bg_lo, bg_hi):
            return Ink(1, None, 10, (0, 0, 1, 1), lo, hi, bg_lo, bg_hi, "")
        # an antialiased black glyph on white: its lightest pixel is nearly white, the text colour is the darkest
        self.assertAlmostEqual(worst_contrast(ink("000000", "f0f0f0", "ffffff", "ffffff")), 21.0)
        # white on blue: the lightest ink pixel is the text colour
        self.assertAlmostEqual(worst_contrast(ink("1d52a6", "ffffff", "0d47a1", "0d47a1")),
                               ratio(1.0, luminance("0d47a1")))
        # the background spans two colours: the one nearest the text counts
        self.assertAlmostEqual(worst_contrast(ink("000000", "101010", "777777", "ffffff")),
                               ratio(luminance("777777"), 0.0))
        # both ink extremes inside the background interval: 1:1
        self.assertEqual(worst_contrast(ink("808080", "909090", "000000", "ffffff")), 1.0)


class InkFormatTest(unittest.TestCase):
    def test_a_broken_ink_reply_is_the_gates_error(self):
        semantic, tree = base()
        good = ink_lines(tree)
        cases = {"missing node": good[1:], "root": good + ["ink\t0\t1\t0,0,0,0\t" + "\t".join(BLACK_ON_WHITE)],
                 "colour": [good[0].replace("000000", "00000g")] + good[1:],
                 "box without ink": [good[0].replace("\t100\t", "\t0\t")] + good[1:],
                 "reason": good[:-1] + ["noink\t%d\tbusy" % (len(tree.nodes) - 1)]}
        for name, lines in cases.items():
            s = step(semantic, tree)
            s.obs["ink"] = tuple(parse_typed_line(INK_FIELDS, line) for line in lines)
            judges = JudgeSet(["ui-render"], contract(), KEY, TODAY)
            with self.assertRaisesRegex(InternalError, "ink facts break their own format", msg=name):
                judges.step_judge(s, PathSoFar([Step(0, OPEN)], 1), None)


class InkChecksTest(unittest.TestCase):
    def test_the_clean_state_has_no_render_finding_and_every_check_examined_nodes(self):
        found = judged(*base(lang=True), finish=True)
        self.assertEqual(render(found), [])
        totals = next(f for f in found if f["check"] == "checks-examined")["observed"]["totals"]
        self.assertTrue(all(v > 0 for v in totals.values()), totals)
        self.assertEqual([f for f in found if f["check"] == "check-vacuous"], [])

    def test_invisible_node_a_text_and_a_button_that_paint_nothing(self):
        semantic, tree = base()
        found = judged(semantic, tree, {2: (0, BLACK_ON_WHITE), 3: (0, BLACK_ON_WHITE)})
        self.assertEqual(render(found), [("invisible-node", "body", "node", "error"),
                                         ("invisible-node", "ok", "node", "error")])
        self.assertIn(expected_id("ui-render", "invisible-node", ["body", "node"]), [f["id"] for f in found])

    def test_a_button_whose_label_paints_nothing(self):
        semantic, tree = base()                       # the button's fill is its ink; its label OK paints nothing
        found = judged(semantic, tree, {4: (0, BLACK_ON_WHITE)})
        self.assertEqual(render(found), [("invisible-node", "ok", "text", "error")])

    def test_a_clipped_label_that_paints_nothing_is_ui_fits_only_when_ui_fit_reports_it(self):
        def clipped(index, gates, the_contract=None):
            semantic, tree = base()
            tree.nodes[index]["fit"]["clipped"] = 1
            found = judged(semantic, tree, {index: (0, BLACK_ON_WHITE)}, gates=gates, the_contract=the_contract,
                           finish=True)
            mine = [(f["observed"]["key"], f["observed"]["part"], f["observed"].get("clipped")) for f in found
                    if f["check"] == "invisible-node"]
            na = next(f for f in found if f["gate"] == "ui-render" and f["check"] == "checks-examined")["observed"]
            return mine, sorted(f["observed"].get("key") for f in found if f["check"] == "text-clipped"), \
                na.get("not_applicable", {}).get("invisible-node", 0)
        both = ("ui-fit", "ui-render")
        self.assertEqual(clipped(4, ("ui-render",)), ([("ok", "text", True)], [], 0))       # ui-render alone
        self.assertEqual(clipped(4, both), ([], ["ok"], 1))                                 # ui-fit's text-clipped
        clip_scope = contract(lambda t: t + '[[element]]\nid = "ok_el"\nkey = "ok"\nwrap = "clipped"\n'
                                           'provenance = "spec:ui-look.md#4.1"\n')
        self.assertEqual(clipped(4, both, clip_scope), ([("ok", "text", True)], [], 0))   # clip scope: no text-clipped
        self.assertEqual(clipped(2, ("ui-render",)), ([("body", "node", True)], [], 0))     # a pure text node
        self.assertEqual(clipped(2, both), ([], ["body"], 1))

    def test_a_cover_that_does_not_hide_the_ink_is_no_finding(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 30, 230, 70), bg=255)                      # opaque, but the body's ink is 100
        self.assertEqual(render(judged(semantic, tree), "invisible-node"), [])

    def test_a_covered_node_is_invisible_and_names_its_cover(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 30, 230, 70), bg=255)                      # opaque, over the body text
        found = judged(semantic, tree, {2: (0, BLACK_ON_WHITE)})
        self.assertEqual(render(found, "invisible-node"), [("invisible-node", "body", "covered", "error")])
        self.assertEqual(next(f for f in found if f["check"] == "invisible-node")["observed"]["by"]["target"],
                         "node/lv_obj/0/30/230/70")
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 30, 230, 70), bg=200)                      # translucent: the body must paint
        self.assertEqual(render(judged(semantic, tree, {2: (0, BLACK_ON_WHITE)}), "invisible-node"),
                         [("invisible-node", "body", "node", "error")])
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="body", flags="H")
        tree.nodes[2]["hidden"] = 1
        self.assertEqual(render(judged(semantic, tree, {2: (0, BLACK_ON_WHITE)}), "invisible-node"), [])

    def test_under_a_correct_modal_or_inert_nothing_painted_is_not_applicable(self):
        semantic, tree = modal()
        found = judged(semantic, tree, {2: (0, BLACK_ON_WHITE), 4: (0, BLACK_ON_WHITE)}, finish=True)
        self.assertEqual(render(found, "invisible-node") + render(found, "contrast-low"), [])
        na = next(f for f in found if f["check"] == "checks-examined")["observed"]["not_applicable"]
        self.assertEqual((na["invisible-node"], na["contrast-low"]), (3, 3))   # title, body, ok under the scrim
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="body", flags="I")
        self.assertEqual(render(judged(semantic, tree, {2: (0, BLACK_ON_WHITE)}), "invisible-node"), [])

    def test_contrast_low_below_the_large_floor(self):
        semantic, tree = base()
        found = judged(semantic, tree, {2: (100, ("bbbbbb", "f0f0f0", "ffffff", "ffffff"))})
        self.assertEqual(render(found), [("contrast-low", "body", "below-large", "error")])
        item = next(f for f in found if f["check"] == "contrast-low")
        self.assertEqual((item["observed"]["ratio"], item["observed"]["against"], item["id"]),
                         (1.9198, "behind", expected_id("ui-render", "contrast-low", ["body", "below-large"])))

    def test_dark_text_under_a_dark_scrim_is_not_a_contrast_finding(self):
        semantic, tree = modal()
        dimmed = ("1a1a1a", "404040", "333333", "333333")                     # #222 text under the scrim
        self.assertEqual(render(judged(semantic, tree, {2: (100, dimmed)}), "contrast-low"), [])
        semantic, tree = base()
        self.assertEqual(render(judged(semantic, tree, {2: (100, dimmed)}), "contrast-low"),
                         [("contrast-low", "body", "below-large", "error")])

    def test_a_text_on_its_own_opaque_fill(self):
        semantic, tree = base()
        tree.nodes[2].update(bg=255, colour="000000")                         # #222 text on a #000 fill, on white
        found = judged(semantic, tree, {2: (300, ("000000", "222222", "ffffff", "ffffff"))})
        self.assertEqual(render(found), [("contrast-low", "body", "below-large", "error")])
        item = next(f for f in found if f["check"] == "contrast-low")["observed"]
        self.assertEqual((item["against"], item["behind"], item["ratio"]), ("own-fill", ["000000"], 1.3199))
        fooled = Ink(2, None, 300, (8, 40, 207, 63), "000000", "222222", "ffffff", "ffffff", "")
        self.assertAlmostEqual(worst_contrast(fooled), 21.0)       # against what is behind, the fill passes for text
        found = judged(semantic, tree, {2: (300, ("000000", "ffffff", "ffffff", "ffffff"))})   # white on black
        self.assertEqual(render(found), [("ink-unmeasurable", "body", None, "error")])
        self.assertEqual(next(f for f in found if f["check"] == "ink-unmeasurable")["observed"]["unmeasured"],
                         [["text", "own-background"]])
        semantic, tree = base()
        tree.nodes[2].update(bg=255, grad=1, colour="000000")                 # a gradient: no sound comparison
        found = judged(semantic, tree, {2: (300, ("000000", "222222", "ffffff", "ffffff"))})
        self.assertEqual(render(found), [("ink-unmeasurable", "body", None, "error")])

    def test_the_decision_at_the_boundaries(self):
        self.assertEqual([decide(r, 3, 4.5) for r in (2.999, 3.0, 4.499, 4.5, 4.54)],
                         ["fail", "between", "between", "pass", "pass"])
        self.assertEqual([decide(r, None, 4.5) for r in (2.0, 4.5)], [None, "pass"])
        self.assertEqual([decide(r, 3, None) for r in (2.0, 3.0)], ["fail", None])
        semantic, tree = base()
        found = judged(semantic, tree, {2: (100, ("767676", "f0f0f0", "ffffff", "ffffff"))})       # 4.54:1
        self.assertEqual([f["check"] for f in found if f["gate"] == "ui-render" and f["check"] != "checks-examined"],
                         [])

    def test_between_the_floors_the_large_text_definition_is_missing(self):
        semantic, tree = base()
        found = judged(semantic, tree, {2: (100, ("777777", "f0f0f0", "ffffff", "ffffff"))})       # 4.48:1
        self.assertEqual(render(found, "contrast-low"), [])
        incomplete = [f for f in found if f["check"] == "contrast-low" or f["check"] == "contract-incomplete"]
        self.assertEqual([(f["check"], f["observed"]["what"], f["observed"]["name"]) for f in incomplete],
                         [("contract-incomplete", "large-text", "body")])

    def test_each_pending_threshold_alone(self):
        text_pending = contract(lambda t: pending(t, "contrast_text ", 'contrast_text = { pending = "15", '
                                                  'provenance = "literature:3.10/contrast_text" }'))
        large_pending = contract(lambda t: pending(t, "contrast_large ", 'contrast_large = { pending = "15", '
                                                   'provenance = "literature:3.10/contrast_large" }'))
        low, high = ("bbbbbb", "f0f0f0", "ffffff", "ffffff"), BLACK_ON_WHITE
        for the_contract, colours, want in ((text_pending, low, ["below-large"]), (text_pending, high, []),
                                            (large_pending, low, []), (large_pending, high, [])):
            semantic, tree = base()
            found = judged(semantic, tree, {2: (100, colours)}, the_contract=the_contract, finish=True)
            self.assertEqual([f["observed"]["part"] for f in found if f["check"] == "contrast-low"], want)
            self.assertEqual(len([f for f in found if f["check"] == "contract-pending"]), 1)
        examined = next(f for f in judged(*base(), the_contract=large_pending, finish=True)
                        if f["check"] == "checks-examined")["observed"]["totals"]
        self.assertEqual(examined["contrast-low"], 3)                          # black on white passes at 4.5

    def test_unmeasured_ink_is_an_error_and_no_verdict(self):
        semantic, tree = base()
        found = judged(semantic, tree, {3: "transformed", 4: "transformed"}, finish=True)
        self.assertEqual(render(found), [("ink-unmeasurable", "ok", None, "error")])
        item = next(f for f in found if f["check"] == "ink-unmeasurable")
        self.assertEqual(item["observed"]["unmeasured"], [["node", "transformed"], ["text", "transformed"]])
        found = judged(*base(), moved=True, finish=True)
        self.assertEqual(sorted(f["observed"]["key"] for f in found if f["check"] == "ink-unmeasurable"),
                         ["body", "ok", "title"])
        vacuous = sorted(f["observed"]["check"] for f in found if f["check"] == "check-vacuous")
        self.assertEqual(vacuous, ["contrast-low", "invisible-node"])

    def test_ink_plan_capped_is_a_run_level_info(self):
        judges = JudgeSet(["ui-render"], contract(), KEY, TODAY)
        found = [f for f in judges.finish(OPEN, capped=["k1"]) if f["check"] == "ink-plan-capped"]
        self.assertEqual([(f["severity"], f["state"], f["id"]) for f in found],
                         [("info", None, expected_id("ui-render", "ink-plan-capped", ["capped", "k1"], True))])

    def test_a_step_without_ink_judges_no_ink_and_ui_render_alone_owns_the_stage(self):
        semantic, tree = base()
        semantic.append(sem("ghost", "button", "", (250, 170, 60, 60), intent="9:0", style="btn"))
        found = judged(semantic, tree, ink=False, finish=True)
        self.assertEqual(sorted(f["observed"]["check"] for f in found if f["check"] == "check-vacuous"),
                         ["contrast-low", "ink-unmeasurable", "invisible-node"])
        self.assertEqual([(f["gate"], f["check"]) for f in found if f["check"] == "stage-unmatched"],
                         [("ui-render", "stage-unmatched")])
        both = judged(semantic, tree, ink=False, gates=("ui-scene", "ui-render"))
        self.assertEqual([(f["gate"], f["check"]) for f in both if f["check"] == "stage-unmatched"],
                         [("ui-scene", "stage-unmatched")])


class StageChecksTest(unittest.TestCase):
    def test_flag_mismatch_hidden_and_shown(self):
        semantic, tree = base()
        tree.nodes[2]["hidden"] = 1
        semantic[0] = sem("title", "text", "Title", (8, 8, 200, 24), style="title", flags="H")
        self.assertEqual(render(judged(semantic, tree, ink=False), "flag-mismatch"),
                         [("flag-mismatch", "body", "hidden", "error"), ("flag-mismatch", "title", "shown", "error")])

    def test_flag_mismatch_clickable(self):
        semantic, tree = base()
        tree.nodes[2]["clickable"] = 1                                     # the body text takes taps
        semantic[2] = sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn", flags="D")
        self.assertEqual(render(judged(semantic, tree, ink=False), "flag-mismatch"),
                         [("flag-mismatch", "body", "clickable", "error"),
                          ("flag-mismatch", "ok", "disabled-clickable", "error")])
        semantic, tree = base()
        semantic[2] = sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn", flags="I")
        self.assertEqual(render(judged(semantic, tree, ink=False), "flag-mismatch"),
                         [("flag-mismatch", "ok", "inert-clickable", "error")])
        semantic, tree = base()
        semantic[2] = sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn", enabled=0)
        tree.nodes[3]["clickable"] = 0                                     # disabled and not clickable: agrees
        self.assertEqual(render(judged(semantic, tree, ink=False), "flag-mismatch"), [])

    def test_a_clickable_layer_is_overlay_policys_not_a_flag_mismatch(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (60, 60, 259, 179), clickable=1, bg=255)
        semantic.append(sem("card", "dialog", "", (60, 60, 200, 120)))
        self.assertEqual(render(judged(semantic, tree, ink=False), "flag-mismatch"), [])

    def test_flag_mismatch_long_mode_against_the_scope(self):
        semantic, tree = base()
        tree.nodes[2]["label"]["long"] = 4                                 # CLIP for the body's `default` scope
        tree.nodes[4]["label"]["long"] = 1                                 # DOTS for the button's `single_line`
        found = judged(semantic, tree, ink=False)
        self.assertEqual(render(found, "flag-mismatch"), [("flag-mismatch", "body", "long-mode", "error"),
                                                          ("flag-mismatch", "ok", "long-mode", "error")])
        self.assertEqual(sorted((f["observed"]["long"], f["observed"]["expected"]) for f in found
                                if f["check"] == "flag-mismatch"), [("clip", "wrap"), ("dots", "wrap")])

    def test_an_ellipsis_scope_needs_dots(self):
        elided = contract(lambda t: t + '[[element]]\nid = "body_el"\nkey = "body"\nwrap = "elided"\n'
                                       'provenance = "spec:ui-look.md#4.1"\n')
        semantic, tree = base()
        found = judged(semantic, tree, ink=False, the_contract=elided)
        self.assertEqual([(f["observed"]["long"], f["observed"]["expected"]) for f in found
                          if f["check"] == "flag-mismatch"], [("wrap", "dots")])
        tree.nodes[2]["label"]["long"] = 1
        self.assertEqual(render(judged(semantic, tree, ink=False, the_contract=elided), "flag-mismatch"), [])

    def test_align_mismatch_on_the_drawn_alignment_only_when_drawn(self):
        semantic, tree = base()
        tree.nodes[2]["label"]["align_drawn"] = 1
        found = judged(semantic, tree, ink=False)
        self.assertEqual(render(found, "align-mismatch"), [("align-mismatch", "body", None, "error")])
        self.assertEqual(next(f for f in found if f["check"] == "align-mismatch")["observed"]["align"], "left")
        tree.nodes[2]["fit"]["unsupported"] = 1                            # no draw task, the style auto: n/a
        found = judged(semantic, tree, ink=False, finish=True)
        self.assertEqual(render(found, "align-mismatch"), [])
        self.assertEqual(next(f for f in found if f["check"] == "checks-examined")["observed"]["not_applicable"],
                         {"align-mismatch": 1})
        tree.nodes[2]["label"]["align"] = 1                                # not drawn, the style says left
        found = judged(semantic, tree, ink=False)
        self.assertEqual([(f["observed"]["align"], f["observed"]["source"]) for f in found
                          if f["check"] == "align-mismatch"], [("left", "style")])
        tree.nodes[2]["label"]["align"] = 2
        self.assertEqual(render(judged(semantic, tree, ink=False), "align-mismatch"), [])

    def test_line_height_above_the_baseline_and_below_is_font_shrunk(self):
        semantic, tree = base()
        tree.nodes[2]["label"]["line_h"] = 20
        self.assertEqual(render(judged(semantic, tree, ink=False), "line-height-mismatch"),
                         [("line-height-mismatch", "body", "above", "error")])
        tree.nodes[2]["label"]["line_h"] = 10
        found = judged(semantic, tree, ink=False, gates=("ui-fit", "ui-render"))
        self.assertEqual(render(found, "line-height-mismatch"), [])
        self.assertEqual([f["check"] for f in found if f["observed"].get("key") == "body"], ["font-shrunk"])


class ExceptionRulesTest(unittest.TestCase):
    def test_an_exception_may_name_every_ui_render_check(self):
        """Every finding id of the ui-render judge an owner may except is in the loader's closed list, and loads."""
        from rigor_lib import ui_contract
        from rigor_lib.ui_judge_findings import GATES, META
        own = set(GATES["ui-render"]) - META - {"stage-unmatched", "stage-text-mismatch", "stage-unowned-target"}
        row = ('\n[[exception]]\nid = "e1"\nrule = "%s"\ntarget = "body"\nreason = "r"\nexpires = 2099-01-31\n'
               'provenance = "owner:D99"\n')
        self.assertNotIn("ink-plan-capped", ui_contract.EXCEPTION_RULES)     # info, never passes an exception
        for rule in sorted(own):
            self.assertIn(rule, ui_contract.EXCEPTION_RULES)
            loaded = ui_contract.loads(CANARY_CONTRACT.read_text() + row % rule)
            self.assertEqual(loaded.tables["exception"][0]["rule"], rule)


class LayerRolesTest(unittest.TestCase):
    def test_the_layer_roles_are_defined_once(self):
        from rigor_lib import ui_judge_contract, ui_judge_vocab
        self.assertIs(ui_judge_vocab.LAYER_ROLES, ui_judge_contract.LAYER_ROLES)


if __name__ == "__main__":
    unittest.main()
