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


def run(rules, contract, *extra):
    done = subprocess.run([sys.executable, "-I", "-B", str(TOOL), "--ui-rules", str(rules), "--contract",
                           str(contract)] + list(extra), capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout, done.stderr


class Derive(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)

    def copy(self, source, name, old=None, new=None):
        text = Path(source).read_text(encoding="utf-8")
        if old is not None:
            self.assertEqual(text.count(old), 1, old)
            text = text.replace(old, new)
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_checked_in_contract_agrees(self):
        code, out, err = run(RULES, LOCKERS, "--print")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), ["banner 0 false", "choose_size 30000 true", "dialog 8000 true",
                                            "lockout 60000 true", "opened 8000 true", "report 300000 true",
                                            "snackbar 4000 true"])

    def test_an_edited_contract_fails(self):
        for old, new in (("lifetime_ms = 30000\n", "lifetime_ms = 45000\n"),
                         ("lifetime_ms = 8000\ncountdown_shown = true\ndismiss = [\"dismiss\", \"countdown\"]",
                          "lifetime_ms = 20000\ncountdown_shown = true\ndismiss = [\"dismiss\", \"countdown\"]"),
                         ("lifetime_ms = 0\ncountdown_shown = false", "lifetime_ms = 0\ncountdown_shown = true")):
            code, _, err = run(RULES, self.copy(LOCKERS, "c.toml", old, new))
            self.assertEqual(code, 1, (old, err))
            self.assertIn("timer ", err)

    def test_a_removed_or_extra_timer_row_fails(self):
        row = ('[[timer]]\nkind = "lockout"\nclass = "screen"\nlifetime_ms = 60000\ncountdown_shown = true\n'
               'dismiss = []\nprovenance = "spec:ui-rules.md#screen-timers"\n')
        code, _, err = run(RULES, self.copy(LOCKERS, "c.toml", row, ""))
        self.assertEqual(code, 1)
        self.assertIn("timer lockout: derived from ui-rules.md but missing in the contract", err)
        extra = row.replace('"lockout"', '"toast"')
        code, _, err = run(RULES, self.copy(LOCKERS, "d.toml", row, row + extra))
        self.assertEqual(code, 1)
        self.assertIn("timer toast: in the contract but not in ui-rules.md", err)

    def test_an_edited_ui_rules_fails(self):
        rules = self.copy(RULES, "r.md", "| Opened | 8 s |", "| Opened | 10 s |")
        code, _, err = run(rules, LOCKERS)
        self.assertEqual(code, 1)
        self.assertIn("timer opened", err)

    def test_a_self_contradicting_ui_rules_is_unreadable(self):
        rules = self.copy(RULES, "r.md", "| Reservation saved snackbar | 4 s |", "| Reservation saved snackbar | 5 s |")
        code, _, err = run(rules, LOCKERS)
        self.assertEqual(code, 2)
        self.assertIn("contradicts itself", err)

    def test_an_unknown_row_or_missing_section_is_unreadable(self):
        rules = self.copy(RULES, "r.md", "| Lockout | 60 s |", "| Lockdown | 60 s |")
        self.assertEqual(run(rules, LOCKERS)[0], 2)
        rules = self.copy(RULES, "s.md", "## Screen timers", "## Screen clocks")
        self.assertEqual(run(rules, LOCKERS)[0], 2)

    def test_a_missing_file_is_unreadable(self):
        self.assertEqual(run(self.dir / "nope.md", LOCKERS)[0], 2)
        self.assertEqual(run(RULES, self.dir / "nope.toml")[0], 2)


if __name__ == "__main__":
    unittest.main()
