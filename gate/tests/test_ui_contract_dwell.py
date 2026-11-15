"""The dwell table of the UI contract: reading time from the word count at the contract's reading rate."""

import unittest
from pathlib import Path

from rigor_lib import ui_contract as uc

LOCKERS = Path(__file__).resolve().parent.parent.parent / "products" / "business-apps" / "ui" / "lockers.toml"
TEXT = LOCKERS.read_text(encoding="utf-8")
RATE = 'rate_wpm = { pending = "11", provenance = "spec:P004#11-q11" }'
LONG = " ".join(["дума"] * 40)


def with_rate(wpm):
    assert RATE in TEXT
    return uc.loads(TEXT.replace(RATE, 'rate_wpm = { value = %s, provenance = "owner:Q11" }' % wpm))


class Dwell(unittest.TestCase):
    def test_the_pending_rate_stops_the_table(self):
        with self.assertRaises(uc.ContractPending) as caught:
            uc.dwell_table(uc.load(LOCKERS), [("m", "en", "dialog", "Hi")])
        self.assertEqual((caught.exception.path, caught.exception.question), ("reading.rate_wpm", "11"))

    def test_reading_time_and_minimum_dwell(self):
        rows = uc.dwell_table(with_rate(175), [("m.short", "en", "snackbar", "Reservation saved."),
                                               ("m.long", "bg", "snackbar", LONG)])
        by = {r["msgid"]: r for r in rows}
        self.assertEqual((by["m.short"]["words"], by["m.short"]["reading_ms"]), (2, 686))
        self.assertEqual(by["m.short"]["min_dwell_ms"], 3500)   # the 3.5 s floor wins over 1 s + reading
        self.assertEqual((by["m.long"]["words"], by["m.long"]["reading_ms"]), (40, 13715))
        self.assertEqual(by["m.long"]["min_dwell_ms"], 14715)
        self.assertEqual(by["m.long"]["lifetime_ms"], 4000)

    def test_a_slower_rate_lengthens_the_reading_time(self):
        slow = uc.dwell_table(with_rate(130), [("m", "en", "dialog", LONG)])[0]
        fast = uc.dwell_table(with_rate(175), [("m", "en", "dialog", LONG)])[0]
        self.assertGreater(slow["reading_ms"], fast["reading_ms"])

    def test_a_timer_shorter_than_the_reading_time_is_found(self):
        rows = uc.dwell_table(with_rate(175), [("m.long", "bg", "snackbar", LONG),
                                               ("m.dialog", "bg", "dialog", LONG),
                                               ("m.ok", "en", "dialog", "That code is not recognised.")])
        found = uc.dwell_findings(rows)
        self.assertEqual([(f["rule"], f["msgid"], f["kind"], f["lifetime_ms"], f["min_dwell_ms"]) for f in found],
                         [("dwell-below-reading-time", "m.dialog", "dialog", 8000, 14715),
                          ("dwell-below-reading-time", "m.long", "snackbar", 4000, 14715)])

    def test_an_untimed_banner_is_never_short(self):
        rows = uc.dwell_table(with_rate(175), [("m.banner", "en", "banner", LONG)])
        self.assertEqual(rows[0]["lifetime_ms"], 0)
        self.assertEqual(uc.dwell_findings(rows), [])

    def test_a_kind_without_a_timer_is_contract_incomplete(self):
        rows = uc.dwell_table(with_rate(175), [("m", "en", "toast", "Hi")])
        found = uc.dwell_findings(rows)
        self.assertEqual([(f["rule"], f["what"], f["name"]) for f in found],
                         [("contract-incomplete", "timer-kind", "toast")])


if __name__ == "__main__":
    unittest.main()
