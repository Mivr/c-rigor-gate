"""The ui-fit judge (U06, P004 3.2): fit-unmeasurable, glyph-missing, text-clipped, full-string-shown and text-overflow
from lvprobe's label and fit records, with the owner's rect and wrap scope; each with its nearest negative cases."""

import unittest

from tests.test_ui_judge_helpers import Tree, base, checks, contract, expected_id, run, sem


def body(scope="default", rect=(8, 40, 200, 24), label="Body text", flags="-", **facts):
    """The base scene whose body text has the scope, rect and label facts given (its box is the rect)."""
    the_contract = facts.pop("the_contract", None)
    semantic, _tree = base()
    semantic[1] = sem("body", "body", label, rect, style="body", importance="2", wrap=scope, flags=flags)
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    x, y, w, h = rect
    tree.label(0, facts.pop("text", label), (x, y, x + w - 1, y + h - 1), **facts)
    button = tree.node(0, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
    tree.label(button, "OK", (48, 117, 67, 132))
    return run(semantic, tree, the_contract=the_contract)


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
        self.assertEqual(body(scope="clipped", clipped=1), [])
        self.assertEqual(body(clipped=0), [])

    def test_a_label_no_scene_node_owns_is_judged_by_its_index(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215), clipped=1, missing=1, full="Stray text")
        found = [f for f in run(semantic, tree) if f["gate"] == "ui-fit"]
        self.assertEqual(ids(found), sorted(expected_id("ui-fit", c, ["index", 5])
                                            for c in ("text-clipped", "glyph-missing", "full-string-shown")))
        self.assertEqual({f["observed"]["stage"] for f in found}, {"O3"})


class FullStringTest(unittest.TestCase):
    def test_dots_without_an_ellipsis_scope(self):
        found = body(rect=(8, 40, 60, 16), label="Body text that is long", text="Body t...",
                     full="Body text that is long", long_mode=1)
        self.assertEqual(ids(found), [expected_id("ui-fit", "full-string-shown", ["body"])])
        self.assertEqual(body(scope="elided", rect=(8, 40, 60, 16), label="Body text that is long", text="Body t...",
                              full="Body text that is long", long_mode=1), [])


class OverflowTest(unittest.TestCase):
    def test_single_line_natural_width_at_the_rect_passes_one_more_fails(self):
        self.assertEqual(body(scope="single_line", rect=(8, 40, 100, 40), natural=(100, 16), laid=(100, 16)), [])
        found = body(scope="single_line", rect=(8, 40, 100, 40), natural=(101, 16), laid=(90, 32), lines=2)
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in found],
                         [(expected_id("ui-fit", "text-overflow", ["body"]), "width")])

    def test_wrapping_laid_height_at_the_rect_passes_one_more_fails(self):
        self.assertEqual(body(rect=(8, 40, 100, 32), natural=(180, 16), laid=(95, 32), lines=2), [])
        found = body(rect=(8, 40, 100, 32), natural=(180, 16), laid=(95, 33), lines=2)
        self.assertEqual([(f["id"], f["observed"]["part"]) for f in found],
                         [(expected_id("ui-fit", "text-overflow", ["body"]), "height")])

    def test_a_line_cap_without_ellipsis(self):
        capped = contract(lambda t: t + '[[wrap]]\nscope = "two"\nwrap = "word"\nmax_lines = 2\nellipsis = false\n'
                          'clip = false\nprovenance = "spec:ui-look.md#5"\n')
        self.assertEqual(body(scope="two", rect=(8, 40, 100, 60), laid=(95, 48), lines=2, the_contract=capped), [])
        self.assertEqual(ids(body(scope="two", rect=(8, 40, 100, 60), laid=(95, 48), lines=3, the_contract=capped)),
                         [expected_id("ui-fit", "text-overflow", ["body"])])

    def test_an_ellipsis_or_clip_scope_makes_the_excess_intended_and_a_hidden_owner_is_not_judged(self):
        self.assertEqual(body(scope="clipped", rect=(8, 40, 100, 40), natural=(150, 16)), [])
        self.assertEqual(body(scope="elided", rect=(8, 40, 100, 16), laid=(95, 32), lines=2), [])
        self.assertEqual(body(scope="single_line", rect=(8, 40, 100, 40), natural=(150, 16), hidden=1), [])

    def test_only_ui_scene_selected_runs_no_fit_check(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215), clipped=1)
        self.assertEqual(checks(run(semantic, tree, gates=("ui-scene",))), ["stage-unmatched"])


if __name__ == "__main__":
    unittest.main()
