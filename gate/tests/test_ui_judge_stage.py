"""The stages of the ui-scene and ui-fit judges (U06): the frame facts parser, the scene vocabulary, the association of
scene nodes with rendered nodes and its findings (`stage-unmatched`, `scene-vocabulary`)."""

import unittest

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_typed_line
from rigor_lib.ui_judge_stage import associate, parse_frame
from tests.test_ui_judge_helpers import Tree, base, checks, expected_id, run, sem


def frame_of(lines):
    return parse_frame(tuple(parse_typed_line(FRAME_FIELDS, line) for line in lines))


class ParseTest(unittest.TestCase):
    def test_the_base_tree_parses_with_its_subtrees(self):
        _semantic, tree = base()
        frame = frame_of(tree.lines())
        self.assertEqual((frame.width, frame.height, len(frame.nodes)), (320, 240, 5))
        self.assertEqual(frame.end, [4, 1, 2, 4, 4])
        self.assertTrue(frame.descends(4, 3) and not frame.descends(3, 4) and frame.related(3, 4))
        self.assertEqual(frame.labels[4].own_text, b"OK")

    def test_malformed_facts_are_the_gates_error_never_a_traceback(self):
        _semantic, tree = base()
        good = tree.lines()
        cases = {
            "count": [good[0].replace("\t5", "\t6")] + good[1:],
            "order": [line.replace("node\t2\t", "node\t7\t") for line in good],
            "depth": [line.replace("node\t4\t3\t2", "node\t4\t3\t1") for line in good],
            "number": [line.replace("label\t1\t-\t16", "label\t1\t-\tx") for line in good],
            "flag": [line.replace("fit\t1\t1\t0", "fit\t1\t2\t0") for line in good],
            "box": [line.replace("fit\t1\t1\t0\t9,9,206,30", "fit\t1\t1\t0\t9,9,206") for line in good],
            "prefix": [line.replace("=Title", "Title") for line in good],
            "dotted": [line.replace("label\t1\t-\t16\t0\t1\t0\t0", "label\t1\t-\t16\t0\t1\t0\t1") for line in good],
            "nohead": good[2:],
            "orphan fit": [line for line in good if not line.startswith("label\t1\t")],
        }
        for name, lines in cases.items():
            self.assertNotEqual(lines, good, name)
            with self.assertRaises(InternalError, msg=name):
                frame_of(lines)

    def test_the_visible_box_is_cut_by_the_display_and_the_clip_chain(self):
        tree = Tree()
        panel = tree.node(0, "lv_obj", (10, 10, 59, 59))
        inner = tree.node(panel, "lv_obj", (40, 40, 99, 99), clip=panel)
        edge = tree.node(0, "lv_obj", (300, 230, 339, 259))
        frame = frame_of(tree.lines())
        self.assertEqual(frame.visible_box(inner), (40, 40, 59, 59))
        self.assertEqual(frame.visible_box(edge), (300, 230, 319, 239))


class AssociationTest(unittest.TestCase):
    def scene(self, semantic, tree):
        from rigor_lib.ui_judge_stage import scene_vocabulary
        from rigor_lib.ui_explore_grammar import parse_record
        from tests.test_ui_judge_helpers import contract
        c = contract()
        nodes = [scene_vocabulary(parse_record("semantic", line), c)[0] for line in semantic]
        return associate(nodes, frame_of(tree.lines()))

    def test_exact_rect_and_text_associate_a_label_and_a_button_with_its_label(self):
        semantic, tree = base()
        found = self.scene(semantic, tree)
        self.assertEqual(found.match, {"title": 1, "body": 2, "ok": 3})
        self.assertEqual(found.text, {"title": 1, "body": 2, "ok": 4})
        self.assertEqual(found.owner, {1: "title", 2: "body", 4: "ok"})
        self.assertEqual(found.unmatched, [])

    def test_one_pixel_off_or_another_text_is_absent(self):
        semantic, tree = base()
        semantic[1] = sem("body", "body", "Body text", (8, 40, 201, 24), style="body", importance="2", wrap="default")
        semantic[0] = sem("title", "title", "Titles", (8, 8, 200, 24), style="title", importance="1", wrap="default")
        found = self.scene(semantic, tree)
        self.assertEqual(found.unmatched, [("body", "absent"), ("title", "absent")])
        self.assertNotIn(2, found.owner)

    def test_two_candidates_or_two_claimants_are_ambiguous_never_a_best_match(self):
        semantic, tree = base()
        tree.label(0, "Body text", (8, 40, 207, 63))           # a second label with the same box and text
        self.assertEqual(self.scene(semantic, tree).unmatched, [("body", "ambiguous")])
        semantic, tree = base()
        semantic.append(sem("body2", "body", "Body text", (8, 40, 200, 24), style="body", importance="2",
                            wrap="default"))
        found = self.scene(semantic, tree)
        self.assertEqual(found.unmatched, [("body", "ambiguous"), ("body2", "ambiguous")])
        self.assertNotIn("body", found.match)

    def test_a_container_matches_an_empty_label_and_a_button_needs_exactly_one_carrier(self):
        semantic, tree = base()
        tree.label(3, "OK", (48, 133, 67, 148))                 # a second "OK" label under the button
        self.assertEqual(self.scene(semantic, tree).unmatched, [("ok", "absent")])
        tree = Tree()
        card = tree.node(0, "lv_obj", (10, 10, 109, 109))
        tree.label(card, "Inside", (20, 20, 79, 35))
        found = self.scene([sem("card", "panel", "", (10, 10, 100, 100))], tree)
        self.assertEqual((found.match, found.text), ({"card": card}, {"card": None}))

    def test_a_dotted_label_associates_by_its_own_full_text(self):
        tree = Tree()
        tree.label(0, "Body t...", (8, 40, 67, 55), full="Body text that is long")
        found = self.scene([sem("body", "body", "Body text that is long", (8, 40, 60, 16), style="body",
                                importance="2", wrap="default")], tree)
        self.assertEqual(found.match, {"body": 1})


class StageFindingTest(unittest.TestCase):
    def test_an_unmatched_scene_node_and_an_unowned_label_are_info_with_exact_ids(self):
        semantic, tree = base()
        semantic.append(sem("ghost", "panel", "", (250, 8, 40, 40)))
        tree.label(0, "Stray", (220, 200, 279, 215))
        found = run(semantic, tree)
        self.assertEqual(sorted(f["id"] for f in found),
                         sorted([expected_id("ui-scene", "stage-unmatched", ["scene", "ghost", "absent"]),
                                 expected_id("ui-scene", "stage-unmatched", ["frame-label", 5])]))
        self.assertEqual({f["severity"] for f in found}, {"info"})

    def test_a_hidden_or_empty_unowned_label_is_not_reported(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215), hidden=1)
        tree.label(0, "", (220, 220, 279, 235))
        self.assertEqual(run(semantic, tree), [])

    def test_only_ui_fit_selected_owns_the_stage_findings(self):
        semantic, tree = base()
        semantic.append(sem("ghost", "panel", "", (250, 8, 40, 40)))
        self.assertEqual([f["id"] for f in run(semantic, tree, gates=("ui-fit",))],
                         [expected_id("ui-fit", "stage-unmatched", ["scene", "ghost", "absent"])])

    def test_every_field_outside_the_vocabulary_is_scene_vocabulary_and_the_node_takes_no_part(self):
        semantic, tree = base()
        cases = {
            "flags": sem("x", "panel", "", (0, 0, 1, 1), flags="hidden,bogus"),
            "intent": sem("x", "panel", "", (0, 0, 1, 1), intent="tap"),
            "role": sem("x", "label", "Text", (0, 0, 1, 1)),
            "style": sem("x", "body", "Text", (0, 0, 1, 1), style="loud", wrap="default", importance="2"),
            "importance": sem("x", "panel", "", (0, 0, 1, 1), importance="normal"),
            "input_policy": sem("x", "panel", "", (0, 0, 1, 1), policy="tap"),
            "wrap_policy": sem("x", "panel", "", (0, 0, 1, 1), wrap="none"),
        }
        for field, line in cases.items():
            found = run(semantic + [line], tree)
            self.assertEqual([(f["check"], f["observed"]["fields"]) for f in found], [("scene-vocabulary", [field])],
                             field)
            self.assertEqual(found[0]["id"], expected_id("ui-scene", "scene-vocabulary", ["scene", "x", [field]]))

    def test_a_duplicate_key_is_one_scene_vocabulary_and_its_label_is_then_unowned(self):
        semantic, tree = base()
        found = run(semantic + [semantic[0]], tree)
        self.assertEqual(checks(found), ["hierarchy-violated", "scene-vocabulary", "stage-unmatched"])   # body and ok: one size
        self.assertEqual([f["observed"]["fields"] for f in found if f["check"] == "scene-vocabulary"], [["key"]])


if __name__ == "__main__":
    unittest.main()
