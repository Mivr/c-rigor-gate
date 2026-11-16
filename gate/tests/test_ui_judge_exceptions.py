"""Exceptions, the run-level findings, the judge set and determinism of the ui-scene and ui-fit judges (U06): a live
exception (against `--today`) turns exactly the finding with its check and target into info; an unused, duplicate or
expired one is exception-unused (an error when its target was visited, info when not); `checks-examined` and
`check-vacuous`; the loader's closed rule list takes the judges' own ids; the judges refuse to run without a contract
or a date; ids do not depend on the order of the scene records; the CLI with the explorer's stub probe."""

import datetime
import unittest

from rigor_lib import ui_contract
from rigor_lib.errors import InternalError
from rigor_lib.ui_judge_findings import JudgeSet
from tests import test_ui_explore_helpers as h
from tests.test_ui_judge_helpers import (CANARY_CONTRACT, KEY, TODAY, Tree, base, checks, contract, expected_id, run,
                                         sem)

RUN_LEVEL = ("checks-examined", "check-vacuous")


def exception(ident, rule, target, expires="2099-12-31"):
    return ('\n[[exception]]\nid = "%s"\nrule = "%s"\ntarget = "%s"\nreason = "test"\nexpires = "%s"\n'
            'provenance = "owner:D1"\n' % (ident, rule, target, expires))


def small_ok():
    """The base scene with the ok button 47 px high: one touch-target-small on `ok`."""
    semantic, _tree = base()
    semantic[2] = sem("ok", "button", "OK", (8, 100, 100, 47), intent="1:0", style="btn")
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    tree.label(0, "Body text", (8, 40, 207, 63))
    button = tree.node(0, "lv_button", (8, 100, 107, 146), clickable=1, bg=255)
    tree.label(button, "OK", (48, 117, 67, 132))
    return semantic, tree


def with_exceptions(*rows):
    return contract(lambda t: t + "".join(rows))


def finished(*args, **kw):
    """The findings of one step and the end of the run, without the run-level counts."""
    return [f for f in run(*args, finish=True, **kw) if f["check"] not in RUN_LEVEL]


class ExceptionTest(unittest.TestCase):
    def test_a_live_exception_turns_exactly_its_finding_into_info(self):
        c = with_exceptions(exception("e1", "touch-target-small", "ok"))
        self.assertEqual([(f["id"], f["severity"], f["observed"]["exception"]) for f in finished(*small_ok(),
                                                                                                 the_contract=c)],
                         [(expected_id("ui-scene", "touch-target-small", ["ok", "dp"]), "info",
                           {"id": "e1", "expires": "2099-12-31"})])

    def test_an_unused_exception_is_an_error_when_its_target_was_visited_and_info_when_not(self):
        for target, severity in (("ok", "error"), ("back", "info")):
            row = exception("e1", "font-below-min", target)
            found = finished(*small_ok(), the_contract=with_exceptions(row))
            self.assertEqual([(f["check"], f["severity"]) for f in found],
                             [("touch-target-small", "error"), ("exception-unused", severity)], target)
            unused = found[1]
            self.assertEqual((unused["id"], unused["state"], unused["path"], unused["observed"]["target_visited"]),
                             (expected_id("ui-scene", "exception-unused", ["exception", "e1"], stateless=True), None,
                              ["open 1000 7"], severity == "error"))

    def test_an_exception_expired_yesterday_is_not_applied_one_expiring_today_is(self):
        expired = with_exceptions(exception("e1", "touch-target-small", "ok", "2026-11-15"))
        found = finished(*small_ok(), the_contract=expired)
        self.assertEqual([(f["check"], f["severity"]) for f in found],
                         [("touch-target-small", "error"), ("exception-unused", "error")])
        self.assertEqual(found[1]["observed"],
                         {"exception": "e1", "rule": "touch-target-small", "target": "ok", "expires": "2026-11-15",
                          "expired": True, "target_visited": True})
        today = with_exceptions(exception("e1", "touch-target-small", "ok", "2026-11-16"))
        self.assertEqual([f["severity"] for f in finished(*small_ok(), the_contract=today)], ["info"])
        self.assertEqual([f["severity"] for f in finished(*small_ok(), the_contract=today,
                                                          today=datetime.date(2026, 11, 17))], ["error", "error"])

    def test_a_duplicate_exception_is_unused(self):
        c = with_exceptions(exception("e1", "touch-target-small", "ok"), exception("e2", "touch-target-small", "ok"))
        found = finished(*small_ok(), the_contract=c)
        self.assertEqual([(f["check"], f["severity"]) for f in found],
                         [("touch-target-small", "info"), ("exception-unused", "error")])
        self.assertEqual((found[0]["observed"]["exception"]["id"], found[1]["observed"]["exception"]), ("e1", "e2"))

    def test_an_exception_for_a_check_of_a_judge_not_selected_is_not_judged(self):
        c = with_exceptions(exception("e1", "touch-target-small", "nobody"))
        self.assertEqual(finished(*base(), gates=("ui-fit",), the_contract=c), [])
        self.assertEqual(checks(finished(*base(), the_contract=c)), ["exception-unused"])

    def test_a_pair_finding_is_excepted_by_both_keys_in_order(self):
        semantic, tree = base()
        tree.label(0, "More", (8, 63, 207, 86))
        semantic.append(sem("more", "text", "More", (8, 63, 200, 24), style="body"))
        c = with_exceptions(exception("e1", "text-overlap", "body/more"))
        self.assertEqual([f["severity"] for f in finished(semantic, tree, the_contract=c)], ["info"])
        c = with_exceptions(exception("e1", "text-overlap", "more/body"))
        self.assertEqual(checks(finished(semantic, tree, the_contract=c), "error"),
                         ["exception-unused", "text-overlap"])

    def test_the_judges_own_ids_may_be_excepted_others_not(self):
        for rule in ("stage-unmatched", "stage-text-mismatch", "fit-unmeasurable", "glyph-missing"):
            self.assertIn(rule, ui_contract.EXCEPTION_RULES)
            self.assertEqual(with_exceptions(exception("e1", rule, "body")).ids("exception"), ["e1"])
        for rule in ("exception-unused", "contract-pending", "scene-vocabulary", "check-vacuous", "glyph-missin"):
            with self.assertRaises(InternalError):
                with_exceptions(exception("e1", rule, "body"))
        semantic, tree = base()
        semantic.append(sem("ghost", "panel", "", (250, 8, 40, 40)))
        c = with_exceptions(exception("e1", "stage-unmatched", "ghost"))
        found = finished(semantic, tree, the_contract=c)
        self.assertEqual([(f["check"], f["observed"]["exception"]["id"]) for f in found], [("stage-unmatched", "e1")])

    def test_an_unowned_label_can_be_excepted_by_its_name(self):
        semantic, tree = base()
        tree.label(0, "Stray", (220, 200, 279, 215), clipped=1)
        name = [f for f in run(semantic, tree) if f["check"] == "text-clipped"][0]["observed"]["label"]["target"]
        c = with_exceptions(exception("e1", "text-clipped", name))
        self.assertEqual([(f["check"], f["severity"]) for f in finished(semantic, tree, the_contract=c)],
                         [("stage-unmatched", "info"), ("text-clipped", "info")])


class RunLevelTest(unittest.TestCase):
    def run_level(self, semantic, tree, **kw):
        return {(f["gate"], f["check"]): f for f in run(semantic, tree, finish=True, **kw) if f["check"] in RUN_LEVEL
                and f["check"] == "checks-examined"}, \
            sorted((f["gate"], f["observed"]["check"]) for f in run(semantic, tree, finish=True, **kw)
                   if f["check"] == "check-vacuous")

    def test_every_judge_reports_the_nodes_each_check_examined_per_state(self):
        examined, vacuous = self.run_level(*base(lang=True))
        scene = examined[("ui-scene", "checks-examined")]
        self.assertEqual((scene["severity"], scene["state"], scene["id"]),
                         ("info", None, expected_id("ui-scene", "checks-examined", ["examined"], stateless=True)))
        self.assertEqual(scene["observed"]["totals"], {
            "occluded-target": 3, "overlay-policy": 0, "touch-target-small": 3, "target-spacing": 3,
            "node-out-of-bounds": 5, "text-overlap": 5, "font-below-min": 5, "hierarchy-violated": 5, "raw-text": 2,
            "wrap-policy-undeclared": 5, "toggle-group-indistinct": 2})
        self.assertEqual(list(scene["observed"]["per_state"]), ["k" * 64])
        self.assertEqual(vacuous, [("ui-scene", "overlay-policy")])

    def test_a_check_that_examined_nothing_and_applies_is_vacuous_one_whose_layers_were_pending_is_not(self):
        _examined, vacuous = self.run_level(*base())
        self.assertEqual(vacuous, [("ui-scene", "overlay-policy"), ("ui-scene", "toggle-group-indistinct")])
        semantic, tree = base(lang=True)
        tree.node(0, "lv_obj", (0, 180, 319, 239))
        semantic.append(sem("b", "banner", "", (0, 180, 320, 60)))
        c = contract(lambda t: t.replace('id = "banner"\nrole = "banner"\npolicy = "pass-through"',
                                         'id = "banner"\nrole = "banner"\npending = "7"'))
        examined, vacuous = self.run_level(semantic, tree, the_contract=c)
        self.assertEqual((examined[("ui-scene", "checks-examined")]["observed"]["totals"]["overlay-policy"], vacuous),
                         (1, []))

    def test_a_scene_without_any_target_leaves_the_target_checks_vacuous(self):
        semantic = [line.replace("\t1:0\t", "\t-\t") for line in base()[0]]
        _examined, vacuous = self.run_level(semantic, base()[1])
        self.assertEqual(vacuous, [("ui-scene", "occluded-target"), ("ui-scene", "overlay-policy"),
                                   ("ui-scene", "target-spacing"), ("ui-scene", "toggle-group-indistinct"),
                                   ("ui-scene", "touch-target-small")])


class JudgeSetTest(unittest.TestCase):
    def test_the_judges_need_a_contract_a_date_and_distinct_known_names(self):
        for gates, the_contract, today in ((["ui-scene"], None, TODAY), (["ui-scene"], contract(), None),
                                           (["ui-nope"], contract(), TODAY), (["ui-fit", "ui-fit"], contract(), TODAY),
                                           ([], contract(), TODAY)):
            with self.assertRaises(InternalError):
                JudgeSet(gates, the_contract, KEY, today)
        self.assertEqual(JudgeSet(["ui-fit", "ui-scene"], contract(), KEY, TODAY).gates, ("ui-scene", "ui-fit"))

    def test_ids_do_not_depend_on_the_order_of_the_scene_records(self):
        semantic, tree = small_ok()
        semantic.append(sem("ghost", "panel", "", (250, 8, 40, 40)))
        semantic.append(sem("more", "text", "", (8, 63, 200, 24), style="body"))
        tree.label(0, "", (8, 63, 207, 86))
        forward = sorted(f["id"] for f in run(semantic, tree))
        backward = sorted(f["id"] for f in run(list(reversed(semantic)), tree))
        self.assertEqual(forward, backward)
        self.assertEqual(len(forward), 3)


# ---- the CLI with the stub probe of the explorer tests -------------------------------------------------------------
def tearDownModule():
    h.assert_no_stubs()


class CliTest(h.ExploreCase):
    def judges(self, mode, *extra, out="f.json", code=None):
        return self.bfs(mode, 1, "--judges", "ui-scene,ui-fit", *extra, out=out, code=code)

    def test_the_judges_refuse_a_probe_without_frame_facts_a_run_without_a_contract_or_a_date(self):
        outcome, _ = self.judges("good", "--contract", CANARY_CONTRACT, "--today", "2026-11-16", code=2)
        self.assertIn("frame-facts", outcome.stderr)
        outcome, _ = self.judges("facts", "--today", "2026-11-16", code=2)
        self.assertIn("need --contract", outcome.stderr)
        outcome, _ = self.judges("facts", "--contract", CANARY_CONTRACT, code=2)
        self.assertIn("need --today", outcome.stderr)
        for bad in ("2026-13-01", "26-11-16", "2026-11-16x"):
            self.judges("facts", "--contract", CANARY_CONTRACT, "--today", bad, code=2)
        outcome, _ = self.bfs("facts", 1, "--today", "2026-11-16", code=2)
        self.assertIn("only for --judges", outcome.stderr)

    def test_the_stub_scene_is_outside_the_vocabulary_byte_identically_twice_and_counted_in_the_summary(self):
        # the stub's records use the toy's product strings (roles label/button, style body, importance normal)
        args = ("--contract", CANARY_CONTRACT, "--today", "2026-11-16", "--summary", self.tmp / "s.json")
        self.judges("facts", *args, out="a.json", code=1)
        self.judges("facts", *args, out="b.json", code=1)
        first = (self.tmp / "a.json").read_bytes()
        self.assertEqual(first, (self.tmp / "b.json").read_bytes())
        found = [f for f in h.findings(self.tmp / "a.json") if f["gate"] in ("ui-scene", "ui-fit")
                 and f["check"] not in RUN_LEVEL]
        self.assertEqual({f["check"] for f in found}, {"scene-vocabulary"})
        self.assertEqual(sorted({f["observed"]["key"] for f in found}), ["button", "notice", "title"])
        import json
        counts = json.loads((self.tmp / "s.json").read_text())["findings"]
        self.assertEqual(counts["ui-scene.scene-vocabulary"], len(found))
        self.assertEqual(counts["ui-scene.checks-examined"], 1)


if __name__ == "__main__":
    unittest.main()
