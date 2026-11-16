"""`gate/tools/ui_contract_derive.py`: the timers re-derived from ui-rules.md against the checked-in contract."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent
REPO = GATE.parent
TOOL = GATE / "tools" / "ui_contract_derive.py"
RULES = GATE / "tests" / "data" / "ui_contract" / "ui-rules.md"
LOCKERS = REPO / "products" / "business-apps" / "ui" / "lockers.toml"
CATALOGUE_DIALOG = "| Dialog | Pad | Clear the dialog | 8 s |"


def run(rules, contract, *extra):
    done = subprocess.run([sys.executable, "-I", "-B", str(TOOL), "--ui-rules", str(rules), "--contract",
                           str(contract)] + list(extra), capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout, done.stderr


class Derive(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)

    def copy(self, source, name, old=None, new=None, count=1):
        text = Path(source).read_text(encoding="utf-8")
        if old is not None:
            self.assertGreaterEqual(text.count(old), 1, old)
            if count == 1:
                self.assertEqual(text.count(old), 1, old)
            text = text.replace(old, new, 1 if count == "first" else -1)
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_checked_in_contract_agrees(self):
        code, out, err = run(RULES, LOCKERS, "--print")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "banner message 0 false dismiss", "choose_size screen 30000 true cancel,countdown",
            "dialog message 8000 true dismiss,countdown", "lockout screen 60000 true -",
            "opened screen 8000 true done,countdown", "report screen 300000 true done,countdown",
            "snackbar message 4000 true dismiss,tap-outside,countdown"])

    def test_an_edited_contract_fails_on_every_derived_field(self):
        for old, new in (("lifetime_ms = 30000\n", "lifetime_ms = 45000\n"),
                         ('kind = "choose_size"\nclass = "screen"', 'kind = "choose_size"\nclass = "message"'),
                         ('kind = "dialog"\nclass = "message"', 'kind = "dialog"\nclass = "screen"'),
                         ('dismiss = ["cancel", "countdown"]', 'dismiss = ["cancel"]'),
                         ('dismiss = ["cancel", "countdown"]', 'dismiss = ["countdown", "cancel"]'),
                         ('dismiss = ["dismiss", "tap-outside", "countdown"]', 'dismiss = ["dismiss", "countdown"]'),
                         ('dismiss = []\nprovenance = "spec:ui-rules.md#screen-timers"',
                          'dismiss = ["done"]\nprovenance = "spec:ui-rules.md#screen-timers"'),
                         ("lifetime_ms = 0\ncountdown_shown = false", "lifetime_ms = 5\ncountdown_shown = true"),
                         ("lifetime_ms = 8000\ncountdown_shown = true\ndismiss = [\"dismiss\", \"countdown\"]",
                          "lifetime_ms = 20000\ncountdown_shown = true\ndismiss = [\"dismiss\", \"countdown\"]")):
            code, _, err = run(RULES, self.copy(LOCKERS, "c.toml", old, new))
            self.assertEqual(code, 1, (old, err))
            self.assertIn("timer ", err)

    def test_a_removed_or_extra_timer_row_fails(self):
        row = ('[[timer]]\nkind = "lockout"\nclass = "screen"\nlifetime_ms = 60000\ncountdown_shown = true\n'
               'dismiss = []\nprovenance = "spec:ui-rules.md#screen-timers"\n')
        code, _, err = run(RULES, self.copy(LOCKERS, "c.toml", row, ""))
        self.assertEqual(code, 1)
        self.assertIn("timer lockout: derived from ui-rules.md but missing in the contract", err)
        code, _, err = run(RULES, self.copy(LOCKERS, "d.toml", row, row + row.replace('"lockout"', '"toast"')))
        self.assertEqual(code, 1)
        self.assertIn("timer toast: in the contract but not in ui-rules.md", err)

    def test_an_edited_ui_rules_fails(self):
        for old, new in (("| Opened | 8 s |", "| Opened | 10 s |"),
                         ("**Done**, or the countdown. Returns to the pad.", "**Done**. Returns to the pad."),
                         ("**Cancel**, or the countdown.", "**Cancel**, **Back**, or the countdown."),
                         ("| Opened | 8 s | Countdown on the opened screen.", "| Opened | 8 s | A clock on the opened screen.")):
            code, _, err = run(self.copy(RULES, "r.md", old, new), LOCKERS)
            self.assertEqual(code, 1, (old, err))
            self.assertIn("timer ", err)

    def unreadable(self, rules, fragment):
        code, out, err = run(rules, LOCKERS)
        self.assertEqual(code, 2, err)
        self.assertIn(fragment, err)
        self.assertNotIn("Traceback", err)

    def test_a_dropped_row_is_unreadable_not_ignored(self):
        # A catalogue row with a cell missing used to be dropped silently.
        self.unreadable(self.copy(RULES, "a.md", CATALOGUE_DIALOG, "| Dialog | Pad | Clear the dialog |", "first"),
                        "a row has 4 cells, not 5")
        self.unreadable(self.copy(RULES, "b.md", CATALOGUE_DIALOG, CATALOGUE_DIALOG + " extra |", "first"),
                        "a row has 6 cells, not 5")
        lockout = "| Lockout | 60 s | Countdown on the wait screen. | None. The pad and the scanner do nothing until the countdown ends. |"
        self.unreadable(self.copy(RULES, "c.md", lockout, "| Lockout | 60 s | Countdown on the wait screen. |"),
                        "a row has 3 cells, not 4")

    def test_an_escaped_pipe_is_refused(self):
        self.unreadable(self.copy(RULES, "a.md", "Clear the dialog | 8 s |", "Clear the \\| dialog | 8 s |", "first"),
                        "escaped pipe")

    def test_an_unknown_kind_is_unreadable_not_ignored(self):
        self.unreadable(self.copy(RULES, "a.md", CATALOGUE_DIALOG, "| Toast | Pad | Clear the dialog | 8 s |", "first"),
                        "unknown kind 'Toast'")

    def test_the_named_not_a_notice_row_is_accepted(self):
        text = RULES.read_text(encoding="utf-8")
        self.assertIn("Part of the report screen, not a notice", text)
        self.assertEqual(run(RULES, LOCKERS)[0], 0)

    def test_a_catalogue_row_without_a_dismiss_intent_is_unreadable(self):
        self.unreadable(self.copy(RULES, "a.md", CATALOGUE_DIALOG, "| Dialog | Pad | None | 8 s |", "first"), "no dismiss intent")

    def test_a_duplicate_or_unknown_screen_timer_row_is_unreadable(self):
        row = "| Opened | 8 s | Countdown on the opened screen. | **Done**, or the countdown. Returns to the pad. |"
        self.unreadable(self.copy(RULES, "a.md", row, row + "\n" + row), "duplicate row for opened")
        self.unreadable(self.copy(RULES, "b.md", "| Lockout | 60 s |", "| Lockdown | 60 s |"), "unknown row 'Lockdown'")

    def test_a_missing_row_header_or_section_is_unreadable(self):
        self.unreadable(self.copy(RULES, "a.md", "| Lockout | 60 s | Countdown on the wait screen. | None. The pad and the scanner do nothing until the countdown ends. |\n", ""), "rows missing")
        self.unreadable(self.copy(RULES, "b.md", "## Screen timers", "## Screen clocks"), "exactly one section")
        self.unreadable(self.copy(RULES, "c.md", "| Screen or notice | Limit |", "| Screen | Limit |"), "no table with the header")

    def test_a_self_contradicting_ui_rules_is_unreadable(self):
        self.unreadable(self.copy(RULES, "a.md", "| Reservation saved snackbar | 4 s |", "| Reservation saved snackbar | 5 s |"),
                        "contradicts itself")

    def test_a_missing_file_is_unreadable(self):
        self.assertEqual(run(self.dir / "nope.md", LOCKERS)[0], 2)
        self.assertEqual(run(RULES, self.dir / "nope.toml")[0], 2)


if __name__ == "__main__":
    unittest.main()
