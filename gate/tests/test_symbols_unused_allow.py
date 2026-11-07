"""T085: `unused-allow` (info) in the symbols gate: policy entries that no object references or a dep already covers."""

from tests.helpers import TempDirTestCase
from tests import test_facts
from tests.test_facts import CTEST, GLOBAL, facts, unit


class UnusedAllow(TempDirTestCase):
    run_gate = test_facts.FactsCase.run_gate

    def findings(self, targets, policy):
        outcome, result = self.run_gate("symbols", targets + [CTEST], policy=GLOBAL + policy, expect_code=0)
        return result, sorted((f["symbol"], f["list"], f["reason"]) for f in result["findings"]
                              if f["rule"] == "unused-allow")

    def mod(self, undefined=(), deps=(), kind="c_library", label="//p:lib"):
        return facts(label, [unit(defined=["f"], undefined=undefined)], deps=deps, kind=kind)

    def test_a_used_entry_is_not_reported(self):
        result, found = self.findings([self.mod(undefined=["memcpy"])], '[module."//p:lib"]\nallow = ["memcpy"]\n')
        self.assertEqual(found, [])
        self.assertEqual(result["findings"], [])

    def test_an_unreferenced_entry_is_reported_as_info_and_stays_a_pass(self):
        result, found = self.findings([self.mod(undefined=["memcpy"])],
                                      '[module."//p:lib"]\nallow = ["memcpy", "bcmp", "abs"]\n')
        self.assertEqual(found, [("abs", "allow", "not referenced"), ("bcmp", "allow", "not referenced")])
        self.assertEqual({f["severity"] for f in result["findings"]}, {"info"})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([f["target"] for f in result["findings"]], ["//p:lib"] * 2)

    def test_a_header_only_module_reports_every_entry(self):
        header = facts("//p:hdr", [])
        _, found = self.findings([header], '[module."//p:hdr"]\nallow = ["memcpy", "bcmp"]\n')
        self.assertEqual(found, [("bcmp", "allow", "not referenced"), ("memcpy", "allow", "not referenced")])

    def test_an_entry_a_dep_already_exports_is_covered(self):
        lib = self.mod(undefined=["ctest_run", "memcpy"], deps=["//ctest:ctest"])
        result, found = self.findings([lib], '[module."//p:lib"]\nallow = ["ctest_run", "memcpy"]\n')
        self.assertEqual(found, [("ctest_run", "allow", "covered by //ctest:ctest")])
        self.assertEqual(result["status"], "PASS")

    def test_an_entry_the_module_defines_itself_is_not_referenced(self):
        _, found = self.findings([self.mod(undefined=["f"])], '[module."//p:lib"]\nallow = ["f"]\n')
        self.assertEqual(found, [("f", "allow", "not referenced")])

    def test_deny_exempt_used_is_quiet_and_unused_is_reported(self):
        policy = '[module."//p:lib"]\ndeny_exempt = ["open", "fopen"]\n'
        result, found = self.findings([self.mod(undefined=["open"])], policy)
        self.assertEqual(found, [("fopen", "deny_exempt", "not referenced")])
        self.assertEqual(result["status"], "PASS")

    def test_a_real_error_still_fails_and_keeps_its_own_finding(self):
        outcome, result = self.run_gate("symbols", [self.mod(undefined=["bcmp"]), CTEST],
                                        policy=GLOBAL + '[module."//p:lib"]\nallow = ["abs"]\n', expect_code=1)
        self.assertEqual(sorted((f["rule"], f["severity"]) for f in result["findings"]),
                         [("undeclared-symbol", "error"), ("unused-allow", "info")])


del test_facts   # the base class is borrowed for run_gate only; the loader must not collect it again here
