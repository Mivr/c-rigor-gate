"""U24 fix-up 1: presence rests on what the gate observes, not on the product's claim (docs/ui-judges.md,
"required-element-missing"): a required element counts only when a scene node that IS it (a role id by the gate's role
of the node, any other id by the product's tag) is associated with a rendered node that is shown, with a non-empty
visible box, and, for a text-bearing node, a non-empty label that is the drawn one. The same rule counts value-split's
nodes. A tag naming a role the node lacks is `identity-role-mismatch`; one abstraction key with two classes is
`state-class-unstable`; `no-msgid` reaches buttons; the required element ids and value ids are exception targets a
state visits; one [[catalogue]] row only."""

import unittest

from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet
from tests.test_ui_judge_helpers import KEY, OPEN, TODAY, Tree, base, contract, expected_id, sem, step
from tests.test_ui_judge_identity import CLEAN, ident, judge, of, with_rows

DONE = lambda t: t.replace('required = ["title", "body"]', 'required = ["title", "done"]')   # noqa: E731


def detail(label="Body text", rect=(8, 40, 200, 24), drawn=True, parent_hidden=False):
    """(semantic, tree) of the base scene whose body is changed: its label, its rect, not drawn, under a hidden
    panel."""
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    if drawn:
        x, y, w, h = rect
        parent = tree.node(0, "lv_obj", (0, 36, 319, 70), hidden=1) if parent_hidden else 0
        tree.label(parent, label, (x, y, x + w - 1, y + h - 1))
    button = tree.node(0, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
    tree.label(button, "OK", (48, 117, 67, 132))
    semantic = [sem("title", "text", "Title", (8, 8, 200, 24), style="title"),
                sem("body", "text", label, rect, style="body"),
                sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn")]
    return semantic, tree


def missing(semantic, tree, nodes=CLEAN, the_contract=None):
    found = judge(semantic, tree, ident("detail", nodes), the_contract=the_contract)
    return [(f["observed"]["element"], f["observed"]["undrawn"]) for f in of(found, "required-element-missing")]


class PresenceTest(unittest.TestCase):
    def test_a_drawn_body_is_present(self):
        self.assertEqual(missing(*detail()), [])

    def test_in_the_scene_but_not_drawn_hidden_below_empty_or_zero_sized_is_missing(self):
        for name, scene in (("no rendered node", detail(drawn=False)),
                            ("a hidden ancestor", detail(parent_hidden=True)),
                            ("an empty label", detail(label="")),
                            ("a zero box", detail(rect=(8, 40, 0, 24))),
                            ("outside the display", detail(rect=(400, 40, 20, 24)))):
            with self.subTest(name):
                self.assertEqual(missing(*scene), [("body", ["body"])])

    def test_a_drawn_text_that_is_not_the_scenes_does_not_count(self):
        semantic, tree = detail()
        tree.nodes[2]["label"]["text"] = b"Other"             # stage-text-mismatch: the scene's text is not drawn
        self.assertEqual(missing(semantic, tree), [("body", ["body"])])

    def test_a_role_id_is_the_gates_role_not_the_tag(self):
        # the body tagged as nothing is still the body (its style's role); a caption tagged `body` is not
        nodes = (("title", "title", "canary.title"), ("body", "-", "canary.body"))
        self.assertEqual(missing(*detail(), nodes=nodes), [])
        semantic, tree = detail()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="caption")
        found = judge(semantic, tree, ident("detail"))
        self.assertEqual([f["observed"]["element"] for f in of(found, "required-element-missing")], ["body"])

    def test_an_other_element_is_the_products_tag_and_must_be_drawn_too(self):
        done = contract(DONE)
        nodes = CLEAN[:2] + (("ok", "done", "canary.ok"),)
        self.assertEqual(missing(*detail(), nodes=nodes, the_contract=done), [])
        self.assertEqual(missing(*detail(), the_contract=done), [("done", [])])
        semantic, tree = detail()
        tree.nodes[3]["hidden"] = 1                            # the button is in the scene, hidden in LVGL
        self.assertEqual(missing(semantic, tree, nodes=nodes, the_contract=done), [("done", ["ok"])])


class RoleMismatchTest(unittest.TestCase):
    def test_a_tag_naming_a_role_the_node_lacks(self):
        for element, role in (("body", "title"), ("countdown", "title")):
            with self.subTest(element=element):
                nodes = (("title", element, "canary.title"),) + CLEAN[1:]
                found = of(judge(*base(), ident("main", nodes)), "identity-role-mismatch")
                self.assertEqual([(f["id"], f["severity"], f["observed"]) for f in found],
                                 [(expected_id("ui-scene", "identity-role-mismatch", ["title"]), "error",
                                   {"stage": "O2", "key": "title", "element": element, "role": role,
                                    "scene_role": "text"})])
        nodes = (("title", "done", "canary.title"),) + CLEAN[1:]       # no role id: the tag is the product's
        self.assertEqual(of(judge(*base(), ident("main", nodes)), "identity-role-mismatch"), [])


class ValuePresenceTest(unittest.TestCase):
    def test_only_drawn_nodes_count_and_by_the_gates_role(self):
        semantic, tree = base()
        semantic.append(sem("num", "text", "37", (8, 180, 40, 24), style="title"))
        self.assertEqual(of(judge(semantic, tree, ident("main")), "value-split"), [])   # not drawn: not counted
        tree.label(0, "37", (8, 180, 47, 203))
        found = of(judge(semantic, tree, ident("main")), "value-split")    # untagged, but its role is the title
        self.assertEqual([f["observed"]["nodes"] for f in found], [["num", "title"]])


class UnstableClassTest(unittest.TestCase):
    def test_one_key_with_two_classes_is_reported_once(self):
        judges = JudgeSet(["ui-scene"], contract(), KEY, TODAY)
        judges.wants_identity(("identity",))
        found = []
        for index, state in enumerate(("main", "main", "detail", "detail")):
            s = step(*base(), index=index + 1)
            s.obs["identity"] = ident(state)
            found += judges.step_judge(s, PathSoFar([Step(0, OPEN)], 1), None)
        unstable = of(found, "state-class-unstable")
        self.assertEqual([(f["id"], f["severity"], f["state"], f["observed"]["classes"]) for f in unstable],
                         [(expected_id("ui-scene", "state-class-unstable", ["unstable", "k" * 64], stateless=True),
                           "error", None, ["detail", "main"])])


class NoMsgidTest(unittest.TestCase):
    def test_a_button_label_of_a_catalogue_role_without_a_msgid(self):
        keys = contract(lambda t: t.replace('text_roles = ["title", "body"]',
                                            'text_roles = ["title", "body", "key_label"]'))
        nodes = CLEAN[:2]                                   # the OK button has no identity line: no msgid
        found = judge(*base(), ident("main", nodes), the_contract=keys)
        self.assertEqual([f["id"] for f in of(found, "raw-text")],
                         [expected_id("ui-scene", "raw-text", ["ok", "no-msgid"])])
        self.assertEqual(of(found, "checks-examined")[0]["observed"]["totals"]["raw-text"], 3)
        self.assertEqual(of(judge(*base(), ident("main", nodes)), "raw-text"), [])   # key_label is not listed


class TargetsAndTablesTest(unittest.TestCase):
    def test_an_unused_exception_of_a_required_element_or_value_of_a_visited_state_is_an_error(self):
        # targets that are no scene key: `done` (required by detail) and the value `number`
        rows = "".join('[[exception]]\nid = "x-%s"\nrule = "%s"\ntarget = "%s"\nreason = "selftest"\n'
                       'expires = "2099-12-31"\nprovenance = "owner:D1"\n' % (n, r, t)
                       for n, r, t in (("req", "required-element-missing", "done"), ("val", "value-split", "number"),
                                       ("far", "required-element-missing", "nothing")))
        rows += '[[value]]\nid = "number"\nelement = "caption"\nprovenance = "spec:P004#3.1"\n'
        nodes = CLEAN[:2] + (("ok", "done", "canary.ok"),)
        found = judge(*base(), ident("detail", nodes), the_contract=contract(lambda t: with_rows(rows)(DONE(t))))
        self.assertEqual(sorted((f["observed"]["exception"], f["severity"]) for f in of(found, "exception-unused")),
                         [("x-far", "info"), ("x-req", "error"), ("x-val", "error")])

    def test_one_catalogue_row_only(self):
        second = '[[catalogue]]\nid = "kit"\nmsgids = "key"\ntext_roles = []\nprovenance = "spec:P004#3.1"\n'
        with self.assertRaises(InternalError):
            contract(with_rows(second))


if __name__ == "__main__":
    unittest.main()
