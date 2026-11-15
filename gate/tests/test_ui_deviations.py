"""U13: `rigor_lib.ui_deviations*`, the readers: where a tag is found, every malformed form, tag-shaped text, the limits, the
deviation sections and their entry count. The ratchet, the real headers and the CLI are in test_ui_deviations_ratchet.py."""

import datetime
import time
import unittest

from rigor_lib import ui_deviations as ud
from rigor_lib import ui_deviations_lex as lex
from rigor_lib import ui_deviations_sections as sec
from rigor_lib.errors import InternalError

LINK = r"https://github\.com/Mivr/club-apps/issues/[0-9]+"
PREFIX = "https://github.com/Mivr/club-apps/issues/"
TODAY = datetime.date(2026, 11, 15)
CTX = ud.Context(PREFIX, LINK, TODAY)


def tag(ident="UI-A1", **over):
    """The text of one valid tag; `over[key] = None` drops the key, a string replaces its value."""
    values = {"oracle": "welcome.slint idle echo", "state": "welcome, choose", "reason": "intentional",
              "link": "docs/lockers/ui-look.md#4.3", "until": "T200"}
    values.update(over)
    body = "".join(', %s="%s"' % (k, v) for k, v in values.items() if v is not None)
    return "@deviation(%s%s)" % (ident, body)


def scan(text, name="a.h"):
    return ud.scan_file(name, text.encode("utf-8"), CTX)


def whys(text):
    return [why for _, _, why in scan("/* %s */\n" % text).bad]


def block(*lines):
    return "/*\n" + "".join(" * %s\n" % line for line in lines) + " */\n"


def entries(*lines):
    """The (heading line, entries) pairs of a block comment made of `lines`."""
    return scan(block(*lines)).sections


class Where(unittest.TestCase):
    def test_a_tag_in_a_block_comment_is_found_with_every_field(self):
        got = scan("int x;\n/* note\n * %s\n */\n" % tag())
        self.assertEqual((got.bad, got.sections), ((), ()))
        self.assertEqual(got.tags, (ud.Tag("UI-A1", "welcome.slint idle echo", ("welcome", "choose"), "intentional",
                                           "docs/lockers/ui-look.md#4.3", "T200", "a.h", 3),))

    def test_a_tag_in_a_line_comment_is_found(self):
        got = scan("// %s\n" % tag("UI-B2"))
        self.assertEqual(([(t.id, t.line) for t in got.tags], got.bad), ([("UI-B2", 1)], ()))

    def test_a_tag_may_span_lines_in_either_comment_kind(self):
        block_text = ("/*\n * @deviation(UI-A1,\n *   oracle=\"o\", state=\"s\",\n *   reason=\"substrate\", link=\"l\",\n"
                      " *   until=\"2027-01-31\")\n */")
        line_text = ("// @deviation(UI-A1,\n//   oracle=\"o\", state=\"s\",\n//   reason=\"substrate\", link=\"l\",\n"
                     "//   until=\"2027-01-31\")\n")
        for text, line in ((block_text, 2), (line_text, 1)):
            with self.subTest(line=line):
                got = scan(text)
                self.assertEqual(([(t.id, t.line) for t in got.tags], got.bad), ([("UI-A1", line)], ()))

    def test_a_tag_in_a_string_or_character_literal_is_not_a_tag(self):
        for code in ('const char *s = "%s";\n', "const char *s = \"/* %s */\";\n",
                     "char c = '\"'; /* x */ const char *s = \"%s\";\n"):
            with self.subTest(code=code):
                self.assertEqual(scan(code % tag().replace('"', '\\"')), ud.FileScan((), (), ()))

    def test_a_string_holding_a_comment_opener_does_not_open_a_comment(self):
        self.assertEqual(scan('const char *s = "/*";\n%s\n' % tag()), ud.FileScan((), (), ()))
        got = scan('const char *s = "/*";\n/* %s */\n' % tag())
        self.assertEqual((len(got.tags), got.bad), (1, ()))

    def test_a_tag_in_code_is_not_a_tag_and_is_not_reported(self):
        self.assertEqual(scan("int x; %s\nvoid f(void);\n" % tag()), ud.FileScan((), (), ()))

    def test_a_tag_in_a_comment_inside_if_0_is_found_and_code_inside_it_is_not(self):
        got = scan("#if 0\n%s\n/* %s */\n#endif\n" % (tag("UI-C1"), tag("UI-C2")))
        self.assertEqual(([t.id for t in got.tags], got.bad), (["UI-C2"], ()))

    def test_a_line_splice_continues_a_line_comment(self):
        got = scan("// begin \\\n%s\n" % tag())
        self.assertEqual((len(got.tags), got.bad), (1, ()))

    def test_crlf_and_lone_cr_line_ends_read_like_lf(self):
        for eol in ("\r\n", "\r"):
            with self.subTest(eol=repr(eol)):
                got = scan(("int a;\n/*\n * %s\n */\n" % tag()).replace("\n", eol))
                self.assertEqual(([t.line for t in got.tags], got.bad), ([3], ()))

    def test_an_unterminated_comment_literal_or_non_utf8_file_is_malformed_never_skipped(self):
        self.assertEqual(scan("int x;\n/* %s\n" % tag()).bad, ((2, None, "unterminated-comment"),))
        self.assertEqual(scan('char *s = "abc;\n').bad, ((1, None, "unterminated-literal"),))
        self.assertEqual(scan("char c = 'a;\n").bad, ((1, None, "unterminated-literal"),))
        self.assertEqual(ud.scan_file("a.h", b"/* \xff */", CTX), ud.FileScan((), ((1, None, "not-utf-8"),), ()))

    def test_results_are_immutable(self):
        got = scan("/* %s */" % tag())
        self.assertIsInstance((got.tags, got.bad, got.sections), tuple)
        self.assertIsInstance(got.tags[0].states, tuple)
        with self.assertRaises(Exception):
            got.tags[0].id = "X-1"
        with self.assertRaises(Exception):
            CTX.today = TODAY


class TagShaped(unittest.TestCase):
    def test_every_text_shaped_like_a_tag_that_is_not_one_is_malformed(self):
        good = tag()
        for name, text in {
            "preceded by a letter": "x" + good, "doubled at-sign": "@" + good, "capital D": good.replace("@deviation", "@Deviation"),
            "all capitals": good.replace("@deviation", "@DEVIATION"), "plural with paren": good.replace("@deviation", "@deviations"),
            "fullwidth at-sign": good.replace("@", "＠"), "fullwidth and capitals": good.replace("@deviation", "＠Deviation"),
            "plural in prose": "the @deviations are listed", "bare": "@deviation", "space before paren": "@deviation (UI-A1)",
            "followed by a word": "@deviation_x(y)", "preceded by underscore": "_" + good, "preceded by digit": "1" + good,
        }.items():
            with self.subTest(name=name):
                self.assertEqual(whys(text), ["bad-tag-start"])

    def test_a_good_tag_after_punctuation_or_white_space_is_still_found(self):
        for before in (" ", "(", ":", "\n", "\t", "-"):
            with self.subTest(before=repr(before)):
                got = scan("/* a%s%s */" % (before, tag()))
                self.assertEqual((len(got.tags), got.bad), (1, ()))

    def test_two_shaped_texts_in_one_comment_are_two_findings(self):
        self.assertEqual(whys("@@deviation(x) @Deviation(y)"), ["bad-tag-start", "bad-tag-start"])


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

    def test_the_id_and_the_values_have_a_length_cap(self):
        self.assertEqual(whys(tag("UI-" + "A" * 61)), [])
        self.assertEqual(whys(tag("UI-" + "A" * 62)), ["bad-id"])
        self.assertEqual(whys(tag(oracle="x" * 512)), [])
        self.assertEqual(whys(tag(oracle="x" * 513)), ["value-too-long"])

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
        self.assertEqual(whys(tag(reason="reference-bug", link=PREFIX + "12")), [])
        for link in (PREFIX + "12x", "https://github.com/Mivr/club-apps/pull/12", "https://github.com/Mivr/other/issues/12",
                     "docs/x.md#1", PREFIX, "xhttps://github.com/Mivr/club-apps/issues/12"):
            with self.subTest(link=link):
                self.assertEqual(whys(tag(reason="reference-bug", link=link)), ["reference-bug-link-not-an-oracle-issue"])
        self.assertEqual(whys(tag(reason="substrate", link="docs/x.md#1")), [])

    def test_a_reference_bug_link_must_also_carry_the_literal_prefix(self):
        wide = ud.Context("https://example.org/issues/", r"https://[a-z.]+/issues/[0-9]+", TODAY)
        text = "/* %s */" % tag(reason="reference-bug", link="https://other.org/issues/1")
        self.assertEqual([w for _, _, w in ud.scan_file("a.h", text.encode(), wide).bad],
                         ["reference-bug-link-not-an-oracle-issue"])

    def test_until_is_a_narrow_task_id_or_a_real_iso_date(self):
        for until in ("T104", "U13", "L045", "U04a", "T1234", "2026-11-15", "2027-11-16"):
            with self.subTest(until=until):
                self.assertEqual(whys(tag(until=until)), [])
        for until, why in (("NEVER-1", "bad-until"), ("T1xx13", "bad-until"), ("B7", "bad-until"), ("U04ab", "bad-until"),
                           ("u13", "bad-until"), ("T12345", "bad-until"), ("T", "bad-until"), ("T1xx.13", "bad-until"),
                           ("2027-02-29", "bad-until-date"), ("2027-13-01", "bad-until-date"), ("2027-1-1", "bad-until"),
                           ("٢027-01-01", "bad-until")):
            with self.subTest(until=until):
                self.assertEqual(whys(tag(until=until)), [why])

    def test_an_until_date_beyond_the_horizon_is_refused_and_a_past_one_is_not(self):
        self.assertEqual(whys(tag(until="2027-11-16")), [])          # today + 366 days
        self.assertEqual(whys(tag(until="2027-11-17")), ["until-too-far"])
        self.assertEqual(whys(tag(until="2099-01-01")), ["until-too-far"])
        self.assertEqual(whys(tag(until="2001-01-01")), [])

    def test_punctuation_errors(self):
        good = tag()
        cases = {
            "trailing comma": (good[:-1] + ",)", "bad-key"),
            "missing comma": (good.replace('", state', '" state'), "expected-comma-or-close"),
            "missing equals": (good.replace("oracle=", "oracle "), "expected-equals"),
            "unquoted value": (good.replace('until="T200"', "until=T200"), "expected-string"),
            "single quotes": (good.replace('until="T200"', "until='T200'"), "expected-string"),
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
        text = '/*\n * @deviation(UI-A1, oracle="a\n * b", state="s", reason="substrate", link="l", until="T100")\n */'
        self.assertEqual(scan(text).bad, ((2, None, "newline-in-string"),))

    def test_an_escaped_quote_and_backslash_are_read(self):
        got = scan("/* %s */" % tag(oracle='say \\"hi\\" a\\\\b'))
        self.assertEqual((got.bad, got.tags[0].oracle), ((), 'say "hi" a\\b'))

    def test_a_failing_check_names_the_tag_id_and_the_line(self):
        self.assertEqual(scan("int a;\n/* ok */\n/* %s */\n" % tag("UI-Z9", reason="bogus")).bad, ((3, "UI-Z9", "bad-reason"),))

    def test_one_bad_tag_does_not_hide_the_next(self):
        got = scan("/* %s\n %s */" % (tag("UI-A1", reason="x"), tag("UI-A2")))
        self.assertEqual(([t.id for t in got.tags], [b[2] for b in got.bad]), (["UI-A2"], ["bad-reason"]))

    def test_fifty_thousand_tags_in_one_comment_are_read_in_bounded_time(self):
        body = "".join("%s\n" % tag("UI-A%d" % k) for k in range(50000))
        started = time.monotonic()
        got = scan("/*\n" + body + "*/")
        self.assertEqual((len(got.tags), got.bad, got.tags[-1].line), (50000, (), 50001))
        self.assertLess(time.monotonic() - started, 20)


class Lexer(unittest.TestCase):
    def groups(self, text):
        return [[n for n, _ in g] for g in lex.lex(text)[1]]

    def test_adjacent_comments_form_one_group_and_code_ends_it(self):
        self.assertEqual(self.groups("// a\n\n// b\nint x;\n// c\n"), [[1, 3], [5]])
        self.assertEqual(self.groups("/* a */ /* b */\n/* c */\n"), [[1, 1, 2]])
        self.assertEqual(self.groups("/* a */ int x; /* b */\n"), [[1], [1]])

    def test_comments_are_separate_units_for_tags(self):
        self.assertEqual(len(lex.lex("/* a */\n/* b */\n// c\n// d\n\n// e\n")[0]), 4)


class Sections(unittest.TestCase):
    def test_each_label_form_counts_three_entries(self):
        forms = {
            "L1": ("L1 a", "L2 b", "L3 c"), "L1:": ("L1: a", "L2: b", "L3: c"), "L1.": ("L1. a", "L2. b", "L3. c"),
            "D1": ("D1 a", "D2 b", "D3 c"), "N3": ("N1 a", "N2 b", "N3 c"), "AB1 (two capitals)": ("AB1 a", "AB2 b", "AB3 c"),
            "ABC1 (three capitals)": ("ABC1 a", "ABC2 b", "ABC3 c"), "1.": ("1. a", "2. b", "3. c"), "1)": ("1) a", "2) b", "3) c"),
            "(1)": ("(1) a", "(2) b", "(3) c"), "a)": ("a) a", "b) b", "c) c"), "(a)": ("(a) a", "(b) b", "(c) c"),
            "roman i.": ("i. a", "ii. b", "iii. c"), "roman (i)": ("(i) a", "(ii) b", "(iii) c"),
            "roman I.": ("I. a", "II. b", "III. c"), "#1": ("#1 a", "#2 b", "#3 c"), "#1:": ("#1: a", "#2: b", "#3: c"),
            "bullet -": ("- a", "- b", "- c"), "bullet *": ("* a", "* b", "* c"), "bullet +": ("+ a", "+ b", "+ c"),
            "bullet •": ("• a", "• b", "• c"), "bullet –": ("– a", "– b", "– c"),
            "Note 1": ("Note 1 a", "Note 2 b", "Note 3 c"), "Note N1": ("Note N1 a", "Note N2 b", "Note N3 c"),
            "D-1": ("D-1 a", "D-2 b", "D-3 c"), "DISAGREE-1": ("DISAGREE-1 a", "DISAGREE-2 b", "DISAGREE-3 c"),
            "(D4,": ("(D1, a)", "(D2, b)", "(D3, c)"),
        }
        for name, lines in forms.items():
            with self.subTest(name=name):
                self.assertEqual(entries("Deviations:", *lines), ((2, 3),))

    def test_what_is_not_a_label(self):
        for line in ("ABCD1 a", "L1a", "L0 a", "L01 a", "L1234 a", "e.g. a", "1.5 a", "(1a) a", "-a", "l1 a", "x y"):
            with self.subTest(line=line):
                self.assertEqual(entries("Deviations:", line, "text"), ((2, 0),))

    def test_a_space_only_separator_is_enough_and_a_missing_one_is_not(self):
        self.assertEqual(entries("Deviations:", "L1 a", "L2  b"), ((2, 2),))
        self.assertEqual(entries("Deviations:", "L1a", "L2b"), ((2, 0),))

    def test_inline_chains_in_every_style(self):
        for name, text in {"(1)": "(1) a (2) b (3) c", "1)": "1) a 2) b 3) c", "(a)": "(a) a (b) b (c) c", "a)": "a) a b) b c) c",
                           "#1": "#1 a #2 b #3 c", "D1": "D1 a. D2 b. D3 c.", "Note 1": "Note 1 a, Note 2 b, Note 3 c",
                           "(i)": "(i) a (ii) b (iii) c", "D-1": "D-1 a D-2 b D-3 c"}.items():
            with self.subTest(name=name):
                self.assertEqual(entries("Deviations: " + text), ((2, 3),))

    def test_a_chain_counts_only_its_in_order_run_from_one(self):
        self.assertEqual(entries("Deviations: (1) a (2) b (4) c (3) d"), ((2, 3),))
        self.assertEqual(entries("Deviations: (2) a (3) b"), ((2, 0),))
        self.assertEqual(entries("Deviations: see D8 and P001 R30"), ((2, 0),))

    def test_sub_bullets_inside_an_entry_are_not_counted(self):
        got = entries("Disagreements:", "L1 first", "    - detail a", "    - detail b", "    (1) x (2) y", "L2 second", "    1. step")
        self.assertEqual(got, ((2, 2),))

    def test_the_top_level_is_the_indent_of_the_first_label(self):
        self.assertEqual(entries("Disagreements:", "  L1 a", "  L2 b", "      L3 c"), ((2, 2),))
        self.assertEqual(entries("Disagreements:", "  - a", "  - b", "  - c"), ((2, 3),))

    def test_a_mixed_section_counts_the_union(self):
        self.assertEqual(entries("Disagreements: (1) x (2) y", "- a", "- b"), ((2, 4),))
        self.assertEqual(entries("Disagreements:", "L1 a", "- b", "(1) c"), ((2, 3),))
        self.assertEqual(entries("Disagreements: (1) x (2) y", "(1) a", "(2) b"), ((2, 2),))   # the same entries, once

    def test_a_repeated_label_counts_again(self):
        self.assertEqual(entries("Disagreements:", "1. a", "1. b"), ((2, 2),))

    def test_a_section_with_prose_and_no_label_has_zero_entries(self):
        self.assertEqual(entries("DISAGREEMENTS (Rust wins). It differs here and there."), ((2, 0),))
        self.assertEqual(entries("DISAGREEMENTS"), ((2, 0),))

    def test_the_heading_words_and_where_they_may_stand(self):
        for line in ("Disagreements:", "DISAGREEMENTS", "Disagreement (D8)", "deviation: x", "Deviations - D1 a", "DEVIATIONS (x)",
                     "-- Deviations:", "=== Disagreements ===", "# Deviations:", "** Disagreements,", "Differences from Rust:",
                     "---- Rust / doc disagreements (D8) ----", "---- A difference from Rust ----", "---- It deviates ----",
                     "---- Where it differs from Rust ----", "---- Deviations ----", "/ Disagreements:"):
            with self.subTest(line=line):
                self.assertEqual(len(entries(line)), 1)
        for line in ("see Disagreements below", "a disagreement here", "Disagreementsx", "xDeviation:", "this deviates from it",
                     "The differences from Rust are below", "Differences between them", "--- not a heading ---", "---",
                     "---- Not here ----", "disagree about it"):
            with self.subTest(line=line):
                self.assertEqual(entries(line), ())

    def test_a_dash_prefix_of_two_is_a_decoration_but_a_letter_prefix_is_not(self):
        self.assertEqual(len(entries("-- Deviations:")), 1)
        self.assertEqual(entries("x Deviations:"), ())

    def test_a_wrapped_sentence_is_not_a_heading_but_a_paragraph_start_is(self):
        self.assertEqual(entries("A fake never aborts; a", "deviation is a VIOLATION: it is counted."), ())
        self.assertEqual(entries("it ends here", "differs from the P value."), ())
        self.assertEqual(len(entries("text", "", "differs from the oracle here")), 1)
        self.assertEqual(len(entries("text", "", "Deviation from the pure move: x")), 1)
        self.assertEqual(len(entries("---- Model ----", "Deviation from the pure move: x")), 1)
        self.assertEqual(entries("text", "Deviation from the pure move: x"), ())
        self.assertEqual(len(entries("text", "Deviations: D1 a. D2 b.")), 1)     # followed by `:`: a heading wherever it stands
        for tail in ("(D8: Rust wins)", ", D1 a", ". D1 a", "; D1 a", "- D1 a", "\u2014 D1 a", "\u2013 D1 a"):
            with self.subTest(tail=tail):
                self.assertEqual(len(entries("text", "Deviations " + tail)), 1)

    def test_a_section_runs_over_a_bare_rule_a_blank_line_and_a_split_comment(self):
        self.assertEqual(scan("/*\n * Deviations:\n * L1 a\n * ---\n * L2 b\n *\n * L3 c\n */\n").sections, ((2, 3),))
        self.assertEqual(scan("// Deviations:\n// L1 a\n\n// L2 b\n\n\n// L3 c\n").sections, ((1, 3),))
        self.assertEqual(scan("/* Deviations:\n * L1 a */\n/* L2 b */\n  /* L3 c */\n").sections, ((1, 3),))
        self.assertEqual(scan("/* Deviations:\n * L1 a */\nint x;\n/* L2 b */\n").sections, ((1, 1),))

    def test_a_titled_rule_an_upper_case_title_or_the_next_heading_ends_a_section(self):
        for end in ("---- Version 2 ----", "---- Not here", "COUNTS", "THE TOKEN", "DESIGN"):
            with self.subTest(end=end):
                self.assertEqual(entries("Disagreements:", "L1 a", "L2 b", end, "L3 c", "1. x", "2. y"), ((2, 2),))
        self.assertEqual(entries("Disagreements:", "L1 a", "Deviations:", "L2 b"), ((2, 1), (4, 1)))
        self.assertEqual(entries("Disagreements:", "L1 a", "Mostly CAPS but not all", "L2 b"), ((2, 2),))
        self.assertEqual(entries("Disagreements:", "L1 a", "ABC", "L2 b"), ((2, 2),))      # fewer than four letters
        self.assertEqual(entries("Disagreements:", "L1 a", "ABCDEFGHIJ" * 9, "L2 b"), ((2, 2),))   # 90 characters: not a title
        self.assertEqual(entries("Disagreements:", "L1 a", "-- a note", "L2 b"), ((2, 2),))      # two dashes are not a rule

    def test_a_numbered_list_of_rules_after_the_section_is_not_counted(self):
        text = block("---- Disagreements (D8) ----", "L1 a", "L2 b", "", "---- Rules ----", "R1 x", "R2 y", "R3 z", "1. one", "2. two")
        self.assertEqual(scan(text).sections, ((2, 2),))

    def test_two_sections_in_one_comment_and_in_two_groups(self):
        self.assertEqual(scan("/* Deviations:\n 1. a\n Disagreements:\n 1. b\n 2. c */\nint x;\n// Deviations: (1) a\n").sections,
                         ((1, 1), (3, 2), (7, 1)))

    def test_results_are_tuples_of_pairs(self):
        self.assertEqual(sec.sections_of(((1, "Deviations:"), (2, "L1 a"))), ((1, 1),))


if __name__ == "__main__":
    unittest.main()
