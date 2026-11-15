"""Exceptions, the judge set and determinism of the ui-scene and ui-fit judges (U06): a live exception turns exactly the
finding with its check and target into info with its expiry; an unused, duplicate or expired one is exception-unused;
the loader's closed rule list takes the judges' own ids; the judges refuse to run without a contract; finding ids do
not depend on the order of the scene records."""

import datetime
import unittest

from rigor_lib import ui_contract
from rigor_lib.errors import InternalError
from rigor_lib.ui_judge_findings import JudgeSet
from tests.test_ui_judge_helpers import KEY, Tree, base, checks, contract, expected_id, run, sem

TODAY = datetime.date(2026, 11, 15)


def exception(ident, rule, target, expires="2099-12-31"):
    return ('\n[[exception]]\nid = "%s"\nrule = "%s"\ntarget = "%s"\nreason = "test"\nexpires = "%s"\n'
            'provenance = "owner:D1"\n' % (ident, rule, target, expires))


def small_ok():
    """The base scene with the ok button 47 px high: one touch-target-small on `ok`."""
    semantic, _tree = base()
    semantic[2] = sem("ok", "key_label", "OK", (8, 100, 100, 47), intent="1:0", style="btn", importance="2",
                      wrap="single_line")
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    tree.label(0, "Body text", (8, 40, 207, 63))
    button = tree.node(0, "lv_button", (8, 100, 107, 146), clickable=1, bg=255)
    tree.label(button, "OK", (48, 117, 67, 132))
    return semantic, tree


def with_exceptions(*rows):
    return contract(lambda t: t + "".join(rows))


class ExceptionTest(unittest.TestCase):
    def test_a_live_exception_turns_exactly_its_finding_into_info(self):
        c = with_exceptions(exception("e1", "touch-target-small", "ok"))
        found = run(*small_ok(), the_contract=c, today=TODAY, finish=True)
        self.assertEqual([(f["id"], f["severity"], f["observed"]["exception"]) for f in found],
                         [(expected_id("ui-scene", "touch-target-small", ["ok", "dp"]), "info",
                           {"id": "e1", "expires": "2099-12-31"})])

    def test_another_target_or_rule_leaves_the_finding_and_the_exception_is_unused(self):
        for row in (exception("e1", "touch-target-small", "back"), exception("e1", "font-below-min", "ok")):
            found = run(*small_ok(), the_contract=with_exceptions(row), today=TODAY, finish=True)
            self.assertEqual([(f["check"], f["severity"]) for f in found],
                             [("touch-target-small", "error"), ("exception-unused", "error")])
            unused = found[1]
            self.assertEqual((unused["id"], unused["state"], unused["path"], unused["observed"]["expired"]),
                             (expected_id("ui-scene", "exception-unused", ["exception", "e1"], stateless=True), None,
                              ["open 1000 7"], False))

    def test_an_exception_expired_yesterday_is_not_applied_one_expiring_today_is(self):
        expired = with_exceptions(exception("e1", "touch-target-small", "ok", "2026-11-14"))
        found = run(*small_ok(), the_contract=expired, today=TODAY, finish=True)
        self.assertEqual([(f["check"], f["severity"]) for f in found],
                         [("touch-target-small", "error"), ("exception-unused", "error")])
        self.assertEqual(found[1]["observed"],
                         {"exception": "e1", "rule": "touch-target-small", "target": "ok", "expires": "2026-11-14",
                          "expired": True})
        today = with_exceptions(exception("e1", "touch-target-small", "ok", "2026-11-15"))
        self.assertEqual([f["severity"] for f in run(*small_ok(), the_contract=today, today=TODAY, finish=True)],
                         ["info"])

    def test_a_duplicate_exception_is_unused(self):
        c = with_exceptions(exception("e1", "touch-target-small", "ok"), exception("e2", "touch-target-small", "ok"))
        found = run(*small_ok(), the_contract=c, today=TODAY, finish=True)
        self.assertEqual([(f["check"], f["severity"]) for f in found],
                         [("touch-target-small", "info"), ("exception-unused", "error")])
        self.assertEqual((found[0]["observed"]["exception"]["id"], found[1]["observed"]["exception"]), ("e1", "e2"))

    def test_an_exception_for_a_check_of_a_judge_not_selected_is_not_judged(self):
        c = with_exceptions(exception("e1", "touch-target-small", "nobody"))
        self.assertEqual(run(*base(), gates=("ui-fit",), the_contract=c, today=TODAY, finish=True), [])
        self.assertEqual(checks(run(*base(), the_contract=c, today=TODAY, finish=True)), ["exception-unused"])

    def test_a_pair_finding_is_excepted_by_both_keys_in_order(self):
        semantic, tree = base()
        tree.label(0, "More", (8, 63, 207, 86))
        semantic.append(sem("more", "body", "More", (8, 63, 200, 24), style="body", importance="2", wrap="default"))
        c = with_exceptions(exception("e1", "text-overlap", "body/more"))
        self.assertEqual([f["severity"] for f in run(semantic, tree, the_contract=c, today=TODAY, finish=True)],
                         ["info"])
        c = with_exceptions(exception("e1", "text-overlap", "more/body"))
        self.assertEqual(checks(run(semantic, tree, the_contract=c, today=TODAY, finish=True), "error"),
                         ["exception-unused", "text-overlap"])

    def test_the_judges_own_ids_may_be_excepted_others_not(self):
        for rule in ("stage-unmatched", "fit-unmeasurable", "glyph-missing"):
            self.assertIn(rule, ui_contract.EXCEPTION_RULES)
            self.assertEqual(with_exceptions(exception("e1", rule, "body")).ids("exception"), ["e1"])
        for rule in ("exception-unused", "contract-pending", "scene-vocabulary", "glyph-missin"):
            with self.assertRaises(InternalError):
                with_exceptions(exception("e1", rule, "body"))
        semantic, tree = base()
        semantic.append(sem("ghost", "panel", "", (250, 8, 40, 40)))
        c = with_exceptions(exception("e1", "stage-unmatched", "ghost"))
        found = run(semantic, tree, the_contract=c, today=TODAY, finish=True)
        self.assertEqual([(f["check"], f["observed"]["exception"]["id"]) for f in found], [("stage-unmatched", "e1")])


class JudgeSetTest(unittest.TestCase):
    def test_the_judges_need_a_contract_and_distinct_known_names(self):
        for gates, the_contract in ((["ui-scene"], None), (["ui-nope"], contract()), (["ui-fit", "ui-fit"], contract()),
                                    ([], contract())):
            with self.assertRaises(InternalError):
                JudgeSet(gates, the_contract, KEY)
        self.assertEqual(JudgeSet(["ui-fit", "ui-scene"], contract(), KEY).gates, ("ui-scene", "ui-fit"))

    def test_ids_do_not_depend_on_the_order_of_the_scene_records(self):
        semantic, tree = small_ok()
        semantic.append(sem("ghost", "panel", "", (250, 8, 40, 40)))
        semantic.append(sem("more", "body", "", (8, 63, 200, 24), style="body", importance="2"))
        tree.label(0, "", (8, 63, 207, 86))
        forward = sorted(f["id"] for f in run(semantic, tree))
        backward = sorted(f["id"] for f in run(list(reversed(semantic)), tree))
        self.assertEqual(forward, backward)
        self.assertEqual(len(forward), 4)


if __name__ == "__main__":
    unittest.main()


# ---- the CLI with the stub probe of the explorer tests -------------------------------------------------------------
from tests import test_ui_explore_helpers as h            # noqa: E402  (after the unit tests above)
from tests.test_ui_judge_helpers import CANARY_CONTRACT   # noqa: E402


def tearDownModule():
    h.assert_no_stubs()


class CliTest(h.ExploreCase):
    def judges(self, mode, *extra, out="f.json", code=None):
        return self.bfs(mode, 1, "--judges", "ui-scene,ui-fit", *extra, out=out, code=code)

    def test_the_judges_refuse_a_probe_without_frame_facts_and_a_run_without_a_contract(self):
        outcome, _ = self.judges("good", "--contract", CANARY_CONTRACT, code=2)
        self.assertIn("frame-facts", outcome.stderr)
        outcome, _ = self.judges("facts", code=2)
        self.assertIn("need --contract", outcome.stderr)

    def test_the_stub_scene_is_outside_the_vocabulary_byte_identically_twice(self):
        # the stub's records use the toy's product strings (roles label/button, importance normal, wrap none)
        self.judges("facts", "--contract", CANARY_CONTRACT, out="a.json", code=1)
        self.judges("facts", "--contract", CANARY_CONTRACT, out="b.json", code=1)
        first = (self.tmp / "a.json").read_bytes()
        self.assertEqual(first, (self.tmp / "b.json").read_bytes())
        found = [f for f in h.findings(self.tmp / "a.json") if f["gate"] in ("ui-scene", "ui-fit")]
        self.assertTrue(found)
        self.assertEqual({f["check"] for f in found}, {"scene-vocabulary"})
        self.assertEqual(sorted({f["observed"]["key"] for f in found}), ["button", "notice", "title"])
