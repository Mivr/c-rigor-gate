"""The pseudo-locale generator (`rigor_lib.ui_pseudo`, U17a): the length rule, monotone envelope, content, kept
placeholders, per-line rules, refusals, determinism, the golden output and acceptance by `po2c`."""

import hashlib
import random
from pathlib import Path

from rigor_lib import po2c, ui_pseudo as up
from tests.helpers import TempDirTestCase, run_rigor

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "ui_pseudo"
CONTRACT = HERE.parent.parent / "products" / "business-apps" / "ui" / "lockers.toml"
HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
NAMES = ("lockers", "kit", "c_only")


def pot(*ids):
    return HEADER + "".join('msgid "%s"\nmsgstr ""\n\n' % i for i in ids)


def po(*pairs):
    return HEADER + "".join('msgid "%s"\nmsgstr "%s"\n\n' % p for p in pairs)


def gen(pot_text, *bgs, pct=0, **kw):
    """The generated text; `bgs` are po texts of the languages bg, de, fr in that order."""
    langs = ["bg", "de", "fr"]
    pos = {langs[i]: [("a.%s.po" % langs[i], t.encode())] for i, t in enumerate(bgs)}
    return up.generate([("a.pot", pot_text.encode())], pos, "en", pct, **kw)[0]


def one(msgid, bg, *more, pct=0):
    """The pseudo msgstr of one msgid (`\\n` in the arguments is a line break of the file)."""
    text = gen(pot(msgid), po((msgid, bg)), *[po((msgid, m)) for m in more], pct=pct)
    return po2c.parse_po("x.po", text.encode())[0][1]


def content(text):
    return text[1:-1]


def real_inputs():
    pots = [(n + ".pot", (DATA / (n + ".pot")).read_bytes()) for n in NAMES]
    pos = [(n + ".po", (DATA / "bg" / (n + ".po")).read_bytes()) for n in NAMES]
    return pots, pos


class Length(TempDirTestCase):
    def test_envelope_is_monotone_and_follows_the_table(self):
        values = [up.envelope(n) for n in range(0, 300)]
        self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))
        self.assertEqual([up.envelope(n) for n in (1, 2, 10)], [3, 6, 30])

    def test_band_edges_never_shrink(self):
        for low, high in ((10, 11), (20, 21), (30, 31), (50, 51), (70, 71)):
            with self.subTest(low=low):
                self.assertGreaterEqual(len(content(one("a" * high, "б"))), len(content(one("a" * low, "б"))))

    def test_exact_lengths_with_a_short_real_translation(self):
        want = {1: 3, 2: 6, 10: 30, 11: 30, 20: 40, 21: 40, 30: 54, 31: 54, 50: 80, 51: 80, 70: 98, 71: 98, 100: 130}
        for n, length in want.items():
            with self.subTest(n=n):
                self.assertEqual(len(content(one("a" * n, "б"))), length)

    def test_one_character_msgid_and_ok_get_their_full_expansion(self):
        self.assertEqual(len(content(one("X", "Х"))), 3)
        self.assertEqual(len(content(one("OK", "ОК"))), 6)

    def test_the_content_is_longer_than_the_longest_bulgarian(self):
        self.assertEqual(len(content(one("Sync", "Синхронизиране"))), 15)   # 14 glyphs: 15, not 14
        self.assertEqual(len(content(one("Small", "Б" * 40))), 41)
        self.assertEqual(len(content(one("Small", "Б" * 14))), 15)          # table 15, real 14
        self.assertEqual(len(content(one("Small", "Б" * 15))), 16)

    def test_the_longest_of_several_languages_wins(self):
        self.assertEqual(len(content(one("Small", "Б" * 20, "x" * 33))), 34)

    def test_the_contract_floor(self):
        msgid = ("word " * 40).strip() + "."   # 200 characters: table 130% = 260
        self.assertEqual(len(content(one(msgid, "б", pct=0))), 260)
        self.assertEqual(len(content(one(msgid, "б", pct=40))), 280)
        self.assertEqual(len(content(one(msgid, "б", pct=20))), 260)

    def test_double_braces_count_as_one_character(self):
        text = one("{{a}}", "{{б}}")
        self.assertEqual(up.displayed(content(text)), 9)   # 3 displayed characters: 9
        self.assertEqual(len(content(text)), 11)
        self.assertEqual(text.count("{{"), 1)

    def test_the_floor_is_an_integer_from_the_contract(self):
        for bad in (None, "40", 40.0, -1, 501):
            with self.subTest(bad=bad), self.assertRaises(up.PseudoError):
                up.generate([("a.pot", pot("a").encode())], {"bg": [("b", po(("a", "б")).encode())]}, "en", bad)


class Content(TempDirTestCase):
    def test_every_pseudo_string_of_the_real_catalogue(self):
        pots, pos = real_inputs()
        count = 0
        for text, name in zip(up.generate(pots, {"bg": pos}, "en", 40), NAMES):
            bg = {m: s for m, s, _ in po2c.parse_po(name, (DATA / "bg" / (name + ".po")).read_bytes())}
            for msgid, value, _ in po2c.parse_po("x", text.encode()):
                self.assertTrue(value.startswith("[") and value.endswith("]"), value)
                if "\n" not in msgid:
                    self.assertGreater(len(value) - 2, len(bg[msgid]))
                count += 1
        self.assertGreater(count, 100)

    def test_padding_uses_the_tallest_and_deepest_glyphs(self):
        body = content(one("Choose a size for the locker", "Изберете размер")).replace(" ", "")
        self.assertTrue(set(body) <= set(up.PADDING))
        self.assertTrue(set("ЙЩрущц") <= set(body))

    def test_a_padding_word_is_as_long_as_the_longest_real_word(self):
        text = content(one("Pick a size", "Изберетеразмерче и така"))   # longest real word: 14 glyphs
        self.assertGreater(len(text), 14)
        for word in text.split(" "):
            self.assertGreaterEqual(len(word), 14)
        text = content(one("Pick one of them now please", "Изберетееееееее една от тях сега моля"))
        self.assertGreater(text.count(" "), 0)
        self.assertTrue(all(len(w) >= 13 for w in text.split(" ")))

    def test_a_single_word_source_stays_one_word(self):
        self.assertNotIn(" ", one("Synchronise", "Синхронизиране на всичко сега"))
        self.assertNotIn(" ", one("Sync", "Синхронизиране"))

    def test_spaces_only_where_the_real_text_has_word_breaks(self):
        self.assertLessEqual(content(one("Open door", "Отвори")).count(" "), 1)
        self.assertLessEqual(content(one("Two words here now", "Едно две")).count(" "), 3)
        self.assertEqual(content(one("Open", "Отвори вратата сега")).count(" "), 0)

    def test_a_glyph_between_a_delimiter_and_a_placeholder_and_no_space_next_to_it(self):
        for msgid, bg in (("{0} done", "{0} готово"), ("done {0}", "готово {0}"), ("{0} and {1}", "{0} и {1}"),
                          ("  padded  ", "  с  ")):
            with self.subTest(msgid=msgid):
                text = one(msgid, bg)
                self.assertTrue(text[1] in up.PADDING and text[-2] in up.PADDING, text)

    def test_an_argument_ending_in_a_bracket_cannot_fake_the_end_delimiter(self):
        text = one("Value {0}", "Стойност {0}")
        self.assertIn(text[-2], up.PADDING)          # a glyph, not the argument, sits before the end delimiter
        self.assertTrue(text.index("{0}") + 3 < len(text) - 1)
        self.assertIn(text[1], up.PADDING)

    def test_percent_signs_are_plain_text(self):
        text = one("100% done", "100% готово")
        self.assertTrue(set(content(text).replace(" ", "")) <= set(up.PADDING), text)
        self.assertNotIn("%", text)

    def test_line_breaks_and_the_rule_per_line(self):
        text = one("Open the door\\nthen press OK now", "Отворете\\nнатиснете ОК сега сега сега")
        lines = content(text).split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(lines[0]), 30)                       # 13 characters: envelope 30; not the BG total
        self.assertGreater(len(lines[1]), len("натиснете ОК сега сега сега"))
        self.assertTrue(text.startswith("[") and text.endswith("]"))

    def test_a_longer_bulgarian_first_line_decides_that_line_only(self):
        text = one("Hi\\nA much longer second line here", "Здравейте приятели мои\\nкратко")
        first, second = content(text).split("\n")
        self.assertEqual(len(first), len("Здравейте приятели мои") + 1)
        self.assertEqual(len(second), 54)   # 30 characters: 54, longer than the BG 6

    def test_blank_lines_stay_blank(self):
        self.assertEqual(content(one("A\\n\\nB", "Б\\n\\nВ")).split("\n")[1], "")

    def test_the_header_names_the_language(self):
        self.assertIn('"Language: xx\\n"', gen(pot("a"), po(("a", "б"))))
        self.assertIn('"Language: yy\\n"', gen(pot("a"), po(("a", "б")), lang="yy"))


class Placeholders(TempDirTestCase):
    def test_kept_in_count_and_order(self):
        for msgid, bg in (("Locker {0} is open", "Шкаф {0} е отворен"), ("Ended {0}:{1} UTC", "Край {0}:{1} UTC"),
                          ("{1} and {0}", "{1} и {0}"), ("Sync: {0} {0}", "Синхр.: {0} {0}"),
                          ("Braces {{ and }} {0}", "Скоби {{ и }} {0}")):
            with self.subTest(msgid=msgid):
                self.assertEqual(po2c.placeholders(one(msgid, bg)), po2c.placeholders(msgid))

    def patched(self, name, replacement, pot_text, po_text):
        original = getattr(up, name)
        setattr(up, name, replacement(original))
        try:
            with self.assertRaises(up.PseudoError) as caught:
                gen(pot_text, po_text)
        finally:
            setattr(up, name, original)
        return str(caught.exception)

    def test_a_dropped_placeholder_is_seen_failing(self):
        why = self.patched("pseudo_text", lambda f: lambda *a: f(*a).replace("{0}", ""),
                           pot("Locker {0} is open"), po(("Locker {0} is open", "Шкаф {0}")))
        self.assertIn("does not keep the placeholders", why)

    def test_a_dropped_repeat_of_a_placeholder_is_seen_failing(self):
        why = self.patched("pseudo_text", lambda f: lambda *a: f(*a).replace("{0}", "", 1),
                           pot("Sync: {0} {0}"), po(("Sync: {0} {0}", "Синхр.: {0} {0}")))
        self.assertIn("does not keep the placeholders", why)

    def test_a_brace_outside_a_placeholder_is_refused_by_the_generator_itself(self):
        for text in ("a { b", "a } b", "a {10} b", "a {x} b"):
            with self.subTest(text=text), self.assertRaises(up.PseudoError):
                up.split_pieces(text)

    def test_a_text_that_is_not_longer_than_the_real_one_is_seen_failing(self):
        why = self.patched("pseudo_text", lambda f: lambda msgid, reals, pct: "[ЙЙ]",
                           pot("Sync"), po(("Sync", "Синхронизиране")))
        self.assertIn("not longer", why)

    def test_po2c_is_run_over_the_generated_file(self):
        why = self.patched("render", lambda f: lambda items, lang: f(items, lang) + '\n#, fuzzy\nmsgid "x"\nmsgstr "y"\n',
                           pot("Sync"), po(("Sync", "Синхр")))
        self.assertIn("po2c refuses", why)

    def refused(self, pot_text, bg_text, *needles):
        with self.assertRaises(up.PseudoError) as caught:
            gen(pot_text, bg_text)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))

    def test_placeholder_only_msgids_are_refused_with_their_name(self):
        for msgid in ("{0}", "{0} {1}", "{0}\\n{1}", "{{}}"):
            with self.subTest(msgid=msgid):
                self.refused(pot(msgid), po((msgid, msgid)), "nothing but placeholders", msgid)

    def test_what_po2c_refuses_is_refused(self):
        self.refused(pot("Item {10} of it"), po(("Item {10} of it", "Ред {10}")), "po2c refuses", "malformed")
        self.refused(pot("Hello"), po(("Hello", "")), "po2c refuses", "Hello")
        self.refused(pot("Hello {0}"), po(("Hello {0}", "Здравей")), "po2c refuses", "placeholders")
        self.refused(pot("Hello {"), po(("Hello {", "Здравей {")), "po2c refuses", "malformed")
        self.refused(pot("Hello }"), po(("Hello }", "Здравей }")), "po2c refuses")
        self.refused(pot("Hello"), HEADER.replace("UTF-8", "ISO-8859-1") + 'msgid "Hello"\nmsgstr "x"\n', "charset")
        self.refused(pot("Hello"), po(("Hello", "x")) + 'msgid "Hello"\nmsgstr "y"\n', "repeated")
        self.refused(pot("Hello"), po(("Other", "x")), "not in")
        self.refused(pot("Hello"), "#, fuzzy\n" + po(("Hello", "x")), "fuzzy")
        self.refused('msgctxt "c"\n' + pot("Hello"), po(("Hello", "x")), "msgctxt")
        self.refused(pot("Hello") + 'msgid "One"\nmsgid_plural "Many"\nmsgstr[0] ""\nmsgstr[1] ""\n',
                     po(("Hello", "x")), "po2c refuses")

    def test_a_pseudo_language_that_clashes_is_refused(self):
        for lang in ("bg", "en"):
            with self.assertRaises(up.PseudoError):
                gen(pot("a"), po(("a", "б")), lang=lang)


class Determinism(TempDirTestCase):
    @staticmethod
    def shuffled(data, seed):
        blocks = data.decode("utf-8").split("\n\n")
        head, rest = blocks[0], blocks[1:]
        random.Random(seed).shuffle(rest)
        return "\n\n".join([head] + rest).encode("utf-8")

    def test_two_runs_are_byte_identical(self):
        pots, pos = real_inputs()
        self.assertEqual(up.generate(pots, {"bg": pos}, "en", 40), up.generate(pots, {"bg": pos}, "en", 40))

    def test_shuffled_input_order_gives_the_same_bytes(self):
        pots, pos = real_inputs()
        want = up.generate(pots, {"bg": pos}, "en", 40)
        for seed in (1, 2, 3):
            got = up.generate([(n, self.shuffled(d, seed)) for n, d in pots],
                              {"bg": [(n, self.shuffled(d, seed + 10)) for n, d in pos]}, "en", 40)
            self.assertEqual(got, want)
        self.assertNotEqual(self.shuffled(pots[0][1], 1), pots[0][1])

    def test_the_command_line_is_deterministic_across_processes(self):
        argv = ["ui-pseudo", "--source-lang", "en", "--contract", CONTRACT, "--pot", DATA / "kit.pot", "--po", "bg",
                DATA / "bg" / "kit.po"]
        a, b = run_rigor(argv), run_rigor(argv)
        self.assertEqual((a.code, b.code), (0, 0), a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.stdout.encode(), (DATA / "golden" / "kit.xx.po").read_bytes())


class Golden(TempDirTestCase):
    def test_the_copy_of_the_real_catalogue_has_its_recorded_hashes(self):
        # Copied from business-apps apps/lockers/lkui/catalog/i18n at commit 996a82f (read only there).
        self.check_sums(DATA, DATA / "SHA256SUMS", 6)

    def test_the_generated_files_are_the_golden_files(self):
        self.check_sums(DATA / "golden", DATA / "GOLDEN.sha256", 3)
        pots, pos = real_inputs()
        for name, text in zip(NAMES, up.generate(pots, {"bg": pos}, "en", 40)):
            self.assertEqual(text.encode(), (DATA / "golden" / (name + ".xx.po")).read_bytes(), name)

    def check_sums(self, base, sums, count):
        lines = [line for line in sums.read_text(encoding="ascii").split("\n") if line]
        self.assertEqual(len(lines), count)
        for line in lines:
            digest, name = line.split("  ")
            self.assertEqual(hashlib.sha256((base / name.lstrip("./")).read_bytes()).hexdigest(), digest, name)

    def test_the_floor_of_the_lockers_contract_is_40(self):
        self.assertEqual(up.contract_floor(str(CONTRACT)), 40)


class WithPo2c(TempDirTestCase):
    def test_po2c_accepts_the_real_catalogue_with_the_pseudo_language(self):
        pots, bg = real_inputs()
        pseudo = [("xx-%s.po" % n, (DATA / "golden" / (n + ".xx.po")).read_bytes()) for n in NAMES]
        names = self.names(pots)
        plain = po2c.build(pots, {"bg": bg}, ["en", "bg"], "en", "lk", names)
        both = po2c.build(pots, {"bg": bg, "xx": pseudo}, ["en", "bg", "xx"], "en", "lk", names)
        self.assertEqual([m.msgid for m in both], [m.msgid for m in plain])
        for message in both:
            xx = message.texts["xx"]
            self.assertTrue(xx.startswith("[") and xx.endswith("]"))
            self.assertEqual(po2c.placeholders(xx), po2c.placeholders(message.msgid))
            if "\n" not in message.msgid:
                self.assertGreater(len(xx) - 2, len(message.texts["bg"]))

    @staticmethod
    def names(pots):
        """Enum name overrides for msgids that differ only in case (the product's BUCK has its own)."""
        groups = {}
        for path, data in pots:
            for msgid, _, _ in po2c.parse_po(path, data):
                groups.setdefault(po2c.enum_words(msgid), []).append(msgid)
        return {m: "%s_V%d" % (w, k) for w, ids in sorted(groups.items()) for k, m in enumerate(dict.fromkeys(ids)) if k}

    def test_a_file_that_po2c_refuses_is_seen_failing(self):
        pots = [("a.pot", pot("Locker {0} is open").encode())]
        bg = [("a.bg.po", po(("Locker {0} is open", "Шкаф {0}")).encode())]
        good = gen(pot("Locker {0} is open"), po(("Locker {0} is open", "Шкаф {0}")))
        with self.assertRaises(po2c.CatalogError):
            po2c.build(pots, {"bg": bg, "xx": [("x.po", good.replace("{0}", "").encode())]}, ["en", "bg", "xx"], "en", "lk")
        po2c.build(pots, {"bg": bg, "xx": [("x.po", good.encode())]}, ["en", "bg", "xx"], "en", "lk")


class CommandLine(TempDirTestCase):
    def args(self, name="c_only", contract=CONTRACT):
        return ["ui-pseudo", "--source-lang", "en", "--contract", contract, "--pot", DATA / (name + ".pot"),
                "--po", "bg", DATA / "bg" / (name + ".po")]

    def test_prints_the_po(self):
        outcome = run_rigor(self.args())
        self.assertEqual(outcome.code, 0, outcome.stderr)
        self.assertEqual(outcome.stdout.encode(), (DATA / "golden" / "c_only.xx.po").read_bytes())

    def test_extended_is_gone(self):
        self.assertEqual(run_rigor(self.args() + ["--extended"]).code, 2)

    def test_a_contract_is_required(self):
        self.assertEqual(run_rigor(["ui-pseudo", "--source-lang", "en", "--pot", DATA / "c_only.pot"]).code, 2)

    def contract_with(self, new):
        text = CONTRACT.read_text(encoding="utf-8")
        line = [x for x in text.split("\n") if x.startswith("pseudo_expansion_overall_pct")][0]
        edited = self.tmp / "contract.toml"
        edited.write_text(text.replace(line, new), encoding="utf-8")
        return edited

    def test_a_missing_or_pending_floor_is_refused_never_off(self):
        out = self.tmp / "o.po"
        pending = 'pseudo_expansion_overall_pct = { pending = "5", provenance = "literature:3.10/pseudo_expansion_overall_pct" }'
        for new in ("", pending):
            with self.subTest(new=new):
                outcome = run_rigor(self.args(contract=self.contract_with(new)) + ["--out", out])
                self.assertEqual(outcome.code, 2, outcome.stdout)
                self.assertFalse(out.exists())
                self.assertIn("UI contract", outcome.stderr)

    def test_a_refusal_is_the_house_message_without_a_traceback(self):
        bad = self.tmp / "bad.po"
        bad.write_text(po(("Hello", "")), encoding="utf-8")
        good = self.tmp / "a.pot"
        good.write_text(pot("Hello"), encoding="utf-8")
        out = self.tmp / "out.po"
        outcome = run_rigor(["ui-pseudo", "--source-lang", "en", "--contract", CONTRACT, "--pot", good, "--po", "bg", bad,
                             "--out", out])
        self.assertEqual(outcome.code, 2, outcome.stderr)
        self.assertFalse(out.exists())
        self.assertIn("refused", outcome.stderr)
        self.assertIn("po2c refuses", outcome.stderr)
        self.assertNotIn("internal error", outcome.stderr)
        self.assertNotIn("Traceback", outcome.stderr)

    def two(self, second):
        first = self.tmp / "first.po"
        argv = self.args() + ["--pot", DATA / "kit.pot", "--po", "bg", DATA / "bg" / "kit.po", "--out", first,
                              "--out", second]
        return first, run_rigor(argv)

    def test_several_pots_need_one_out_each(self):
        outcome = run_rigor(self.args() + ["--pot", DATA / "kit.pot", "--po", "bg", DATA / "bg" / "kit.po"])
        self.assertEqual(outcome.code, 2)
        self.assertIn("one --out per --pot", outcome.stderr)

    def test_writing_is_all_or_nothing(self):
        old = self.tmp / "first.po"
        old.write_bytes(b"old")
        first, outcome = self.two(self.tmp / "no-such-dir" / "second.po")
        self.assertEqual(outcome.code, 2, outcome.stderr)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["first.po"])
        self.assertEqual(old.read_bytes(), b"old")
        self.assertIn("cannot write", outcome.stderr)
        self.assertNotIn("Traceback", outcome.stderr)

    def test_all_outputs_are_written_when_all_succeed(self):
        first, outcome = self.two(self.tmp / "second.po")
        self.assertEqual(outcome.code, 0, outcome.stderr)
        self.assertEqual(first.read_bytes(), (DATA / "golden" / "c_only.xx.po").read_bytes())
        self.assertEqual((self.tmp / "second.po").read_bytes(), (DATA / "golden" / "kit.xx.po").read_bytes())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["first.po", "second.po"])
