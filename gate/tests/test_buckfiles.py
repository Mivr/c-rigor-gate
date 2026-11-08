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

    def lib(self, **kw):
        return LOAD + "c_library(name = \"a\", %s)\n" % ", ".join("%s = %s" % i for i in kw.items())

    def test_glob_forms_are_green(self):
        for value in ('glob(["src/*.c"])', 'glob(["src/*.c", "src/a.c"])', '["a.c"] + glob(["src/*.c"])',
                      'glob(["src/*.c"]) + ["a.c"]', 'glob(["src/scene_*.c"])'):
            with self.subTest(value=value):
                self.setUp()
                self.assertEqual(self.check({"BUCK": self.lib(srcs=value)}, 0), [])
        self.setUp()
        self.assertEqual(self.check({"BUCK": self.lib(srcs='glob(["src/*.c"])', headers='["a.h"] + glob(["src/*.h"])')}, 0), [])
        self.setUp()
        self.assertEqual(self.check({"BUCK": LOAD + 'c_test(name = "t", srcs = glob(["src/t.c"]))\n'}, 0), [])

    def test_glob_forms_that_stay_red(self):
        for value in ('glob(["**/*.c"])', 'glob(["src/**/*.c"])', 'glob(["../src/*.c"])', 'glob(["/src/*.c"])',
                      'glob(["tests/**"])', 'glob(["src/*/*.c"])', 'glob(["src/**.c"])', 'glob(["src/*.cc"])',
                      'glob(["*.c"])', 'glob(["src/a*b*.c"])', 'glob(["src/.c"])', 'glob(["src/..c"])',
                      'glob([])', 'glob(["src/*.c"], exclude = ["src/x.c"])', 'glob(include = ["src/*.c"])',
                      'glob("src/*.c")', 'glob(["src/*.c"], [])', 'glob(PATTERNS)', 'glob(["src/*.c", X])',
                      'glob(["src/*.c"]) + glob(["src/*.h"])', 'glob(["src/*.c"]) + ["a.c"] + ["b.c"]',
                      'glob(["src/*.c"]) + X', 'X + glob(["src/*.c"])', '["a.c"] + ["b.c"]',
                      'glob(["src/*.c"]) + glob(["src/*.c"]) + ["a.c"]', 'glob(["src/*.c"]) * 2', 'glob(["src/*.c"]) + []',
                      'glob(["src/*.c"]) - ["a.c"]', 'native.glob(["src/*.c"])',
                      '[f for f in glob(["src/*.c"])]', 'glob(["src/*.c"]) if X else []'):
            with self.subTest(value=value):
                self.setUp()
                self.red(self.lib(srcs=value), "bad-argument")

    def test_glob_only_in_srcs_and_headers_of_the_three_macros(self):
        for text in (self.lib(deps='glob(["src/*.c"])'), self.lib(name='glob(["src/*.c"])'),
                     self.lib(visibility='glob(["src/*.c"])'), self.lib(system_libs='glob(["src/*.c"])'),
                     LOAD + 'c_test(name = "t", deps = glob(["src/*.c"]))\n',
                     LOADS + 'c_fuzz(name = "f", srcs = glob(["src/*.c"]))\n',
                     LOAD + 'c_library(name = "a", srcs = glob(["tests/**"]))\n'):
            with self.subTest(text=text):
                self.setUp()
                self.red(text, "bad-argument")

    def test_glob_pattern_files_are_not_named_files_of_the_layout(self):
        from rigor_lib import product_layout
        text = self.lib(srcs='glob(["src/*.c"])', headers='["a.h"] + glob(["src/*.h"])')
        self.assertEqual(product_layout.named_files([("BUCK", text)], {"src/a.c", "a.h", "x"}), {"a.h"})

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

    def test_system_libs_on_a_library(self):
        self.assertEqual(self.check({"BUCK": LOAD + 'c_library(name = "a", srcs = ["a.c"], system_libs = ["pthread"])\n'}, 0), [])

    def test_system_libs_is_a_c_library_keyword_only(self):
        for macro in ("c_test", "c_binary", "c_fuzz"):
            self.red('load("@gate//rules:c.bzl", "%s")\n%s(name = "a", srcs = ["a.c"], system_libs = ["pthread"])\n'
                     % (macro, macro), "bad-argument")

    def test_system_libs_must_be_literal_strings(self):
        self.red(LOAD + 'c_library(name = "a", srcs = ["a.c"], system_libs = LIBS)\n', "bad-argument")
        self.red(LOAD + 'c_library(name = "a", srcs = ["a.c"], system_libs = [LIB])\n', "bad-argument")

    def test_exported_deps_on_a_library(self):
        self.assertEqual(self.check({"BUCK": LOAD + 'c_library(name = "a", srcs = ["a.c"], exported_deps = [":c", "//p:d"])\n'}, 0), [])

    def test_exported_deps_is_a_c_library_keyword_only(self):
        for macro in ("c_test", "c_binary", "c_fuzz"):
            self.red('load("@gate//rules:c.bzl", "%s")\n%s(name = "a", srcs = ["a.c"], exported_deps = [":c"])\n'
                     % (macro, macro), "bad-argument")

    def test_exported_deps_are_checked_like_deps(self):
        self.red(LOAD + 'c_library(name = "a", exported_deps = ["@prelude//x:y"])\n', "bad-argument")
        self.red(LOAD + 'c_library(name = "a", exported_deps = DEPS)\n', "bad-argument")
        self.red(LOAD + 'c_library(name = "a", exported_deps = glob(["src/*.c"]))\n', "bad-argument")

    def test_exported_deps_may_not_name_a_test(self):
        files = {"BUCK": LOAD + 'c_test(name = "t", srcs = ["t.c"])\n'
                 'c_library(name = "a", srcs = ["a.c"], exported_deps = [":t"])\n'}
        self.assertEqual(self.check(files, 1), ["bad-argument"])

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

    def test_the_default_list_is_the_gate_s_own_and_names_mbedtls_and_lvgl_only(self):
        with open(os.path.join(REPO, "third_party", "ALLOWED_LABELS"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), MBED + "\ngate//third_party/lvgl:lvgl\n")
        found = self.check(LOAD + 'c_library(name = "a", deps = ["%s"])\n' % MBED, 0, allowed=None)
        self.assertEqual(found, [])
        self.setUp()
        self.assertEqual(self.check(LOAD + 'c_library(name = "a", deps = ["gate//third_party/curl:curl"])\n', 1,
                                    allowed=None), [("bad-argument", "dep")])


PEER = "gate//third_party/tls_peer:tls_peer"
LOADS = 'load("@gate//rules:c.bzl", "c_library", "c_binary", "c_test", "c_fuzz")\n'


class TestOnlyLabelCase(TempDirTestCase):
    """The TLS peer label is accepted from a `c_test` and from nothing else, by any route."""

    def check(self, files, code, test_allowed=PEER + "\n"):
        root = self.sub("product")
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(data, encoding="utf-8")
        lst = self.tmp / "ALLOWED_TEST_LABELS"
        lst.write_text(test_allowed, encoding="utf-8")
        allowed = self.tmp / "ALLOWED_LABELS"
        allowed.write_text(MBED + "\n", encoding="utf-8")
        self.assertExit(run_rigor(["buckfiles", "--root", root, "--out", self.tmp / "out.json",
                                   "--allowed-labels", allowed, "--allowed-test-labels", lst]), code)
        return sorted((f["rule"], f.get("why")) for f in read_json(self.tmp / "out.json")["findings"])

    def test_a_test_may_name_it(self):
        self.assertEqual(self.check({"BUCK": LOADS + 'c_test(name = "t", srcs = ["t.c"], deps = [":l", "%s", "%s"])\n' % (PEER, MBED)}, 0), [])

    def test_no_other_macro_may_name_it(self):
        for macro in ("c_library", "c_binary", "c_fuzz"):
            with self.subTest(macro=macro):
                self.setUp()
                found = self.check({"BUCK": LOADS + '%s(name = "a", srcs = ["a.c"], deps = ["%s"])\n' % (macro, PEER)}, 1)
                self.assertEqual(found, [("bad-argument", "test-only-dep")])

    def test_the_list_decides(self):
        self.assertEqual(self.check({"BUCK": LOADS + 'c_test(name = "t", deps = ["%s"])\n' % PEER}, 1, test_allowed=""),
                         [("bad-argument", "dep")])

    def test_other_spellings_are_refused(self):
        for label in ("//third_party/tls_peer:tls_peer", "@" + PEER, "gate//third_party/tls_peer:srv_archive",
                      "gate//third_party/tls_peer:mbedtls_srv", "gate//third_party/tls_peer:tls_peer_symbols",
                      "//third_party/selftest:srv", "//third_party:x", "root//third_party/tls_peer:tls_peer"):
            with self.subTest(label=label):
                self.setUp()
                self.assertEqual(self.check({"BUCK": LOADS + 'c_test(name = "t", deps = ["%s"])\n' % label}, 1),
                                 [("bad-argument", "dep")])

    def test_a_library_may_not_depend_on_a_test_or_on_what_a_test_derives(self):
        for dep in (":t", ":t_facts", ":t_results", ":t_coverage", "//pkg/p:t", "//other/pkg/p:t_results", "//pkg/p:t_facts"):
            with self.subTest(dep=dep):
                self.setUp()
                files = {"p/BUCK": LOADS + 'c_test(name = "t", deps = ["%s"])\n' % PEER,
                         "q/BUCK": LOADS + 'c_library(name = "l", srcs = ["l.c"], deps = [])\n'}
                files["p/BUCK" if dep.startswith(":") else "q/BUCK"] += \
                    'c_binary(name = "b", srcs = ["b.c"], deps = ["%s"])\n' % dep
                self.assertEqual(self.check(files, 1), [("bad-argument", "test-target")])

    def test_similar_names_elsewhere_are_not_refused(self):
        files = {"p/BUCK": LOADS + 'c_test(name = "t")\n',
                 "q/BUCK": LOADS + 'c_library(name = "t", srcs = ["l.c"])\nc_binary(name = "b", deps = [":t", ":t2"])\n'}
        self.assertEqual(self.check(files, 0), [])

    def test_list_defects_are_exit_2(self):
        for text in (PEER, "# x\n" + PEER + "\n", PEER + "\n" + PEER + "\n", "gate//ctest:ctest\n"):
            with self.subTest(text=text):
                self.setUp()
                self.check({"BUCK": LOADS + 'c_test(name = "t")\n'}, 2, test_allowed=text)

    def test_the_default_test_list_is_the_gate_s_own(self):
        with open(os.path.join(REPO, "third_party", "ALLOWED_TEST_LABELS"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), PEER + "\n")
        root = self.sub("product")
        (root / "BUCK").write_text(LOADS + 'c_test(name = "t", deps = ["%s"])\nc_library(name = "l", deps = ["%s"])\n' % (PEER, PEER),
                                   encoding="utf-8")
        outcome = run_rigor(["buckfiles", "--root", root, "--out", self.tmp / "o.json"])
        self.assertExit(outcome, 1)
        self.assertEqual([(f["rule"], f["why"], f["line"]) for f in read_json(self.tmp / "o.json")["findings"]],
                         [("bad-argument", "test-only-dep", 3)])


CAT_LOAD = 'load("@gate//rules:c.bzl", "c_catalog", "c_library", "c_test")\n'
CAT = ('c_catalog(name = "cat", pots = ["a.pot", "b.pot"], po = {"bg": ["a.bg.po", "b.bg.po"]}, langs = ["bg", "en"],\n'
       '          source_lang = "en", symbol = "lk_cat", runtime = "//lib/fmt/i18n:i18n", visibility = ["PUBLIC"])\n')


class CatalogCase(TempDirTestCase):
    """T105: `c_catalog` takes literal strings, lists of strings and one dict of lists of strings, nothing else."""

    def check(self, source, code, files=None):
        root = self.sub("product")
        (root / "BUCK").write_text(source, encoding="utf-8")
        for rel, data in (files or {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(data, encoding="utf-8")
        self.assertExit(run_rigor(["buckfiles", "--root", root, "--out", self.tmp / "out.json"]), code)
        return sorted((f["rule"], f.get("why")) for f in read_json(self.tmp / "out.json")["findings"])

    def bad(self, source, why="value"):
        self.assertEqual(self.check(source, 1), [("bad-argument", why)])

    def test_the_literal_call_is_accepted(self):
        self.assertEqual(self.check(CAT_LOAD + CAT, 0), [])

    def test_more_languages_and_an_empty_dict_are_literal_too(self):
        self.assertEqual(self.check(CAT_LOAD + CAT.replace('{"bg": ["a.bg.po", "b.bg.po"]}', '{"bg": ["a"], "de": []}'), 0), [])
        self.setUp()
        self.assertEqual(self.check(CAT_LOAD + CAT.replace('{"bg": ["a.bg.po", "b.bg.po"]}', "{}"), 0), [])

    def test_a_same_package_runtime_is_accepted(self):
        self.assertEqual(self.check(CAT_LOAD + CAT.replace("//lib/fmt/i18n:i18n", ":i18n"), 0), [])

    def test_deps_are_checked_like_any_dep(self):
        self.assertEqual(self.check(CAT_LOAD + CAT.replace('visibility', 'deps = ["//lib/base/core:core", ":x"], visibility'), 0), [])
        self.setUp()
        self.bad(CAT_LOAD + CAT.replace('visibility', 'deps = ["gate//third_party/curl:curl"], visibility'), "dep")
        self.setUp()
        self.bad(CAT_LOAD + CAT.replace('visibility', 'deps = ":x", visibility'), "dep")

    def test_names_is_a_literal_string_dict(self):
        self.assertEqual(self.check(CAT_LOAD + CAT.replace('visibility', 'names = {"a": "B"}, visibility'), 0), [])
        for value in ('{"a": ["B"]}', '{"a": x}', '{"a": "B" + "C"}', '{k: "B"}', '{**x}', '["a"]', '"a"', 'dict(a = "B")'):
            with self.subTest(value=value):
                self.setUp()
                self.bad(CAT_LOAD + CAT.replace('visibility', 'names = %s, visibility' % value))

    def test_names_belongs_to_the_catalog_only(self):
        self.bad(CAT_LOAD + 'c_library(name = "a", names = {"a": "B"})\n', "keyword")

    def test_the_load_may_name_it(self):
        self.assertEqual(self.check('load("@gate//rules:c.bzl", "c_catalog")\n', 0), [])

    def test_a_computed_po_is_refused(self):
        for po in ('{"bg": glob(["*.po"])}', '{"bg": ["a"] + ["b"]}', '{k: ["a"]}', '{"bg": "a.po"}', '{**x}',
                   '{"bg": [x]}', '{"bg": ["a"], "bg" + "x": []}', 'dict(bg = ["a"])', '["a"]', '"a"'):
            with self.subTest(po=po):
                self.setUp()
                self.bad(CAT_LOAD + CAT.replace('{"bg": ["a.bg.po", "b.bg.po"]}', po))

    def test_a_dict_is_refused_anywhere_else(self):
        for key in ("pots", "langs", "symbol"):
            with self.subTest(key=key):
                self.setUp()
                self.bad(CAT_LOAD + 'c_catalog(name = "cat", %s = {"a": ["b"]})\n' % key)
        self.setUp()
        self.bad(CAT_LOAD + 'c_library(name = "a", srcs = {"a": ["b"]})\n')

    def test_computed_strings_are_refused(self):
        for key, value in (("pots", 'glob(["*.pot"])'), ("pots", '["a"] + ["b"]'), ("langs", "x"), ("symbol", '"a" + "b"'),
                           ("source_lang", "None"), ("symbol", "1"), ("pots", "[1]")):
            with self.subTest(key=key, value=value):
                self.setUp()
                self.bad(CAT_LOAD + 'c_catalog(name = "cat", %s = %s)\n' % (key, value))

    def test_runtime_must_be_one_string(self):
        for value in ('["//a:b"]', "x", '"a" + "b"'):
            with self.subTest(value=value):
                self.setUp()
                self.bad(CAT_LOAD + CAT.replace('"//lib/fmt/i18n:i18n"', value))

    def test_runtime_is_a_dep(self):
        for label in ("gate//third_party/curl:curl", "//a:b:c", "root//a:b", "@x//a:b", ""):
            with self.subTest(label=label):
                self.setUp()
                self.bad(CAT_LOAD + CAT.replace("//lib/fmt/i18n:i18n", label), "dep")

    def test_runtime_may_not_be_a_test(self):
        source = CAT_LOAD + CAT.replace("//lib/fmt/i18n:i18n", ":t") + 'c_test(name = "t", srcs = ["t.c"])\n'
        self.assertEqual(self.check(source, 1), [("bad-argument", "test-target")])

    def test_only_its_own_keywords(self):
        for extra in ('srcs = ["a.c"]', 'headers = ["a.h"]', 'compiler_flags = ["-w"]', "**{}", 'system_libs = ["pthread"]'):
            with self.subTest(extra=extra):
                self.setUp()
                self.bad(CAT_LOAD + 'c_catalog(name = "cat", %s)\n' % extra, "keyword")

    def test_its_keywords_are_not_the_others(self):
        for key in ("pots", "po", "langs", "source_lang", "symbol", "runtime"):
            with self.subTest(key=key):
                self.setUp()
                self.bad(CAT_LOAD + 'c_library(name = "a", %s = ["x"])\n' % key, "keyword")

    def test_positional_is_refused(self):
        self.bad(CAT_LOAD + 'c_catalog("cat")\n', "positional")

    def test_native_and_raw_calls_are_still_refused(self):
        self.assertEqual(self.check(CAT_LOAD + 'native.cxx_library(name = "a")\n', 1), [("bad-call", None)])

    def test_named_catalog_files_are_not_a_finding_here(self):
        self.assertEqual(self.check(CAT_LOAD + CAT, 0, files={"a.pot": "", "a.bg.po": ""}), [])
