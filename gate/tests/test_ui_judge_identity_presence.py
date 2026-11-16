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
from tests.test_ui_judge_helpers import OPEN, TODAY, Tree, base, contract, expected_id, sem, step
from tests.test_ui_judge_identity import CLEAN, KEY, ident, judge, of, with_rows

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
                                 [(expected_id("ui-scene", "identity-role-mismatch", ["title", "role"]), "error",
                                   {"stage": "O2", "key": "title", "part": "role", "element": element,
                                    "role": role, "scene_role": "text"})])
        nodes = (("title", "version", "canary.title"),) + CLEAN[1:]    # no role, element or extra id: no verdict
        self.assertEqual(of(judge(*base(), ident("main", nodes)), "identity-role-mismatch"), [])


class ValuePresenceTest(unittest.TestCase):
    def test_only_drawn_nodes_count_and_by_the_gates_role(self):
        semantic, tree = base()
        semantic.append(sem("num", "text", "37", (8, 180, 40, 24), style="title"))
        self.assertEqual(of(judge(semantic, tree, ident("main")), "value-split"), [])   # not drawn: not counted
        tree.label(0, "37", (8, 180, 47, 203))
        found = of(judge(semantic, tree, ident("main")), "value-split")    # untagged, but its role is the title
        self.assertEqual([f["observed"]["nodes"] for f in found], [["num", "title"]])


def unstable(scenes):
    """The state-class-unstable findings of steps (semantic, tree, class) that share one abstraction key."""
    judges = JudgeSet(["ui-scene"], contract(), KEY, TODAY)
    judges.wants_identity(("identity",))
    found = []
    for index, (semantic, tree, state) in enumerate(scenes):
        s = step(semantic, tree, word="w%d" % index, index=index + 1)
        s.obs["identity"] = ident(state)
        found += judges.step_judge(s, PathSoFar([Step(0, OPEN)], 1), None)
    return of(found, "state-class-unstable")


class UnstableClassTest(unittest.TestCase):
    def test_one_observation_naming_two_classes_is_reported_once_per_pair(self):
        found = unstable([base() + ("main",), base() + ("main",), base() + ("detail",), base() + ("detail",)])
        self.assertEqual([(f["id"], f["severity"], f["state"], f["observed"]) for f in found],
                         [(expected_id("ui-scene", "state-class-unstable", ["unstable", "k" * 64, ["detail", "main"]],
                                       stateless=True), "error", None,
                           {"key": "k" * 64, "classes": ["detail", "main"], "witness_path": [OPEN, "w0"]})])

    def test_a_third_class_is_a_finding_of_its_own(self):
        found = unstable([base() + ("main",), base() + ("detail",), base() + ("nowhere",)])
        self.assertEqual([f["observed"]["classes"] for f in found], [["detail", "main"], ["main", "nowhere"]])
        self.assertEqual(len({f["id"] for f in found}), 2)

    def test_different_observations_under_one_key_are_key_too_coarses_not_this(self):
        other = base()
        other[0][1] = other[0][1].replace("Body text", "Other text")
        self.assertEqual(unstable([base() + ("main",), other + ("detail",)]), [])


class TagBindingTest(unittest.TestCase):
    def test_a_required_element_row_id_is_present_at_its_rows_key_without_a_tag(self):
        row = '[[element]]\nid = "done"\nkey = "ok"\nprovenance = "spec:ui-look.md#4.2"\n'
        done = contract(lambda t: with_rows(row)(DONE(t)))
        self.assertEqual(missing(*detail(), the_contract=done), [])          # the OK button is untagged
        nodes = CLEAN[:2] + (("ok", "-", "canary.ok"), ("title", "done", "canary.title"))
        self.assertEqual(missing(*detail(), nodes=nodes, the_contract=done), [])   # a tag elsewhere moves nothing


    def parts(self, nodes, semantic=None, tree=None, the_contract=None):
        semantic, tree = (semantic, tree) if semantic else base()
        return [f["observed"]["part"] for f in of(judge(semantic, tree, ident("main", nodes),
                                                        the_contract=the_contract), "identity-role-mismatch")]

    def test_an_element_row_id_is_its_rows_key(self):
        self.assertEqual(self.parts((("title", "title", "canary.title"), ("ok", "lang_bg", "canary.ok"))),
                         ["element"])
        semantic, tree = base(lang=True)
        self.assertEqual(self.parts(CLEAN + (("lang_bg", "lang_bg", "canary.bg"),), semantic, tree), [])

    def test_a_control_is_a_button_and_a_group_a_panel_over_drawn_buttons(self):
        self.assertEqual(self.parts((("title", "dismiss", "canary.title"),) + CLEAN[1:]), ["constraint"])
        self.assertEqual(self.parts(CLEAN[:2] + (("ok", "dismiss", "canary.ok"),)), [])
        semantic, tree = base()
        semantic.append(sem("pad", "panel", "", (0, 90, 120, 70)))
        tree.node(0, "lv_obj", (0, 90, 119, 159))                  # the button is NOT under the panel
        self.assertEqual(self.parts(CLEAN + (("pad", "numpad", "-"),), semantic, tree), ["constraint"])

    def test_a_group_with_a_drawn_button_under_it(self):
        tree = Tree()
        tree.label(0, "Title", (8, 8, 207, 31))
        tree.label(0, "Body text", (8, 40, 207, 63))
        pad = tree.node(0, "lv_obj", (0, 90, 119, 159))
        button = tree.node(pad, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
        tree.label(button, "OK", (48, 117, 67, 132))
        semantic = base()[0] + [sem("pad", "panel", "", (0, 90, 120, 70))]
        self.assertEqual(self.parts(CLEAN + (("pad", "numpad", "-"),), semantic, tree), [])

    def test_no_verdict_for_a_text_whose_typographic_role_is_unresolved(self):
        semantic, tree = base()
        semantic[0] = sem("title", "text", "Title", (8, 8, 200, 24), style=77)     # no [[style]] has token 77
        found = judge(semantic, tree, ident("main", (("title", "body", "canary.title"),) + CLEAN[1:]))
        self.assertEqual(of(found, "identity-role-mismatch"), [])
        self.assertEqual(of(found, "checks-examined")[0]["observed"]["totals"]["identity-role-mismatch"], 1)


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
        nodes = CLEAN[:2] + (("ok", "-", "OK"),)                   # fix-up 2: a button's label equal to its msgid
        self.assertEqual([f["id"] for f in of(judge(*base(), ident("main", nodes), the_contract=keys), "raw-text")],
                         [expected_id("ui-scene", "raw-text", ["ok", "msgid"])])


class TargetsAndTablesTest(unittest.TestCase):
    def test_an_unused_exception_of_a_required_element_of_a_visited_state_is_an_error(self):
        # targets that are no scene key: `done` (required by detail) and the value `number`
        rows = "".join('[[exception]]\nid = "x-%s"\nrule = "%s"\ntarget = "%s"\nreason = "selftest"\n'
                       'expires = "2099-12-31"\nprovenance = "owner:D1"\n' % (n, r, t)
                       for n, r, t in (("req", "required-element-missing", "done"), ("val", "value-split", "number"),
                                       ("far", "required-element-missing", "nothing")))
        rows += '[[value]]\nid = "number"\nelement = "caption"\nprovenance = "spec:P004#3.1"\n'
        nodes = CLEAN[:2] + (("ok", "done", "canary.ok"),)
        found = judge(*base(), ident("detail", nodes), the_contract=contract(lambda t: with_rows(rows)(DONE(t))))
        self.assertEqual(sorted((f["observed"]["exception"], f["severity"]) for f in of(found, "exception-unused")),
                         [("x-far", "info"), ("x-req", "error"), ("x-val", "info")])   # no node is the value

    def test_a_value_id_is_visited_only_where_a_node_is_that_value(self):
        rows = '[[exception]]\nid = "x-val"\nrule = "value-split"\ntarget = "number"\nreason = "selftest"\n' \
            'expires = "2099-12-31"\nprovenance = "owner:D1"\n' \
            '[[value]]\nid = "number"\nelement = "caption"\nprovenance = "spec:P004#3.1"\n'
        found = judge(*base(), ident("main"), the_contract=contract(with_rows(rows)))
        self.assertEqual([f["severity"] for f in of(found, "exception-unused")], ["info"])   # no caption: not visited
        semantic, tree = base()
        semantic[1] = sem("body", "text", "Body text", (8, 40, 200, 24), style="caption")
        found = judge(semantic, tree, ident("main"), the_contract=contract(with_rows(rows)))
        self.assertEqual([f["severity"] for f in of(found, "exception-unused")], ["error"])

    def test_one_name_one_meaning(self):
        def role_named(name):     # the canary's role `caption` renamed, with its references
            return lambda t: t.replace('id = "caption"\nstyle = "caption"', 'id = "%s"\nstyle = "caption"' % name) \
                .replace('role = "caption"', 'role = "%s"' % name) \
                .replace('roles = ["caption"]', 'roles = ["%s"]' % name)
        self.assertEqual(len(contract(role_named("small_caption")).rows("role")), 5)   # the renaming itself loads
        for edit in (role_named("numpad"), role_named("panel"),
                     with_rows('[[element]]\nid = "body"\nkey = "zzz"\nprovenance = "spec:ui-look.md#4.2"\n')):
            with self.assertRaises(InternalError):
                contract(edit)

    def test_one_catalogue_row_only(self):
        second = '[[catalogue]]\nid = "kit"\nmsgids = "key"\ntext_roles = []\nprovenance = "spec:P004#3.1"\n'
        with self.assertRaises(InternalError):
            contract(with_rows(second))


if __name__ == "__main__":
    unittest.main()
