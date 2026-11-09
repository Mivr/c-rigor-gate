"""Tests for tools/affected.py (T044): the path to selftest map, fail-closed, and the real rules file."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "affected.py"

spec = importlib.util.spec_from_file_location("affected", TOOL)
aff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aff)

RULES = """
[[rule]]
glob = "a/**"
selftests = ["grade"]
[[rule]]
glob = "a/b/*.c"
selftests = ["ctest"]
[[rule]]
glob = "docs/x?.md"
selftests = []
[[rule]]
glob = "everything/**"
selftests = ["all"]
[[rule]]
glob = "**"
selftests = ["fuzz"]
"""


def rules_from(text):
    with tempfile.NamedTemporaryFile("w", suffix=".toml", dir=os.environ.get("TMPDIR", "/var/tmp"), delete=False) as f:
        f.write(text)
    try:
        return aff.load_rules(f.name)
    finally:
        os.unlink(f.name)


class GlobTests(unittest.TestCase):
    def test_star_stays_in_segment_and_double_star_crosses(self):
        self.assertTrue(aff.glob_regex("a/*.c").match("a/x.c"))
        self.assertIsNone(aff.glob_regex("a/*.c").match("a/b/x.c"))
        self.assertTrue(aff.glob_regex("a/**").match("a/b/c/d"))
        self.assertIsNone(aff.glob_regex("a/**").match("ab/c"))

    def test_question_and_literals_and_whole_path(self):
        self.assertTrue(aff.glob_regex("x?.md").match("xy.md"))
        self.assertIsNone(aff.glob_regex("x?.md").match("x/.md"))
        self.assertIsNone(aff.glob_regex("x.md").match("xamd"))
        self.assertIsNone(aff.glob_regex("x.md").match("dir/x.md"))
        self.assertIsNone(aff.glob_regex("gate/rigor").match("gate/rigor_lib/a.py"))


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.rules = rules_from(RULES)

    def test_gate_is_always_selected(self):
        chosen, _ = aff.select([], self.rules)
        self.assertEqual(chosen, {"gate"})
        chosen, _ = aff.select(["docs/xy.md"], self.rules)
        self.assertEqual(chosen, {"gate"})

    def test_first_matching_rule_decides(self):
        chosen, why = aff.select(["a/b/x.c"], self.rules)
        self.assertEqual(chosen, {"gate", "grade"})
        self.assertIn("rule a/**", why["grade"])

    def test_union_over_paths(self):
        chosen, _ = aff.select(["a/x", "docs/xy.md"], self.rules)
        self.assertEqual(chosen, {"gate", "grade"})

    def test_all_expands(self):
        chosen, _ = aff.select(["everything/z"], self.rules)
        self.assertEqual(chosen, set(aff.ALL))

    def test_no_rule_selects_everything(self):
        chosen, why = aff.select(["zzz"], rules_from(RULES.split('[[rule]]\nglob = "**"')[0]))
        self.assertEqual(chosen, set(aff.ALL))
        self.assertIn("fail closed", why["grade"])

    def test_unmatched_ignores_catch_all(self):
        self.assertEqual(aff.unmatched(["a/x", "q/r"], self.rules), ["q/r"])

    def test_bad_rules_are_errors(self):
        with self.assertRaises(ValueError):
            rules_from('[[rule]]\nglob = "a"\nselftests = ["nope"]\n')
        with self.assertRaises(ValueError):
            rules_from('[[rule]]\nglob = "a"\n')


class RealRulesTests(unittest.TestCase):
    def setUp(self):
        self.rules = aff.load_rules()

    def pick(self, *paths):
        return aff.select(paths, self.rules)[0]

    def test_mandatory_everything_paths(self):
        for path in ("rules/c.bzl", "toolchains/BUCK", "prelude/x.bzl", ".buckconfig", "tools/buck2",
                     "tools/buck2.version", "gate/rigor_lib/grade_build.py", "gate/rigor_lib/grade.py", "gate/rigor"):
            self.assertEqual(self.pick(path), set(aff.ALL), path)

    def test_unknown_path_selects_everything(self):
        self.assertEqual(self.pick("brand_new_dir/file.c"), set(aff.ALL))

    def test_trajectory_only_change(self):
        self.assertEqual(self.pick("gate/rigor_lib/trajectory_git.py", "docs/trajectory.md"), {"gate", "trajectory_real"})

    def test_docs_and_plan_select_only_gate(self):
        self.assertEqual(self.pick("plan/backlog.md", "docs/gate.md"), {"gate"})

    def test_each_selftest_script_selects_itself(self):
        for name in ("grade", "mutate", "structure", "product_checks", "toolchain", "ctest", "fuzz", "third_party",
                     "canaries", "profiles", "require"):
            self.assertIn(name, self.pick("selftest/%s.sh" % name))

    def test_every_tracked_file_has_a_specific_rule(self):
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
        paths = [p.decode() for p in out.split(b"\0") if p]
        self.assertEqual(aff.unmatched(paths, self.rules), [])

    def test_no_selftest_or_canary_reads_a_product_directory_its_rule_does_not_select(self):
        """T066: a product directory named in a selftest, canary or script must select that selftest."""
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "products", "canaries", "selftest"],
                             capture_output=True, check=True).stdout
        products = sorted({p.decode().split("/")[1] for p in out.split(b"\0") if p.startswith(b"products/")})
        self.assertIn("selftest", products)
        for raw in out.split(b"\0"):
            path = raw.decode()
            if path.startswith("canaries/"):
                kinds = {"canaries"}
            elif path.startswith("selftest/"):
                kinds = self.pick(path) - {"gate"}
            else:
                continue
            text = (ROOT / path).read_text(errors="replace")
            for product in products:
                if "products/%s" % product in text:
                    chosen = self.pick("products/%s/x.c" % product)
                    self.assertTrue(kinds <= chosen, "%s mentions products/%s, whose rule selects %s"
                                    % (path, product, sorted(chosen)))


class CliTests(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-I", "-B", str(TOOL)] + list(args), capture_output=True, text=True,
                              timeout=60)

    def test_same_commit_is_gate_only(self):
        done = self.run_tool("HEAD", "HEAD")
        self.assertEqual((done.returncode, done.stdout), (0, "gate\n"))

    def test_why_output_names_the_rule(self):
        done = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        done = self.run_tool("--why", "HEAD", "HEAD")
        self.assertEqual(done.stdout, "gate\talways\n")

    def test_usage_error(self):
        self.assertEqual(self.run_tool("onlyone").returncode, 2)

    def test_bad_revision_fails(self):
        self.assertEqual(self.run_tool("no-such-rev", "HEAD").returncode, 2)


if __name__ == "__main__":
    unittest.main()
