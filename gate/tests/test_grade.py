"""Unit tests for the parts of `rigor grade` that do not need Buck2 (selftest/grade.sh does)."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from rigor_lib import grade_checks, grade_context, grade_pipeline, grade_tree, product_layout, verdict
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, base_env


def write_product(directory, text):
    path = directory / "product.toml"
    path.write_text(text, encoding="utf-8")
    return path


class PipelineTable(unittest.TestCase):
    def test_gate_ids_match_the_order_file(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids, verdict.read_order(str(GATE_DIR / "order.txt")))

    def test_every_step_is_callable_and_ids_are_unique(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(callable(step) for _, step in grade_pipeline.GATES))


class Layout(TempDirTestCase):
    def config(self, include, exclude=()):
        text = 'name = "p"\n[layout]\ninclude = %r\nexclude = %r\n' % (list(include), list(exclude))
        return product_layout.load_product(str(write_product(self.tmp, text.replace("'", '"'))))

    def test_copy_and_not_included(self):
        config = self.config(["core/**"])
        self.assertEqual(product_layout.classify(config, "core/BUCK"), product_layout.COPY)
        self.assertEqual(product_layout.classify(config, "other/a.c"), product_layout.NOT_INCLUDED)

    def test_product_exclude(self):
        config = self.config(["core/**"], ["core/gen/**"])
        self.assertEqual(product_layout.classify(config, "core/gen/x.c"),
                         product_layout.EXCLUDED_BY_PRODUCT)

    def test_gate_exclusions_win_over_include(self):
        config = self.config(["**"])
        for path in (".buckconfig", "core/.buckconfig.local", ".buckroot", "a/b/rules.bzl", "tools/buck2",
                     "toolchains/BUCK", "prelude/x", "gate/rigor", ".gitignore", ".github/w.yml",
                     "core/.gitattributes"):
            self.assertEqual(product_layout.classify(config, path), product_layout.EXCLUDED_BY_GATE, path)
        self.assertEqual(product_layout.classify(config, "core/tools/x.c"), product_layout.COPY)

    def test_bad_product_files_are_internal_errors(self):
        bad = ['name = "p"\n', 'name = "P"\n[layout]\ninclude = ["a"]\n',
               'name = "p"\n[layout]\ninclude = []\n', 'name = "p"\n[layout]\ninclude = ["a"]\nx = 1\n',
               'name = "p"\nextra = 1\n[layout]\ninclude = ["a"]\n',
               'name = "p"\n[layout]\ninclude = ["a/**/**b"]\n']
        for text in bad:
            with self.assertRaises(InternalError, msg=text):
                product_layout.load_product(str(write_product(self.tmp, text)))


class Buckconfig(unittest.TestCase):
    GATE = (b"[cells]\n  root = .\n\n[buck2_re_client]\nengine_address = a\ntls = false\n\n"
            b"[http]\n  connect_timeout_ms = 1\n\n[parser]\n  x = y\n")

    def test_re_settings_are_copied_and_cells_are_the_grading_cells(self):
        text = grade_tree.generated_buckconfig(self.GATE).decode()
        self.assertIn("[buck2_re_client]\nengine_address = a\ntls = false\n", text)
        self.assertIn("[http]\n  connect_timeout_ms = 1\n", text)
        self.assertIn("  toolchains = gate/toolchains\n", text)
        self.assertIn("  gate = gate\n", text)
        self.assertNotIn("x = y", text)

    def test_missing_section_is_an_error(self):
        with self.assertRaises(InternalError):
            grade_tree.generated_buckconfig(b"[cells]\n")


class SealedEnvironment(TempDirTestCase):
    HOSTILE = {"HOME": "/tmp/evil", "BUCK2_BIN": "/bin/false", "BUCK_LOG": "x", "XDG_CONFIG_HOME": "/e",
               "LD_PRELOAD": "/e.so", "LD_LIBRARY_PATH": "/e", "PYTHONPATH": "/e", "SSH_AUTH_SOCK": "/e",
               "https_proxy": "http://e", "ALL_PROXY": "http://e", "GIT_DIR": "/e", "TMPDIR": "/e"}

    def test_exactly_the_fixed_variables(self):
        with mock.patch.dict(os.environ, self.HOSTILE):
            env = grade_context.sealed_env(str(self.tmp))
        self.assertEqual(set(env), {"HOME", "PATH", "LANG", "TMPDIR"})
        self.assertEqual(env["PATH"], "/usr/local/bin:/usr/bin:/bin")
        self.assertEqual(env["LANG"], "C.UTF-8")
        self.assertEqual(env["HOME"], str(self.tmp / "home"))
        self.assertEqual(env["TMPDIR"], str(self.tmp / "tmp"))
        self.assertEqual(os.listdir(env["HOME"]), [])

    def test_home_is_recreated_empty(self):
        home = self.tmp / "home"
        home.mkdir()
        (home / ".buckconfig.local").write_text("[x]\n")
        grade_context.sealed_env(str(self.tmp))
        self.assertFalse((home / ".buckconfig.local").exists())


class SealedEnvironment(TempDirTestCase):
    HOSTILE = {"HOME": "/tmp/evil", "BUCK2_BIN": "/bin/false", "BUCK_LOG": "x", "XDG_CONFIG_HOME": "/e",
               "LD_PRELOAD": "/e.so", "LD_LIBRARY_PATH": "/e", "PYTHONPATH": "/e", "SSH_AUTH_SOCK": "/e",
               "https_proxy": "http://e", "ALL_PROXY": "http://e", "GIT_DIR": "/e", "TMPDIR": "/e"}

    def test_exactly_the_fixed_variables(self):
        with mock.patch.dict(os.environ, self.HOSTILE):
            env = grade_context.sealed_env(str(self.tmp))
        self.assertEqual(set(env), {"HOME", "PATH", "LANG", "TMPDIR"})
        self.assertEqual(env["PATH"], "/usr/local/bin:/usr/bin:/bin")
        self.assertEqual(env["LANG"], "C.UTF-8")
        self.assertEqual(env["HOME"], str(self.tmp / "home"))
        self.assertEqual(env["TMPDIR"], str(self.tmp / "tmp"))
        self.assertEqual(os.listdir(env["HOME"]), [])

    def test_prepare_work_leaves_home_empty(self):
        home = self.tmp / "home"
        home.mkdir()
        (home / ".buckconfig.local").write_text("[x]\n")
        grade_context.prepare_work(str(self.tmp))
        self.assertEqual(os.listdir(str(home)), [])
        self.assertTrue((self.tmp / "tmp").is_dir())


class DirtyGateCheckout(TempDirTestCase):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.tmp)] + list(args), env=base_env(), check=True,
                       capture_output=True)

    def test_clean_is_accepted_and_tracked_change_is_refused(self):
        self.git("init", "-q")
        (self.tmp / "a.txt").write_text("1\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "x")
        with mock.patch.object(grade_context, "GATE_ROOT", str(self.tmp)):
            self.assertEqual(len(grade_context.gate_checkout_sha()), 40)
            (self.tmp / "untracked.txt").write_text("u\n")  # untracked files do not count
            self.assertEqual(len(grade_context.gate_checkout_sha()), 40)
            (self.tmp / "a.txt").write_text("2\n")
            with self.assertRaises(InternalError):
                grade_context.gate_checkout_sha()
            self.git("add", "a.txt")  # staged is still uncommitted
            with self.assertRaises(InternalError):
                grade_context.gate_checkout_sha()
        self.assertTrue(os.path.isdir(str(self.tmp)))


if __name__ == "__main__":
    unittest.main()


class ExpectedTool(TempDirTestCase):
    """gate/tools/expected.py: add-only maintenance of expected-tests.json."""

    TOOL = GATE_DIR / "tools" / "expected.py"

    def setUp(self):
        super().setUp()
        self.products = self.sub("products")
        (self.products / "p").mkdir()
        self.results = self.sub("results")

    def results_file(self, name, ids, summary=True):
        lines = ['{"id":"%s","status":"pass","asserts":1,"reason":""}' % i for i in ids]
        if summary:
            lines.append('{"summary":{"total":%d,"passed":%d}}' % (len(ids), len(ids)))
        (self.results / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_tool(self, *extra):
        argv = [sys.executable, "-I", "-B", str(self.TOOL), "add", "--product", "p",
                "--products-dir", str(self.products), "--results", *extra]
        return subprocess.run(argv, capture_output=True, text=True, timeout=60)

    def listed(self):
        return json.loads((self.products / "p" / "expected-tests.json").read_text())["ids"]

    def test_creates_sorted_list(self):
        self.results_file("a.jsonl", ["z/b", "a/b"])
        done = self.run_tool(str(self.results))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.listed(), ["a/b", "z/b"])

    def test_merge_only_adds_and_keeps_old_ids(self):
        (self.products / "p" / "expected-tests.json").write_text('{"ids": ["old/one", "a/b"]}')
        self.results_file("a.jsonl", ["a/b", "new/two"])
        self.assertEqual(self.run_tool(str(self.results)).returncode, 0)
        self.assertEqual(self.listed(), ["a/b", "new/two", "old/one"])

    def test_two_directories_are_merged(self):
        other = self.sub("other")
        self.results_file("a.jsonl", ["a/one"])
        (other / "b.jsonl").write_text('{"id":"b/two","status":"fail","asserts":1,"reason":"x"}\n'
                                       '{"summary":{"total":1,"passed":0}}\n')
        self.assertEqual(self.run_tool(str(self.results), str(other)).returncode, 0)
        self.assertEqual(self.listed(), ["a/one", "b/two"])

    def test_malformed_results_change_nothing(self):
        path = self.products / "p" / "expected-tests.json"
        path.write_text('{"ids": ["old/one"]}')
        self.results_file("a.jsonl", ["a/one"], summary=False)
        self.assertEqual(self.run_tool(str(self.results)).returncode, 2)
        self.assertEqual(path.read_text(), '{"ids": ["old/one"]}')

    def test_bad_inputs_are_exit_2(self):
        self.assertEqual(self.run_tool(str(self.tmp / "missing")).returncode, 2)
        (self.products / "p" / "expected-tests.json").write_text("not json")
        self.results_file("a.jsonl", ["a/one"])
        self.assertEqual(self.run_tool(str(self.results)).returncode, 2)

    def test_merge_function_refuses_to_lose_ids(self):
        sys.path.insert(0, str(GATE_DIR / "tools"))
        try:
            import expected
        finally:
            sys.path.remove(str(GATE_DIR / "tools"))
        self.assertEqual(expected.merge({"b/x"}, {"a/y"}), ["a/y", "b/x"])


class ProductChecksStep(TempDirTestCase):
    def grading(self, assemble_status, files):
        tree = self.sub("tree")
        for path, data in files.items():
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            (tree / path).write_text(data, encoding="utf-8")
        return grade_context.Grading(
            args=None, product=None, gate_sha="", work=str(self.tmp), src="", tree=str(tree),
            results="", test_results="", status={"assemble": assemble_status},
            product_paths=sorted(files))

    def test_buckfiles_reads_product_files_only(self):
        good = 'load("@gate//rules:c.bzl", "c_library")\nc_library(name = "a", srcs = ["a.c"])\n'
        g = self.grading("PASS", {"core/BUCK": good, "core/a.c": ""})
        (self.tmp / "tree" / "gate").mkdir()
        (self.tmp / "tree" / "gate" / "BUCK").write_text("native.cxx_library()\n")
        self.assertEqual(grade_checks.buckfiles_gate(g).status, "PASS")

    def test_buckfiles_fails_on_a_raw_rule(self):
        g = self.grading("PASS", {"core/BUCK": "native.cxx_library(name = 'a')\n"})
        result = grade_checks.buckfiles_gate(g)
        self.assertEqual([f["rule"] for f in result.findings], ["bad-call"])
        self.assertEqual(result.findings[0]["path"], "core/BUCK")

    def test_no_tree_means_not_run(self):
        g = self.grading("FAIL", {})
        for step in (grade_checks.buckfiles_gate, grade_checks.semantic_gate, grade_checks.symbols_gate):
            self.assertIsNone(step(g))
