"""T055: in `rigor grade` the symbols gate reads the policy whole, `level` included (B32 follow-up).

The module level arms the `exports` check: L1 exempt, L2 reports a missing list, L3 and above fail on it, and a
table with neither `level` nor `exports` stays the legacy, unchecked case.
"""

import json
import os
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_checks
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase
from tests.test_facts import CTEST, GLOBAL, LIBC, facts, unit


class GradedSymbolsGate(TempDirTestCase):
    def graded(self, table):
        """The symbols gate's result for a graded run whose policy has `table` for //p:lib."""
        product = self.sub("products/p")
        (product / "product.toml").write_text("name = \"p\"\n", encoding="utf-8")
        (product / "policy.toml").write_text(GLOBAL + '[module."//p:lib"]\n' + table, encoding="utf-8")
        fdir = self.sub("built/facts")
        for name, document in (("a.json", facts("//p:lib", [unit(defined=["f"])])), ("b.json", CTEST)):
            (fdir / name).write_text(json.dumps(document), encoding="utf-8")
        libc = self.tmp / "built" / "libc.symbols"
        libc.write_text(LIBC, encoding="utf-8")
        g = SimpleNamespace(args=SimpleNamespace(product=str(product / "product.toml")),
                            work=str(self.sub("work")), status={"assemble": "PASS"})
        built = grade_checks.FactsBuild(str(fdir), str(libc), {})
        with mock.patch.object(grade_checks, "build_facts", return_value=built):
            return grade_checks.symbols_gate(g)

    def rules(self, result):
        return sorted((f["rule"], f["severity"]) for f in result.findings)

    def test_l3_without_a_list_fails_the_graded_symbols_gate(self):
        result = self.graded('level = "L3"\n')
        self.assertEqual(self.rules(result), [("exports-missing", "error")])
        self.assertEqual(result.status, "FAIL")

    def test_l4_and_l5_fail_too(self):
        for level in ("L4", "L5"):
            self.assertEqual(self.graded('level = "%s"\n' % level).status, "FAIL", level)

    def test_l2_without_a_list_is_only_info(self):
        result = self.graded('level = "L2"\n')
        self.assertEqual(self.rules(result), [("exports-missing", "info")])
        self.assertEqual(result.status, "PASS")

    def test_l1_is_exempt(self):
        self.assertEqual(self.graded('level = "L1"\n').findings, [])

    def test_a_table_with_neither_level_nor_exports_is_legacy_and_unchecked(self):
        self.assertEqual(self.graded("allow = []\n").findings, [])

    def test_an_exports_list_is_still_compared_at_l3(self):
        self.assertEqual(self.graded('level = "L3"\nexports = ["f"]\n').findings, [])
        result = self.graded('level = "L3"\nexports = ["g"]\n')
        self.assertEqual(self.rules(result), [("unexpected-export", "error")])

    def test_a_malformed_level_is_an_internal_error_never_unchecked(self):
        for level in ('"L0"', '"l3"', "3", '["L3"]'):
            with self.assertRaises(InternalError, msg=level):
                self.graded("level = %s\n" % level)
