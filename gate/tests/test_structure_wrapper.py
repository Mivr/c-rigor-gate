"""A translation unit that only includes product code (annas-c tests/kit.c): real clang ASTs in
fixtures/structure/<case>/ (sources, ast.json, includes.txt; the directory is `@D@`)."""

import json
import os
import shutil

from rigor_lib import structure_scan
from tests.helpers import GATE_DIR, TempDirTestCase

FIXTURES = GATE_DIR / "tests" / "fixtures" / "structure"
SYSTEM = "/usr/lib/clang/18/include"
DATA = ("ast.json", "includes.txt")


class WrapperCase(TempDirTestCase):
    def scan(self, case, src="tests/w.c", extra=None):
        base = str(self.sub(case))
        for name in os.listdir(FIXTURES / case):
            if name not in DATA:
                shutil.copytree(FIXTURES / case / name, os.path.join(base, name), dirs_exist_ok=True)
        if extra:
            with open(os.path.join(base, src), "a", encoding="utf-8") as handle:
                handle.write(extra)
        ast = json.loads((FIXTURES / case / "ast.json").read_text().replace("@D@", base))
        includes = (FIXTURES / case / "includes.txt").read_text().replace("@D@", base)
        files = structure_scan.Files([SYSTEM])
        return structure_scan.unit_facts("//t:t", os.path.join(base, src), ast, includes, files)

    def refused(self, case, src="tests/w.c", needle="blind", extra=None):
        with self.assertRaises(structure_scan.ScanError) as caught:
            self.scan(case, src, extra)
        self.assertIn(needle, str(caught.exception))


class AcceptedTest(WrapperCase):
    def test_a_kit_that_only_includes_its_implementation_is_scanned_through_it(self):
        facts = self.scan("kit", "tests/kit.c")
        self.assertEqual([f["name"] for f in facts["functions"]], ["kit_twice", "kit_sum"])
        self.assertTrue(all(f["file"].endswith("tests/kit_impl.h") for f in facts["functions"]))
        paths = sorted(x["path"].rsplit("/", 1)[1] for x in facts["files"])
        self.assertEqual(paths, ["kit.c", "kit_impl.h"])
        main = next(x for x in facts["files"] if x["path"].endswith("kit.c"))
        self.assertEqual(main["lines"], 3)

    def test_several_includes_with_spacing_and_comments_are_a_wrapper(self):
        facts = self.scan("kit_two")
        self.assertEqual(sorted(f["name"] for f in facts["functions"]), ["a_fn", "b_fn"])

    def test_the_same_functions_are_reported_once_per_unit_as_for_any_header(self):
        first = self.scan("kit", "tests/kit.c")
        self.assertEqual(len(first["functions"]), 2)


class RefusedTest(WrapperCase):
    def test_a_define_next_to_the_include_is_blind(self):
        self.refused("red_define")

    def test_a_pragma_next_to_the_include_is_blind(self):
        self.refused("red_pragma")

    def test_a_system_include_alone_is_blind(self):
        self.refused("red_system")

    def test_an_include_that_produced_no_location_is_blind(self):
        self.refused("red_nolocation", needle="produced no location")

    def test_an_empty_main_file_is_blind(self):
        self.refused("red_empty", needle="empty")

    def test_a_main_file_with_only_a_macro_is_blind(self):
        self.refused("red_macro")

    def test_scanning_a_file_the_dump_does_not_belong_to_is_blind(self):
        self.refused("wrong_file", src="tests/other.c")

    def test_an_include_of_a_file_the_compiler_did_not_read_is_blind(self):
        self.refused("kit", src="tests/kit.c", needle="never_read.h", extra='#include "tests/never_read.h"\n')


class StripCommentsTest(WrapperCase):
    def test_comments_become_blanks_and_strings_are_kept(self):
        text = '/* a */x// b\n"/*"y /**/\n'
        self.assertEqual(structure_scan.strip_comments(text).split(), ["x", '"/*"y'])

    def test_an_unterminated_comment_is_an_error(self):
        with self.assertRaises(structure_scan.ScanError):
            structure_scan.strip_comments("int x; /* open")
