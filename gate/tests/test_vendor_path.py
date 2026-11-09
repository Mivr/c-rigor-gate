"""T133: a file is gate-owned third-party code only when the compiler read it from the output tree of the gate's
cell, right after `buck-out/<version>`. A product directory that carries the fragment is the product's."""

import unittest

from rigor_lib import cscan, mutants_gate, structure_scan

PRODUCT_MARKER = "/art/gate/third_party/"   # a product grade: the gate is a cell of its own
GATE_ROOT_MARKER = "/art/root/third_party/"  # the gate's own selftests: the gate is the root cell
REAL = "buck-out/v2/art/gate/third_party/mbedtls/__mbedtls_headers__/0123456789abcdef/buck-headers/mbedtls/ssl.h"
SPOOF = "buck-out/v2/art/root/core/art/gate/third_party/__core__/0123456789abcdef/buck-headers/core/spoof.h"
SPOOF_HEADERS = "buck-out/v2/art/root/core/__core__/0123456789abcdef/buck-headers/core/art/gate/third_party/spoof.h"
UNKNOWN = ["core/art/gate/third_party/spoof.h", "/work/art/gate/third_party/x.h",
           "/work/tree/art/gate/third_party/x.h", "buck-out", "buck-out/v2", "x/buck-out"]


def collectors(markers):
    return [cscan.Collector([], markers), structure_scan.Files([], markers)]


class VendorPathTest(unittest.TestCase):
    def each(self, markers):
        return collectors(markers)

    def test_the_real_third_party_tree_in_a_product_grade(self):
        for scanner in self.each([PRODUCT_MARKER]):
            self.assertTrue(scanner.is_system(REAL))
            self.assertTrue(scanner.is_system("/work/tree/" + REAL))   # absolute below the project root

    def test_the_same_when_the_gate_is_the_root_cell(self):
        path = REAL.replace("/art/gate/", "/art/root/")
        for scanner in self.each([GATE_ROOT_MARKER]):
            self.assertTrue(scanner.is_system(path))
            self.assertFalse(scanner.is_system(REAL))   # another cell's tree

    def test_a_product_directory_named_like_the_tree_is_not_exempt(self):
        for scanner in self.each([PRODUCT_MARKER]):
            self.assertFalse(scanner.is_system(SPOOF))
            self.assertFalse(scanner.is_system(SPOOF_HEADERS))
            self.assertFalse(scanner.is_system("/work/tree/" + SPOOF_HEADERS))
            self.assertFalse(scanner.is_system("buck-out/v2/art/root/buck-out/v2/art/gate/third_party/x.h"))

    def test_a_path_with_no_recognisable_layout_is_product_code(self):
        for scanner in self.each([PRODUCT_MARKER]):
            for path in UNKNOWN:
                self.assertFalse(scanner.is_system(path), path)

    def test_the_other_kind_or_cell_is_not_the_tree(self):
        for scanner in self.each([PRODUCT_MARKER]):
            self.assertFalse(scanner.is_system("buck-out/v2/art/other/third_party/x.h"))
            self.assertFalse(scanner.is_system("buck-out/v2/art/gate/third_partyx/x.h"))

    def test_the_library_name_is_read_from_the_anchored_path_only(self):
        files = structure_scan.Files([], [PRODUCT_MARKER])
        self.assertEqual(files.vendor_lib(REAL), "mbedtls")
        self.assertIsNone(files.vendor_lib(SPOOF))
        self.assertIsNone(files.vendor_lib("buck-out/v2/art/gate/third_party/"))

    def test_the_two_scanners_decide_alike(self):
        for path in (REAL, SPOOF, SPOOF_HEADERS, "/w/" + REAL, "x.h", "buck-out/v2/art/gate/third_party/"):
            self.assertEqual(cscan.vendor_tail(path, [PRODUCT_MARKER]),
                             structure_scan.vendor_tail(path, [PRODUCT_MARKER]), path)

    def test_a_spoofed_header_text_is_judged_as_the_products(self):
        text = '# 1 "%s" 1\n#pragma clang diagnostic ignored "-Wall"\n__attribute__((no_sanitize("address"))) int f;\n' % SPOOF_HEADERS
        collector = cscan.Collector([], [PRODUCT_MARKER])
        collector.scan(text)
        self.assertEqual(len(collector.pragmas), 1)
        self.assertTrue(collector.attributes)
        real = cscan.Collector([], [PRODUCT_MARKER])
        real.scan(text.replace(SPOOF_HEADERS, REAL))
        self.assertFalse(real.pragmas)

    def test_the_mutation_generator_decides_by_cell_not_by_fragment(self):
        packages = frozenset(["core"])
        self.assertTrue(mutants_gate.outside_product(REAL, packages))
        self.assertFalse(mutants_gate.outside_product(SPOOF, packages))
        self.assertFalse(mutants_gate.outside_product(SPOOF_HEADERS, packages))
        self.assertFalse(mutants_gate.outside_product("/work/tree/" + SPOOF_HEADERS, packages))
        self.assertFalse(mutants_gate.outside_product("core/art/gate/third_party/spoof.h", packages))
