"""The pseudo-locale generator (`rigor_lib.ui_pseudo`, U17a): determinism, delimiters, the length rule, kept
placeholders, plural forms and contexts, refusals, and acceptance by `po2c` together with the real lockers catalogue.
"""

import hashlib
import random
import subprocess
import sys
from pathlib import Path

from rigor_lib import po2c, ui_pseudo as up
from tests.helpers import GATE_DIR, TempDirTestCase, run_rigor

DATA = Path(__file__).resolve().parent / "data" / "ui_pseudo"
HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
TALL_DEEP = set("ЙЩрущц")


def pot(*ids):
    return HEADER + "".join('msgid "%s"\nmsgstr ""\n\n' % i for i in ids)


def po(*pairs):
    return HEADER + "".join('msgid "%s"\nmsgstr "%s"\n\n' % p for p in pairs)


def gen(pot_text, bg_text, **kw):
    return up.generate([("a.pot", pot_text.encode())], {"bg": [("a.bg.po", bg_text.encode())]}, "en", **kw)[0]


def pseudo_of(msgid, bg, **kw):
    """The pseudo msgstr of one msgid, read back through the generator's own parser."""
    entries = up.parse("x.po", gen(pot(msgid), po((msgid, bg)), **kw).encode())
    return entries[0].strs[0]


class Length(TempDirTestCase):
    def test_table_rows(self):
        got = [(n, up.ibm_percent(n)) for n in (1, 10, 11, 20, 21, 30, 31, 50, 51, 70, 71, 500)]
        self.assertEqual(got, [(1, 300), (10, 300), (11, 200), (20, 200), (21, 180), (30, 180), (31, 160), (50, 160),
                               (51, 140), (70, 140), (71, 130), (500, 130)])

    def test_boundary_10_and_11(self):
        self.assertEqual(len(pseudo_of("a" * 10, "б")), 30)
        self.assertEqual(len(pseudo_of("a" * 11, "б")), 22)

    def test_boundary_70_and_71(self):
        self.assertEqual(len(pseudo_of("ab " * 23 + "a", "б")), 98)   # 70 characters
        self.assertEqual(len(pseudo_of("ab " * 23 + "ab", "б")), 93)  # 71 characters, 71 * 1.3 rounded up

    def test_the_longer_bulgarian_string_wins(self):
        self.assertEqual(len(pseudo_of("Small", "Б" * 40)), 40)
        self.assertEqual(len(pseudo_of("Small", "Б" * 15)), 15)   # table: 5 * 3 = 15
        self.assertEqual(len(pseudo_of("Small", "Б" * 14)), 15)

    def test_the_longest_of_several_languages_wins(self):
        texts = up.generate([("a.pot", pot("Small").encode())],
                            {"bg": [("a.bg.po", po(("Small", "Б" * 20)).encode())],
                             "de": [("a.de.po", po(("Small", "x" * 33)).encode())]}, "en")
        self.assertEqual(len(up.parse("x", texts[0].encode())[0].strs[0]), 33)

    def test_the_contract_floor(self):
        # 200-character sentence: table 130% = 260; floor 40% = 280; floor 20% = 240 < 260.
        msgid = ("word " * 40).strip() + "."   # 200 characters
        self.assertEqual(len(msgid), 200)
        self.assertEqual(len(pseudo_of(msgid, "б")), 260)
        self.assertEqual(len(pseudo_of(msgid, "б", overall_pct=40)), 280)
        self.assertEqual(len(pseudo_of(msgid, "б", overall_pct=20)), 260)

    def test_target_length_is_a_pure_function(self):
        self.assertEqual(up.target_length("x" * 10, [0]), 30)
        self.assertEqual(up.target_length("x" * 10, [31]), 31)
        self.assertEqual(up.target_length("x" * 10, [0], 400), 50)


class Content(TempDirTestCase):
    def test_every_pseudo_string_starts_and_ends_with_the_delimiters(self):
        data = DATA
        pots = [(str(data / n), (data / n).read_bytes()) for n in ("lockers.pot", "kit.pot", "c_only.pot")]
        pos = {"bg": [(str(data / "bg" / n), (data / "bg" / n).read_bytes())
                      for n in ("lockers.po", "kit.po", "c_only.po")]}
        outs = up.generate(pots, pos, "en", overall_pct=40)
        count = 0
        for text in outs:
            for entry in up.parse("x", text.encode()):
                value = entry.strs[0]
                self.assertTrue(value.startswith(up.START) and value.endswith(up.END), value)
                count += 1
        self.assertGreater(count, 100)

    def test_padding_uses_the_tallest_and_deepest_glyphs(self):
        value = pseudo_of("Choose a size for the locker", "Изберете размер")
        body = value[1:-1].replace(" ", "")
        self.assertTrue(set(body) <= set(up.PADDING))
        self.assertTrue(TALL_DEEP <= set(body))
        self.assertTrue(set(up.PADDING) >= TALL_DEEP)

    def test_padding_words_wrap(self):
        value = pseudo_of("Choose a size for the locker", "Изберете размер")
        self.assertTrue(all(len(w) <= up.WORD + 2 for w in value.split(" ")))
        self.assertGreater(value.count(" "), 3)

    def test_no_space_next_to_a_delimiter(self):
        for n in range(1, 40):
            value = pseudo_of("x" * n, "б")
            self.assertNotIn(" " + up.END, value)
            self.assertNotIn(up.START + " ", value)

    def test_line_breaks_are_kept(self):
        value = pseudo_of("First line\\nSecond line\\n\\nFourth", "Първи\\nВтори\\n\\nЧетвърти")
        self.assertEqual(value.count("\n"), 3)
        lines = value.split("\n")
        self.assertEqual(lines[2], "")
        self.assertTrue(lines[0].startswith(up.START) and lines[-1].endswith(up.END))
        self.assertGreater(len(value), len("First line\nSecond line\n\nFourth"))

    def test_the_header_names_the_language(self):
        text = gen(pot("a"), po(("a", "б")))
        self.assertIn('"Language: xx\\n"', text)
        self.assertIn('"Language: yy\\n"', gen(pot("a"), po(("a", "б")), lang="yy"))


class Placeholders(TempDirTestCase):
    def tokens(self, text):
        return up.tokens_of(text, up.TOKEN)

    def test_kept_in_count_and_order(self):
        for msgid, bg in (("Locker {0} is open", "Шкаф {0} е отворен"), ("Ended {0}:{1} UTC", "Край {0}:{1} UTC"),
                          ("{1} and {0}", "{1} и {0}"), ("Sync: {0} {0}", "Синхр.: {0} {0}"),
                          ("Braces {{ and }} {0}", "Скоби {{ и }} {0}")):
            with self.subTest(msgid=msgid):
                value = pseudo_of(msgid, bg)
                self.assertEqual(self.tokens(value), self.tokens(msgid))

    def test_a_placeholder_in_the_pot_that_the_generator_would_drop_is_seen_failing(self):
        original = up.pseudo_text

        def dropping(msgid, want, token=up.TOKEN):
            return original(msgid, want, token).replace("{0}", "")
        up.pseudo_text = dropping
        try:
            with self.assertRaises(up.PseudoError) as caught:
                gen(pot("Locker {0} is open"), po(("Locker {0} is open", "Шкаф {0}")))
        finally:
            up.pseudo_text = original
        self.assertIn("placeholders", str(caught.exception))

    def test_a_swapped_order_is_seen_failing(self):
        entry = up.parse("x", pot("{0} then {1}").encode())[0]
        with self.assertRaises(up.PseudoError):
            up.check_kept(entry, {0: "[{1} ЙщрЩу {0}]"}, up.TOKEN)

    def test_a_dropped_line_break_is_seen_failing(self):
        entry = up.parse("x", pot("a\\nb").encode())[0]
        with self.assertRaises(up.PseudoError):
            up.check_kept(entry, {0: "[ЙщрЩ]"}, up.TOKEN)

    def test_a_placeholder_only_msgid_is_refused(self):
        for msgid in ("{0}", "{0} {1}", "{0}\\n{1}"):
            with self.subTest(msgid=msgid):
                with self.assertRaises(up.PseudoError) as caught:
                    gen(pot(msgid), po((msgid, msgid)))
                self.assertIn("nothing but placeholders", str(caught.exception))

    def test_printf_and_named_placeholders_in_extended_mode(self):
        msgid = "Found %d of %s in {name}, 100%%"
        value = pseudo_of(msgid, "Намерени %d от %s в {name}, 100%%", extended=True)
        self.assertEqual(up.tokens_of(value, up.TOKEN), ["%d", "%s", "{name}", "%%"])


class Extended(TempDirTestCase):
    POT = ('msgctxt "menu"\nmsgid "Open"\nmsgstr ""\n\nmsgctxt "verb"\nmsgid "Open"\nmsgstr ""\n\n'
           'msgid "One locker"\nmsgid_plural "%d lockers"\nmsgstr[0] ""\nmsgstr[1] ""\n\n')
    BG = ('msgctxt "menu"\nmsgid "Open"\nmsgstr "Отвори менюто"\n\nmsgctxt "verb"\nmsgid "Open"\nmsgstr "Отвори"\n\n'
          'msgid "One locker"\nmsgid_plural "%d lockers"\nmsgstr[0] "Един шкаф"\nmsgstr[1] "%d шкафа"\n'
          'msgstr[2] "%d шкафчета за деца"\n\n')

    def run_ext(self):
        return gen(HEADER + self.POT, HEADER + self.BG, extended=True)

    def test_plural_forms_get_one_string_each(self):
        entries = {(e.ctx, e.msgid): e for e in up.parse("x", self.run_ext().encode())}
        one = entries[(None, "One locker")]
        self.assertEqual(sorted(one.strs), [0, 1, 2])
        self.assertEqual(one.plural, "%d lockers")
        self.assertTrue(all(s.startswith("[") and s.endswith("]") for s in one.strs.values()))
        self.assertEqual(up.tokens_of(one.strs[1], up.TOKEN), ["%d"])
        self.assertEqual(up.tokens_of(one.strs[2], up.TOKEN), ["%d"])
        self.assertEqual(up.tokens_of(one.strs[0], up.TOKEN), [])
        self.assertGreaterEqual(len(one.strs[2]), len("%d шкафчета за деца"))   # the longest real form

    def test_msgctxt_is_kept_and_keeps_entries_apart(self):
        entries = up.parse("x", self.run_ext().encode())
        self.assertEqual(sorted(((e.ctx or "", e.msgid) for e in entries)), [("", "One locker"), ("menu", "Open"),
                                                                    ("verb", "Open")])
        by_ctx = {e.ctx: e.strs[0] for e in entries}
        self.assertGreaterEqual(len(by_ctx["menu"]), len("Отвори менюто"))

    def test_strict_mode_refuses_what_po2c_refuses(self):
        for text in (self.POT,):
            with self.assertRaises(up.PseudoError) as caught:
                gen(HEADER + text, HEADER + self.BG)
            self.assertIn("po2c refuses", str(caught.exception))


class Determinism(TempDirTestCase):
    def read_all(self):
        names = ("lockers", "kit", "c_only")
        pots = [(n + ".pot", (DATA / (n + ".pot")).read_bytes()) for n in names]
        pos = [(n + ".po", (DATA / "bg" / (n + ".po")).read_bytes()) for n in names]
        return pots, pos

    @staticmethod
    def shuffled(data, seed):
        blocks = data.decode("utf-8").split("\n\n")
        head, rest = blocks[0], blocks[1:]
        random.Random(seed).shuffle(rest)
        return "\n\n".join([head] + rest).encode("utf-8")

    def test_two_runs_are_byte_identical(self):
        pots, pos = self.read_all()
        first = up.generate(pots, {"bg": pos}, "en", overall_pct=40)
        second = up.generate(pots, {"bg": pos}, "en", overall_pct=40)
        self.assertEqual([t.encode() for t in first], [t.encode() for t in second])

    def test_shuffled_input_order_gives_the_same_bytes(self):
        pots, pos = self.read_all()
        want = [t.encode() for t in up.generate(pots, {"bg": pos}, "en")]
        for seed in (1, 2, 3):
            shuffled_pots = [(n, self.shuffled(d, seed)) for n, d in pots]
            shuffled_pos = [(n, self.shuffled(d, seed + 10)) for n, d in pos]
            got = [t.encode() for t in up.generate(shuffled_pots, {"bg": shuffled_pos}, "en")]
            self.assertEqual(got, want)

    def test_the_shuffle_really_reorders(self):
        pots, _ = self.read_all()
        self.assertNotEqual(self.shuffled(pots[0][1], 1), pots[0][1])

    def test_the_command_line_is_deterministic_across_processes(self):
        args = ["--source-lang", "en", "--pot", str(DATA / "kit.pot"), "--po", "bg", str(DATA / "bg" / "kit.po")]
        argv = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "ui_pseudo.py")] + args
        a = subprocess.run(argv, capture_output=True, timeout=60)
        b = subprocess.run(argv, capture_output=True, timeout=60)
        self.assertEqual((a.returncode, b.returncode), (0, 0))
        self.assertEqual(a.stdout, b.stdout)
        self.assertGreater(len(a.stdout), 1000)


class WithPo2c(TempDirTestCase):
    def test_the_copy_of_the_real_catalogue_has_its_recorded_hashes(self):
        # Copied from business-apps apps/lockers/lkui/catalog/i18n at commit 996a82f (read only there).
        sums = (DATA / "SHA256SUMS").read_text(encoding="ascii").split("\n")
        recorded = {line.split("  ")[1][2:]: line.split("  ")[0] for line in sums if line}
        self.assertEqual(sorted(recorded), ["bg/c_only.po", "bg/kit.po", "bg/lockers.po", "c_only.pot", "kit.pot",
                                            "lockers.pot"])
        for name, digest in recorded.items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), digest, name)

    def test_po2c_accepts_the_real_catalogue_with_the_pseudo_language(self):
        names = ("lockers", "kit", "c_only")
        pots = [(n + ".pot", (DATA / (n + ".pot")).read_bytes()) for n in names]
        bg = [(n + ".po", (DATA / "bg" / (n + ".po")).read_bytes()) for n in names]
        pseudo = [("xx-%s.po" % n, t.encode()) for n, t in zip(names, up.generate(pots, {"bg": bg}, "en", "xx", 40))]
        # The real product resolves enum name collisions with names=; the same two entries here.
        plain = po2c.build(pots, {"bg": bg}, ["en", "bg"], "en", "lk", self.names(pots, bg))
        both = po2c.build(pots, {"bg": bg, "xx": pseudo}, ["en", "bg", "xx"], "en", "lk", self.names(pots, bg))
        self.assertEqual([m.msgid for m in both], [m.msgid for m in plain])
        for message in both:
            xx = message.texts["xx"]
            self.assertTrue(xx.startswith("[") and xx.endswith("]"))
            self.assertEqual(po2c.placeholders(xx), po2c.placeholders(message.msgid))
            self.assertGreaterEqual(len(xx), len(message.texts["bg"]))
            self.assertGreaterEqual(len(xx), up.ceil_percent(len(message.msgid), up.ibm_percent(len(message.msgid))))

    @staticmethod
    def names(pots, bg):
        """Enum name overrides for msgids that differ only in case or punctuation (the product's BUCK has its own):
        every msgid of a colliding group but the first gets a numbered name."""
        groups = {}
        for path, data in pots:
            for msgid, _, _ in po2c.parse_po(path, data):
                groups.setdefault(po2c.enum_words(msgid), []).append(msgid)
        out = {}
        for words, ids in sorted(groups.items()):
            for k, msgid in enumerate(dict.fromkeys(ids)):
                if k:
                    out[msgid] = "%s_V%d" % (words, k)
        return out

    def test_a_generated_file_that_po2c_refuses_is_seen_failing(self):
        pots = [("a.pot", pot("Locker {0} is open").encode())]
        bg = [("a.bg.po", po(("Locker {0} is open", "Шкаф {0}")).encode())]
        good = up.generate(pots, {"bg": bg}, "en")[0]
        broken = good.replace("{0}", "")
        with self.assertRaises(po2c.CatalogError):
            po2c.build(pots, {"bg": bg, "xx": [("x.po", broken.encode())]}, ["en", "bg", "xx"], "en", "lk")
        po2c.build(pots, {"bg": bg, "xx": [("x.po", good.encode())]}, ["en", "bg", "xx"], "en", "lk")


class Refusals(TempDirTestCase):
    def refused(self, pot_text, bg_text, *needles):
        with self.assertRaises(up.PseudoError) as caught:
            gen(pot_text, bg_text)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))

    def test_what_po2c_refuses_is_refused(self):
        self.refused(pot("Hello"), po(("Hello", "")), "po2c refuses", "Hello")
        self.refused(pot("Hello {0}"), po(("Hello {0}", "Здравей")), "po2c refuses", "placeholders")
        self.refused(pot("Hello {"), po(("Hello {", "Здравей {")), "po2c refuses", "malformed")
        self.refused(pot("Hello"), HEADER.replace("UTF-8", "ISO-8859-1") + 'msgid "Hello"\nmsgstr "x"\n', "charset")
        self.refused(pot("Hello"), po(("Hello", "x")) + 'msgid "Hello"\nmsgstr "y"\n', "repeated")
        self.refused(pot("Hello"), po(("Other", "x")), "not in")
        self.refused(pot("Hello"), "#, fuzzy\n" + po(("Hello", "x")), "fuzzy")

    def test_a_pseudo_language_that_clashes_is_refused(self):
        with self.assertRaises(up.PseudoError):
            gen(pot("a"), po(("a", "б")), lang="bg")

    def test_the_command_line_exits_2_without_an_output_file(self):
        out = self.tmp / "out.po"
        bad = self.tmp / "bad.po"
        bad.write_text(po(("Hello", "")), encoding="utf-8")
        good = self.tmp / "a.pot"
        good.write_text(pot("Hello"), encoding="utf-8")
        outcome = run_rigor(["ui-pseudo", "--source-lang", "en", "--pot", good, "--po", "bg", bad, "--out", out])
        self.assertEqual(outcome.code, 2, outcome.stderr)
        self.assertFalse(out.exists())
        self.assertIn("po2c refuses", outcome.stderr)

    def test_the_command_line_prints_the_po(self):
        outcome = run_rigor(["ui-pseudo", "--source-lang", "en", "--pot", DATA / "c_only.pot", "--po", "bg",
                             DATA / "bg" / "c_only.po"])
        self.assertEqual(outcome.code, 0, outcome.stderr)
        self.assertIn('"Language: xx\\n"', outcome.stdout)
        self.assertIn("Digits entered: {0}", outcome.stdout)
        self.assertEqual(outcome.stdout.encode("utf-8"), gen_real("c_only").encode("utf-8"))

    def test_several_pots_need_one_out_each(self):
        outcome = run_rigor(["ui-pseudo", "--source-lang", "en", "--pot", DATA / "c_only.pot", "--pot",
                             DATA / "kit.pot", "--po", "bg", DATA / "bg" / "c_only.po", "--po", "bg",
                             DATA / "bg" / "kit.po"])
        self.assertEqual(outcome.code, 2)
        self.assertIn("one --out per --pot", outcome.stderr)


def gen_real(name):
    return up.generate([(name, (DATA / (name + ".pot")).read_bytes())],
                       {"bg": [(name, (DATA / "bg" / (name + ".po")).read_bytes())]}, "en")[0]
