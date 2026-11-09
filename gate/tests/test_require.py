"""T128: `gate//rt:require` is accepted by every gate that looks at dependencies, and by nothing wider."""

import json
import unittest
from types import SimpleNamespace

from rigor_lib import facts_rt, facts_third_party, layering, layering_check, structure
from tests.helpers import GATE_DIR, TempDirTestCase, read_json, run_rigor
from tests.test_facts import CTEST, GLOBAL, LIBC, POLICY, facts, unit
from tests.test_layering import GOOD, THIRD, mod, world

LOAD = 'load("@gate//rules:c.bzl", "c_binary", "c_catalog", "c_fuzz", "c_library", "c_test")\n'
REQUIRE = "gate//rt:require"


def trap_unit(file=facts_rt.HEADER, name="__builtin_trap"):
    document = unit(identifiers=[(name, 12)])
    document["identifiers"][0]["file"] = file
    return document


class BuckFiles(TempDirTestCase):
    def rules(self, source):
        root = self.sub("product")
        (root / "BUCK").write_text(LOAD + source, encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["buckfiles", "--root", root, "--out", out])
        return outcome.code, sorted(f["rule"] for f in read_json(out)["findings"]
                      if f["rule"] != "unused-allow")   # info, tested apart

    def test_a_library_a_binary_and_a_test_may_name_it(self):
        for macro in ("c_library", "c_binary", "c_test"):
            with self.subTest(macro=macro):
                self.assertEqual(self.rules('%s(name = "a", srcs = ["a.c"], deps = ["%s", ":b"])\n' % (macro, REQUIRE)),
                                 (0, []))

    def test_a_library_may_export_it(self):
        self.assertEqual(self.rules('c_library(name = "a", srcs = ["a.c"], exported_deps = ["%s"])\n' % REQUIRE),
                         (0, []))

    def test_nothing_else_of_the_gate_cell_is_accepted(self):
        for label in ("gate//rt:require2", "gate//rt:other", "gate//ctest:perf", "gate//ctest:ctest",
                      "gate//rt:require_facts", "gate//rt/sub:require", "gate//rt:Require", "gate//rt:require "):
            with self.subTest(label=label):
                self.assertEqual(self.rules('c_library(name = "a", srcs = ["a.c"], deps = ["%s"])\n' % label),
                                 (1, ["bad-argument"]))

    def test_other_macros_may_not_name_it(self):
        for call in ('c_fuzz(name = "f", srcs = ["f.c"], deps = ["%s"])' % REQUIRE,
                     'c_catalog(name = "c", pots = ["a.pot"], po = {}, langs = ["en"], source_lang = "en", '
                     'symbol = "c", runtime = "%s")' % REQUIRE):
            with self.subTest(call=call):
                code, rules = self.rules(call + "\n")
                self.assertEqual((code, rules), (1, ["bad-argument"]))

    def test_a_test_derived_label_is_still_not_a_dep(self):
        self.assertEqual(self.rules('c_test(name = "t", srcs = ["t.c"])\n'
                                    'c_library(name = "a", srcs = ["a.c"], deps = [":t_facts"])\n')[0], 1)


class Gates(TempDirTestCase):
    """`rigor facts` on hand-made facts."""

    def rules(self, gate, targets, code, policy=POLICY):
        fdir = self.sub("facts")
        for index, document in enumerate(targets):
            (fdir / ("f%d.json" % index)).write_text(json.dumps(document), encoding="utf-8")
        (self.tmp / "policy.toml").write_text(policy, encoding="utf-8")
        (self.tmp / "libc.symbols").write_text(LIBC, encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["facts", "--gate", gate, "--facts", fdir, "--policy", self.tmp / "policy.toml",
                             "--libc", self.tmp / "libc.symbols", "--out", out])
        if code is not None:
            self.assertExit(outcome, code)
        return sorted((f["rule"], f.get("name") or f.get("dep") or f.get("target")) for f in read_json(out)["findings"]
                      if f["rule"] != "unused-allow")   # info, tested apart


class Semantic(Gates):
    def sem(self, units, deps=(), label="//p:lib", policy=POLICY):
        return self.rules("semantic-suppressions", [facts(label, units, deps=deps), CTEST], None, policy)

    def test_the_trap_in_the_gates_header_is_not_the_products(self):
        for dep in (REQUIRE, "//rt:require"):
            with self.subTest(dep=dep):
                self.assertEqual(self.sem([trap_unit()], [dep]), [])

    def test_without_the_dependency_it_is_judged_as_before(self):
        self.assertEqual(self.sem([trap_unit()]), [("forbidden-builtin", "__builtin_trap")])

    def test_another_file_is_judged_as_before(self):
        for file in ("p/a.c", "p/rt/require.h", "other/rt/require.h", "rt/require.hh"):
            with self.subTest(file=file):
                self.assertEqual(self.sem([trap_unit(file)], [REQUIRE]), [("forbidden-builtin", "__builtin_trap")])

    def test_another_builtin_in_the_header_is_judged_as_before(self):
        self.assertEqual(self.sem([trap_unit(name="__builtin_unreachable")], [REQUIRE]),
                         [("forbidden-builtin", "__builtin_unreachable")])

    def test_a_product_that_traps_itself_is_judged_as_before(self):
        both = unit(identifiers=[("__builtin_trap", 7)])
        both["identifiers"].append(trap_unit()["identifiers"][0])
        self.assertEqual(self.sem([both], [REQUIRE]), [("forbidden-builtin", "__builtin_trap")])

    def test_allow_builtins_is_not_needed_and_still_works(self):
        policy = '[global]\ndeny = ["kill"]\ntrusted = ["//ctest:ctest"]\n[module."//p:lib"]\nallow_builtins = ["__builtin_trap"]\n'
        self.assertEqual(self.sem([trap_unit("p/a.c")], [REQUIRE], policy=policy), [])

    def test_the_facts_of_the_library_are_not_a_module(self):
        library = facts("//rt:require", [])
        self.assertEqual(self.rules("semantic-suppressions", [facts("//p:lib", [trap_unit()], deps=[REQUIRE]),
                                                              library, CTEST], 0), [])


class Symbols(Gates):
    def test_no_facts_and_no_policy_entry_needed(self):
        found = self.rules("symbols", [facts("//p:lib", [unit(defined=["lib_f"])], deps=[REQUIRE]), CTEST], 0)
        self.assertEqual(found, [])

    def test_its_facts_may_be_present(self):
        for label in ("//rt:require", REQUIRE):
            with self.subTest(label=label):
                found = self.rules("symbols", [facts("//p:lib", [unit(defined=["lib_f"])], deps=["//rt:require"]),
                                                 facts(label, []), CTEST], 0)
                self.assertEqual(found, [])

    def test_any_other_dep_without_facts_is_still_a_finding(self):
        found = self.rules("symbols", [facts("//p:lib", [unit(defined=["lib_f"])], deps=["gate//rt:other"]), CTEST], 1)
        self.assertEqual(found, [("missing-dep-facts", "gate//rt:other")])


class Layering(unittest.TestCase):
    def test_its_facts_are_outside_the_contract(self):
        library = mod("//rt:require", [], [])
        world_ = world(mod("//lib/base/core:core", ["//rt:require"], ["core_add"]), library)
        result = layering_check.run(world_, layering.load(GOOD), frozenset(), THIRD)
        self.assertEqual([f["rule"] for f in result.findings if f["rule"] != "contract-stale"], [])
        self.assertEqual(result.metadata["modules"], 1)


class Structure(unittest.TestCase):
    def test_no_facts_needed(self):
        deps = {"//p:lib": SimpleNamespace(deps=("//rt:require", "gate//rt:require"))}
        self.assertEqual(structure.consistency_findings(deps, {"//p:lib": "L3"}, frozenset()), [])

    def test_other_gate_like_labels_still_need_facts(self):
        deps = {"//p:lib": SimpleNamespace(deps=("//rt:require_x", "//rt:other"))}
        found = structure.consistency_findings(deps, {"//p:lib": "L3"}, frozenset())
        self.assertEqual(sorted(f["dep"] for f in found), ["//rt:other", "//rt:require_x"])


class Labels(unittest.TestCase):
    def test_spellings(self):
        self.assertTrue(facts_rt.is_require("//rt:require") and facts_rt.is_require(REQUIRE))
        self.assertFalse(any(facts_rt.is_require(x) for x in ("//rt:require2", "rt:require", "x//rt:require", "")))

    def test_split_drops_it_and_keeps_the_rest(self):
        got = facts_third_party.split({"//rt:require": SimpleNamespace(kind="c_library"),
                                       "//p:lib": SimpleNamespace(kind="c_library")}, THIRD)
        self.assertEqual((sorted(got[0]), got[1], got[2]), (["//p:lib"], {}, []))


if __name__ == "__main__":
    unittest.main()
