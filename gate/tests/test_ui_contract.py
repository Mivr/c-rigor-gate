"""The UI contract loader (`rigor_lib.ui_contract`) against the checked-in lockers contract and edited copies."""

import re
import unittest
from pathlib import Path

from rigor_lib import ui_contract as uc
from rigor_lib.errors import InternalError

REPO = Path(__file__).resolve().parent.parent.parent
LOCKERS = REPO / "products" / "business-apps" / "ui" / "lockers.toml"
TEXT = LOCKERS.read_text(encoding="utf-8")
KIOSK_METRICS = {"display": 200, "headline": 48, "title": 40, "body": 32, "staff": 24, "caption": 16}
# The section 3.10 quantities of P004 (one key each) that the contract must carry.
SECTION_3_10_KEYS = (
    "keypad_key_min_mm", "button_recommended_mm", "button_floor_mm", "touch_min_mm", "touch_min_dp",
    "hit_overlap_allowed", "spacing_hard_mm", "spacing_recommended_mm", "probe_grid_pct", "probe_disc_radius_mm",
    "feedback_rendered_frames_max", "feedback_target_frames", "frame_hz", "busy_indicator_ms",
    "busy_progress_cancel_ms", "dwell_base_ms", "dwell_floor_ms", "dwell_chars_per_word", "flicker_floor_ms",
    "legibility_xheight_deg", "contrast_text", "contrast_large", "pseudo_expansion_overall_pct",
    "relational_geometry_tol_px", "pixel_tolerance", "hierarchy_ratio_k")


def edited(old, new, count=1):
    assert TEXT.count(old) >= 1, old
    return TEXT.replace(old, new, count)


def must_fail(test, text, fragment):
    with test.assertRaises(InternalError) as caught:
        uc.loads(text)
    test.assertIn(fragment, str(caught.exception))


class Checked(unittest.TestCase):
    def test_the_lockers_contract_loads(self):
        contract = uc.load(LOCKERS)
        self.assertEqual(contract.product, "business-apps/lockers")
        self.assertEqual(contract.get("window", "width_px"), 1280)
        self.assertEqual(contract.get("window", "height_px"), 800)

    def test_every_entry_and_row_has_a_provenance(self):
        contract = uc.load(LOCKERS)
        count = 0
        for section in contract.scalars.values():
            for entry in section.values():
                uc.check_provenance("entry", entry.provenance)
                count += 1
        for rows in contract.tables.values():
            for row in rows:
                uc.check_provenance("row", row["provenance"])
                count += 1
        self.assertGreater(count, 100)

    def test_removing_a_provenance_is_an_error(self):
        must_fail(self, edited('{ value = 1280, provenance = "spec:ui-look.md#1" }', "{ value = 1280 }"),
                  "window.width_px has no provenance")
        must_fail(self, edited('kind = "lockout"\nclass = "screen"\nlifetime_ms = 60000\ncountdown_shown = true\n'
                               'dismiss = []\nprovenance = "spec:ui-rules.md#screen-timers"\n',
                               'kind = "lockout"\nclass = "screen"\nlifetime_ms = 60000\ncountdown_shown = true\n'
                               'dismiss = []\n'), "no provenance")

    def test_a_malformed_provenance_is_an_error(self):
        for bad in ("whatever", "spec:ui-look.md", "spec:#x", "oracle:", "owner:", "literature:", "guess:foo"):
            must_fail(self, edited('{ value = 1280, provenance = "spec:ui-look.md#1" }',
                                   '{ value = 1280, provenance = "%s" }' % bad), "provenance")

    def test_every_provenance_kind_is_accepted(self):
        for good in ("spec:ui-rules.md#screen-timers", "oracle:Rust KioskMetrics", "literature:3.10/frame_hz",
                     "owner:D17"):
            self.assertEqual(uc.check_provenance("x", good), good)

    def test_every_threshold_cites_its_section_3_10_key(self):
        contract = uc.load(LOCKERS)
        self.assertEqual(tuple(sorted(contract.scalars["thresholds"])), tuple(sorted(SECTION_3_10_KEYS)))
        for key, entry in contract.scalars["thresholds"].items():
            self.assertEqual(entry.provenance, "literature:3.10/" + key)

    def test_a_threshold_citing_another_key_is_an_error(self):
        must_fail(self, edited('provenance = "literature:3.10/frame_hz"', 'provenance = "spec:ui-look.md#1"'),
                  "must cite its own section 3.10 key")

    def test_style_to_px_matches_kiosk_metrics(self):
        contract = uc.load(LOCKERS)
        for name, px in KIOSK_METRICS.items():
            self.assertEqual(contract.get("type_scale", name), px)
        sizes = {row["id"]: contract.style_px(row["id"]) for row in contract.tables["style"]}
        self.assertEqual(sizes["display"], 200)
        self.assertEqual(sizes["headline"], 48)
        self.assertEqual(sizes["title"], 40)
        self.assertEqual(sizes["count_large"], 40)
        self.assertEqual(sizes["body"], 32)
        self.assertEqual(sizes["btn_key"], 32)
        self.assertEqual(sizes["staff"], 24)
        self.assertEqual(sizes["btn_lang_on"], 24)
        self.assertEqual(sizes["caption"], 16)
        self.assertEqual(sorted(row["token"] for row in contract.tables["style"]), list(range(1, 22)))
        self.assertTrue(set(sizes.values()) <= set(KIOSK_METRICS.values()))

    def test_a_changed_type_scale_is_visible(self):
        contract = uc.loads(edited('body     = { value = 32', 'body     = { value = 30'))
        self.assertEqual(contract.style_px("body"), 30)   # the table follows the scale: a test above pins 32

    def test_the_undecided_entries_are_pending(self):
        contract = uc.load(LOCKERS)
        pending = dict(contract.pending_entries())
        for path in ("panel.diagonal_in", "panel.viewing_distance_mm", "reading.rate_wpm", "policy.error_dialog",
                     "policy.target_population"):
            self.assertIn(path, pending)
        self.assertEqual(pending["panel.diagonal_in"], "9")
        self.assertEqual(pending["policy.target_population"], "10")
        self.assertEqual(pending["reading.rate_wpm"], "11")
        self.assertEqual(pending["policy.error_dialog"], "11")

    def test_a_judge_reading_a_pending_value_gets_contract_pending(self):
        contract = uc.load(LOCKERS)
        for section, key, question in (("panel", "diagonal_in", "9"), ("reading", "rate_wpm", "11"),
                                       ("policy", "error_dialog", "11"), ("thresholds", "keypad_key_min_mm", "10")):
            with self.assertRaises(uc.ContractPending) as caught:
                contract.get(section, key)
            self.assertEqual(caught.exception.question, question)
            self.assertEqual(caught.exception.path, "%s.%s" % (section, key))
            self.assertNotIsInstance(caught.exception, InternalError)
            self.assertTrue(contract.is_pending(section, key))
        with self.assertRaises(uc.ContractPending):
            contract.ppi()
        found = uc.pending_finding(caught.exception)
        self.assertEqual((found["rule"], found["severity"], found["question"]), ("contract-pending", "error", "10"))

    def test_a_decided_panel_gives_a_ppi(self):
        text = edited('diagonal_in         = { pending = "9", provenance = "spec:P004#11-q9" }',
                      'diagonal_in         = { value = 10.1, provenance = "owner:Q9" }')
        contract = uc.loads(text)
        self.assertAlmostEqual(contract.ppi(), 149.4, delta=0.2)   # P004 3.10: a 10.1 inch 1280x800 panel
        self.assertAlmostEqual(contract.mm_to_px(20), 117.6, delta=0.3)

    def test_pending_needs_a_question_number_and_excludes_a_value(self):
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ pending = "18", provenance = "spec:P004#11-q9" }', 1), "question number")
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ pending = "9", value = 10.1, provenance = "spec:P004#11-q9" }', 1),
                  "exactly one of")
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ provenance = "spec:P004#11-q9" }', 1), "exactly one of")

    def test_unknown_keys_are_errors(self):
        must_fail(self, edited('schema = "ui-contract/1"', 'schema = "ui-contract/1"\nextra = 1'), "unknown top-level")
        must_fail(self, edited("[clock]", "[clock]\nextra = { value = 1, provenance = \"owner:x\" }"),
                  "unknown entries")
        must_fail(self, edited('usage = "text"', 'usage = "text"\ncolour = "red"'), "unknown keys")
        must_fail(self, edited('{ value = 250, provenance', '{ value = 250, note = "x", provenance'),
                  "unknown keys")

    def test_missing_keys_and_sections_are_errors(self):
        must_fail(self, edited('tick_ms = { value = 250, provenance = "spec:P004#3.10-dwell" }', ""),
                  "missing entries: tick_ms")
        must_fail(self, edited('token = 1\n', ''), "missing keys: token")
        must_fail(self, re.sub(r"\[clock\]\n.*\n", "", TEXT, count=1), "[clock]")
        must_fail(self, edited('product = "business-apps/lockers"', ""), "product")
        must_fail(self, edited('schema = "ui-contract/1"', 'schema = "ui-contract/2"'), "schema")

    def test_wrong_types_are_errors(self):
        must_fail(self, edited('{ value = 1280,', '{ value = "1280",'), "wrong type")
        must_fail(self, edited('{ value = 1280,', '{ value = 12.5,'), "wrong type")
        must_fail(self, edited('{ value = false, provenance = "literature:3.10/hit_overlap_allowed"',
                               '{ value = 0, provenance = "literature:3.10/hit_overlap_allowed"'), "wrong type")
        must_fail(self, edited('lifetime_ms = 30000', 'lifetime_ms = "30000"'), "wrong type")
        must_fail(self, edited('countdown_shown = false', 'countdown_shown = "no"'), "wrong type")
        must_fail(self, edited('weight = 600', 'weight = 500'), "wrong type")
        must_fail(self, edited('align = "centre"', 'align = "right"'), "wrong type")
        must_fail(self, edited('{ value = 1280,', '{ value = true,'), "wrong type")

    def test_duplicate_entries_are_errors(self):
        must_fail(self, edited('[[timer]]\nkind = "opened"', '[[timer]]\nkind = "choose_size"'), "duplicate kind")
        must_fail(self, edited('id = "headline"\ntoken = 2', 'id = "display"\ntoken = 2'), "duplicate id")
        must_fail(self, edited("[clock]\n", "[clock]\n[clock]\n"), "not valid TOML")

    def test_dangling_references_are_errors(self):
        must_fail(self, edited('scale = "caption"', 'scale = "tiny"'), "not a type_scale entry")
        must_fail(self, edited('style = "display"', 'style = "nonesuch"'), "not a [[style]] id")
        must_fail(self, edited('role = "key_label"', 'role = "nonesuch"'), "not a [[role]] id")
        must_fail(self, edited('shown_on = ["welcome", "choose_size", "opened"]', 'shown_on = ["nonesuch"]'),
                  "not a [[state_class]] id")

    def test_an_empty_or_invalid_toml_is_an_error(self):
        must_fail(self, "", "schema")
        must_fail(self, "schema = [", "not valid TOML")

    def test_exceptions_are_optional_and_strict(self):
        self.assertEqual(uc.load(LOCKERS).tables["exception"], [])
        row = ('\n[[exception]]\nid = "e1"\nrule = "touch-target-small"\ntarget = "lang_bg"\nreason = "circle"\n'
               'provenance = "owner:D99"\n')
        self.assertEqual(uc.loads(TEXT + row).ids("exception"), ["e1"])
        must_fail(self, TEXT + row.replace('provenance = "owner:D99"\n', ""), "no provenance")
        must_fail(self, TEXT + row + row, "duplicate id")

    def test_the_input_policy_matches_ui_rules(self):
        layers = {r["layer"]: r for r in uc.load(LOCKERS).tables["input_layer"]}
        self.assertTrue(layers["dialog"]["blocks_input_below"])
        self.assertFalse(layers["dialog"]["tap_outside_dismisses"])      # a stray tap must not skip an acknowledgement
        self.assertTrue(layers["snackbar"]["tap_outside_dismisses"])
        self.assertFalse(layers["banner_persistent"]["tap_outside_dismisses"])
        self.assertFalse(layers["lockout"]["accepts_input"])
        self.assertFalse(layers["splash"]["accepts_input"])


class Incomplete(unittest.TestCase):
    def test_a_covered_product_is_complete(self):
        contract = uc.load(LOCKERS)
        self.assertEqual(uc.incomplete(contract, contract.ids("timer"), contract.ids("state_class"),
                                       contract.ids("role")), [])

    def test_removing_a_timer_row_gives_contract_incomplete(self):
        kinds = uc.load(LOCKERS).ids("timer")
        row = ('[[timer]]\nkind = "snackbar"\nclass = "message"\nlifetime_ms = 4000\ncountdown_shown = true\n'
               'dismiss = ["dismiss", "tap-outside", "countdown"]\nprovenance = "spec:ui-rules.md#message-catalogue"\n')
        contract = uc.loads(edited(row, ""))
        found = uc.incomplete(contract, timer_kinds=kinds)
        self.assertEqual([(f["rule"], f["what"], f["name"]) for f in found],
                         [("contract-incomplete", "timer-kind", "snackbar")])
        self.assertEqual(found[0]["severity"], "error")

    def test_every_missing_state_class_and_role_is_reported(self):
        contract = uc.load(LOCKERS)
        found = uc.incomplete(contract, ["dialog", "toast"], ["welcome", "settings", "admin"], ["body", "tooltip"])
        self.assertEqual([(f["what"], f["name"]) for f in found],
                         [("timer-kind", "toast"), ("state-class", "admin"), ("state-class", "settings"),
                          ("role", "tooltip")])


if __name__ == "__main__":
    unittest.main()
