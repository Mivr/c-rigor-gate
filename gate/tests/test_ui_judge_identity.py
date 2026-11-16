"""The identity checks of the ui-scene judge (U24, docs/ui-judges.md): required-element-missing, value-split, the
identity parts of raw-text, `check-blocked` without identity, their verdicts in checks-examined and their vacuity;
and the contract tables they read ([[value]], [[catalogue]], [[identity_literal]]: docs/ui-contract.md). The scenes
are the helpers' clean base (title, body, ok) against the canary contract: `main` requires the title, `detail` the
title and the body; the title is one value; msgids are keys and the title and body roles are catalogue text."""

import copy
import unittest

from rigor_lib import ui_contract
from rigor_lib.errors import InternalError
from rigor_lib.ui_explore_grammar import parse_identity
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet
from types import SimpleNamespace

from tests.test_ui_judge_helpers import OPEN, TODAY, base, contract, expected_id, sem, step

# the helpers' key with what ui_explore_key.normalised reads (state-class-unstable compares normalised observations)
KEY = SimpleNamespace(fields=("role",), facts=(), derived=(), ignore=())
CLEAN = (("title", "title", "canary.title"), ("body", "body", "canary.body"), ("ok", "-", "canary.ok"))


def ident(state, nodes=CLEAN):
    """The parsed identity records of `state` and (key, element, msgid, args...) per node."""
    lines = ["state\t" + state] + ["\t".join(["node", k, e, m, str(len(a))] + ["=" + x for x in a])
                                   for k, e, m, *a in nodes]
    return parse_identity(lines)


def judge(semantic, tree, identity, the_contract=None, caps=("identity",), gates=("ui-scene",), finish=True):
    judges = JudgeSet(list(gates), the_contract or contract(), KEY, TODAY)
    judges.wants_identity(caps)
    s = step(semantic, tree)
    if identity is not None:
        s.obs["identity"] = identity
    found = judges.step_judge(s, PathSoFar([Step(0, OPEN)], 1), None)
    if finish:
        found = found + judges.finish(OPEN)
    return [{k: v for k, v in copy.deepcopy(f).items() if k != "_evidence"} for f in found]


def of(found, *checks):
    return [f for f in found if f["check"] in checks]


def ident_checks(found):
    return of(found, "required-element-missing", "value-split", "raw-text", "check-blocked", "identity-role-mismatch",
              "state-class-unstable")


def vacuous(found):
    """The identity checks among the vacuous ones (the base scene leaves overlay-policy and the toggle group
    vacuous)."""
    return [f["observed"]["check"] for f in of(found, "check-vacuous")
            if f["observed"]["check"] in ("required-element-missing", "value-split")]


def with_rows(text):
    return lambda t: t + "\n" + text


class RequiredElementTest(unittest.TestCase):
    def test_the_clean_state_has_no_finding_and_every_identity_check_reaches_its_verdicts(self):
        found = judge(*base(), ident("main"))
        self.assertEqual(ident_checks(found), [])
        examined = of(found, "checks-examined")[0]["observed"]["totals"]
        self.assertEqual((examined["required-element-missing"], examined["value-split"], examined["raw-text"],
                          examined["identity-role-mismatch"]), (1, 1, 2, 2))
        self.assertEqual(vacuous(found), [])

    def test_a_required_element_no_scene_node_is_is_missing(self):
        semantic, tree = base()
        del semantic[1]                                  # the body is not in the scene (its label is still drawn)
        nodes = (("title", "title", "canary.title"), ("ok", "-", "canary.ok"))
        found = of(judge(semantic, tree, ident("detail", nodes)), "required-element-missing")
        self.assertEqual([(f["id"], f["severity"], f["observed"]) for f in found],
                         [(expected_id("ui-scene", "required-element-missing", ["detail", "body"]), "error",
                           {"stage": "O2", "state_class": "detail", "element": "body", "undrawn": []})])

    def test_a_node_hidden_by_its_scene_flag_does_not_count_as_present(self):
        semantic, tree = base()
        semantic[1] = semantic[1].replace("\t1\t-\t-\t", "\t1\t-\tH\t")
        found = of(judge(semantic, tree, ident("detail")), "required-element-missing")
        self.assertEqual([f["observed"]["undrawn"] for f in found], [["body"]])
        self.assertEqual(of(judge(*base(), ident("detail")), "required-element-missing"), [])

    def test_an_unknown_state_class_is_contract_incomplete_and_no_verdict(self):
        found = judge(*base(), ident("nowhere"))
        self.assertEqual([f["id"] for f in of(found, "contract-incomplete")],
                         [expected_id("ui-scene", "contract-incomplete", ["state-class", "nowhere"], stateless=True)])
        self.assertEqual(of(found, "required-element-missing"), [])
        self.assertEqual(vacuous(found), ["required-element-missing"])

    def test_an_element_only_a_node_outside_the_vocabulary_carries_reaches_no_verdict(self):
        # `done` is no role id: its presence is the product's tag, and only an unreadable node carries it
        done = contract(lambda t: t.replace('required = ["title", "body"]', 'required = ["title", "done"]'))
        semantic, tree = base()
        semantic.append(sem("odd", "label", "x", (8, 180, 20, 20)))
        nodes = CLEAN + (("odd", "done", "canary.x"),)
        found = judge(semantic, tree, ident("detail", nodes), the_contract=done)
        self.assertEqual(of(found, "required-element-missing"), [])
        self.assertEqual(of(found, "checks-examined")[0]["observed"]["totals"]["required-element-missing"], 1)


class ValueSplitTest(unittest.TestCase):
    def split(self, flags="-"):
        semantic, tree = base()
        semantic.append(sem("num", "text", "37", (8, 180, 40, 24), style="title", flags=flags))
        tree.label(0, "37", (8, 180, 47, 203))
        return semantic, tree, ident("main", CLEAN + (("num", "title", "canary.num", "37"),))

    def test_the_nodes_of_one_value_number_more_than_max_nodes(self):
        found = of(judge(*self.split()), "value-split")
        self.assertEqual([(f["id"], f["observed"]) for f in found],
                         [(expected_id("ui-scene", "value-split", ["title"]),
                           {"stage": "O2", "value": "title", "element": "title", "nodes": ["num", "title"],
                            "max_nodes": 1})])

    def test_max_nodes_and_a_hidden_node(self):
        two = contract(lambda t: t.replace('id = "title"\nelement = "title"\n', 'id = "title"\nelement = "title"\n'
                                                                             'max_nodes = 2\n'))
        self.assertEqual(of(judge(*self.split(), the_contract=two), "value-split"), [])
        self.assertEqual(of(judge(*self.split(flags="H")), "value-split"), [])


class RawTextTest(unittest.TestCase):
    def test_a_label_equal_to_its_msgid_is_a_raw_msgid(self):
        nodes = (("title", "title", "canary.title"), ("body", "body", "Body text"))
        found = of(judge(*base(), ident("main", nodes)), "raw-text")
        self.assertEqual([(f["id"], f["observed"]) for f in found],
                         [(expected_id("ui-scene", "raw-text", ["body", "msgid"]),
                           {"stage": "O2", "key": "body", "part": "msgid"})])

    def test_an_identity_literal_and_source_text_msgids_are_not_reported(self):
        nodes = (("title", "title", "canary.title"), ("body", "body", "Body text"))
        literal = contract(with_rows('[[identity_literal]]\nmsgid = "Body text"\nprovenance = "spec:P004#3.1"\n'))
        self.assertEqual(of(judge(*base(), ident("main", nodes), the_contract=literal), "raw-text"), [])
        source = contract(lambda t: t.replace('msgids = "key"', 'msgids = "source-text"'))
        found = judge(*base(), ident("main", nodes), the_contract=source)
        self.assertEqual(of(found, "raw-text"), [])
        self.assertEqual(of(found, "checks-examined")[0]["observed"]["not_applicable"], {"raw-text": 2})

    def test_catalogue_text_without_a_msgid(self):
        nodes = (("title", "title", "canary.title"), ("body", "body", "-"))
        found = of(judge(*base(), ident("main", nodes)), "raw-text")
        self.assertEqual([(f["id"], f["observed"]) for f in found],
                         [(expected_id("ui-scene", "raw-text", ["body", "no-msgid"]),
                           {"stage": "O2", "key": "body", "part": "no-msgid", "role": "body"})])
        no_roles = contract(lambda t: t.replace('text_roles = ["title", "body"]', 'text_roles = ["title"]'))
        self.assertEqual(of(judge(*base(), ident("main", nodes), the_contract=no_roles), "raw-text"), [])

    def test_without_identity_raw_text_keeps_its_empty_part_only(self):
        semantic, tree = base()
        semantic[1] = semantic[1].replace("\tBody text\t", "\t\t")
        found = of(judge(semantic, tree, None, caps=None), "raw-text")
        self.assertEqual([f["observed"]["part"] for f in found], ["empty"])


class BlockedTest(unittest.TestCase):
    def test_a_probe_without_identity_blocks_each_identity_check_that_applies(self):
        found = judge(*base(), None, caps=("frame-facts",))
        blocked = of(found, "check-blocked")
        self.assertEqual([(f["id"], f["severity"], f["state"], f["observed"]) for f in blocked],
                         [(expected_id("ui-scene", "check-blocked", ["blocked", c], stateless=True), "error", None,
                           {"check": c, "needs": "identity"}) for c in ("required-element-missing", "value-split",
                                                                       "raw-text")])
        totals = of(found, "checks-examined")[0]["observed"]["totals"]
        self.assertNotIn("value-split", totals)
        self.assertEqual(vacuous(found), [])
        bare = contract(lambda t: t.split("# U24: the tables")[0])
        self.assertEqual([f["observed"]["check"] for f in of(judge(*base(), None, the_contract=bare,
                                                                    caps=("frame-facts",)), "check-blocked")],
                         ["required-element-missing"])

    def test_no_block_without_ui_scene_or_when_the_caller_does_not_say(self):
        self.assertEqual(of(judge(*base(), None, caps=("frame-facts",), gates=("ui-fit",)), "check-blocked"), [])
        self.assertEqual(of(judge(*base(), None, caps=None), "check-blocked"), [])
        judges = JudgeSet(["ui-fit"], contract(), KEY, TODAY)
        self.assertEqual((judges.wants_identity(("identity",)), judges.identity), (False, None))
        judges = JudgeSet(["ui-scene"], contract(), KEY, TODAY)
        self.assertEqual((judges.wants_identity(("identity",)), judges.identity), (True, True))

    def test_ids_do_not_depend_on_the_order_of_the_identity_records(self):
        nodes = (("title", "title", "canary.title"), ("body", "-", "Body text"), ("ok", "-", "canary.ok"))
        forward = sorted(f["id"] for f in judge(*base(), ident("detail", nodes)))
        backward = sorted(f["id"] for f in judge(*base(), ident("detail", tuple(reversed(nodes)))))
        self.assertEqual(forward, backward)


class ContractTablesTest(unittest.TestCase):
    def test_the_tables_may_be_absent_and_are_read_with_their_defaults(self):
        bare = contract(lambda t: t.split("# U24: the tables")[0])
        self.assertEqual((bare.rows("value"), bare.rows("catalogue"), bare.rows("identity_literal")), ((), (), ()))
        full = contract()
        self.assertEqual(([dict(r) for r in full.rows("value")], full.rows("catalogue")[0]["msgids"]),
                         ([{"id": "title", "element": "title", "provenance": "spec:P004#3.1"}], "key"))

    def test_the_loader_refuses_malformed_rows(self):
        bad = (('element = "title"', 'element = "nothing"'),            # not a role, element or extra element
               ('element = "title"', 'element = "title"\nmax_nodes = 0'),
               ('element = "title"', 'element = "title"\nmax_nodes = "2"'),
               ('msgids = "key"', 'msgids = "keys"'),
               ('text_roles = ["title", "body"]', 'text_roles = ["title", "nobody"]'),
               ('[[catalogue]]\nid = "canary"', '[[catalogue]]\nid = "canary"\nextra = 1'),
               ('element = "title"\nprovenance = "spec:P004#3.1"\n', 'element = "title"\n'))
        for old, new in bad:
            with self.subTest(new=new), self.assertRaises(InternalError):
                contract(lambda t, o=old, n=new: t.replace(o, n, 1))
        twice = '[[value]]\nid = "again"\nelement = "title"\nprovenance = "spec:P004#3.1"\n'
        with self.assertRaises(InternalError):
            contract(with_rows(twice))
        with self.assertRaises(InternalError):
            contract(with_rows('[[identity_literal]]\nmsgid = ""\nprovenance = "spec:P004#3.1"\n'))
        ok = '[[value]]\nid = "flag"\nelement = "lang_bg"\nmax_nodes = 64\nprovenance = "spec:P004#3.1"\n'
        self.assertEqual(len(contract(with_rows(ok)).rows("value")), 2)   # an [[element]] id names a value too

    def test_the_lockers_contract_still_loads_without_the_tables(self):
        lockers = ui_contract.load(contract.__globals__["REPO"] / "products" / "business-apps" / "ui" / "lockers.toml")
        self.assertEqual((lockers.rows("value"), lockers.rows("catalogue")), ((), ()))


if __name__ == "__main__":
    unittest.main()
