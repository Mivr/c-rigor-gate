"""U13: `rigor_lib.ui_deviations`, the tag reader: where a tag is found, every malformed form, the DISAGREEMENTS entry
count, the immutable results. The ratchet, the real headers and the CLI are in test_ui_deviations_ratchet.py."""

import datetime
import unittest

from rigor_lib import ui_deviations as ud
from rigor_lib.errors import InternalError

LINK = r"https://github\.com/Mivr/club-apps/issues/[0-9]+"
BASE = ud.Baseline("business-apps", 10, (), LINK)
TODAY = datetime.date(2026, 11, 15)


def tag(ident="UI-A1", **over):
    """The text of one valid tag; `over[key] = None` drops the key, a string replaces its value."""
    values = {"oracle": "welcome.slint idle echo", "state": "welcome, choose", "reason": "intentional",
              "link": "docs/lockers/ui-look.md#4.3", "until": "T200"}
    values.update(over)
    body = "".join(', %s="%s"' % (k, v) for k, v in values.items() if v is not None)
    return "@deviation(%s%s)" % (ident, body)


def scan(text, link=LINK):
    return ud.scan_header("a.h", text.encode("utf-8"), link)


def whys(text):
    return [why for _, _, why in scan("/* %s */\n" % text)[1]]


class Where(unittest.TestCase):
    def test_a_tag_in_a_block_comment_is_found_with_every_field(self):
        tags, bad, secs = scan("int x;\n/* note\n * %s\n */\n" % tag())
        self.assertEqual(bad, ())
        self.assertEqual(secs, ())
        self.assertEqual(tags, (ud.Tag("UI-A1", "welcome.slint idle echo", ("welcome", "choose"), "intentional",
                                       "docs/lockers/ui-look.md#4.3", "T200", "a.h", 3),))

    def test_a_tag_in_a_line_comment_is_found(self):
        tags, bad, _ = scan("// %s\n" % tag("UI-B2"))
        self.assertEqual((len(tags), tags[0].id, tags[0].line, bad), (1, "UI-B2", 1, ()))

    def test_a_tag_may_span_lines_in_either_comment_kind(self):
        block = "/*\n * @deviation(UI-A1,\n *   oracle=\"o\", state=\"s\",\n *   reason=\"substrate\", link=\"l\",\n *   until=\"2027-01-31\")\n */"
        line = "// @deviation(UI-A1,\n//   oracle=\"o\", state=\"s\",\n//   reason=\"substrate\", link=\"l\",\n//   until=\"2027-01-31\")\n"
        for text in (block, line):
            with self.subTest(text=text[:12]):
                tags, bad, _ = scan(text)
                self.assertEqual(([t.id for t in tags], [t.line for t in tags], bad), (["UI-A1"], [2 if text[1] == "*" else 1], ()))

    def test_a_tag_in_a_string_or_character_literal_is_not_a_tag(self):
        for code in ('const char *s = "%s";\n', "const char *s = \"/* %s */\";\n", "char c = '\"'; /* x */ const char *s = \"%s\";\n"):
            with self.subTest(code=code):
                self.assertEqual(scan(code % tag().replace('"', '\\"')), ((), (), ()))

    def test_a_string_holding_a_comment_opener_does_not_open_a_comment(self):
        text = 'const char *s = "/*";\n%s\n' % tag()
        self.assertEqual(scan(text), ((), (), ()))
        tags, bad, _ = scan('const char *s = "/*";\n/* %s */\n' % tag())
        self.assertEqual((len(tags), bad), (1, ()))

    def test_a_tag_in_code_is_not_a_tag_and_is_not_reported(self):
        self.assertEqual(scan("int x; %s\nvoid f(void);\n" % tag()), ((), (), ()))

    def test_a_tag_in_a_comment_inside_if_0_is_found_and_code_inside_it_is_not(self):
        text = "#if 0\n%s\n/* %s */\n#endif\n" % (tag("UI-C1"), tag("UI-C2"))
        tags, bad, _ = scan(text)
        self.assertEqual(([t.id for t in tags], bad), (["UI-C2"], ()))

    def test_a_line_splice_continues_a_line_comment(self):
        tags, bad, _ = scan("// begin \\\n%s\n" % tag())
        self.assertEqual((len(tags), bad), (1, ()))

    def test_crlf_and_lone_cr_line_ends_read_like_lf(self):
        for eol in ("\r\n", "\r"):
            with self.subTest(eol=repr(eol)):
                tags, bad, _ = scan(("int a;\n/*\n * %s\n */\n" % tag()).replace("\n", eol))
                self.assertEqual(([t.line for t in tags], bad), ([3], ()))

    def test_a_word_that_merely_starts_with_the_tag_name_or_follows_a_word_character_is_not_a_tag(self):
        for text in ("@deviations are listed here", "x@deviation(UI-A1)", "@deviation_x(y)"):
            with self.subTest(text=text):
                self.assertEqual(scan("/* %s */" % text), ((), (), ()))

    def test_an_unterminated_comment_literal_or_non_utf8_file_is_malformed_never_skipped(self):
        self.assertEqual(scan("int x;\n/* %s\n" % tag())[1], ((2, None, "unterminated-comment"),))
        self.assertEqual(scan('char *s = "abc;\n')[1], ((1, None, "unterminated-literal"),))
        self.assertEqual(scan("char c = 'a;\n")[1], ((1, None, "unterminated-literal"),))
        self.assertEqual(ud.scan_header("a.h", b"/* \xff */", LINK), ((), ((1, None, "not-utf-8"),), ()))

    def test_results_are_immutable(self):
        tags, bad, secs = scan("/* %s */" % tag())
        self.assertIsInstance(tags, tuple)
        self.assertIsInstance(bad, tuple)
        self.assertIsInstance(secs, tuple)
        self.assertIsInstance(tags[0].states, tuple)
        with self.assertRaises(Exception):
            tags[0].id = "X-1"
        with self.assertRaises(Exception):
            BASE.cap = 1


class Malformed(unittest.TestCase):
    def test_every_closed_key_is_required(self):
        for key in ("oracle", "state", "reason", "link", "until"):
            with self.subTest(key=key):
                self.assertEqual(whys(tag(**{key: None})), ["missing-key:" + key])

    def test_an_unknown_key_and_a_duplicate_key(self):
        self.assertEqual(whys(tag()[:-1] + ', owner="x")'), ["unknown-key:owner"])
        self.assertEqual(whys(tag()[:-1] + ', link="y")'), ["duplicate-key:link"])
        self.assertEqual(whys(tag()[:-1] + ', Until="y")'), ["unknown-key:Until"])

    def test_the_id_grammar_is_exact(self):
        for ident, ok in (("UI-A1", True), ("L1-A.B-C", True), ("A9-1", True), ("ui-a1", False), ("UIA1", False),
                          ("1A-X", False), ("UI-", False), ("UI-a", False), ("UI-A_1", False)):
            with self.subTest(ident=ident):
                self.assertEqual(whys(tag(ident)), [] if ok else ["bad-id"])
        self.assertEqual(whys("@deviation()"), ["bad-id"])
        self.assertEqual(whys('@deviation(, oracle="x")'), ["bad-id"])

    def test_values_may_not_be_empty_or_padded(self):
        for key in ("oracle", "state", "reason", "link", "until"):
            for value in ("", " ", " x", "x "):
                with self.subTest(key=key, value=value):
                    self.assertEqual(whys(tag(**{key: value})), ["empty-or-padded-value:" + key])

    def test_the_reason_list_is_closed(self):
        for reason in ("intentional", "substrate"):
            self.assertEqual(whys(tag(reason=reason)), [])
        for reason in ("Intentional", "oracle-bug", "intentional,substrate", "reference_bug"):
            with self.subTest(reason=reason):
                self.assertEqual(whys(tag(reason=reason)), ["bad-reason"])

    def test_the_state_is_a_list_of_distinct_names(self):
        self.assertEqual(whys(tag(state="welcome")), [])
        self.assertEqual(whys(tag(state="welcome,choose, opened.x")), [])
        for state in ("welcome,,choose", "welcome,welcome", "wel come", "-x", ",", "a,"):
            with self.subTest(state=state):
                self.assertEqual(whys(tag(state=state)), ["bad-state"])

    def test_the_link_has_no_white_space_and_a_reference_bug_names_an_oracle_issue(self):
        self.assertEqual(whys(tag(link="a b")), ["bad-link"])
        issue = "https://github.com/Mivr/club-apps/issues/12"
        self.assertEqual(whys(tag(reason="reference-bug", link=issue)), [])
        for link in ("https://github.com/Mivr/club-apps/issues/12x", "https://github.com/Mivr/club-apps/pull/12",
                     "https://github.com/Mivr/other/issues/12", "docs/x.md#1", "https://github.com/Mivr/club-apps/issues/"):
            with self.subTest(link=link):
                self.assertEqual(whys(tag(reason="reference-bug", link=link)),
                                 ["reference-bug-link-not-an-oracle-issue"])
        self.assertEqual(whys(tag(reason="substrate", link="docs/x.md#1")), [])

    def test_until_is_a_task_id_or_a_real_iso_date(self):
        for until in ("T104", "U13", "B7", "T1xx13", "2027-01-31", "2028-02-29"):
            with self.subTest(until=until):
                self.assertEqual(whys(tag(until=until)), [] if until != "T1xx13" else ["bad-until"])
        for until, why in (("2027-02-29", "bad-until-date"), ("2027-13-01", "bad-until-date"), ("2027-1-1", "bad-until"),
                           ("soon", "bad-until"), ("t1", "bad-until"), ("T", "bad-until"), ("٢027-01-01", "bad-until")):
            with self.subTest(until=until):
                self.assertEqual(whys(tag(until=until)), [why])

    def test_punctuation_errors(self):
        good = tag()
        cases = {
            "trailing comma": (good[:-1] + ",)", "bad-key"),
            "missing comma": (good.replace('", state', '" state'), "expected-comma-or-close"),
            "missing equals": (good.replace("oracle=", "oracle "), "expected-equals"),
            "unquoted value": (good.replace('until="T200"', "until=T200"), "expected-string"),
            "single quotes": (good.replace('until="T200"', "until='T200'"), "expected-string"),
            "no paren": ("@deviation UI-A1", "missing-paren"),
            "bare tag": ("@deviation", "missing-paren"),
            "bad escape": (good.replace("echo", "ec\\ho"), "bad-escape"),
            "unterminated": ('@deviation(UI-A1, oracle="x', "unterminated-tag"),
            "no close": ('@deviation(UI-A1, oracle="x"', "expected-comma-or-close"),
            "tab in string": (good.replace("idle", "id\tle"), "control-character"),
            "key with digit": (good.replace("until=", "until2="), "expected-equals"),
        }
        for name, (text, why) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(whys(text), [why])

    def test_a_newline_inside_a_value_is_malformed(self):
        text = '/*\n * @deviation(UI-A1, oracle="a\n * b", state="s", reason="substrate", link="l", until="T1")\n */'
        self.assertEqual(scan(text)[1], ((2, None, "newline-in-string"),))

    def test_an_escaped_quote_and_backslash_are_read(self):
        tags, bad, _ = scan("/* %s */" % tag(oracle='say \\"hi\\" a\\\\b'))
        self.assertEqual((bad, tags[0].oracle), ((), 'say "hi" a\\b'))

    def test_a_failing_check_names_the_tag_id_and_the_line(self):
        text = "int a;\n/* ok */\n/* %s */\n" % tag("UI-Z9", reason="bogus")
        self.assertEqual(scan(text)[1], ((3, "UI-Z9", "bad-reason"),))

    def test_one_bad_tag_does_not_hide_the_next(self):
        tags, bad, _ = scan("/* %s\n %s */" % (tag("UI-A1", reason="x"), tag("UI-A2")))
        self.assertEqual(([t.id for t in tags], [b[2] for b in bad]), (["UI-A2"], ["bad-reason"]))


class Sections(unittest.TestCase):
    def secs(self, text):
        return scan(text)[2]

    def test_label_lines_count_as_entries(self):
        text = "/*\n * DISAGREEMENTS (x)\n *  L1  one\n *      more\n *  L2  two\n *  L10 ten\n */"
        self.assertEqual(self.secs(text), ((2, 3),))

    def test_each_marker_form_counts(self):
        for forms in (("1. a", "2. b", "3. c"), ("1) a", "2) b", "3) c"), ("(1) a", "(2) b", "(3) c"),
                      ("- a", "- b", "- c"), ("* a", "* b", "* c"), ("+ a", "+ b", "+ c"), ("L1 a", "L2 b", "L3 c")):
            text = "/*\n * DISAGREEMENTS:\n" + "".join(" * %s\n" % f for f in forms) + " */"
            with self.subTest(forms=forms):
                self.assertEqual(self.secs(text), ((2, 3),))

    def test_inline_numbers_count_as_a_chain_from_one(self):
        self.assertEqual(self.secs("/* DISAGREEMENTS (Rust wins). (1) a (2) b (3) c. */"), ((1, 3),))
        self.assertEqual(self.secs("/* DISAGREEMENTS (Rust wins). (1) a (2) b\n (4) c (3) d */"), ((1, 3),))
        self.assertEqual(self.secs("/* DISAGREEMENTS (2) a (3) b */"), ((1, 1),))

    def test_a_section_without_a_recognised_entry_is_one_entry(self):
        self.assertEqual(self.secs("/* DISAGREEMENTS (Rust wins). It differs here. */"), ((1, 1),))
        self.assertEqual(self.secs("/* DISAGREEMENTS */"), ((1, 1),))

    def test_the_heading_must_start_a_comment_line(self):
        self.assertEqual(self.secs("/* see DISAGREEMENTS below */"), ())
        self.assertEqual(self.secs("/* the DISAGREEMENTS are listed in x */"), ())
        self.assertEqual(self.secs("/* Disagreements\n 1. a */"), ())
        self.assertEqual(self.secs("/* DISAGREEMENTSX\n 1. a */"), ())
        self.assertEqual(self.secs("/* ---- DISAGREEMENTS (x) ---- */"), ((1, 1),))

    def test_a_rule_line_ends_the_section_and_a_second_heading_starts_another(self):
        text = ("/*\n * ---- DISAGREEMENTS ----\n * L1 a\n * L2 b\n *\n * ---- Version 2 ----\n * L3 not an entry\n"
                " * DISAGREEMENTS again\n * 1. x\n */")
        self.assertEqual(self.secs(text), ((2, 2), (8, 1)))

    def test_a_section_ends_with_its_comment(self):
        text = "/* DISAGREEMENTS\n 1. a\n 2. b */\n/* 3. not an entry */\n"
        self.assertEqual(self.secs(text), ((1, 2),))

    def test_line_comment_sections_are_read_across_lines(self):
        self.assertEqual(self.secs("// DISAGREEMENTS\n// 1. a\n// 2. b\nint x;\n// 3. c\n"), ((1, 2),))

    def test_a_label_line_must_have_text_after_it_and_no_colon_form(self):
        self.assertEqual(self.secs("/* DISAGREEMENTS\n C12: not a label\n L1\n */"), ((1, 1),))

    def test_sections_across_comments_add_up_in_the_finding(self):
        text = "/* DISAGREEMENTS\n 1. a\n 2. b */\n/* DISAGREEMENTS\n 1. c */\n"
        files = [("a.h", text.encode())]
        _, found = ud.analyse(files, BASE, TODAY)
        self.assertEqual(found, ({"rule": "deviation-untagged", "severity": "error", "path": "a.h", "line": 1,
                                  "entries": 3, "tags": 0},))


class Parse(unittest.TestCase):
    def test_today_is_a_strict_iso_date(self):
        self.assertEqual(ud.parse_today("2026-11-15"), TODAY)
        for bad in ("2026-1-5", "20261115", "2026-02-30", "", "today", "2026-11-15 ", "٢026-11-15", None):
            with self.subTest(bad=bad):
                with self.assertRaises(InternalError):
                    ud.parse_today(bad)


if __name__ == "__main__":
    unittest.main()
