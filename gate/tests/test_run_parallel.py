"""run_parallel.py: discovery parity, failure reporting, count mismatch."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import GATE_DIR

RUNNER = GATE_DIR / "tests" / "run_parallel.py"
HELPERS_IMPORT = "from tests.helpers import TempDirTestCase\n"


class RunParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="run_parallel.")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A scratch gate tree: runner + a tests package that we control.
        self.gate = Path(self.tmp) / "gate"
        tests = self.gate / "tests"
        tests.mkdir(parents=True)
        shutil.copy(RUNNER, tests / "run_parallel.py")
        (tests / "__init__.py").write_text("")

    def add(self, name, body):
        (self.gate / "tests" / f"test_{name}.py").write_text(body)

    def run_runner(self, *extra):
        env = {"PATH": "/usr/bin:/bin", "TMPDIR": self.tmp}
        return subprocess.run(
            [sys.executable, "-I", "-B", str(self.gate / "tests" / "run_parallel.py"), *extra],
            cwd=self.tmp, env=env, capture_output=True, text=True)

    def test_all_pass(self):
        self.add("a", "import unittest\nclass T(unittest.TestCase):\n"
                      "    def test_x(self): pass\n    def test_y(self): pass\n")
        self.add("b", "import unittest\nclass T(unittest.TestCase):\n    def test_z(self): pass\n")
        out = self.run_runner("--jobs", "2")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("Ran 3 tests in", out.stdout)

    def test_failure_and_import_error_named(self):
        self.add("good", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n")
        self.add("bad", "import unittest\nclass T(unittest.TestCase):\n"
                        "    def test_no(self): self.fail('boom-marker')\n")
        self.add("broken", "import does_not_exist_anywhere\n")
        out = self.run_runner()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("FAIL tests.test_bad", out.stdout)
        self.assertIn("boom-marker", out.stdout)
        self.assertIn("test_broken", out.stdout)
        self.assertIn("could not be imported", out.stdout)

    def test_hung_module_is_killed(self):
        self.add("hang", "import time, unittest\nclass T(unittest.TestCase):\n"
                         "    def test_h(self): time.sleep(60)\n")
        out = self.run_runner("--timeout", "1")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("killed after", out.stdout)

    def test_count_mismatch_fails(self):
        # The module reports fewer tests than were discovered: tests vanish at run time.
        self.add("vanish", "import unittest\n"
                           "class T(unittest.TestCase):\n    def test_a(self): pass\n"
                           "    def test_b(self): pass\n"
                           "def load_tests(loader, tests, pattern):\n"
                           "    import sys\n"
                           "    if sys.argv[0] == '-c':\n"
                           "        return unittest.TestSuite([t for s in tests for t in s][:1])\n"
                           "    return tests\n")
        out = self.run_runner()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("discovered", out.stdout)

    def test_no_tests_is_runner_error(self):
        out = self.run_runner()
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)

    def test_bad_jobs_is_runner_error(self):
        self.add("a", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n")
        self.assertEqual(self.run_runner("--jobs", "0").returncode, 2)
