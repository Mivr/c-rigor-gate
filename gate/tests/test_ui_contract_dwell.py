"""The dwell table of the UI contract: reading time from the characters as displayed (P004 3.10)."""

import unittest
from pathlib import Path

from rigor_lib import ui_contract as uc
from rigor_lib.errors import InternalError

LOCKERS = Path(__file__).resolve().parent.parent.parent / "products" / "business-apps" / "ui" / "lockers.toml"
TEXT = LOCKERS.read_text(encoding="utf-8")
RATE = 'rate_wpm = { pending = "11", provenance = "spec:P004#11-q11" }'
KIOSK_BUSY = "Киоскът е зает: друг процес държи ключа на релето; само един киоск може да управлява таблото."
DIALOG = "lifetime_ms = 8000\ncountdown_shown = true\ndismiss = [\"dismiss\", \"countdown\"]"


def with_rate(wpm, text=TEXT):
    assert RATE in text
    return uc.loads(text.replace(RATE, 'rate_wpm = { value = %s, provenance = "owner:Q11" }' % wpm))


def msg(msgid, text, kind="dialog", lang="en", **extra):
    item = {"msgid": msgid, "lang": lang, "kind": kind, "text": text}
    item.update(extra)
    return item


class Dwell(unittest.TestCase):
    def test_the_pending_rate_stops_the_table(self):
        with self.assertRaises(uc.ContractPending) as caught:
            uc.dwell_table(uc.load(LOCKERS), [msg("m", "Hi")])
        self.assertEqual((caught.exception.path, caught.exception.question), ("reading.rate_wpm", "11"))

    def test_the_p004_example(self):
        # P004 3.10: a 45-character message is 3.8 s at 175 wpm and 4.7 s at 130 wpm.
        text = "x" * 45
        fast = uc.dwell_table(with_rate(175), [msg("m", text)])[0]
        slow = uc.dwell_table(with_rate(130), [msg("m", text)])[0]
        self.assertEqual((fast["chars"], fast["reading_ms"], fast["min_dwell_ms"]), (45, 2756, 3756))
        self.assertEqual((slow["reading_ms"], slow["min_dwell_ms"]), (3709, 4709))

    def test_the_constant_chars_per_word_is_used(self):
        other = TEXT.replace('{ value = 5.6, provenance = "design:P004#3.10-dwell_chars_per_word" }',
                             '{ value = 7, provenance = "design:P004#3.10-dwell_chars_per_word" }')
        self.assertNotEqual(other, TEXT)
        row = uc.dwell_table(with_rate(175, other), [msg("m", "x" * 45)])[0]
        self.assertEqual(row["reading_ms"], 2205)   # 45 * 60 / (175 * 7) s, rounded up

    def test_the_floor_wins_for_a_short_text_and_the_base_is_added(self):
        row = uc.dwell_table(with_rate(175), [msg("m", "Reservation saved.", "snackbar")])[0]
        self.assertEqual((row["chars"], row["reading_ms"], row["min_dwell_ms"], row["lifetime_ms"]), (18, 1103, 3500, 4000))

    def test_cyrillic_is_counted_in_characters(self):
        self.assertEqual(len(KIOSK_BUSY), 93)
        row = uc.dwell_table(with_rate(130), [msg("fault", KIOSK_BUSY, lang="bg")])[0]
        self.assertEqual((row["chars"], row["reading_ms"], row["min_dwell_ms"]), (93, 7665, 8665))

    def test_characters_find_what_a_word_count_would_not(self):
        # The Bulgarian staff sentence has 16 words: a word count at 130 wpm gives 1000 + 7385 = 8385 ms.
        self.assertEqual(len(KIOSK_BUSY.split()), 16)
        contract = with_rate(130, TEXT.replace(DIALOG, DIALOG.replace("8000", "8500")))
        found = uc.dwell_findings(uc.dwell_table(contract, [msg("fault", KIOSK_BUSY, lang="bg")]))
        self.assertEqual([(f["rule"], f["lifetime_ms"], f["min_dwell_ms"]) for f in found],
                         [("dwell-below-reading-time", 8500, 8665)])

    def test_a_lifetime_equal_to_the_minimum_is_fine_and_one_ms_below_is_not(self):
        minimum = uc.dwell_table(with_rate(130), [msg("fault", KIOSK_BUSY, lang="bg")])[0]["min_dwell_ms"]
        for lifetime, count in ((minimum, 0), (minimum - 1, 1), (minimum + 1, 0)):
            contract = with_rate(130, TEXT.replace(DIALOG, DIALOG.replace("8000", str(lifetime))))
            found = uc.dwell_findings(uc.dwell_table(contract, [msg("fault", KIOSK_BUSY, lang="bg")]))
            self.assertEqual(len(found), count, lifetime)

    def test_dialogs_at_eight_seconds(self):
        rows = uc.dwell_table(with_rate(175), [msg("m.ok", "That code is not recognised."),
                                               msg("m.long", "x" * 120)])
        self.assertEqual([f["msgid"] for f in uc.dwell_findings(rows)], ["m.long"])

    def test_an_untimed_banner_is_never_short(self):
        rows = uc.dwell_table(with_rate(175), [msg("m.banner", "x" * 500, "banner")])
        self.assertEqual(rows[0]["lifetime_ms"], 0)
        self.assertEqual(uc.dwell_findings(rows), [])

    def test_placeholders_need_their_longest_expansion(self):
        contract = with_rate(175)
        row = uc.dwell_table(contract, [msg("m", "Locker {0}: ask staff.", max_expansion={"{0}": "123456"})])[0]
        self.assertEqual(row["chars"], len("Locker 123456: ask staff."))
        with self.assertRaises(InternalError) as caught:
            uc.dwell_table(contract, [msg("m", "Locker {0}: ask staff.")])
        self.assertIn("{0}", str(caught.exception))
        with self.assertRaises(InternalError):
            uc.dwell_table(contract, [msg("m", "Locker {0} of {1}", max_expansion={"{0}": "12"})])
        with self.assertRaises(InternalError):
            uc.dwell_table(contract, [msg("m", "No placeholder.", max_expansion={"{0}": "12"})])
        with self.assertRaises(InternalError):
            uc.dwell_table(contract, [msg("m", "Locker {0}", max_expansion={"{0}": "{1}"})])
        with self.assertRaises(InternalError):
            uc.dwell_table(contract, [msg("m", "Locker {0}", max_expansion={"{0}": ""})])
        with self.assertRaises(InternalError):
            uc.dwell_table(contract, [msg("m", "Locker {0}", max_expansion="12")])

    def test_a_malformed_message_is_the_house_error(self):
        contract = with_rate(175)
        for bad in ({"msgid": "m", "lang": "en", "kind": "dialog"}, msg("m", None), msg("m", ""), msg("m", "   "),
                    msg("", "x"), dict(msg("m", "x"), extra=1), "text", None, (1, 2, 3, 4)):
            with self.assertRaises(InternalError, msg=repr(bad)):
                uc.dwell_table(contract, [bad])

    def test_a_duplicate_message_is_an_error(self):
        with self.assertRaises(InternalError) as caught:
            uc.dwell_table(with_rate(175), [msg("m", "a"), msg("m", "b")])
        self.assertIn("duplicate message", str(caught.exception))
        self.assertEqual(len(uc.dwell_table(with_rate(175), [msg("m", "a"), msg("m", "b", lang="bg")])), 2)

    def test_one_contract_incomplete_per_missing_kind(self):
        rows = uc.dwell_table(with_rate(175), [msg("a", "Hi", "toast"), msg("b", "Hi", "toast"), msg("c", "Hi", "hint")])
        found = uc.dwell_findings(rows)
        self.assertEqual([(f["rule"], f["what"], f["name"]) for f in found],
                         [("contract-incomplete", "timer-kind", "hint"), ("contract-incomplete", "timer-kind", "toast")])

    def test_the_table_is_immutable(self):
        rows = uc.dwell_table(with_rate(175), [msg("a", "Hi")])
        self.assertIsInstance(rows, tuple)
        with self.assertRaises(TypeError):
            rows[0]["chars"] = 1

    def test_reading_ms_is_exact(self):
        self.assertEqual(uc.reading_ms(0, 175, 5.6), 0)
        self.assertEqual(uc.reading_ms(980, 100, 5.6), 105000)   # 980 chars at 560 chars/min is 105 s exactly
        self.assertEqual(uc.reading_ms(981, 100, 5.6), 105108)   # 105107.14 rounded up


if __name__ == "__main__":
    unittest.main()
