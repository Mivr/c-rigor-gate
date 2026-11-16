"""The `ui-render` judge (U07, docs/ui-judges-render.md) on hand-built observations: the ink checks (`invisible-node`,
`contrast-low`, `ink-unmeasurable`), the stage checks (`flag-mismatch`, `align-mismatch`, `line-height-mismatch`), the
WCAG arithmetic, the ink records' format, the explorer's ink plan and the refusal of a probe without `ink`."""

import copy
import unittest

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import INK_FIELDS, parse_typed_line
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import InkPlan, Step
from rigor_lib.ui_judge_findings import JudgeSet
from rigor_lib.ui_judge_render_ink import Ink, luminance, ratio, worst_contrast
from tests.helpers import TempDirTestCase, run_rigor
from tests.test_ui_judge_helpers import (CANARY_CONTRACT, KEY, OPEN, TODAY, Tree, base, contract, expected_id, pending,
                                         sem, step)
from tests.test_ui_explore_helpers import TOY

BLACK_ON_WHITE = ("000000", "f0f0f0", "ffffff", "ffffff")


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
        self.assertEqual(render(found), [("invisible-node", "body", None, "error"),
                                         ("invisible-node", "ok", None, "error")])
        self.assertIn(expected_id("ui-render", "invisible-node", ["body"]), [f["id"] for f in found])

    def test_a_covered_or_hidden_node_is_not_invisible(self):
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 30, 230, 70), bg=255)                      # opaque, over the body text
        self.assertEqual(render(judged(semantic, tree, {2: (0, BLACK_ON_WHITE)}), "invisible-node"), [])
        semantic, tree = base()
        tree.node(0, "lv_obj", (0, 30, 230, 70), bg=200)                      # translucent: the body must paint
        self.assertEqual(render(judged(semantic, tree, {2: (0, BLACK_ON_WHITE)}), "invisible-node"),
                         [("invisible-node", "body", None, "error")])
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="body", flags="H")
        tree.nodes[2]["hidden"] = 1
        self.assertEqual(render(judged(semantic, tree, {2: (0, BLACK_ON_WHITE)}), "invisible-node"), [])

    def test_contrast_low_below_the_large_floor(self):
        semantic, tree = base()
        found = judged(semantic, tree, {2: (100, ("bbbbbb", "f0f0f0", "ffffff", "ffffff"))})
        self.assertEqual(render(found), [("contrast-low", "body", "below-large", "error")])
        item = next(f for f in found if f["check"] == "contrast-low")
        self.assertEqual((item["observed"]["ratio"], item["id"]),
                         (1.9198, expected_id("ui-render", "contrast-low", ["body", "below-large"])))

    def test_between_the_floors_the_large_text_definition_is_missing(self):
        semantic, tree = base()
        found = judged(semantic, tree, {2: (100, ("777777", "f0f0f0", "ffffff", "ffffff"))})       # 4.48:1
        self.assertEqual(render(found, "contrast-low"), [])
        incomplete = [f for f in found if f["check"] == "contrast-low" or f["check"] == "contract-incomplete"]
        self.assertEqual([(f["check"], f["observed"]["what"], f["observed"]["name"]) for f in incomplete],
                         [("contract-incomplete", "large-text", "body")])

    def test_pending_thresholds_are_contract_pending_and_no_verdict(self):
        the_contract = contract(lambda t: pending(t, "contrast_text ", 'contrast_text = { pending = "15", '
                                                  'provenance = "literature:3.10/contrast_text" }'))
        semantic, tree = base()
        found = judged(semantic, tree, {2: (100, ("bbbbbb", "f0f0f0", "ffffff", "ffffff"))}, the_contract=the_contract,
                       finish=True)
        self.assertEqual(render(found, "contrast-low"), [])
        pendings = [(f["observed"]["check"], f["observed"]["entry"]) for f in found if f["check"] == "contract-pending"]
        self.assertIn(("contrast-low", "thresholds.contrast_text"), pendings)
        self.assertIn("contrast-low", [f["observed"]["check"] for f in found if f["check"] == "check-vacuous"])

    def test_unmeasured_ink_is_info_and_no_verdict(self):
        semantic, tree = base()
        found = judged(semantic, tree, {3: "transformed", 4: "transformed"}, finish=True)
        self.assertEqual(render(found), [("ink-unmeasurable", "ok", None, "info")])
        item = next(f for f in found if f["check"] == "ink-unmeasurable")
        self.assertEqual(item["observed"]["unmeasured"], [["node", "transformed"], ["text", "transformed"]])
        found = judged(*base(), moved=True, finish=True)
        self.assertEqual(sorted(f["observed"]["key"] for f in found if f["check"] == "ink-unmeasurable"),
                         ["body", "ok", "title"])
        vacuous = sorted(f["observed"]["check"] for f in found if f["check"] == "check-vacuous")
        self.assertEqual(vacuous, ["contrast-low", "invisible-node"])

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

    def test_align_mismatch_on_the_drawn_alignment_only_when_drawn(self):
        semantic, tree = base()
        tree.nodes[2]["label"]["align_drawn"] = 1
        found = judged(semantic, tree, ink=False)
        self.assertEqual(render(found, "align-mismatch"), [("align-mismatch", "body", None, "error")])
        self.assertEqual(next(f for f in found if f["check"] == "align-mismatch")["observed"]["align_drawn"], "left")
        tree.nodes[2]["fit"]["unsupported"] = 1                            # no draw task: nothing to compare
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


class LayerRolesTest(unittest.TestCase):
    def test_the_layer_roles_are_defined_once(self):
        from rigor_lib import ui_judge_contract, ui_judge_vocab
        self.assertIs(ui_judge_vocab.LAYER_ROLES, ui_judge_contract.LAYER_ROLES)


class InkPlanTest(unittest.TestCase):
    def test_each_state_key_is_inked_once_and_the_second_run_inks_the_same_steps(self):
        plan = InkPlan(set())
        steps = [Step(i, "w", key=k) for i, k in enumerate("abab")]
        self.assertEqual([plan.wants(s) for s in steps], [True, True, False, False])
        later = [Step(i, "w", key=k) for i, k in enumerate("cab")]
        self.assertEqual([plan.wants(s) for s in later], [True, False, False])
        for s in steps[:2]:
            s.obs["ink"] = ()
        again = InkPlan.again(type("Run", (), {"steps": steps})())
        self.assertEqual([again.wants(s) for s in steps], [True, True, False, False])


class NeedsInkTest(TempDirTestCase):
    def test_ui_render_refuses_a_probe_without_ink(self):
        probe = self.tmp / "no-ink"
        probe.write_text("#!/bin/sh\necho 'ui-probe/1 ready frame-facts'\nexec cat >/dev/null\n")
        probe.chmod(0o755)
        done = run_rigor(["ui-explore", "--probe", probe, "--catalogue", TOY, "--strategy", "sweep",
                          "--origin-ms", "1000", "--seed", "7", "--judges", "ui-render", "--contract", CANARY_CONTRACT,
                          "--today", "2026-11-16", "--out", self.tmp / "out.json"])
        self.assertEqual(done.code, 2, done.stderr)
        self.assertIn("ui-render needs a probe that announces ink", done.stderr)


if __name__ == "__main__":
    unittest.main()
