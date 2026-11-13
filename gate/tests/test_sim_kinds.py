"""T2G1: a `c_sim` world is product code for every gate (kind matching): its facts are accepted, judged as a module,
and its build file is checked like any other. A product cannot hide code in a world."""

from rigor_lib import facts_data, grade_structure, guards_gate, policy_check, structure_data
from tests.helpers import TempDirTestCase, read_json, run_rigor
from tests import test_facts
from tests.test_facts import CTEST, GLOBAL, facts, unit

LOADS = 'load("@gate//rules:c.bzl", "c_sim", "c_library")\n'


class KindsCase(TempDirTestCase):
    run_gate = test_facts.FactsCase.run_gate   # the helper only; not the tests of that class

    def test_every_table_of_kinds_knows_c_sim(self):
        self.assertIn("c_sim", facts_data.KINDS)
        self.assertIn("c_sim", structure_data.KINDS)
        self.assertIn("c_sim", grade_structure.KINDS)
        self.assertIn("c_sim", policy_check.PRODUCT_KINDS)
        self.assertIn("c_sim", guards_gate.MODULE_KINDS)

    def test_a_c_sim_is_not_exempt_like_a_test(self):
        from rigor_lib import facts_symbols, profiles
        self.assertNotIn("c_sim", structure_data.EXEMPT_KINDS)
        self.assertNotIn("c_sim", facts_symbols.TEST_KINDS)
        self.assertNotIn("c_sim", profiles.TEST_KINDS)

    def test_a_denied_symbol_in_a_world_is_a_finding(self):
        world = facts("//p:sim", [unit(defined=["toy_variant"], undefined=["kill"])], kind="c_sim")
        policy = GLOBAL + '[module."//p:sim"]\nexports = ["toy_variant"]\n'
        outcome, result = self.run_gate("symbols", [world, CTEST], policy=policy, expect_code=1)
        self.assertEqual([(f["rule"], f["symbol"]) for f in result["findings"]], [("denied-symbol", "kill")])

    def test_a_world_without_a_policy_entry_is_refused(self):
        world = facts("//p:sim", [unit(defined=["toy_variant"])], kind="c_sim")
        outcome, result = self.run_gate("symbols", [world, CTEST], policy=GLOBAL, expect_code=1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["module-not-in-policy"])

    def test_a_world_with_writable_data_needs_the_policy_to_allow_it(self):
        data = [("g_world", 64, "bss", True)]
        world = facts("//p:sim", [unit(defined=["toy_variant"], data=data)], kind="c_sim")
        policy = GLOBAL + '[module."//p:sim"]\nexports = ["toy_variant"]\n'
        outcome, result = self.run_gate("symbols", [world, CTEST], policy=policy, expect_code=1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["mutable-data"])
        outcome, result = self.run_gate("symbols", [world, CTEST], policy=policy + "allow_mutable_data = true\n",
                                        expect_code=0)

    def test_the_semantic_gate_scans_a_world(self):
        world = facts("//p:sim", [unit(pragmas=[(3, 'clang diagnostic ignored "-Wall"')])], kind="c_sim")
        outcome, result = self.run_gate("semantic-suppressions", [world, CTEST], expect_code=1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["pragma"])

    def test_an_unknown_kind_is_still_an_error(self):
        world = facts("//p:sim", [unit()], kind="c_simulation")
        outcome, _ = self.run_gate("symbols", [world, CTEST])
        self.assertEqual(outcome.code, 2)


class BuckFileCase(TempDirTestCase):
    def check(self, text, code):
        root = self.sub("product")
        (root / "BUCK").write_text(text, encoding="utf-8")
        self.assertExit(run_rigor(["buckfiles", "--root", root, "--out", self.tmp / "out.json"]), code)
        return sorted((f["rule"], f.get("why")) for f in read_json(self.tmp / "out.json")["findings"])

    def test_a_world_with_literal_budgets_is_accepted(self):
        self.assertEqual(self.check(LOADS + 'c_sim(name = "s", srcs = ["w.c"], deps = [":l"], seeds = 20, run_ms = 5000, shards = 2)\n', 0), [])

    def test_budgets_must_be_int_literals_and_srcs_never_a_glob(self):
        for tail in ('seeds = "20"', 'seeds = 2 * 10', 'run_ms = None', 'shards = [2]', 'srcs = glob(["*.c"])',
                     'compiler_flags = ["-O3"]', 'corpus = ["a"]', 'runs = 5'):
            with self.subTest(tail=tail):
                self.setUp()
                found = self.check(LOADS + 'c_sim(name = "s", srcs = ["w.c"], %s)\n' % tail.replace('srcs = ["w.c"], ', ""), 1) \
                    if tail.startswith("srcs") else self.check(LOADS + 'c_sim(name = "s", srcs = ["w.c"], %s)\n' % tail, 1)
                self.assertEqual({rule for rule, _ in found}, {"bad-argument"})

    def test_budget_keywords_belong_to_c_sim_only(self):
        self.assertEqual({rule for rule, _ in self.check(LOADS + 'c_library(name = "l", srcs = ["l.c"], seeds = 3)\n', 1)},
                         {"bad-argument"})
