"""Tests for `po2c` (T105, `c_catalog`): the PO subset, the template rules, the enum names, the C text.

Every failure of the generator is a build error that names the file, the line and the msgid; each test below
checks that text. Hand-written PO text, no compiler involved.
"""

import subprocess
import sys

from rigor_lib import po2c
from tests.helpers import GATE_DIR, TempDirTestCase

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n"Language: bg\\n"\n\n'


def pot_text(*ids):
    return HEADER + "".join('msgid "%s"\nmsgstr ""\n\n' % i for i in ids)


def po_text(*pairs):
    return HEADER + "".join('msgid "%s"\nmsgstr "%s"\n\n' % pair for pair in pairs)


def make(pots, bgs, langs=("bg", "en"), source="en", symbol="lk_cat"):
    """build() from texts: `pots` and `bgs` are lists of str (one bg po per pot)."""
    return po2c.build([("p%d.pot" % k, t.encode("utf-8")) for k, t in enumerate(pots)],
                      {"bg": [("p%d.bg.po" % k, t.encode("utf-8")) for k, t in enumerate(bgs)]},
                      list(langs), source, symbol)


def one(msgid, msgstr):
    return make([pot_text(msgid)], [po_text((msgid, msgstr))])


class ParseCase(TempDirTestCase):
    def parse(self, text):
        return po2c.parse_po("f.po", text.encode("utf-8") if isinstance(text, str) else text)

    def red(self, text, *needles):
        with self.assertRaises(po2c.CatalogError) as caught:
            self.parse(text)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))

    def test_entries_and_header_are_dropped(self):
        self.assertEqual(self.parse(HEADER + 'msgid "a"\nmsgstr "b"\n\nmsgid "c"\nmsgstr "d"\n'),
                         [("a", "b", 6), ("c", "d", 9)])

    def test_continuation_lines_are_concatenated(self):
        text = 'msgid "ab"\n"cd"\nmsgstr ""\n"x"\n"y"\n'
        self.assertEqual(self.parse(text), [("abcd", "xy", 1)])
        text = 'msgid "a"\n"b"\nmsgstr ""\n"c"\n" d"\n'
        self.assertEqual(self.parse(text), [("ab", "c d", 1)])

    def test_comments_and_blank_lines_are_ignored(self):
        text = '# translator\n#. extracted\n#: src.rs:1\n#, c-format\n\nmsgid "a"\n# inside\nmsgstr "b"\n#~ msgid "gone"\n'
        self.assertEqual(self.parse(text), [("a", "b", 6)])

    def test_escapes(self):
        self.assertEqual(self.parse('msgid "a\\\\b\\"c\\nd\\te"\nmsgstr "x"\n'), [('a\\b"c\nd\te', "x", 1)])

    def test_unsupported_escapes_fail(self):
        for escape in ("\\x41", "\\0", "\\r", "\\a", "\\'", "\\u00e9"):
            self.red('msgid "a%s"\nmsgstr "b"\n' % escape, "f.po:1", "unsupported escape")

    def test_trailing_backslash_fails(self):
        self.red('msgid "a\\"\nmsgstr "b"\n', "f.po:1")

    def test_unescaped_quote_fails(self):
        self.red('msgid "a"b"\nmsgstr "b"\n', "f.po:1", "unescaped")

    def test_unquoted_value_fails(self):
        self.red('msgid a\nmsgstr "b"\n', "f.po:1", "quoted")

    def test_unsupported_keywords_fail(self):
        for text, word in (('msgctxt "c"\nmsgid "a"\nmsgstr "b"\n', "msgctxt"),
                           ('msgid "a"\nmsgid_plural "as"\nmsgstr[0] "b"\n', "msgid_plural"),
                           ('msgid "a"\nmsgstr[0] "b"\n', "msgstr")):
            self.red(text, "f.po:", "not supported")

    def test_fuzzy_fails(self):
        self.red('#, fuzzy\nmsgid "a"\nmsgstr "b"\n', "f.po:1", "fuzzy")
        self.red('#, c-format, fuzzy\nmsgid "a"\nmsgstr "b"\n', "f.po:1", "fuzzy")

    def test_a_flag_that_only_contains_fuzzy_is_not_fuzzy(self):
        self.assertEqual(self.parse('#, not-fuzzy-really\nmsgid "a"\nmsgstr "b"\n'), [("a", "b", 2)])

    def test_invalid_utf8_names_its_line(self):
        self.red(b'msgid "a"\nmsgstr "b"\nmsgid "\xff"\nmsgstr "c"\n', "f.po:3", "UTF-8")

    def test_header_charset(self):
        self.red('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=ISO-8859-1\\n"\n', "f.po:1", "ISO-8859-1")
        self.assertEqual(self.parse('msgid ""\nmsgstr "Content-Type: text/plain; charset=utf-8\\n"\n'), [])

    def test_header_without_content_type_is_fine(self):
        self.assertEqual(self.parse('msgid ""\nmsgstr ""\n'), [])

    def test_duplicate_msgid_in_a_file_fails(self):
        self.red('msgid "a"\nmsgstr "b"\n\nmsgid "a"\nmsgstr "c"\n', "f.po:4", 'msgid "a"', "repeated")

    def test_two_headers_fail(self):
        self.red('msgid ""\nmsgstr ""\n\nmsgid ""\nmsgstr ""\n', "f.po:4", "repeated")

    def test_msgid_without_msgstr_fails(self):
        self.red('msgid "a"\n\nmsgid "b"\nmsgstr "c"\n', "f.po:1", 'msgid "a"')
        self.red('msgid "a"\n', "f.po:1", 'msgid "a"')

    def test_msgstr_without_msgid_fails(self):
        self.red('msgstr "a"\n', "f.po:1", "without a msgid")
        self.red('msgid "a"\nmsgstr "b"\nmsgstr "c"\n', "f.po:3", "without a msgid")

    def test_continuation_outside_an_entry_fails(self):
        self.red('"a"\n', "f.po:1", "continuation")

    def test_syntax_error_fails(self):
        self.red('hello\n', "f.po:1", "syntax")


class TemplateCase(TempDirTestCase):
    def test_grammar(self):
        self.assertEqual(po2c.placeholders("a {0} b {1}{0}"), [0, 1, 0])
        self.assertEqual(po2c.placeholders("{{{0}}}"), [0])
        self.assertEqual(po2c.placeholders("{{0}}"), [])
        self.assertEqual(po2c.placeholders("100%}}{{"), [])
        self.assertEqual(po2c.placeholders("{9}"), [9])

    def test_malformed(self):
        for text in ("{", "}", "{10}", "{0 }", "{00}", "{-1}", "{a}", "{ }", "{}", "a{", "a}", "{{{", "}}}", "{0", "{٣}"):
            with self.assertRaises(ValueError, msg=text):
                po2c.placeholders(text)

    def test_malformed_source_msgid_fails(self):
        with self.assertRaises(po2c.CatalogError) as caught:
            one("Open {10}", "Отвори")
        self.assertIn("p0.pot:6", str(caught.exception))
        self.assertIn("Open {10}", str(caught.exception))

    def test_malformed_translation_fails(self):
        with self.assertRaises(po2c.CatalogError) as caught:
            one("Open {0}", "Отвори {0")
        self.assertIn("p0.bg.po:6", str(caught.exception))
        self.assertIn("Open {0}", str(caught.exception))

    def test_source_indices_must_start_at_zero_without_gaps(self):
        for msgid in ("{1}", "{0} {2}", "{2} {1}"):
            with self.assertRaises(po2c.CatalogError) as caught:
                one(msgid, msgid)
            self.assertIn("0..n-1", str(caught.exception))

    def test_n_args_counts_distinct_indices(self):
        messages = make([pot_text("a", "{0}", "{1} {0} {1}", "x {{0}}")],
                        [po_text(("a", "b"), ("{0}", "{0}"), ("{1} {0} {1}", "{0} {1}"), ("x {{0}}", "y {{0}}"))])
        self.assertEqual([m.n_args for m in messages], [0, 1, 2, 0])

    def test_translation_drops_a_placeholder(self):
        with self.assertRaises(po2c.CatalogError) as caught:
            one("Locker {0}", "Шкафче")
        self.assertIn("p0.bg.po:6", str(caught.exception))
        self.assertIn('msgid "Locker {0}"', str(caught.exception))

    def test_translation_adds_a_placeholder(self):
        with self.assertRaises(po2c.CatalogError):
            one("Locker {0}", "Шкафче {0} {1}")

    def test_reordering_is_fine(self):
        self.assertEqual(one("{0} of {1}", "{1} от {0}")[0].n_args, 2)

    def test_a_single_use_must_stay_single(self):
        with self.assertRaises(po2c.CatalogError) as caught:
            one("Locker {0}", "{0} {0}")
        self.assertIn("2 times", str(caught.exception))

    def test_a_repeated_index_may_change_its_count(self):
        self.assertEqual(one("{0} {0}", "{0}")[0].n_args, 1)
        self.assertEqual(one("{0} {0}", "{0} {0} {0}")[0].n_args, 1)

    def test_a_repeated_index_may_not_vanish(self):
        with self.assertRaises(po2c.CatalogError):
            one("{0} {0} {1}", "{1}")


class CatalogCase(TempDirTestCase):
    def fails(self, call, *needles):
        with self.assertRaises(po2c.CatalogError) as caught:
            call()
        for needle in needles:
            self.assertIn(needle, str(caught.exception))

    def test_first_appearance_order_over_pots(self):
        messages = make([pot_text("b", "a"), pot_text("c", "d")],
                        [po_text(("b", "1"), ("a", "2")), po_text(("c", "3"), ("d", "4"))])
        self.assertEqual([m.msgid for m in messages], ["b", "a", "c", "d"])
        self.assertEqual(messages[0].texts, {"en": "b", "bg": "1"})

    def test_a_shared_msgid_is_one_id(self):
        messages = make([pot_text("a", "x"), pot_text("y", "a")],
                        [po_text(("a", "1"), ("x", "2")), po_text(("y", "3"), ("a", "1"))])
        self.assertEqual([m.msgid for m in messages], ["a", "x", "y"])

    def test_a_shared_msgid_with_another_translation_fails(self):
        self.fails(lambda: make([pot_text("a"), pot_text("a")], [po_text(("a", "1")), po_text(("a", "2"))]),
                   "p1.pot:6", 'msgid "a"', "earlier pot", "bg")

    def test_empty_msgstr_fails(self):
        self.fails(lambda: one("a", ""), "p0.bg.po:6", 'msgid "a"', "bg")

    def test_missing_msgstr_fails(self):
        self.fails(lambda: make([pot_text("a", "b")], [po_text(("a", "1"))]), 'msgid "b"', "bg")

    def test_po_msgid_not_in_its_pot_fails(self):
        self.fails(lambda: make([pot_text("a")], [po_text(("a", "1"), ("b", "2"))]),
                   "p0.bg.po:9", 'msgid "b"', "p0.pot")

    def test_po_msgid_of_another_pot_fails(self):
        self.fails(lambda: make([pot_text("a"), pot_text("b")], [po_text(("a", "1"), ("b", "2")), po_text(("b", "2"))]),
                   "p0.bg.po", 'msgid "b"')

    def test_duplicate_in_a_pot_fails(self):
        self.fails(lambda: make([pot_text("a", "a")], [po_text(("a", "1"))]), "p0.pot:9", "repeated")

    def test_inputs_are_checked(self):
        pots = [("p.pot", pot_text("a").encode())]
        good = {"bg": [("p.po", po_text(("a", "1")).encode())]}
        self.fails(lambda: po2c.build(pots, good, ["bg", "en"], "en", "1bad"), "symbol")
        self.fails(lambda: po2c.build(pots, good, ["bg", "en"], "en", ""), "symbol")
        self.fails(lambda: po2c.build(pots, good, ["bg", "bg", "en"], "en", "s"), "langs")
        self.fails(lambda: po2c.build(pots, good, ["bg"], "en", "s"), "langs")
        self.fails(lambda: po2c.build(pots, good, ["bg", "en", "fr"], "en", "s"), "po languages")
        self.fails(lambda: po2c.build(pots, {"bg": [], }, ["bg", "en"], "en", "s"), "0 po files for 1 pots")
        self.fails(lambda: po2c.build([], {"bg": []}, ["bg", "en"], "en", "s"), "no pot")
        self.fails(lambda: po2c.build([("p.pot", pot_text().encode())], {"bg": [("p.po", po_text().encode())]},
                                      ["bg", "en"], "en", "s"), "no message")

    def test_three_languages(self):
        pots = [("p.pot", pot_text("a {0}").encode())]
        pos = {"bg": [("b.po", po_text(("a {0}", "б {0}")).encode())], "de": [("d.po", po_text(("a {0}", "d {0}")).encode())]}
        messages = po2c.build(pots, pos, ["bg", "en", "de"], "en", "s")
        self.assertEqual(messages[0].texts, {"en": "a {0}", "bg": "б {0}", "de": "d {0}"})
        source = po2c.render_source(messages, ["bg", "en", "de"], "s", "x/s.h")
        self.assertIn('"\\320\\261 {0}", "a {0}", "d {0}",', source)


class NamesCase(TempDirTestCase):
    def test_words(self):
        for msgid, words in (("Small", "SMALL"), ("Small · Full", "SMALL_FULL"), ("  hi!  ", "HI"),
                             ("a--b", "A_B"), ("3 left", "N3_LEFT"), ("{0} opened", "N0_OPENED"),
                             ("Café au lait", "CAF_AU_LAIT"), ("x" * 60, "X" * 48), ("12" + "y" * 60, "N12" + "Y" * 46),
                             ("ab " + "c" * 44 + " d", "AB_" + "C" * 44), ("...", ""), ("éé", "")):
            self.assertEqual(po2c.enum_words(msgid), words, msg=msgid)

    def test_enum_names_have_the_prefix(self):
        messages = [po2c.Message("Open", 0, {}), po2c.Message("{0} left", 1, {})]
        self.assertEqual(po2c.enum_names(messages, "lk_cat"), ["LK_CAT_OPEN", "LK_CAT_N0_LEFT"])

    def test_a_collision_fails(self):
        messages = [po2c.Message("Open", 0, {}), po2c.Message("open!", 0, {})]
        with self.assertRaises(po2c.CatalogError) as caught:
            po2c.enum_names(messages, "c")
        self.assertIn('msgid "open!"', str(caught.exception))
        self.assertIn('"Open"', str(caught.exception))
        self.assertIn("C_OPEN", str(caught.exception))

    def test_a_collision_after_truncation_fails(self):
        messages = [po2c.Message("a" * 48 + "b", 0, {}), po2c.Message("a" * 48 + "c", 0, {})]
        with self.assertRaises(po2c.CatalogError):
            po2c.enum_names(messages, "c")

    def test_a_name_without_words_fails(self):
        with self.assertRaises(po2c.CatalogError) as caught:
            po2c.enum_names([po2c.Message("...", 0, {})], "c")
        self.assertIn('msgid "..."', str(caught.exception))


class OutputCase(TempDirTestCase):
    def messages(self):
        return make([pot_text("Open {0}", 'Say \\"hi\\"\\n')], [po_text(("Open {0}", "Отвори {0}"), ('Say \\"hi\\"\\n', "Каза\\n\\t\\\\ \\\"x\\\" ?? 1"))])

    def test_c_string_escapes(self):
        self.assertEqual(po2c.c_string("ab c"), '"ab c"')
        self.assertEqual(po2c.c_string("é"), '"\\303\\251"')
        self.assertEqual(po2c.c_string('"\\?'), '"\\042\\134\\077"')
        self.assertEqual(po2c.c_string("\n\t"), '"\\012\\011"')
        self.assertEqual(po2c.c_string("\n1"), '"\\0121"')   # three digits: the next digit is not swallowed
        self.assertEqual(po2c.c_string("\x7f"), '"\\177"')
        self.assertEqual(po2c.c_string("€9"), '"\\342\\202\\2549"')
        self.assertNotIn("\\x", po2c.c_string("éaéb"))

    def test_header(self):
        text = po2c.render_header(self.messages(), "lk_cat", "lib/fmt/i18n/i18n.h")
        self.assertIn('#include "lib/fmt/i18n/i18n.h"', text)
        self.assertIn("    LK_CAT_OPEN_0 = 0,\n", text)
        self.assertIn("    LK_CAT_SAY_HI = 1,\n", text)
        self.assertIn("    LK_CAT__COUNT = 2,\n} lk_cat_msg_t;", text)
        self.assertIn("extern const i18n_catalog_t lk_cat;", text)
        self.assertIn("#ifndef C_CATALOG_LK_CAT_H", text)

    def test_source(self):
        text = po2c.render_source(self.messages(), ["bg", "en"], "lk_cat", "pkg/cat.h")
        self.assertIn('#include "pkg/cat.h"', text)
        self.assertIn("static const char *const lk_cat_str[4] = {", text)
        self.assertIn('    "\\320\\236\\321\\202\\320\\262\\320\\276\\321\\200\\320\\270 {0}", "Open {0}",\n', text)
        self.assertIn("static const uint8_t lk_cat_n_args[2] = {\n    1,\n    0,\n};", text)
        self.assertIn("_Static_assert(sizeof(lk_cat_str) / sizeof(lk_cat_str[0]) == (size_t)4,", text)
        self.assertIn("_Static_assert(sizeof(lk_cat_n_args) / sizeof(lk_cat_n_args[0]) == (size_t)2,", text)
        self.assertIn("_Static_assert((size_t)LK_CAT__COUNT == (size_t)2,", text)
        self.assertIn("const i18n_catalog_t lk_cat = {\n    .n_msgs = 2,\n    .n_langs = 2,\n", text)
        self.assertNotIn("\\x", text)
        self.assertTrue(text.isascii())

    def test_no_mutable_object(self):
        text = po2c.render_source(self.messages(), ["bg", "en"], "lk_cat", "pkg/cat.h")
        for line in text.splitlines():
            if "=" in line and "{" in line and "_Static_assert" not in line:
                self.assertTrue(line.startswith("static const ") or line.startswith("const "), msg=line)


class CliCase(TempDirTestCase):
    def files(self, pot, bg):
        (self.tmp / "a.pot").write_bytes(pot.encode("utf-8"))
        (self.tmp / "a.bg.po").write_bytes(bg.encode("utf-8"))

    def run_cli(self):
        command = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "po2c.py"), "--symbol", "lk_cat",
                   "--langs", "bg,en", "--source-lang", "en", "--header", "pkg/cat.h", "--runtime-header",
                   "lib/fmt/i18n/i18n.h", "--pot", str(self.tmp / "a.pot"), "--po", "bg", str(self.tmp / "a.bg.po"),
                   "--out-h", str(self.tmp / "o.h"), "--out-c", str(self.tmp / "o.c")]
        return subprocess.run(command, capture_output=True, text=True, timeout=60)

    def test_deterministic_output(self):
        self.files(pot_text("a", "b {0}"), po_text(("a", "а"), ("b {0}", "б {0}")))
        done = self.run_cli()
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        first = ((self.tmp / "o.h").read_bytes(), (self.tmp / "o.c").read_bytes())
        (self.tmp / "o.h").unlink()
        (self.tmp / "o.c").unlink()
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(((self.tmp / "o.h").read_bytes(), (self.tmp / "o.c").read_bytes()), first)

    def test_error_exits_1_names_file_line_msgid_and_writes_nothing(self):
        self.files(pot_text("a"), po_text(("a", "")))
        done = self.run_cli()
        self.assertEqual(done.returncode, 1)
        self.assertIn("a.bg.po:6", done.stderr)
        self.assertIn('msgid "a"', done.stderr)
        self.assertFalse((self.tmp / "o.h").exists() or (self.tmp / "o.c").exists())

    def test_unreadable_input_exits_1(self):
        self.files(pot_text("a"), po_text(("a", "1")))
        (self.tmp / "a.bg.po").unlink()
        done = self.run_cli()
        self.assertEqual(done.returncode, 1)
        self.assertIn("cannot read", done.stderr)

    def test_bad_include_path_exits_1(self):
        self.files(pot_text("a"), po_text(("a", "1")))
        command = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "po2c.py"), "--symbol", "s",
                   "--langs", "bg,en", "--source-lang", "en", "--header", "../x.h", "--runtime-header", "r.h",
                   "--pot", str(self.tmp / "a.pot"), "--po", "bg", str(self.tmp / "a.bg.po"),
                   "--out-h", str(self.tmp / "o.h"), "--out-c", str(self.tmp / "o.c")]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 1)
        self.assertIn("include path", done.stderr)
