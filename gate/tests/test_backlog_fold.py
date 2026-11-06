"""Tests for tools/backlog_fold.py (T047): fold, --check, and the format's refusals."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "backlog_fold.py"
HEADER = "# T\n\n| # | Gap | Found by | Planned fix |\n|---|---|---|---|\n"


def run(*args):
    return subprocess.run([sys.executable, "-I", "-B", str(TOOL), *args], capture_output=True, text=True)


class FoldTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.d = self.root / "plan" / "backlog.d"
        self.d.mkdir(parents=True)
        (self.d / "_header.md").write_text(HEADER)

    def frag(self, name, body="found_by: me\nfix: later\n\nthe gap\n"):
        (self.d / name).write_text(body)

    def fold(self, *extra):
        return run("--root", str(self.root), *extra)

    def test_repo_backlog_is_current(self):
        r = run("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_sorted_numerically_and_idempotent(self):
        self.frag("B10.md")
        self.frag("B2.md", "found_by: a\nfix: b\n\nc\n")
        self.assertEqual(self.fold().returncode, 0)
        out = (self.root / "plan" / "backlog.md").read_text()
        self.assertEqual(out, HEADER + "| B2 | c | a | b |\n| B10 | the gap | me | later |\n")
        self.assertEqual(self.fold().returncode, 0)
        self.assertEqual((self.root / "plan" / "backlog.md").read_text(), out)
        self.assertEqual(self.fold("--check").returncode, 0)

    def test_check_fails_on_hand_edit_and_prints_diff(self):
        self.frag("B1.md")
        self.fold()
        with open(self.root / "plan" / "backlog.md", "a") as f:
            f.write("| B9 | sneaky | x | y |\n")
        r = self.fold("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("-| B9 | sneaky", r.stdout)

    def test_check_fails_when_missing(self):
        self.frag("B1.md")
        self.assertEqual(self.fold("--check").returncode, 1)

    def test_optional_quirks(self):
        self.frag("B1.md", "found_by: a\nfix:\n\ng\n")
        self.frag("B2.md", "found_by: a\nfix: f `a | b`\nclosing_pipe: no\n\ng\n")
        self.fold()
        self.assertEqual((self.root / "plan" / "backlog.md").read_text(),
                         HEADER + "| B1 | g | a | |\n| B2 | g | a | f `a | b`\n")

    def refused(self, name, body, needle):
        self.frag(name, body)
        r = self.fold()
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(needle, r.stderr)
        self.assertFalse((self.root / "plan" / "backlog.md").exists())

    def test_refusals(self):
        self.refused("B01.md", "found_by: a\nfix: b\n\nc\n", "not a fragment name")
        (self.d / "B01.md").unlink()
        self.refused("B1.md", "found_by: a\n\nc\n", "missing header")
        self.refused("B1.md", "found_by: a\nfix: b\nfix: c\n\nd\n", "each once")
        self.refused("B1.md", "found_by: a\nfix: b\nwho: c\n\nd\n", "each once")
        self.refused("B1.md", "found_by: a\nfix: b\nd\n", "each once")
        self.refused("B1.md", "found_by: a\nfix: b\n\nd\ne\n", "exactly one line")
        self.refused("B1.md", "found_by: a\nfix: b\n\nd", "exactly one line")
        self.refused("B1.md", "found_by: a\nfix: b\n\n\n", "empty")
        self.refused("B1.md", "found_by: a\nfix: b\n\nx | y\n", "'|'")
        self.refused("B1.md", "found_by: a|b\nfix: b\n\nx\n", "'|'")
        self.refused("B1.md", "found_by: a\nfix: b\nclosing_pipe: maybe\n\nx\n", "closing_pipe")
        (self.d / "B1.md").unlink()
        self.frag("notes.txt", "x")
        self.assertEqual(self.fold().returncode, 2)

    def test_pipes_in_code_spans_and_escapes_are_allowed(self):
        self.frag("B1.md", "found_by: a\nfix: run `a | b` or a \\| b\n\nif `x || y`\n")
        self.assertEqual(self.fold().returncode, 0)

    def test_duplicate_ids_refused_by_name_rules(self):
        self.frag("B3.md")
        self.frag("b3.md")
        self.assertEqual(self.fold().returncode, 2)

    def test_missing_header_refused(self):
        (self.d / "_header.md").unlink()
        r = self.fold()
        self.assertEqual(r.returncode, 2)
        self.assertIn("_header.md", r.stderr)


if __name__ == "__main__":
    unittest.main()
