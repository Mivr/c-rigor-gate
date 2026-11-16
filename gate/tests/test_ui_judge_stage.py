"""The stages of the ui-scene and ui-fit judges (U06): the frame facts parser, the scene vocabulary, the association of
scene nodes with rendered nodes and its findings (`stage-unmatched`, `stage-text-mismatch`, `scene-vocabulary`,
`contract-incomplete` for a style token)."""

import hashlib
import unittest

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_record, parse_typed_line
from rigor_lib.ui_judge_stage import parse_frame
from rigor_lib.ui_judge_vocab import associate, read
from tests.test_ui_judge_helpers import Tree, base, checks, contract, expected_id, run, sem


def frame_of(lines):
    return parse_frame(tuple(parse_typed_line(FRAME_FIELDS, line) for line in lines))


class ParseTest(unittest.TestCase):
    def test_the_base_tree_parses_with_its_subtrees(self):
        _semantic, tree = base()
        frame = frame_of(tree.lines())
        self.assertEqual((frame.width, frame.height, len(frame.nodes)), (320, 240, 5))
        self.assertEqual(frame.end, [4, 1, 2, 4, 4])
        self.assertTrue(frame.descends(4, 3) and not frame.descends(3, 4) and frame.related(3, 4))
        self.assertEqual((frame.labels[4].own_text, frame.nodes[3].bg), (b"OK", "ffffff"))

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


def associated(semantic, tree, accessible=frozenset()):
    c = contract()
    nodes = [read(parse_record("semantic", line), c)[0] for line in semantic]
    return associate(nodes, frame_of(tree.lines()), accessible)


class AssociationTest(unittest.TestCase):
    def test_exact_rect_and_text_associate_a_label_and_a_button_with_its_label(self):
        found = associated(*base())
        self.assertEqual((found.match, found.text, found.owner), ({"title": 1, "body": 2, "ok": 3},
                                                                 {"title": 1, "body": 2, "ok": 4},
                                                                 {1: "title", 2: "body", 4: "ok"}))
        self.assertEqual((found.unmatched, found.mismatch), ([], []))

    def test_one_pixel_off_is_absent_and_another_text_at_the_box_is_a_text_mismatch(self):
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 201, 24), style="body")
        semantic[0] = sem("title", "text", "Titles", (8, 8, 200, 24), style="title")
        found = associated(semantic, tree)
        self.assertEqual((found.unmatched, found.mismatch), ([("body", "absent")], ["title"]))
        self.assertEqual((found.match["title"], found.text["title"], found.claimed), (1, None, {1}))

    def test_equal_boxes_pair_by_rank_and_unequal_counts_are_ambiguous(self):
        tree = Tree()
        scrim = tree.node(0, "lv_obj", (10, 10, 109, 59), clickable=1)
        card = tree.node(scrim, "lv_obj", (10, 10, 109, 59), clickable=1, bg=255)
        pair = [sem("s", "scrim", "", (10, 10, 100, 50), intent="9:0"), sem("c", "banner", "", (10, 10, 100, 50))]
        self.assertEqual(associated(pair, tree).match, {"s": scrim, "c": card})
        self.assertEqual(associated(pair[:1], tree).unmatched, [("s", "ambiguous")])
        tree.node(0, "lv_obj", (10, 10, 109, 59))
        self.assertEqual(associated(pair, tree).unmatched, [("c", "ambiguous"), ("s", "ambiguous")])

    def test_a_button_needs_exactly_one_carrier_and_a_panel_label_is_compared_unless_its_element_is_accessible(self):
        semantic, tree = base()
        tree.label(3, "OK", (48, 133, 67, 148))                 # a second "OK" label under the button
        self.assertEqual(associated(semantic, tree).mismatch, ["ok"])
        tree = Tree()
        echo = tree.label(0, "", (10, 10, 109, 59))            # the kiosk's echo panel: an empty label
        scene = [sem("echo", "panel", "Digits entered: 0", (10, 10, 100, 50))]
        self.assertEqual(associated(scene, tree).mismatch, ["echo"])
        found = associated(scene, tree, accessible={"echo"})
        self.assertEqual((found.match, found.text, found.mismatch), ({"echo": echo}, {"echo": None}, []))

    def test_an_incompatible_rank_pairing_is_ambiguous_never_a_silent_wrong_match(self):
        tree = Tree()
        scrim = tree.node(0, "lv_obj", (10, 10, 109, 59), clickable=1)
        tree.node(scrim, "lv_obj", (10, 10, 109, 59), clickable=1, bg=255)
        swapped = [sem("c", "banner", "", (10, 10, 100, 50)), sem("s", "scrim", "", (10, 10, 100, 50), intent="9:0")]
        self.assertEqual(associated(swapped, tree).unmatched, [("c", "ambiguous"), ("s", "ambiguous")])
        tree = Tree()
        tree.node(0, "lv_obj", (10, 10, 109, 59), clickable=1)
        for line in (sem("b", "button", "", (10, 10, 100, 50), style="btn"),
                     sem("t", "text", "", (10, 10, 100, 50), style="body"),
                     sem("i", "panel", "", (10, 10, 100, 50), intent="1:0")):
            self.assertEqual(len(associated([line], tree).match), 1 if line.startswith("i\t") else 0, line)
        tree.nodes[1]["clickable"] = 0
        self.assertEqual(associated([sem("i", "panel", "", (10, 10, 100, 50), intent="1:0")], tree).match, {})

    def test_a_dotted_label_associates_by_its_own_full_text_and_the_root_is_not_associated(self):
        tree = Tree()
        tree.label(0, "Body t...", (8, 40, 67, 55), full="Body text that is long")
        found = associated([sem("1", "root", "", (0, 0, 320, 240)),
                            sem("body", "text", "Body text that is long", (8, 40, 60, 16), style="body")], tree)
        self.assertEqual((found.match, found.unmatched), ({"body": 1}, []))


class StageFindingTest(unittest.TestCase):
    def test_unmatched_is_info_for_a_plain_node_and_an_error_for_an_interactive_node_or_a_layer(self):
        semantic, tree = base()
        semantic += [sem("ghost", "panel", "", (250, 8, 40, 40)), sem("gone", "button", "x", (250, 60, 60, 60),
                                                                     intent="2:0", style="btn"),
                     sem("veil", "dialog", "", (0, 180, 320, 60))]
        found = {f["id"]: f["severity"] for f in run(semantic, tree) if f["check"] == "stage-unmatched"}
        self.assertEqual(found, {
            expected_id("ui-scene", "stage-unmatched", ["scene", "ghost", "absent"]): "info",
            expected_id("ui-scene", "stage-unmatched", ["scene", "gone", "absent"]): "error",
            expected_id("ui-scene", "stage-unmatched", ["scene", "veil", "absent"]): "error"})

    def test_an_unmatched_node_names_its_candidates_and_an_unknown_control_is_an_unowned_target(self):
        semantic, tree = base()
        button = tree.node(0, "lv_button", (150, 150, 249, 199), clickable=1, bg=255)
        tree.label(button, "Go", (190, 165, 209, 180))
        semantic.append(sem("go", "button", "Go", (150, 140, 100, 50), intent="2:0", style="btn"))
        found = run(semantic, tree)
        scene = [f["observed"] for f in found if f["check"] == "stage-unmatched" and f["observed"]["side"] == "scene"]
        self.assertEqual([(o["key"], o["scene_box"], o["candidates"]) for o in scene],
                         [("go", [150, 140, 249, 189], [{"class": "lv_button", "box": [150, 150, 249, 199]}])])
        target = "node/lv_button/150/150/249/199"
        unowned = [f for f in found if f["check"] == "stage-unowned-target"]
        self.assertEqual([(f["id"], f["severity"]) for f in unowned],
                         [(expected_id("ui-scene", "stage-unowned-target", [target]), "error")])

    def test_an_unowned_label_is_named_by_class_box_and_text_hash_never_by_index(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215))
        target = "node/lv_label/220/200/279/215/" + hashlib.sha256(b"Stray").hexdigest()[:8]
        found = run(semantic, tree)
        self.assertEqual([(f["id"], f["severity"], f["observed"]["label"]["target"]) for f in found],
                         [(expected_id("ui-scene", "stage-unmatched", ["frame-label", target]), "info", target)])

    def test_a_text_mismatch_is_an_error_and_its_label_is_not_also_unowned(self):
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text!", (8, 40, 200, 24), style="body")
        found = run(semantic, tree)
        self.assertEqual([(f["id"], f["severity"]) for f in found if f["gate"] == "ui-scene"],
                         [(expected_id("ui-scene", "stage-text-mismatch", ["scene", "body"]), "error")])

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
            "role": sem("x", "label", "", (0, 0, 1, 1)),
            "flags": [sem("x", "panel", "", (0, 0, 1, 1), flags=f) for f in ("IQ", "II", "inert", "")],
            "intent": sem("x", "panel", "", (0, 0, 1, 1), intent="tap"),
            "style": [sem("x", "panel", "", (0, 0, 1, 1), style=t) for t in ("body_x", "-1", "07")],
            "importance": sem("x", "panel", "", (0, 0, 1, 1), importance="normal"),
            "input_policy": sem("x", "panel", "", (0, 0, 1, 1), policy="modal"),
            "wrap_policy": sem("x", "panel", "", (0, 0, 1, 1), wrap="none"),
        }
        for field, lines in cases.items():
            for line in lines if isinstance(lines, list) else [lines]:
                found = run(semantic + [line], tree)
                self.assertEqual([(f["check"], f["observed"]["fields"]) for f in found],
                                 [("scene-vocabulary", [field])], (field, line))
                self.assertEqual(found[0]["id"], expected_id("ui-scene", "scene-vocabulary", ["scene", "x", [field]]))

    def test_present_policies_of_the_vocabulary_are_accepted(self):
        semantic, tree = base()
        for line in (sem("x", "panel", "", (0, 0, 1, 1), flags="IDWNSHX", importance="3", wrap="default"),
                     sem("y", "panel", "", (0, 0, 1, 1), policy="capture-and-dismiss")):
            self.assertNotIn("scene-vocabulary", checks(run(semantic + [line], tree)))

    def test_a_duplicate_key_is_one_scene_vocabulary_and_its_label_is_then_unowned(self):
        semantic, tree = base()
        found = run(semantic + [semantic[0]], tree)
        self.assertEqual(checks(found), ["hierarchy-violated", "scene-vocabulary", "stage-unmatched"])
        self.assertEqual([f["observed"]["fields"] for f in found if f["check"] == "scene-vocabulary"], [["key"]])

    def test_a_style_token_the_contract_lacks_is_contract_incomplete_once_per_token(self):
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style=4)
        found = run(semantic, tree)
        self.assertEqual([(f["id"], f["state"]) for f in found],
                         [(expected_id("ui-scene", "contract-incomplete", ["style-token", 4], stateless=True), None)])


if __name__ == "__main__":
    unittest.main()
