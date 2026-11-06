"""Tests for `rigor buckfiles`: red first, every shape of a build file that must be refused."""

import os

from tests.helpers import TempDirTestCase, read_json, run_rigor

LOAD = 'load("@gate//rules:c.bzl", "c_library", "c_test")\n'
GOOD = LOAD + 'c_library(name = "a", srcs = ["a.c"], headers = ["a.h"], deps = [":b", "//x:y"], visibility = ["PUBLIC"])\n'


class BuckFilesCase(TempDirTestCase):
    def check(self, files, code):
        root = self.sub("product")
        for rel, data in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        out = self.tmp / "out.json"
        outcome = run_rigor(["buckfiles", "--root", root, "--out", out])
        self.assertExit(outcome, code)
        return sorted(f["rule"] for f in read_json(out)["findings"]) if out.exists() else None

    def red(self, source, *rules, path="BUCK"):
        self.assertEqual(self.check({path: source}, 1), sorted(rules))

    def test_green_build_file(self):
        self.assertEqual(self.check({"core/BUCK": GOOD, "BUCK": GOOD, "core/a.c": "int x;"}, 0), [])

    def test_green_empty_and_comment_only(self):
        self.assertEqual(self.check({"BUCK": "# nothing here\n"}, 0), [])

    def test_assignment(self):
        self.red(GOOD + 'FLAGS = ["-w"]\n', "bad-statement")

    def test_native_call(self):
        self.red(LOAD + 'native.cxx_library(name = "a", srcs = ["a.c"])\n', "bad-call")

    def test_raw_rule_call(self):
        self.red(LOAD + 'cxx_library(name = "a", srcs = ["a.c"])\n', "bad-call")

    def test_second_load(self):
        self.red(GOOD + 'load("@gate//rules:c.bzl", "c_binary")\n', "extra-load")

    def test_load_of_another_file(self):
        self.red('load("//tools:flags.bzl", "c_library")\n', "bad-load")

    def test_load_of_unknown_symbol(self):
        self.red('load("@gate//rules:c.bzl", "cxx_library")\n', "bad-load")

    def test_load_with_alias(self):
        self.red('load("@gate//rules:c.bzl", lib = "c_library")\n', "bad-load")

    def test_second_load_of_another_file_is_both(self):
        self.red(GOOD + 'load("//x:y.bzl", "z")\n', "bad-load", "extra-load")

    def test_compiler_flags_keyword(self):
        self.red(LOAD + 'c_library(name = "a", srcs = ["a.c"], compiler_flags = ["-w"])\n', "bad-argument")

    def test_kwargs_splat(self):
        self.red(LOAD + 'c_library(**{"name": "a"})\n', "bad-argument")

    def test_positional_argument(self):
        self.red(LOAD + 'c_library("a")\n', "bad-argument")

    def test_glob(self):
        self.red(LOAD + 'c_library(name = "a", srcs = glob(["*.c"]))\n', "bad-argument")

    def test_comprehension_value(self):
        self.red(LOAD + 'c_library(name = "a", srcs = [x for x in ["a.c"]])\n', "bad-argument")

    def test_concatenation_value(self):
        self.red(LOAD + 'c_library(name = "a", srcs = ["a.c"] + ["b.c"])\n', "bad-argument")

    def test_string_concatenation_value(self):
        self.red(LOAD + 'c_library(name = "a" + "b", srcs = ["a.c"])\n', "bad-argument")

    def test_fstring_value(self):
        self.red(LOAD + 'c_library(name = f"a", srcs = ["a.c"])\n', "bad-argument")

    def test_non_string_values(self):
        self.red(LOAD + 'c_library(name = "a", srcs = [1])\n', "bad-argument")
        self.red(LOAD + 'c_library(name = "a", srcs = None)\n', "bad-argument")
        self.red(LOAD + 'c_library(name = "a", srcs = ("a.c",))\n', "bad-argument")
        self.red(LOAD + 'c_library(name = b"a")\n', "bad-argument")

    def test_select_value(self):
        self.red(LOAD + 'c_library(name = "a", srcs = select({"DEFAULT": ["a.c"]}))\n', "bad-argument")

    def test_def_if_for_import_expression_statements(self):
        self.red("def f():\n    pass\n", "bad-statement")
        self.red("if True:\n    pass\n", "bad-statement")
        self.red("for x in []:\n    pass\n", "bad-statement")
        self.red("import os\n", "bad-statement")
        self.red('"just a string"\n', "bad-statement")
        self.red("1 + 1\n", "bad-statement")
        self.red("x: int = 1\n", "bad-statement")

    def test_call_in_a_wrapper(self):
        self.red(LOAD + '(lambda: c_library(name = "a"))()\n', "bad-call")

    def test_parse_errors_are_findings(self):
        self.red("c_library(name = \n", "parse-error")
        self.red("\x00\n", "parse-error")
        self.red(b"\xff\xfe\n", "parse-error")

    def test_unknown_keyword(self):
        self.red(LOAD + 'c_library(name = "a", exec_compatible_with = ["x"])\n', "bad-argument")

    def test_bzl_file_anywhere(self):
        self.assertEqual(self.check({"BUCK": GOOD, "deep/er/flags.bzl": "X = 1\n"}, 1), ["forbidden-file"])

    def test_other_build_configuration_files(self):
        for name in ("BUCK.v2", "TARGETS", "TARGETS.v2", "PACKAGE", ".buckconfig", ".buckconfig.local",
                     ".buckroot", "x.bxl", "buck", "Buck", "BUCK.bak", "PACKAGE.v2"):
            with self.subTest(name=name):
                self.assertEqual(self.check({"BUCK": GOOD, "sub/" + name: ""}, 1), ["forbidden-file"])
                self.setUp()

    def test_symlinked_build_file_and_directory(self):
        root = self.sub("product")
        (root / "real").mkdir()
        (root / "real" / "BUCK").write_text(GOOD, encoding="utf-8")
        os.symlink("real/BUCK", root / "BUCK")
        os.symlink("real", root / "linkdir")
        out = self.tmp / "out.json"
        self.assertExit(run_rigor(["buckfiles", "--root", root, "--out", out]), 1)
        self.assertEqual(sorted(f["rule"] for f in read_json(out)["findings"]), ["symlink", "symlink"])

    def test_findings_are_deterministic(self):
        first = self.check({"BUCK": GOOD + "X = 1\n", "a/BUCK": GOOD + "Y = 2\n"}, 1)
        out = self.tmp / "out.json"
        before = out.read_bytes()
        run_rigor(["buckfiles", "--root", self.tmp / "product", "--out", out])
        self.assertEqual(out.read_bytes(), before)
        self.assertEqual(first, ["bad-statement", "bad-statement"])

    def test_missing_root_is_exit_2_and_fails_closed(self):
        out = self.tmp / "out.json"
        out.write_text("stale", encoding="utf-8")
        self.assertExit(run_rigor(["buckfiles", "--root", self.tmp / "nope", "--out", out]), 2)
        self.assertEqual(read_json(out)["status"], "FAIL")
        self.assertEqual(read_json(out)["findings"][0]["rule"], "internal-error")
