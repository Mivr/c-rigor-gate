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

    def test_deps_must_be_same_cell_labels(self):
        for dep in ("gate//ctest:ctest", "@gate//ctest:ctest", "prelude//cxx:x", "toolchains//:cxx", "root//a:b",
                    "a", "a:b", ":", "//a", "//a:b c", ":a/b", "//a:b:c", ""):
            with self.subTest(dep=dep):
                self.red(LOAD + 'c_library(name = "a", deps = ["%s"])\n' % dep, "bad-argument")
        self.assertEqual(self.check({"BUCK": LOAD + 'c_library(name = "a", deps = [])\n'}, 0), [])

    def test_good_deps(self):
        for dep in (":b", ":b-c_d.e+f", "//pkg:name", "//pkg/sub.dir:n", "//:root"):
            with self.subTest(dep=dep):
                self.setUp()
                self.assertEqual(self.check({"BUCK": LOAD + 'c_library(name = "a", deps = ["%s"])\n' % dep}, 0), [])

    def test_deps_as_a_bare_string_is_not_a_list_of_labels(self):
        self.red(LOAD + 'c_library(name = "a", deps = "//a:b")\n', "bad-argument")

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


MBED = "gate//third_party/mbedtls:mbedtls"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ThirdPartyLabelCase(TempDirTestCase):
    """Exact labels from the gate-owned allowlist are the only cell-prefixed deps a product may name."""

    def check(self, source, code, allowed=MBED + "\n", extra=()):
        root = self.sub("product")
        (root / "BUCK").write_text(source, encoding="utf-8")
        argv = ["buckfiles", "--root", root, "--out", self.tmp / "out.json"]
        if allowed is not None:
            lst = self.tmp / "ALLOWED_LABELS"
            lst.write_text(allowed, encoding="utf-8")
            argv += ["--allowed-labels", lst]
        outcome = run_rigor(argv + list(extra))
        self.assertExit(outcome, code)
        out = self.tmp / "out.json"
        return sorted((f["rule"], f.get("why")) for f in read_json(out)["findings"])

    def dep(self, label, code, **kw):
        return self.check(LOAD + 'c_library(name = "a", srcs = ["a.c"], deps = ["%s"])\n' % label, code, **kw)

    def test_the_allowlisted_label_is_accepted_by_every_macro(self):
        for macro in ("c_library", "c_binary", "c_test"):
            with self.subTest(macro=macro):
                source = 'load("@gate//rules:c.bzl", "%s")\n%s(name = "a", srcs = ["a.c"], deps = [":b", "%s"])\n' % (
                    macro, macro, MBED)
                self.assertEqual(self.check(source, 0), [])
                self.setUp()

    def test_other_third_party_looking_labels_are_refused(self):
        for label in ("gate//third_party/curl:curl", "gate//third_party/mbedtls:mbedtls_x", "gate//third_party/mbedtls:mbed",
                      "gate//third_party/mbedtls/:mbedtls", "gate//third_party/mbedtls:mbedtls:x",
                      "gate//third_party/mbedtls:*", "gate//third_party/...", "gate//third_party/mbedtls:all",
                      "third_party//mbedtls:mbedtls", "gate//third_party:mbedtls",
                      "gate//third_party/mbedtls:mbedtls_symbols", "gate//third_party/mbedtls:mbedtls_facts"):
            with self.subTest(label=label):
                self.assertEqual(self.dep(label, 1), [("bad-argument", "dep")])
                self.setUp()

    def test_near_misses_of_the_allowlisted_label_are_refused(self):
        for label in (MBED + " ", " " + MBED, "@" + MBED, "@gate//third_party/mbedtls:mbedtls", "GATE//third_party/mbedtls:mbedtls",
                      "gate//third_party/mbedtls:Mbedtls", "gate//third_party//mbedtls:mbedtls",
                      "gate//third_party/./mbedtls:mbedtls", "gate//third_party/mbedtls:mbedtls\n",
                      "root//third_party/mbedtls:mbedtls", "gate//third_party/mbedtls:mbedtls#x"):
            with self.subTest(label=label):
                self.assertEqual(self.dep(label.replace("\n", "\\n"), 1), [("bad-argument", "dep")])
                self.setUp()

    def test_the_label_is_not_allowed_without_the_list_naming_it(self):
        self.assertEqual(self.dep(MBED, 1, allowed="gate//third_party/other:other\n"), [("bad-argument", "dep")])
        self.setUp()
        self.assertEqual(self.dep(MBED, 1, allowed=""), [("bad-argument", "dep")])

    def test_the_label_is_not_a_prefix_match(self):
        self.assertEqual(self.dep(MBED + "x", 1, allowed=MBED + "\n"), [("bad-argument", "dep")])

    def test_the_label_in_any_other_keyword_is_not_a_dep(self):
        # srcs/headers entries are checked by the macros (plain file names), visibility is not a dep.
        found = self.check(LOAD + 'c_library(name = "a", srcs = ["a.c"], visibility = ["%s"])\n' % MBED, 0)
        self.assertEqual(found, [])

    def test_a_bare_string_dep_is_not_a_list(self):
        self.assertEqual(self.check(LOAD + 'c_library(name = "a", deps = "%s")\n' % MBED, 1), [("bad-argument", "dep")])

    def test_list_defects_are_exit_2(self):
        for text in ("# comment\n" + MBED + "\n", MBED + "\n\n", "\n" + MBED + "\n", MBED + "\n" + MBED + "\n",
                     MBED + " \n", "//third_party/mbedtls:mbedtls\n", "gate//third_party/*:x\n",
                     "gate//third_party/mbedtls:mbedtls", MBED + "\r\n", "\xe9\n", "gate//ctest:ctest\n",
                     "gate//x/y:z\n", "prelude//cxx:cxx\n"):
            with self.subTest(text=text):
                self.check(LOAD + 'c_library(name = "a")\n', 2, allowed=text)
                self.setUp()

    def test_a_missing_or_empty_list_file(self):
        self.check(LOAD + 'c_library(name = "a")\n', 2, allowed=None, extra=["--allowed-labels", self.tmp / "nope"])
        self.setUp()
        self.check(LOAD + 'c_library(name = "a")\n', 0, allowed="")

    def test_a_symlinked_list_is_refused(self):
        real = self.tmp / "real"
        real.write_text(MBED + "\n", encoding="utf-8")
        link = self.tmp / "link"
        os.symlink(real, link)
        root = self.sub("product")
        (root / "BUCK").write_text(LOAD + 'c_library(name = "a")\n', encoding="utf-8")
        self.assertExit(run_rigor(["buckfiles", "--root", root, "--allowed-labels", link]), 2)

    def test_the_default_list_is_the_gate_s_own_and_names_mbedtls_only(self):
        with open(os.path.join(REPO, "third_party", "ALLOWED_LABELS"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), MBED + "\n")
        found = self.check(LOAD + 'c_library(name = "a", deps = ["%s"])\n' % MBED, 0, allowed=None)
        self.assertEqual(found, [])
        self.setUp()
        self.assertEqual(self.check(LOAD + 'c_library(name = "a", deps = ["gate//third_party/curl:curl"])\n', 1,
                                    allowed=None), [("bad-argument", "dep")])
