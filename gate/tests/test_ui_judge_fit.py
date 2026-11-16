"""The ui-fit judge (U06, P004 3.2): fit-unmeasurable, glyph-missing, text-clipped, full-string-shown, text-overflow and
font-shrunk from lvprobe's label and fit records, with the owner's rect and the wrap scope and line height the contract
gives its typographic role and style; each with its nearest negative cases."""

import hashlib
import unittest

from tests.test_ui_judge_helpers import Tree, base, checks, contract, expected_id, run, sem


def scoped(scope):
    """The canary contract with the role body's wrap scope replaced."""
    return contract(lambda t: t.replace('role = "body"\nscope = "default"', 'role = "body"\nscope = "%s"' % scope))


def body(rect=(8, 40, 200, 24), label="Body text", flags="-", the_contract=None, style="body", **facts):
    """The base scene whose body text has the rect, label and label facts given (its box is the rect)."""
    semantic, _tree = base()
    semantic[1] = sem("body", "text", label, rect, style=style, flags=flags)
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    x, y, w, h = rect
    tree.label(0, facts.pop("text", label), (x, y, x + w - 1, y + h - 1), **facts)
    button = tree.node(0, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
    tree.label(button, "OK", (48, 117, 67, 132))
    return [f for f in run(semantic, tree, the_contract=the_contract) if f["gate"] == "ui-fit"]


def ids(found):
    return sorted(f["id"] for f in found)


class MeasureTest(unittest.TestCase):
    def test_an_unsupported_label_or_one_without_fit_is_unmeasurable_and_nothing_else(self):
        self.assertEqual(ids(body(unsupported=1, drawn=0, glyphs="-", visible="-", clipped=1, missing=2)),
                         [expected_id("ui-fit", "fit-unmeasurable", ["body", "facts"])])
        found = body(fit=False)
        self.assertEqual([(f["id"], f["observed"]["reason"]) for f in found],
                         [(expected_id("ui-fit", "fit-unmeasurable", ["body", "facts"]), "no-fit")])

    def test_one_missing_glyph_is_glyph_missing_none_is_not(self):
        self.assertEqual(ids(body(missing=1)), [expected_id("ui-fit", "glyph-missing", ["body"])])
        self.assertEqual(body(missing=0), [])


class ClipTest(unittest.TestCase):
    def test_clipped_is_text_clipped_unless_the_scope_declares_a_clip(self):
        self.assertEqual(ids(body(clipped=1)), [expected_id("ui-fit", "text-clipped", ["body"])])
        self.assertEqual(body(clipped=1, the_contract=scoped("clipped")), [])
        self.assertEqual(body(clipped=0), [])

    def test_a_label_no_scene_node_owns_is_judged_by_class_box_and_text_hash(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215), clipped=1, missing=1, full="Stray text")
        target = "node/lv_label/220/200/279/215/" + hashlib.sha256(b"Stray text").hexdigest()[:8]
        found = [f for f in run(semantic, tree) if f["gate"] == "ui-fit"]
        self.assertEqual(ids(found), sorted(expected_id("ui-fit", c, ["label", target])
                                            for c in ("text-clipped", "glyph-missing", "full-string-shown")))
        self.assertEqual({f["observed"]["stage"] for f in found}, {"O3"})


class FullStringTest(unittest.TestCase):
    def test_dots_without_an_ellipsis_scope(self):
        facts = dict(rect=(8, 40, 60, 16), label="Body text that is long", text="Body t...",
                     full="Body text that is long", long_mode=1)
        self.assertEqual(ids(body(**facts)), [expected_id("ui-fit", "full-string-shown", ["body"])])
        self.assertEqual(body(the_contract=scoped("elided"), **facts), [])


class OverflowTest(unittest.TestCase):
    def test_single_line_natural_width_at_the_rect_passes_one_more_fails(self):
        single = scoped("single_line")
        self.assertEqual(body(rect=(8, 40, 100, 40), natural=(100, 16), laid=(100, 16), the_contract=single), [])
        found = body(rect=(8, 40, 100, 40), natural=(101, 16), laid=(90, 32), lines=2, the_contract=single)
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in found],
                         [(expected_id("ui-fit", "text-overflow", ["body"]), "width")])

    def test_wrapping_laid_height_at_the_rect_passes_one_more_fails(self):
        self.assertEqual(body(rect=(8, 40, 100, 32), natural=(180, 16), laid=(95, 32), lines=2), [])
        found = body(rect=(8, 40, 100, 32), natural=(180, 16), laid=(95, 33), lines=2)
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in found],
                         [(expected_id("ui-fit", "text-overflow", ["body"]), "height")])

    def test_a_line_cap_without_ellipsis(self):
        capped = contract(lambda t: t.replace('role = "body"\nscope = "default"', 'role = "body"\nscope = "two"')
                          + '[[wrap]]\nscope = "two"\nwrap = "word"\nmax_lines = 2\nellipsis = false\n'
                          'clip = false\nprovenance = "spec:ui-look.md#5"\n')
        self.assertEqual(body(rect=(8, 40, 100, 60), laid=(95, 48), lines=2, the_contract=capped), [])
        self.assertEqual(ids(body(rect=(8, 40, 100, 60), laid=(95, 48), lines=3, the_contract=capped)),
                         [expected_id("ui-fit", "text-overflow", ["body"])])

    def test_an_ellipsis_or_clip_scope_makes_the_excess_intended_and_a_hidden_label_is_not_judged(self):
        self.assertEqual(body(rect=(8, 40, 100, 40), natural=(150, 16), the_contract=scoped("clipped")), [])
        self.assertEqual(body(rect=(8, 40, 100, 16), laid=(95, 32), lines=2, the_contract=scoped("elided")), [])
        self.assertEqual(body(rect=(8, 40, 100, 16), laid=(95, 32), lines=2, hidden=1), [])

    def test_a_role_without_a_scope_is_not_judged_for_overflow_and_the_rest_still_is(self):
        c = contract(lambda t: t.replace('[[role_wrap]]\nrole = "body"\nscope = "default"\n'
                                         'provenance = "spec:ui-look.md#5"\n', ""))
        found = body(rect=(8, 40, 100, 16), laid=(95, 32), lines=2, clipped=1, the_contract=c)
        self.assertEqual(ids(found), [expected_id("ui-fit", "text-clipped", ["body"])])

    def test_only_ui_scene_selected_runs_no_fit_check(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215), clipped=1)
        self.assertEqual(checks(run(semantic, tree, gates=("ui-scene",))), ["stage-unmatched"])


class VerdictTest(unittest.TestCase):
    def test_an_intended_excess_is_no_text_overflow_verdict(self):
        def overflow_verdicts(the_contract):
            found = run(*base(), the_contract=the_contract, finish=True)
            return [f["observed"]["totals"]["text-overflow"] for f in found
                    if f["check"] == "checks-examined" and f["gate"] == "ui-fit"]
        self.assertEqual(overflow_verdicts(contract()), [3])                  # title, body, OK
        self.assertEqual(overflow_verdicts(scoped("clipped")), [2])           # the body's excess is intended
        self.assertEqual(overflow_verdicts(scoped("elided")), [2])


class FontShrunkTest(unittest.TestCase):
    def test_a_line_height_one_below_the_styles_is_a_finding_at_it_none(self):
        # every style of the canary contract has a 16 px line
        self.assertEqual(body(line_h=16), [])
        self.assertEqual(body(line_h=17), [])
        found = body(line_h=15)
        self.assertEqual([(f["id"], f["observed"]["line_h"], f["observed"]["baseline_line_h"], f["observed"]["basis"])
                          for f in found],
                         [(expected_id("ui-fit", "font-shrunk", ["body"]), 15, 16, "product-baseline:abd8895")])

    def test_a_style_without_a_line_height_is_contract_incomplete(self):
        c = contract(lambda t: t.replace('[[style_line]]\nstyle = "body"\nline_height_px = 16\n'
                                         'provenance = "product-baseline:abd8895"\n', ""))
        self.assertEqual(ids(body(line_h=10, the_contract=c)),
                         [expected_id("ui-fit", "contract-incomplete", ["style-line", "body"], stateless=True)])


if __name__ == "__main__":
    unittest.main()
