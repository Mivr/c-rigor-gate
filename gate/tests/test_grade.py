"""Unit tests for the parts of `rigor grade` that do not need Buck2 (selftest/grade.sh does)."""

import os
import subprocess
import unittest
from unittest import mock

from rigor_lib import grade_context, grade_pipeline, grade_tree, product_layout, verdict
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
