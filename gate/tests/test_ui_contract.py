"""The UI contract loader (`rigor_lib.ui_contract`) against the checked-in lockers contract and edited copies."""

import datetime
import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from rigor_lib import ui_contract as uc
from rigor_lib.errors import InternalError

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
LOCKERS = REPO / "products" / "business-apps" / "ui" / "lockers.toml"
P004 = REPO / "plan" / "P004-visual-gate.md"
TEXT = LOCKERS.read_text(encoding="utf-8")
EXPECTED_PENDING = [
    ("panel.diagonal_in", "9"), ("panel.viewing_distance_mm", "9"), ("policy.error_dialog", "11"),
    ("policy.target_population", "10"), ("reading.rate_wpm", "11"), ("table:importance", "7"),
    ("thresholds.button_floor_mm", "10"), ("thresholds.button_recommended_mm", "10"),
    ("thresholds.contrast_large", "15"), ("thresholds.contrast_text", "15"), ("thresholds.flicker_floor_ms", "5"),
    ("thresholds.hierarchy_ratio_k", "5"), ("thresholds.keypad_key_min_mm", "10"),
    # U06: rows the spec does not decide per role (P004 11 q7)
    ("layer.banner", "7"), ("layer.banner-scrim", "7"), ("role_wrap.key_label", "7"),
    ("role_wrap.screen_headline", "7"), ("role_wrap.small_button_label", "7"), ("role_wrap.staff_strong", "7")]
# ui-look.md 4.2, token by token: (name, scale-px, weight). Written out here, not read from the contract.
STYLES = {1: ("display", 200, 600), 2: ("headline", 48, 600), 3: ("title", 40, 600), 4: ("body", 32, 400),
          5: ("body_muted", 32, 400), 6: ("count_large", 40, 400), 7: ("staff", 24, 400),
          8: ("staff_strong", 24, 600), 9: ("caption", 16, 400), 10: ("caption_muted", 16, 400),
          11: ("caption_error", 16, 400), 12: ("notice_title", 40, 600), 13: ("notice_body", 32, 400),
          14: ("notice_caption", 16, 400), 15: ("btn_key", 32, 600), 16: ("btn_action", 32, 600),
          17: ("btn_action_small", 24, 600), 18: ("btn_cancel", 32, 600), 19: ("btn_cancel_small", 24, 600),
          20: ("btn_lang_on", 24, 600), 21: ("btn_lang_off", 24, 600)}
KIOSK_METRICS = {"display": 200, "headline": 48, "title": 40, "body": 32, "staff": 24, "caption": 16}
# P004 3.10, quantity (first column of its table) -> the contract keys that carry it. Independent of the loader.
QUANTITY_KEYS = {
    "Keypad key (serial code entry, standing)": ("keypad_key_min_mm",),
    "Other kiosk buttons and toggles": ("button_recommended_mm", "button_floor_mm"),
    "Any touch target": ("touch_min_mm", "touch_min_dp"),
    "Hit-rect overlap between distinct intents": ("hit_overlap_allowed",),
    "Edge-to-edge spacing": ("spacing_hard_mm", "spacing_recommended_mm"),
    "Hit-test probe region P(n)": ("probe_grid_pct", "probe_disc_radius_mm"),
    "Visual feedback / echo latency": ("feedback_rendered_frames_max", "feedback_target_frames", "frame_hz"),
    "Busy indicator": ("busy_indicator_ms", "busy_progress_cancel_ms"),
    "Transient message dwell D(m)": ("dwell_base_ms", "dwell_floor_ms", "dwell_chars_per_word"),
    "Flicker floor T_perc": ("flicker_floor_ms",),
    "Text legibility": ("legibility_xheight_deg",),
    "Contrast": ("contrast_text", "contrast_large"),
    "Pseudo-locale expansion": ("pseudo_expansion_overall_pct",),
    "Relational geometry vs Rust": ("relational_geometry_tol_px",),
    "Pixel tolerance (C vs C)": ("pixel_tolerance",),
    "Hierarchy ratio k (level 1 vs 2)": ("hierarchy_ratio_k",),
}
DESIGN_KEYS = {"probe_grid_pct", "feedback_target_frames", "frame_hz", "dwell_base_ms", "dwell_floor_ms",
               "dwell_chars_per_word", "flicker_floor_ms", "relational_geometry_tol_px", "hierarchy_ratio_k"}
IMPORTANCE = ('\n[[importance]]\nlevel = 1\nroles = ["hero_number", "screen_headline"]\nprovenance = "owner:Q7"\n')


def edited(old, new, text=TEXT):
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1)


def with_importance(rows):
    """TEXT with the importance table decided (the pending line replaced by `rows`)."""
    return edited('importance = { pending = "7", provenance = "spec:P004#11-q7" }\n', "") + rows


def full_importance():
    roles = uc.load(LOCKERS).ids("role")
    return '\n[[importance]]\nlevel = 1\nroles = %s\nprovenance = "owner:Q7"\n' % ("[" + ", ".join('"%s"' % r for r in roles) + "]")


def must_fail(test, text, fragment):
    with test.assertRaises(InternalError) as caught:
        uc.loads(text)
    test.assertIn(fragment, str(caught.exception))


class Checked(unittest.TestCase):
    def test_the_lockers_contract_loads(self):
        contract = uc.load(LOCKERS)
        self.assertEqual(contract.product, "business-apps/lockers")
        self.assertEqual((contract.get("window", "width_px"), contract.get("window", "height_px")), (1280, 800))

    def test_the_exact_pending_set(self):
        self.assertEqual(uc.load(LOCKERS).pending_entries(), sorted(EXPECTED_PENDING))

    def test_removing_each_provenance_in_turn_is_an_error(self):
        contract = uc.load(LOCKERS)
        wanted = (sum(len(s) for s in contract.scalars.values()) + sum(len(r) for r in contract.tables.values())
                  + len(contract.pending_tables))
        pattern = re.compile(r', provenance = "[^"]*"|^provenance = "[^"]*"\n', re.M)
        matches = list(pattern.finditer(TEXT))
        self.assertEqual(len(matches), wanted)
        for found in matches:
            text = TEXT[:found.start()] + TEXT[found.end():]
            with self.assertRaises(InternalError, msg=found.group(0)) as caught:
                uc.loads(text)
            self.assertIn("provenance", str(caught.exception))

    def test_a_malformed_provenance_is_an_error(self):
        old = '{ value = 1280, provenance = "spec:ui-look.md#1" }'
        for bad in ("whatever", "spec:ui-look.md", "spec:#x", "oracle:", "owner:", "owner:foo", "literature:",
                    "guess:foo", "spec:other.md#x", "spec:ui-look.md#1\\n", "design:ui-look.md#1", "design:P004#",
                    "oracle: padded", "oracle:two\\nlines", "spec: ui-look.md#1"):
            must_fail(self, edited(old, '{ value = 1280, provenance = "%s" }' % bad), "provenance")

    def test_every_provenance_kind_is_accepted(self):
        for good in ("spec:ui-rules.md#screen-timers", "spec:P004#3.5", "spec:hardware-safety.md#1",
                     "oracle:Rust KioskMetrics", "literature:3.10/frame_hz", "design:P004#3.10-frame_hz",
                     "owner:D17", "owner:Q9", "owner:T-12"):
            self.assertEqual(uc.check_provenance("x", good), good)

    def test_the_threshold_keys_follow_the_p004_table(self):
        lines = P004.read_text(encoding="utf-8").split("### 3.10 ")[1].split("\n## ")[0].splitlines()
        quantities = [l.split("|")[1].strip() for l in lines if l.startswith("| ")][1:]
        self.assertEqual(sorted(quantities), sorted(QUANTITY_KEYS))
        contract = uc.load(LOCKERS)
        self.assertEqual(sorted(contract.scalars["thresholds"]), sorted(k for ks in QUANTITY_KEYS.values() for k in ks))

    def test_thresholds_cite_literature_or_design(self):
        for key, entry in uc.load(LOCKERS).scalars["thresholds"].items():
            want = ("design:P004#3.10-" if key in DESIGN_KEYS else "literature:3.10/") + key
            self.assertEqual(entry.provenance, want)

    def test_a_threshold_with_the_wrong_form_is_an_error(self):
        must_fail(self, edited('provenance = "design:P004#3.10-frame_hz"', 'provenance = "literature:3.10/frame_hz"'),
                  "a threshold must have the provenance")
        must_fail(self, edited('provenance = "literature:3.10/touch_min_dp"', 'provenance = "design:P004#3.10-touch_min_dp"'),
                  "a threshold must have the provenance")
        must_fail(self, edited('provenance = "literature:3.10/touch_min_dp"', 'provenance = "spec:ui-look.md#1"'),
                  "a threshold must have the provenance")

    def test_style_to_px_matches_kiosk_metrics(self):
        contract = uc.load(LOCKERS)
        for name, px in KIOSK_METRICS.items():
            self.assertEqual(contract.get("type_scale", name), px)
        rows = {row["token"]: row for row in contract.tables["style"]}
        self.assertEqual(sorted(rows), list(range(1, 22)))
        for token, (name, px, weight) in STYLES.items():
            self.assertEqual((rows[token]["id"], contract.style_px(name), rows[token]["weight"]), (name, px, weight))

    def test_a_changed_type_scale_moves_the_styles(self):
        self.assertEqual(uc.loads(edited('body     = { value = 32', 'body     = { value = 34')).style_px("body"), 34)

    # ---- pending -------------------------------------------------------------------------------------------------
    def test_a_judge_reading_a_pending_value_gets_contract_pending(self):
        contract = uc.load(LOCKERS)
        for section, key, question in (("panel", "diagonal_in", "9"), ("reading", "rate_wpm", "11"),
                                       ("policy", "error_dialog", "11"), ("thresholds", "contrast_text", "15")):
            with self.assertRaises(uc.ContractPending) as caught:
                contract.get(section, key)
            self.assertEqual((caught.exception.path, caught.exception.question), ("%s.%s" % (section, key), question))
            self.assertNotIsInstance(caught.exception, InternalError)
        with self.assertRaises(uc.ContractPending):
            contract.ppi()

    def test_the_severity_of_contract_pending_is_fixed(self):
        with self.assertRaises(uc.ContractPending) as caught:
            uc.load(LOCKERS).get("panel", "diagonal_in")
        found = uc.pending_finding(caught.exception)
        self.assertEqual((found["rule"], found["severity"], found["question"]), ("contract-pending", "error", "9"))
        with self.assertRaises(TypeError):
            uc.pending_finding(caught.exception, "info")
        self.assertEqual(uc.PENDING_SEVERITY, "error")

    def test_a_pending_table_gives_contract_pending(self):
        contract = uc.load(LOCKERS)
        for call in (lambda: contract.rows("importance"), lambda: contract.ids("importance"),
                     lambda: contract.row("importance", 1)):
            with self.assertRaises(uc.ContractPending) as caught:
                call()
            self.assertEqual((caught.exception.path, caught.exception.question), ("table:importance", "7"))

    def test_a_decided_importance_table_loads_and_is_checked(self):
        contract = uc.loads(with_importance(full_importance()))
        self.assertEqual(contract.ids("importance"), [1])
        self.assertNotIn(("table:importance", "7"), contract.pending_entries())
        must_fail(self, with_importance(IMPORTANCE + IMPORTANCE.replace("level = 1", "level = 2")), "more than one level")
        must_fail(self, with_importance(IMPORTANCE.replace('"hero_number"', '"nonesuch"')), "not a [[role]] id")
        must_fail(self, edited('importance = { pending = "7", provenance = "spec:P004#11-q7" }\n', "") , "[[importance]] is missing")
        must_fail(self, TEXT + IMPORTANCE, "is pending (pending_tables) and must have no rows")

    def test_a_role_without_an_importance_level_is_incomplete(self):
        contract = uc.loads(with_importance(IMPORTANCE))
        found = uc.incomplete(contract)
        self.assertIn(("importance", "caption"), [(f["what"], f["name"]) for f in found])
        self.assertNotIn(("importance", "hero_number"), [(f["what"], f["name"]) for f in found])
        self.assertEqual(uc.incomplete(uc.loads(with_importance(full_importance()))), [])

    def test_pending_is_a_closed_list(self):
        must_fail(self, edited('{ value = 1280, provenance = "spec:ui-look.md#1" }',
                               '{ pending = "9", provenance = "spec:ui-look.md#1" }'), "may not be pending")
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ pending = "10", provenance = "spec:P004#11-q9" }'), "pending must be exactly '9'")
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ pending = "18", provenance = "spec:P004#11-q9" }'), "pending must be exactly")
        must_fail(self, edited("[pending_tables]\n", '[pending_tables]\nrole = { pending = "7", provenance = "owner:Q7" }\n'),
                  "may not name 'role'")
        must_fail(self, edited('importance = { pending = "7"', 'importance = { pending = "8"'), "pending must be exactly")

    def test_pending_and_value_together_or_neither_is_an_error(self):
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ pending = "9", value = 10.1, provenance = "spec:P004#11-q9" }'), "exactly one of")
        must_fail(self, edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                               '{ provenance = "spec:P004#11-q9" }'), "exactly one of")

    def test_a_decided_panel_gives_a_ppi(self):
        contract = uc.loads(edited('{ pending = "9", provenance = "spec:P004#11-q9" }',
                                   '{ value = 10.1, provenance = "owner:Q9" }'))
        self.assertAlmostEqual(contract.ppi(), 149.4, delta=0.2)
        self.assertAlmostEqual(contract.mm_to_px(20), 117.6, delta=0.3)

    # ---- malformed input is the house error, never a traceback -------------------------------------------------------
    def test_malformed_input_is_the_house_error(self):
        pending = '{ pending = "9", provenance = "spec:P004#11-q9" }'
        for text in (edited(pending, '{ pending = ["9"], provenance = "spec:P004#11-q9" }'),
                     edited(pending, '{ pending = 9, provenance = "spec:P004#11-q9" }'),
                     edited(pending, '{ pending = { a = 1 }, provenance = "spec:P004#11-q9" }'),
                     edited('{ value = 1280,', '{ value = [1280],'),
                     edited('{ value = 1280,', '{ value = { a = 1 },'),
                     edited('provenance = "spec:ui-look.md#1" }', 'provenance = 5 }'),
                     edited('provenance = "spec:ui-look.md#1" }', 'provenance = ["x"] }'),
                     edited('[window]\n', '[window2]\n'),
                     edited('[[timer]]\nkind = "opened"', '[[timer]]\nkind = ["opened"]'),
                     edited('[[timer]]\nkind = "opened"', '[[timer]]\nkind = {a = 1}'),
                     edited('dismiss = ["done", "countdown"]', 'dismiss = [["done"]]'),
                     edited('dismiss = ["done", "countdown"]', 'dismiss = "done"'),
                     edited('shown_on = ["welcome", "choose_size", "opened"]', 'shown_on = [{a = 1}]'),
                     "timer = 5\nschema = 'x'", 'schema = "ui-contract/1"\nproduct = 5',
                     'schema = "ui-contract/1"\nproduct = "x"\nwindow = 5',
                     'schema = "ui-contract/1"\nproduct = "x"\npending_tables = 5',
                     TEXT + "\nexception = 5\n"):
            with self.assertRaises(InternalError, msg=text[:80]):
                uc.loads(text)

    def test_a_file_that_is_not_utf8_is_the_house_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            path.write_bytes(b'schema = "\xff\xfe"')
            with self.assertRaises(InternalError):
                uc.load(path)
            with self.assertRaises(InternalError):
                uc.load(Path(tmp) / "missing.toml")

    def test_unknown_missing_and_empty_are_errors(self):
        must_fail(self, edited('schema = "ui-contract/1"', 'schema = "ui-contract/1"\nextra = 1'), "unknown top-level")
        must_fail(self, edited("[clock]", "[clock]\nextra = { value = 1, provenance = \"owner:D1\" }"), "unknown entries")
        must_fail(self, edited('usage = "text"', 'usage = "text"\ncolour = "red"'), "unknown keys")
        must_fail(self, edited('{ value = 250, provenance', '{ value = 250, note = "x", provenance'), "unknown keys")
        must_fail(self, edited('tick_ms = { value = 250, provenance = "spec:P004#3.5" }', ""), "missing entries: tick_ms")
        must_fail(self, edited('token = 1\n', ''), "missing keys: token")
        must_fail(self, re.sub(r"\[clock\]\n.*\n", "", TEXT, count=1), "[clock]")
        must_fail(self, edited('product = "business-apps/lockers"', ""), "product")
        must_fail(self, edited('schema = "ui-contract/1"', 'schema = "ui-contract/2"'), "schema")
        must_fail(self, "", "schema")
        must_fail(self, "schema = [", "not valid TOML")

    def test_whitespace_empty_and_bad_names_are_errors(self):
        for bad in ("", " ", "  x", "x\\n", "Has Space", "UPPER"):
            must_fail(self, edited('id = "display"\ntoken = 1', 'id = "%s"\ntoken = 1' % bad), "wrong type")
        for bad in ("", " ", "a b", "/x"):
            must_fail(self, edited('product = "business-apps/lockers"', 'product = "%s"' % bad), "product")
        must_fail(self, edited('kind = "opened"', 'kind = ""'), "wrong type")

    def test_wrong_types_and_ranges_are_errors(self):
        for old, new in (('{ value = 1280,', '{ value = "1280",'), ('{ value = 1280,', '{ value = 12.5,'),
                         ('{ value = 1280,', '{ value = true,'), ('{ value = 1280,', '{ value = -1,'),
                         ('{ value = 1280,', '{ value = nan,'), ('{ value = 1280,', '{ value = inf,'),
                         ('{ value = 1280,', '{ value = 0,'),
                         ('lifetime_ms = 30000\n', 'lifetime_ms = -1\n'), ('lifetime_ms = 30000\n', 'lifetime_ms = true\n'),
                         ('lifetime_ms = 30000\n', 'lifetime_ms = "30000"\n'), ('lifetime_ms = 30000\n', 'lifetime_ms = nan\n'),
                         ('countdown_shown = false', 'countdown_shown = "no"'), ('weight = 600', 'weight = 500'),
                         ('weight = 600', 'weight = true'), ('align = "centre"', 'align = "right"'),
                         ('token = 1\n', 'token = 22\n'), ('token = 1\n', 'token = 0\n'),
                         ('{ value = false, provenance = "literature:3.10/hit_overlap_allowed"',
                          '{ value = 0, provenance = "literature:3.10/hit_overlap_allowed"'),
                         ('{ value = [20, 50, 80]', '{ value = [20, 50, 101]'), ('{ value = [20, 50, 80]', '{ value = [50, 20, 80]'),
                         ('{ value = [20, 50, 80]', '{ value = []'), ('{ value = [20, 50, 80]', '{ value = [20, true]'),
                         ('{ value = 5.6,', '{ value = 11,'), ('{ value = 5.6,', '{ value = 2,'),
                         ('{ value = 3500,', '{ value = -1,'), ('{ value = 1, provenance = "literature:3.10/spacing_hard_mm"',
                                                                 '{ value = 0, provenance = "literature:3.10/spacing_hard_mm"'),
                         ('{ value = 60,', '{ value = 100000,'), ('{ value = 14,', '{ value = 1e9,')):
            must_fail(self, edited(old, new), "wrong type or range" if "value" in old else "wrong type")

    def test_the_rate_and_contrast_bounds(self):
        rate = 'rate_wpm = { pending = "11", provenance = "spec:P004#11-q11" }'
        for bad in (49, 401, 0, -5):
            must_fail(self, edited(rate, 'rate_wpm = { value = %d, provenance = "owner:Q11" }' % bad), "wrong type or range")
        self.assertEqual(uc.loads(edited(rate, 'rate_wpm = { value = 50, provenance = "owner:Q11" }')).get("reading", "rate_wpm"), 50)
        contrast = 'contrast_text                 = { pending = "15", provenance = "literature:3.10/contrast_text" }'
        for bad in (0.9, 21.1):
            must_fail(self, edited(contrast, 'contrast_text = { value = %s, provenance = "literature:3.10/contrast_text" }' % bad),
                      "wrong type or range")

    def test_threshold_orderings(self):
        floor = 'button_floor_mm               = { pending = "10", provenance = "literature:3.10/button_floor_mm" }'
        recommended = 'button_recommended_mm         = { pending = "10", provenance = "literature:3.10/button_recommended_mm" }'
        both = edited(floor, 'button_floor_mm = { value = 25, provenance = "literature:3.10/button_floor_mm" }')
        both = edited(recommended, 'button_recommended_mm = { value = 19, provenance = "literature:3.10/button_recommended_mm" }', both)
        must_fail(self, both, "button_floor_mm (25) may not exceed button_recommended_mm (19)")
        must_fail(self, edited('{ value = 3, provenance = "literature:3.10/spacing_recommended_mm"',
                               '{ value = 0.5, provenance = "literature:3.10/spacing_recommended_mm"'), "spacing_hard_mm")
        must_fail(self, edited('{ value = 2, provenance = "design:P004#3.10-feedback_target_frames"',
                               '{ value = 6, provenance = "design:P004#3.10-feedback_target_frames"'), "feedback_target_frames")
        must_fail(self, edited('{ value = 1000, provenance = "literature:3.10/busy_indicator_ms"',
                               '{ value = 20000, provenance = "literature:3.10/busy_indicator_ms"'), "busy_indicator_ms")
        must_fail(self, edited('{ value = 1000, provenance = "design:P004#3.10-dwell_base_ms"',
                               '{ value = 4000, provenance = "design:P004#3.10-dwell_base_ms"'), "dwell_base_ms")
        must_fail(self, edited('{ value = 14, provenance = "literature:3.10/touch_min_mm"',
                               '{ value = 18, provenance = "literature:3.10/touch_min_mm"').replace(
                                   floor, 'button_floor_mm = { value = 16.5, provenance = "literature:3.10/button_floor_mm" }'),
                  "touch_min_mm (18) may not exceed button_floor_mm (16.5)")

    def test_duplicate_entries_are_errors(self):
        must_fail(self, edited('[[timer]]\nkind = "opened"', '[[timer]]\nkind = "choose_size"'), "duplicate kind")
        must_fail(self, edited('id = "headline"\ntoken = 2', 'id = "display"\ntoken = 2'), "duplicate id")
        must_fail(self, edited('id = "headline"\ntoken = 2', 'id = "headline"\ntoken = 1'), "tokens are not unique")
        must_fail(self, edited("[clock]\n", "[clock]\n[clock]\n"), "not valid TOML")

    def test_dangling_references_are_errors(self):
        must_fail(self, edited('scale = "caption"', 'scale = "tiny"'), "not a type_scale entry")
        must_fail(self, edited('style = "display"', 'style = "nonesuch"'), "not a [[style]] id")
        must_fail(self, edited('role = "key_label"', 'role = "nonesuch"'), "not a [[role]] id")
        must_fail(self, edited('shown_on = ["welcome", "choose_size", "opened"]', 'shown_on = ["nonesuch"]'),
                  "not a [[state_class]] id")
        must_fail(self, edited('required = ["staff_strong", "done"]', 'required = ["staff_strong", "nonesuch"]'),
                  "required element 'nonesuch' is unknown")

    def test_the_inspection_state_class_exists(self):
        self.assertIn("inspection", uc.load(LOCKERS).ids("state_class"))

    def test_role_consistency(self):
        must_fail(self, edited('role = "caption"\nfont_px_min = 16', 'role = "caption"\nfont_px_min = 20'), "exceeds the role's style size")
        must_fail(self, edited('role = "key_label"\nfont_px_min = 32\ntouch_dp_min = 48', 'role = "key_label"\nfont_px_min = 32\ntouch_dp_min = 0'), "a button needs touch_dp_min")
        must_fail(self, edited('role = "key_label"\nfont_px_min = 32\ntouch_dp_min = 48', 'role = "key_label"\nfont_px_min = 32\ntouch_dp_min = 30'), "touch_dp_min")
        must_fail(self, edited('id = "caption"\nstyle = "caption"\nalign = "centre"', 'id = "caption"\nstyle = "caption"\nalign = "left"'), "only a notice role may be left-aligned")
        must_fail(self, edited('id = "caption"\nstyle = "caption"\nalign = "centre"', 'id = "caption"\nstyle = "caption"\nalign = "centre"\nalign_banner = "left"'), "only valid for a notice role")
        must_fail(self, edited('id = "key_label"\nstyle = "btn_key"\nalign = "centre"', 'id = "key_label"\nstyle = "btn_key"\nalign = "left"'), "left-aligned")
        self.assertEqual(uc.loads(edited('id = "notice_body"\nstyle = "notice_body"\nalign = "centre"\nalign_banner = "left"',
                                         'id = "notice_body"\nstyle = "notice_body"\nalign = "left"\nalign_banner = "left"')).product,
                         "business-apps/lockers")

    def test_a_role_without_a_role_min_row_is_incomplete(self):
        row = '[[role_min]]\nrole = "error_caption"\nfont_px_min = 16\ntouch_dp_min = 0\nprovenance = "spec:ui-look.md#4.1"\n'
        found = uc.incomplete(uc.loads(edited(row, "")))
        self.assertEqual([(f["what"], f["name"]) for f in found], [("role-min", "error_caption")])

    def test_timer_and_wrap_consistency(self):
        must_fail(self, edited('kind = "lockout"\nclass = "screen"\nlifetime_ms = 60000', 'kind = "lockout"\nclass = "screen"\nlifetime_ms = 0'),
                  "a countdown needs lifetime_ms above 0")
        must_fail(self, edited('dismiss = ["dismiss"]\nprovenance = "spec:ui-rules.md#message-catalogue"', 'dismiss = []\nprovenance = "spec:ui-rules.md#message-catalogue"'),
                  "every message can be dismissed")
        must_fail(self, edited('wrap = "none"\nmax_lines = 1', 'wrap = "none"\nmax_lines = 2'), "wrap none means max_lines 1")
        must_fail(self, edited('wrap = "word"\nmax_lines = 0\nellipsis = false', 'wrap = "word"\nmax_lines = 0\nellipsis = true'), "an ellipsis needs a line cap")
        must_fail(self, edited('members = ["lang_bg", "lang_en"]', 'members = ["lang_bg"]'), "wrong type or range")

    # ---- exceptions ------------------------------------------------------------------------------------------------
    ROW = ('\n[[exception]]\nid = "e1"\nrule = "touch-target-small"\ntarget = "lang_bg"\nreason = "circle"\n'
           'expires = 2027-01-31\nprovenance = "owner:D99"\n')

    def test_exceptions_are_optional_and_strict(self):
        self.assertEqual(uc.load(LOCKERS).tables["exception"], ())
        contract = uc.loads(TEXT + self.ROW)
        self.assertEqual(contract.ids("exception"), ["e1"])
        self.assertEqual(len(contract.active_exceptions(datetime.date(2027, 1, 31))), 1)
        self.assertEqual(len(contract.active_exceptions(datetime.date(2027, 2, 1))), 0)
        self.assertEqual(uc.loads(TEXT + self.ROW.replace("2027-01-31", '"2027-01-31"')).ids("exception"), ["e1"])
        must_fail(self, TEXT + self.ROW + self.ROW, "duplicate id")

    def test_a_bad_exception_is_an_error(self):
        for old, new, fragment in (('expires = 2027-01-31\n', "", "missing keys: expires"),
                                   ('expires = 2027-01-31\n', 'expires = "soon"\n', "wrong type"),
                                   ('expires = 2027-01-31\n', 'expires = "2027-13-45"\n', "wrong type"),
                                   ('provenance = "owner:D99"', 'provenance = "spec:ui-rules.md#presentation"', "owner: provenance"),
                                   ('provenance = "owner:D99"\n', "", "no provenance"),
                                   ('rule = "touch-target-small"', 'rule = "anything-goes"', "wrong type"),
                                   ('target = "lang_bg"', 'target = "*"', "wrong type"),
                                   ('target = "lang_bg"', 'target = "lang_*"', "wrong type"),
                                   ('target = "lang_bg"', 'target = ""', "wrong type"),
                                   ('reason = "circle"', 'reason = " "', "wrong type"),
                                   ('reason = "circle"\n', 'reason = "circle"\nextra = 1\n', "unknown keys")):
            must_fail(self, TEXT + self.ROW.replace(old, new), fragment)

    # ---- immutability --------------------------------------------------------------------------------------------------
    def test_what_the_loader_returns_is_immutable(self):
        contract = uc.load(LOCKERS)
        row = contract.row("timer", "dialog")
        with self.assertRaises(TypeError):
            row["lifetime_ms"] = 1
        with self.assertRaises(TypeError):
            contract.scalars["window"]["width_px"] = None
        with self.assertRaises(TypeError):
            contract.scalars["foo"] = {}
        with self.assertRaises(TypeError):
            contract.tables["timer"] = ()
        with self.assertRaises(AttributeError):
            contract.tables["timer"].append(row)
        with self.assertRaises(AttributeError):
            row["dismiss"].append("x")
        with self.assertRaises(AttributeError):
            contract.get("thresholds", "probe_grid_pct").append(1)
        with self.assertRaises(AttributeError):
            contract.entry("window", "width_px").value = 1
        self.assertEqual(contract.get("thresholds", "probe_grid_pct"), (20, 50, 80))

    def test_the_input_policy_matches_ui_rules(self):
        layers = {r["layer"]: r for r in uc.load(LOCKERS).tables["input_layer"]}
        self.assertTrue(layers["dialog"]["blocks_input_below"])
        self.assertFalse(layers["dialog"]["tap_outside_dismisses"])
        self.assertTrue(layers["snackbar"]["tap_outside_dismisses"])
        self.assertFalse(layers["banner_persistent"]["tap_outside_dismisses"])
        self.assertFalse(layers["lockout"]["accepts_input"])
        self.assertFalse(layers["splash"]["accepts_input"])

    def test_the_test_copy_of_ui_rules_has_its_recorded_hash(self):
        data = HERE / "data" / "ui_contract"
        recorded = (data / "ui-rules.md.sha256").read_text(encoding="ascii").strip()
        self.assertEqual(hashlib.sha256((data / "ui-rules.md").read_bytes()).hexdigest(), recorded)


class Incomplete(unittest.TestCase):
    def test_a_covered_product_is_complete(self):
        contract = uc.load(LOCKERS)
        self.assertEqual(uc.incomplete(contract, contract.ids("timer"), contract.ids("state_class"),
                                       contract.ids("role")), [])

    def test_removing_a_timer_row_gives_contract_incomplete(self):
        kinds = uc.load(LOCKERS).ids("timer")
        row = ('[[timer]]\nkind = "snackbar"\nclass = "message"\nlifetime_ms = 4000\ncountdown_shown = true\n'
               'dismiss = ["dismiss", "tap-outside", "countdown"]\nprovenance = "spec:ui-rules.md#message-catalogue"\n')
        found = uc.incomplete(uc.loads(edited(row, "")), timer_kinds=kinds)
        self.assertEqual([(f["rule"], f["what"], f["name"], f["severity"]) for f in found],
                         [("contract-incomplete", "timer-kind", "snackbar", "error")])

    def test_every_missing_state_class_and_role_is_reported(self):
        found = uc.incomplete(uc.load(LOCKERS), ["dialog", "toast"], ["welcome", "settings", "admin"], ["body", "tooltip"])
        self.assertEqual([(f["what"], f["name"]) for f in found],
                         [("timer-kind", "toast"), ("state-class", "admin"), ("state-class", "settings"),
                          ("role", "tooltip")])


class JudgeTablesTest(unittest.TestCase):
    """U06: the tables the ui-scene and ui-fit judges read (style_role, role_wrap, layer, element, style_line, the
    toggle group's marks)."""

    def test_the_lockers_tables_resolve(self):
        contract = uc.load(LOCKERS)
        self.assertEqual(contract.role_of_style(contract.style_by_token(15)["id"]), "key_label")
        self.assertEqual(contract.role_of_style(contract.style_by_token(20)["id"]), "small_button_label")
        self.assertIsNone(contract.style_by_token(0))
        self.assertEqual(contract.row_value("role_wrap", "subtitle", "scope"), "default")
        with self.assertRaises(uc.ContractPending) as caught:
            contract.row_value("role_wrap", "key_label", "scope")
        self.assertEqual((caught.exception.path, caught.exception.question), ("role_wrap.key_label", "7"))
        self.assertEqual(contract.layer_row("scrim", "dialog")["policy"], "capture-modal-inert")
        self.assertIsNone(contract.layer_row("scrim"))
        self.assertEqual([r["key"] for r in contract.rows("element")], ["11", "12"])
        self.assertEqual(contract.row("style_line", "display")["line_height_px"], 229)

    def test_the_tables_are_strict(self):
        must_fail(self, edited('style = "btn_action"\nrole = "key_label"', 'style = "btn_key"\nrole = "key_label"'),
                  "already names this style")
        must_fail(self, edited('role = "subtitle"\nscope = "default"', 'role = "subtitle"\nscope = "nowhere"'),
                  "must be [[role]] and [[wrap]] ids")
        must_fail(self, edited('role = "key_label"\npending = "7"', 'role = "key_label"\npending = "5"'),
                  "pending must be exactly")
        must_fail(self, edited('role = "key_label"\npending = "7"', 'role = "key_label"\nscope = "default"\npending = "7"'),
                  "exactly one of `scope` and `pending`")
        must_fail(self, edited('role = "scrim"\ncard = "dialog"\n', 'role = "scrim"\n'), "a scrim row needs `card`")
        must_fail(self, edited('id = "snackbar"\nrole = "snackbar"', 'id = "snackbar"\nrole = "dialog"'),
                  "a second row for the same role and card")
        must_fail(self, edited('policy = "capture-modal-inert"', 'policy = "modal"'), "wrong type or range")
        must_fail(self, edited('id = "lang_bg"\nkey = "11"', 'id = "lang_xx"\nkey = "11"'), "must be an [[element]] id")
        must_fail(self, edited('marks = ["bg", "style"]', 'marks = ["colour"]'), "wrong type or range")
        must_fail(self, edited('style = "display"\nline_height_px', 'style = "nonesuch"\nline_height_px'),
                  "is not a [[style]] id")
        must_fail(self, edited('id = "subtitle"\nstyle = "body_muted"', 'id = "subtitle"\nstyle = "body"'),
                  "two roles share a style")


if __name__ == "__main__":
    unittest.main()
