"""Layout coverage (B14): product code the layout leaves out is a finding."""

import unittest

from rigor_lib import product_layout as pl
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase


class Coverage(TempDirTestCase):
    def config(self, include, exclude=()):
        text = 'name = "p"\n[layout]\ninclude = %s\nexclude = %s\n' % (
            str(list(include)).replace("'", '"'), str(list(exclude)).replace("'", '"'))
        path = self.tmp / "product.toml"
        path.write_text(text, encoding="utf-8")
        return pl.load_product(str(path))

    def run_case(self, files, include=("core/**",), exclude=(), bucks=()):
        entries = [(f, "100644") for f in files]
        return pl.coverage_findings(self.config(include, exclude), entries, list(bucks))

    def rules(self, *args, **kwargs):
        return sorted((rule, path) for rule, path, _ in self.run_case(*args, **kwargs))

    def test_clean_layout_has_no_findings(self):
        self.assertEqual(self.rules(["core/BUCK", "core/a.c", "docs/a.md", "plan/t.md"]), [])

    def test_unlisted_module_directory(self):
        self.assertEqual(self.rules(["core/BUCK", "app/BUCK", "app/src/x.c"]),
                         [("ungraded-path", "app/BUCK"), ("ungraded-path", "app/src/x.c")])

    def test_odd_extensions_and_case(self):
        for name in ("a/X.C", "a/x.H", "a/x.inc", "a/x.def", "a/x.cpp", "a/x.S", "a/x.c.", "a/BUCK.v2",
                     "a/buck", "a/TARGETS", "a/PACKAGE"):
            self.assertEqual(self.rules(["core/x.c", name]), [("ungraded-path", name)], name)

    def test_file_named_in_buck_srcs_is_code_whatever_its_name(self):
        buck = ("core/BUCK", 'c_library(name = "x", srcs = ["../docs/payload.txt", "ok.txt", ":dep"])')
        files = ["core/BUCK", "core/ok.txt", "docs/payload.txt"]
        self.assertEqual(self.rules(files, bucks=[buck]),
                         [("ungraded-path", "docs/payload.txt")])
        # the same, single quoted, nested deeper
        buck = ("core/sub/BUCK", "c_library(srcs = ['../../docs/payload.txt'])")
        self.assertEqual(self.rules(["core/sub/BUCK", "docs/payload.txt"], bucks=[buck]),
                         [("ungraded-path", "docs/payload.txt")])

    def test_c_file_under_excluded_docs_is_excluded_code(self):
        self.assertEqual(self.rules(["core/x.c", "core/docs/x.c", "core/docs/BUCK"], exclude=["core/docs/**"]),
                         [("excluded-code", "core/docs/BUCK"), ("excluded-code", "core/docs/x.c")])

    def test_module_in_directory_named_like_an_exclude(self):
        self.assertEqual(self.rules(["core/fixtures/m/BUCK"], include=["core/**"], exclude=["**/fixtures/**"]),
                         [("excluded-code", "core/fixtures/m/BUCK")])

    def test_exclude_of_non_code_is_fine(self):
        self.assertEqual(self.rules(["core/x.c", "core/docs/a.md"], exclude=["core/docs/**"]), [])

    def test_stale_include(self):
        self.assertEqual(self.rules(["core/x.c"], include=["core/**", "html/**"]), [("stale-include", "html/**")])

    def test_include_naming_gate_excluded_paths_is_inert_not_stale(self):
        self.assertEqual(self.rules(["core/x.c"], include=["core/**", ".buckconfig", "tools/**"]), [])

    def test_code_under_gate_excluded_paths_is_ignored_code(self):
        files = ["core/x.c", "third_party/z/z.c", "third_party/z/BUCK", "Tools/y.c", "prelude/p.h"]
        self.assertEqual(self.rules(files), [("ignored-code", "Tools/y.c"), ("ignored-code", "prelude/p.h"),
                                             ("ignored-code", "third_party/z/BUCK"),
                                             ("ignored-code", "third_party/z/z.c")])

    def test_gate_exclusion_also_catches_other_letter_case(self):
        self.assertTrue(pl.is_gate_excluded("THIRD_PARTY/x"))
        self.assertTrue(pl.is_gate_excluded("a/.BUCKCONFIG"))
        self.assertFalse(pl.is_gate_excluded("core/tools/x.c"))

    def test_case_only_collision(self):
        self.assertEqual(self.rules(["core/a.c", "core/A.c"]),
                         [("case-collision", "core/A.c"), ("case-collision", "core/a.c")])

    def test_unicode_form_collision(self):
        self.assertEqual(len(self.rules(["core/é.c", "core/é.c"])), 2)

    def test_submodule_is_ungraded_unless_it_is_the_gate(self):
        config = self.config(["core/**"])
        found = pl.coverage_findings(config, [("core/x.c", "100644"), ("gate", "160000"), ("vendor", "160000"),
                                               ("core/sub", "160000")], [])
        self.assertEqual(sorted((r, p) for r, p, _ in found),
                         [("ungraded-path", "core/sub"), ("ungraded-path", "vendor")])

    def test_symlinks_are_judged_by_name(self):
        config = self.config(["core/**"])
        found = pl.coverage_findings(config, [("core/x.c", "100644"), ("app/hidden.c", "120000"),
                                               ("CLAUDE.md", "120000")], [])
        self.assertEqual([(r, p) for r, p, _ in found], [("ungraded-path", "app/hidden.c")])

    def test_third_party_is_always_excluded(self):
        self.assertIn("third_party/**", pl.ALWAYS_EXCLUDED)

    def test_bad_globs_still_internal_errors(self):
        with self.assertRaises(InternalError):
            self.config(["a/**b"])


if __name__ == "__main__":
    unittest.main()
