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


class CpuQuotaTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(RUNNER.parent))
        self.addCleanup(sys.path.remove, str(RUNNER.parent))
        import run_parallel
        self.rp = run_parallel
        self.dir = tempfile.mkdtemp(prefix="cpumax.")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def fixture(self, text):
        path = Path(self.dir) / "cpu.max"
        path.write_text(text)
        return str(path)

    def test_quota_limits_cpus(self):
        self.assertEqual(self.rp.effective_cpus(self.fixture("200000 100000\n")), 2)
        self.assertEqual(self.rp.effective_cpus(self.fixture("150000 100000\n")), 2)
        self.assertEqual(self.rp.effective_cpus(self.fixture("50000 100000\n")), 1)

    def test_default_jobs_from_quota(self):
        self.assertEqual(self.rp.default_jobs(self.fixture("200000 100000\n")), 4)
        self.assertEqual(self.rp.default_jobs(self.fixture("50000 100000\n")), 2)

    def test_max_and_malformed_and_missing_fall_back(self):
        base = self.rp.effective_cpus(str(Path(self.dir) / "absent"))
        self.assertEqual(self.rp.effective_cpus(self.fixture("max 100000\n")), base)
        for bad in ("", "garbage", "abc def", "100 0"):
            self.assertEqual(self.rp.effective_cpus(self.fixture(bad)), base, bad)
        self.assertTrue(2 <= self.rp.default_jobs(self.fixture("max 100000")) <= 16)
