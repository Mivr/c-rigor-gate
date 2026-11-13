"""Unit tests of the `mutants` step of `rigor grade` that need no Buck2 (selftest/grade.sh has the rest).

The step decides three things the product must not be able to influence: which modules are mutated
(the gate-owned policy levels), which tests run against a module's mutants (the tests of the module's own
package that depend on it directly, found by a query in the tree), and whether "nothing was mutated" passes (never).
"""

import json
import os
import shutil
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

from rigor_lib import facts_policy, grade_build, grade_context, grade_mutants, grade_pipeline, grade_policy, verdict
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase


def layout(libs=(), binaries=(), tests=None, deps=None, external=()):
    """A product layout: `tests` maps a test label to its direct deps; `deps` maps a library to its deps."""
    tests = tests or {}
    graph = dict(deps or {})
    graph.update({t: tuple(d) for t, d in tests.items()})
    for label in tuple(libs) + tuple(external):
        graph.setdefault(label, ())
    own = {label: tuple(d for d in deps if d.startswith("//")) for label, deps in graph.items() if label.startswith("//")}
    return grade_mutants.Layout(frozenset(libs), frozenset(binaries), frozenset(tests), own, frozenset(external), graph)


def rules(found):
    return sorted((f["rule"], f.get("module", f.get("target"))) for f in found)


class Planning(unittest.TestCase):
    def test_tests_are_the_ones_of_the_module_s_own_package_that_depend_on_it_directly(self):
        lay = layout(libs=["//a:a", "//b:b"],
                     tests={"//a:t1": ["//a:a"], "//a:t0": [], "//b:t2": ["//b:b"], "//b:t3": ["//a:a", "//b:b"]},
                     deps={"//b:b": ("//a:a",)})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//b:b": "L2"})
        self.assertEqual(plan.findings, [])
        by_label = {m.label: m for m in plan.modules}
        # not //b:t3: it lists a directly, but from another package; not //a:t0: own package, but it does not list a
        self.assertEqual(by_label["//a:a"].tests, ("//a:t1",))
        self.assertEqual(by_label["//b:b"].tests, ("//b:t2", "//b:t3"))
        self.assertEqual(grade_mutants.direct_tests(lay, "//a:a"), ("//a:t1", "//b:t3"))

    def test_own_package_means_the_same_package_exactly_not_a_parent_child_or_prefix(self):
        tests = {"//a:t": ["//a:a"], "//a/sub:t": ["//a:a"], "//ab:t": ["//a:a"], "//:t": ["//a:a"]}
        lay = layout(libs=["//a:a", "//a/sub:s"], tests=dict(tests, **{"//a/sub:own": ["//a/sub:s"], "//a:up": ["//a/sub:s"]}))
        self.assertEqual(grade_mutants.own_tests(lay, "//a:a"), ("//a:t",))
        self.assertEqual(grade_mutants.own_tests(lay, "//a/sub:s"), ("//a/sub:own",))

    def test_a_module_listed_only_by_tests_of_other_packages_is_a_module_without_tests(self):
        lay = layout(libs=["//a:a", "//b:b"], tests={"//b:t": ["//a:a", "//b:b"], "//c:t": ["//a:a"]})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//b:b": "L3"})
        self.assertEqual([(f["rule"], f["severity"], f["module"], f["foreign_tests"]) for f in plan.findings],
                         [("module-without-tests", "error", "//a:a", 2)])
        self.assertEqual([m.label for m in plan.modules], ["//b:b"])   # never mutated without a test that counts

    def test_a_foreign_test_and_what_only_it_links_are_no_input_of_the_module_s_mutants(self):
        """An edit in //big:big must not change the `c_mutants` call of //a:a (its action keys): only the foreign
        test links it. //own:dep is linked by a's own test, so it stays."""
        def planned(big_deps):
            lay = layout(libs=["//a:a", "//big:big", "//own:dep", "//far:far"],
                         tests={"//a:t": ["//a:a", "//own:dep"], "//big:t": ["//big:big", "//a:a"]},
                         deps={"//big:big": big_deps})
            return grade_mutants.plan(lay, {"//a:a": "L3", "//big:big": "L3", "//own:dep": "L1", "//far:far": "L1"})
        first, second = planned(("//a:a",)), planned(("//a:a", "//far:far"))
        module = {m.label: m for m in first.modules}["//a:a"]
        self.assertEqual((module.tests, module.deps), (("//a:t",), ("//own:dep",)))
        text = [grade_mutants.build_file_text([m for m in p.modules if m.label == "//a:a"]) for p in (first, second)]
        self.assertEqual(text[0], text[1])
        self.assertNotIn("big", text[0])
        self.assertIn("//b", grade_mutants.build_file_text([m for m in first.modules if m.label == "//big:big"]))

    def test_a_test_that_reaches_the_module_only_through_another_library_is_not_selected(self):
        lay = layout(libs=["//a:a", "//b:b"], tests={"//b:t": ["//b:b"]}, deps={"//b:b": ("//a:a",)})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//b:b": "L1"})
        self.assertEqual(rules(plan.findings), [("module-without-tests", "//a:a")])
        self.assertEqual(plan.modules, [])

    def test_a_module_without_a_level_is_a_finding_and_is_not_mutated(self):
        lay = layout(libs=["//a:a", "//b:b"], tests={"//a:t": ["//a:a"], "//b:t": ["//b:b"]})
        plan = grade_mutants.plan(lay, {"//a:a": "L3"})
        self.assertEqual(rules(plan.findings), [("level-missing", "//b:b")])
        self.assertEqual([m.label for m in plan.modules], ["//a:a"])

    def test_level_one_is_not_mutated_and_is_not_a_finding(self):
        lay = layout(libs=["//a:a", "//b:b"], tests={"//a:t": ["//a:a"], "//b:t": ["//b:b"]})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//b:b": "L1"})
        self.assertEqual(plan.findings, [])
        self.assertEqual([m.label for m in plan.modules], ["//a:a"])

    def test_levels_two_to_five_are_all_mutated_with_their_level(self):
        libs = ["//a:l%d" % n for n in (2, 3, 4, 5)]
        lay = layout(libs=libs, tests={"//a:t%d" % n: ["//a:l%d" % n] for n in (2, 3, 4, 5)})
        plan = grade_mutants.plan(lay, {"//a:l%d" % n: "L%d" % n for n in (2, 3, 4, 5)})
        self.assertEqual([(m.label, m.level) for m in plan.modules],
                         [("//a:l2", "L2"), ("//a:l3", "L3"), ("//a:l4", "L4"), ("//a:l5", "L5")])

    def test_a_binary_needs_a_level_and_cannot_be_mutated(self):
        lay = layout(libs=["//a:a"], binaries=["//app:app", "//app:other"], tests={"//a:t": ["//a:a"]})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//app:app": "L2"})
        self.assertEqual(rules(plan.findings), [("level-missing", "//app:other"), ("unmutatable-module", "//app:app")])
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//app:app": "L1", "//app:other": "L1"})
        self.assertEqual(plan.findings, [])

    def test_a_level_on_a_test_is_a_finding(self):
        lay = layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//a:t": "L3"})
        self.assertEqual(rules(plan.findings), [("level-on-test", "//a:t")])

    def test_nothing_to_mutate_is_a_finding(self):
        for lay, levels in ((layout(), {}),
                            (layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]}), {"//a:a": "L1"}),
                            (layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]}), {})):
            plan = grade_mutants.plan(lay, levels)
            self.assertIn("no-mutated-modules", [f["rule"] for f in plan.findings], levels)
            self.assertEqual(plan.modules, [])

    def test_a_policy_level_for_a_module_the_product_does_not_have_is_ignored_here(self):
        lay = layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//gone:gone": "L3"})
        self.assertEqual(plan.findings, [])

    def test_link_deps_are_the_closure_without_the_module_dependents_first(self):
        lay = layout(
            libs=["//m:m", "//b:b", "//c:c", "//d:d", "//z:z"],
            tests={"//m:t": ["//m:m", "//b:b"]}, external=["gate//ctest:ctest"],
            deps={"//m:m": ("//d:d", "gate//ctest:ctest"), "//b:b": ("//c:c", "//m:m"), "//c:c": (),
                  "//d:d": (), "//z:z": ()})
        plan = grade_mutants.plan(lay, {"//m:m": "L3", "//b:b": "L1", "//c:c": "L1", "//d:d": "L1", "//z:z": "L1"})
        (module,) = plan.modules
        self.assertEqual(set(module.deps), {"//b:b", "//c:c", "//d:d", "gate//ctest:ctest"})   # z is not linked
        self.assertLess(module.deps.index("//b:b"), module.deps.index("//c:c"))   # b needs c

    TLS = "gate//third_party/mbedtls:mbedtls"
    HDR = "gate//third_party/mbedtls:mbedtls_headers"

    def tls_layout(self, **more):
        """`//a:a` is mutated; its test also links `//t:tls`, which depends on a third-party library (T070)."""
        deps = {"//t:tls": (self.TLS,), self.TLS: (), self.HDR: ()}
        deps.update(more.pop("deps", {}))
        return layout(libs=["//a:a", "//t:tls"], tests={"//a:t": ["//a:a", "//t:tls"]},
                      external=[self.TLS, self.HDR], deps=deps, **more)

    def test_a_third_party_library_of_another_cell_is_linked_after_the_library_that_needs_it(self):
        plan = grade_mutants.plan(self.tls_layout(), {"//a:a": "L3", "//t:tls": "L1"})
        self.assertEqual(plan.findings, [])
        (module,) = plan.modules
        self.assertEqual(module.deps, ("//t:tls", self.TLS))   # dependents first: the archive after its user

    def test_a_third_party_library_reached_through_the_module_or_exported_deps_is_linked(self):
        lay = self.tls_layout(deps={"//a:a": (self.HDR,), self.HDR: (self.TLS,), self.TLS: ()})
        (module,) = grade_mutants.plan(lay, {"//a:a": "L3", "//t:tls": "L1"}).modules
        self.assertEqual(set(module.deps), {"//t:tls", self.HDR, self.TLS})
        self.assertEqual(module.deps[-1], self.TLS)   # the archive everything needs comes last

    def test_only_what_the_tests_link_is_linked(self):
        lay = self.tls_layout(deps={"//a:a": ()})
        links = dict(lay.links, **{"//a:t": ("//a:a",)})
        lay = grade_mutants.Layout(lay.libs, lay.binaries, frozenset({"//a:t"}), lay.deps, lay.external, links)
        (module,) = grade_mutants.plan(lay, {"//a:a": "L3", "//t:tls": "L1"}).modules
        self.assertEqual(module.deps, ())   # neither //t:tls nor mbedtls: this test does not link them

    def test_a_dep_that_is_no_library_of_the_layout_is_a_finding_and_nothing_is_dropped(self):
        for odd in ("gate//other:thing", "//x:unknown", "prelude//a:b"):
            lay = layout(libs=["//a:a"], tests={"//a:t": ["//a:a", odd]})
            plan = grade_mutants.plan(lay, {"//a:a": "L3"})
            self.assertEqual(plan.findings, [{"rule": "unresolved-link-dep", "severity": "error",
                                              "module": "//a:a", "dep": odd}], odd)
            self.assertEqual(plan.modules, [], odd)

    def test_an_unresolved_dep_deeper_in_the_closure_is_found_too(self):
        lay = layout(libs=["//a:a", "//b:b"], tests={"//a:t": ["//a:a", "//b:b"]},
                     deps={"//b:b": ("gate//third_party/gone:gone",)})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//b:b": "L1"})
        self.assertEqual([(f["rule"], f["dep"]) for f in plan.findings],
                         [("unresolved-link-dep", "gate//third_party/gone:gone")])

    def test_the_plan_does_not_depend_on_the_order_of_the_input(self):
        tests = {"//a:t%d" % n: ["//a:a"] for n in range(5)}
        first = grade_mutants.plan(layout(libs=["//a:a"], tests=tests), {"//a:a": "L3"})
        shuffled = dict(reversed(list(tests.items())))
        second = grade_mutants.plan(layout(libs=["//a:a"], tests=shuffled), {"//a:a": "L3"})
        self.assertEqual(first, second)
        self.assertEqual(first.modules[0].tests, tuple(sorted(tests)))


def named(label):
    return grade_mutants.target_name(grade_mutants.Module(label, "L2", (), ()))


class GeneratedPackage(unittest.TestCase):
    def modules(self):
        lay = layout(libs=["//core:core", "//url:url"],
                     tests={"//core:t": ["//core:core"], "//url:t": ["//url:url", "//core:core"]},
                     deps={"//url:url": ("//core:core",)})
        return grade_mutants.plan(lay, {"//core:core": "L3", "//url:url": "L2"}).modules

    def test_the_build_file_is_exactly_one_gate_macro_call_per_module(self):
        text = grade_mutants.build_file_text(self.modules())
        self.assertEqual(text, (
            'load("@gate//rules:c.bzl", "c_mutants")\n\n'
            'c_mutants(\n    name = "%s",\n    module = "//core:core",\n'
            '    tests = [\n        "//core:t",\n    ],\n    deps = [\n    ],\n)\n\n'
            'c_mutants(\n    name = "%s",\n    module = "//url:url",\n'
            '    tests = [\n        "//url:t",\n    ],\n    deps = [\n        "//core:core",\n    ],\n)\n')
            % (named("//core:core"), named("//url:url")))

    def test_a_target_name_depends_on_the_label_alone_never_on_the_position(self):
        """T121: the name is in every output path of the target's actions, so in their cache keys."""
        modules = self.modules()
        self.assertTrue(grade_mutants.target_name(modules[0]).startswith("m_core_core_"))
        for subset in (modules, modules[1:], modules[::-1]):
            for m in subset:
                self.assertEqual(grade_mutants.target_name(m), named(m.label))
        self.assertNotEqual(named("//a_b:c"), named("//a:b_c"))   # the same sanitised text, two labels
        self.assertNotEqual(named("//a:b"), named("//a:c"))
        self.assertRegex(named("//a-b/c:d"), r"^m_[A-Za-z0-9_]+$")

    def test_names_and_policy_labels_follow_the_modules(self):
        modules = self.modules()
        a, b = "//gate-mutants:" + named("//core:core"), "//gate-mutants:" + named("//url:url")
        self.assertEqual([grade_mutants.target_label(m) for m in modules], [a, b])
        self.assertEqual(grade_mutants.policy_text(modules),
                         '[module."%s"]\nlevel = "L3"\n\n[module."%s"]\nlevel = "L2"\n' % (a, b))


class PerfModules(unittest.TestCase):
    """T090: a module with perf entries in the policy links what its perf binaries link and runs the perf targets."""
    PERF = {"//core:core": {"//core:p_perf": "O(1)", "//core:q_perf": "O(n)"}}

    def planned(self, perf, binaries=("//core:p", "//core:q"), deps=None):
        lay = layout(libs=["//core:core", "//u:u"], binaries=binaries, tests={"//core:t": ["//core:core"]},
                     deps=dict({"//core:p": ("//core:core", "//u:u"), "//core:q": ("//core:core",)}, **(deps or {})))
        return grade_mutants.plan(lay, {"//core:core": "L3", "//u:u": "L1", "//core:p": "L1", "//core:q": "L1"}, perf)

    def test_the_perf_targets_and_classes_are_part_of_the_module_and_their_deps_are_linked(self):
        chosen = self.planned(self.PERF)
        (module,) = chosen.modules
        self.assertEqual(module.perf, (("//core:p_perf", "O(1)"), ("//core:q_perf", "O(n)")))
        self.assertEqual(module.deps, ("//u:u",))   # linked for the perf binary p, not for the test
        self.assertEqual(chosen.findings, [])

    def test_without_perf_entries_nothing_changes(self):
        for perf in (None, {}, {"//other:x": {"//core:p_perf": "O(1)"}}):
            (module,) = self.planned(perf).modules
            self.assertEqual((module.perf, module.deps), ((), ()))

    def test_a_perf_target_without_a_perf_binary_is_a_finding_and_is_dropped(self):
        chosen = self.planned({"//core:core": {"//core:p_perf": "O(1)", "//core:gone_perf": "O(1)"}})
        self.assertEqual([(f["rule"], f["target"]) for f in chosen.findings], [("perf-target-unknown", "//core:gone_perf")])
        self.assertEqual(chosen.modules[0].perf, (("//core:p_perf", "O(1)"),))

    def test_the_build_file_calls_the_perf_macro_only_for_a_module_with_perf(self):
        lay = layout(libs=["//core:core", "//url:url"], binaries=["//core:p"],
                     tests={"//core:t": ["//core:core"], "//url:t": ["//url:url"]}, deps={"//core:p": ("//core:core",)})
        modules = grade_mutants.plan(lay, {"//core:core": "L3", "//url:url": "L2", "//core:p": "L1"},
                                     {"//core:core": {"//core:p_perf": "O(log n)"}}).modules
        text = grade_mutants.build_file_text(modules)
        self.assertNotIn("mutate.bzl", text)
        a, b = named("//core:core"), named("//url:url")
        self.assertIn('c_mutants(\n    name = "%s",\n    module = "//core:core",\n'
                      '    tests = [\n        "//core:t",\n    ],\n    perf = [\n        "//core:p_perf",\n    ],\n' % a, text)
        self.assertIn('c_mutants(\n    name = "%s",' % b, text)
        self.assertEqual(grade_mutants.policy_text(modules),
                         '[module."//gate-mutants:%s"]\nlevel = "L3"\n'
                         '[module."//gate-mutants:%s".perf."//core:p_perf"]\nclass = "O(log n)"\n\n'
                         '[module."//gate-mutants:%s"]\nlevel = "L2"\n' % (a, a, b))

    def test_the_gate_perf_binaries_need_no_level_and_the_perf_harness_is_never_linked_into_a_test(self):
        lay = layout(libs=["//core:core"], binaries=["//gate-perf:lk"], external=["gate//ctest:perf"],
                     tests={"//core:t": ["//core:core"]}, deps={"//gate-perf:lk": ("//core:core", "gate//ctest:perf")})
        chosen = grade_mutants.plan(lay, {"//core:core": "L3"}, {"//core:core": {"//gate-perf:lk_perf": "O(1)"}})
        self.assertEqual(chosen.findings, [])
        self.assertEqual((chosen.modules[0].deps, chosen.modules[0].perf), ((), (("//gate-perf:lk_perf", "O(1)"),)))

    def test_a_plan_without_perf_has_the_old_build_file(self):
        lay = layout(libs=["//core:core"], tests={"//core:t": ["//core:core"]})
        text = grade_mutants.build_file_text(grade_mutants.plan(lay, {"//core:core": "L3"}).modules)
        self.assertNotIn("mutate.bzl", text)


class QueryParsing(unittest.TestCase):
    def test_labels_lose_the_root_cell_and_other_cells_keep_theirs(self):
        tests = {"root//core:t_results": {"test": "root//core:t"}}
        attrs = {"root//core:core": {"deps": ["root//x:x", "gate//ctest:ctest", "prelude//a:b"]},
                 "root//core:t": {"deps": ["root//core:core", "gate//ctest:ctest"]},
                 "root//core:core_mutsrc": {}, "root//app:app": {"deps": ["root//core:core"]},
                 "gate//ctest:ctest": {}, "gate//third_party/m:m": {"deps": ["gate//third_party/m:h"],
                                                                      "exported_deps": ["gate//third_party/m:e"]}}
        lay = grade_mutants.parse_layout(tests, attrs, ["root//app:app"])
        self.assertEqual(lay.libs, frozenset({"//core:core"}))
        self.assertEqual(lay.external, frozenset({"gate//ctest:ctest", "gate//third_party/m:m"}))
        self.assertEqual(lay.binaries, frozenset({"//app:app"}))
        self.assertEqual(lay.tests, frozenset({"//core:t"}))
        self.assertEqual(lay.deps["//core:core"], ("//x:x",))   # what the witness scope reads: this cell only
        self.assertEqual(lay.deps["//core:t"], ("//core:core",))
        self.assertEqual(lay.links["//core:core"], ("//x:x", "gate//ctest:ctest", "prelude//a:b"))
        self.assertEqual(lay.links["//core:t"], ("//core:core", "gate//ctest:ctest"))
        self.assertEqual(lay.links["gate//third_party/m:m"], ("gate//third_party/m:h", "gate//third_party/m:e"))

    def test_libraries_of_other_cells_are_queried_until_the_closure_is_complete(self):
        known = {"gate//t:a": {"deps": ["gate//t:b"]}, "gate//t:b": {"exported_deps": ["gate//t:c", "root//x:x"]},
                 "gate//t:c": {}}
        asked = []

        def query(labels):
            asked.append(labels)
            return {label: known[label] for label in labels if label in known}   # a non-library is not returned
        attrs = {"root//x:x": {"deps": ["gate//t:a", "gate//t:notlib"]}, "root//x:t": {"deps": ["root//x:x"]}}
        out = grade_mutants.add_external(attrs, query)
        self.assertEqual(sorted(out), ["gate//t:a", "gate//t:b", "gate//t:c", "root//x:t", "root//x:x"])
        self.assertEqual(asked, [["gate//t:a", "gate//t:notlib"], ["gate//t:b"], ["gate//t:c"]])

    def test_a_query_that_returns_something_odd_is_an_internal_error(self):
        with self.assertRaises(InternalError):
            grade_mutants.add_external({"root//x:x": {"deps": ["gate//t:a"]}}, lambda labels: [])

    def test_odd_query_output_is_an_internal_error(self):
        for tests, attrs in (([], {}), ({"root//a:t_results": {}}, {}), ({"root//a:t_results": {"test": 3}}, {}),
                             ({}, {"root//a:a": {"deps": "x"}, "root//a:a_mutsrc": {}}), ({}, {"bad label": {}}),
                             ({}, {"gate//a:a": {"exported_deps": "x"}}), ({}, {"gate//a:a": {"deps": [3]}})):
            with self.assertRaises(InternalError):
                grade_mutants.parse_layout(tests, attrs, [])


class Levels(TempDirTestCase):
    def policy(self, text):
        path = self.tmp / "policy.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    GOOD = ('[global]\ndeny = ["kill"]\ntrusted = ["gate//ctest:ctest"]\n\n'
            '[module."//core:core"]\nlevel = "L3"\nallow = ["memcpy"]\n\n'
            '[module."//core:t"]\nallow = []\n')

    def test_levels_are_read_per_module(self):
        self.assertEqual(grade_policy.load_levels(self.policy(self.GOOD)), {"//core:core": "L3"})

    def test_a_bad_level_is_a_policy_defect(self):
        for level in ('"L0"', '"L6"', '"l3"', "3", '["L3"]', '""'):
            text = '[global]\ndeny = []\n[module."//core:core"]\nlevel = %s\n' % level
            with self.assertRaises(InternalError, msg=level):
                grade_policy.load_levels(self.policy(text))

    def test_a_policy_that_is_not_toml_or_has_no_module_table_is_a_defect(self):
        for text in ("not toml [", '[global]\ndeny = []\n[module]\nx = 1\n', 'module = 3\n[global]\ndeny = []\n'):
            with self.assertRaises(InternalError, msg=text):
                grade_policy.load_levels(self.policy(text))

    def test_the_symbols_reader_takes_the_whole_policy_and_ignores_impl(self):
        text = self.GOOD.replace('level = "L3"', 'level = "L3"\nimpl = ["core/core.c"]')
        loaded = facts_policy.load_policy(self.policy(text))
        self.assertEqual(loaded.deny, frozenset({"kill"}))
        self.assertEqual(loaded.trusted, frozenset({"gate//ctest:ctest"}))
        self.assertEqual(set(loaded.modules), {"//core:core", "//core:t"})
        self.assertEqual(loaded.modules["//core:core"].allow, frozenset({"memcpy"}))
        self.assertEqual(loaded.modules["//core:core"].level, "L3")

    def test_a_typo_next_to_impl_is_still_rejected_by_the_symbols_reader(self):
        text = self.GOOD.replace('level = "L3"', 'level = "L3"\nimpl = ["core/core.c"]\nalloww = ["x"]')
        with self.assertRaises(InternalError):
            facts_policy.load_policy(self.policy(text))

    def test_the_document_is_what_the_witness_scope_reads(self):
        text = self.GOOD.replace('level = "L3"', 'level = "L3"\nimpl = ["core/core.c"]')
        document = grade_policy.load_document(self.policy(text))
        self.assertEqual(document["module"]["//core:core"]["impl"], ["core/core.c"])
        with self.assertRaises(InternalError):
            grade_policy.load_document(str(self.tmp / "missing.toml"))

    def test_the_shipped_policies_load(self):
        for product in ("selftest", "annas-c"):
            path = str(GATE_DIR.parent / "products" / product / "policy.toml")
            levels = grade_policy.load_levels(path)
            self.assertTrue(levels, product)
            facts_policy.load_policy(path)


class WorkDirectory(TempDirTestCase):
    def test_what_an_earlier_grading_left_in_the_work_directory_is_removed(self):
        work = self.sub("work")
        for name in ("facts", "mutants-reports", "tree"):
            (work / name).mkdir()
            (work / name / "stale.json").write_text("{}", encoding="utf-8")
        with mock.patch("rigor_lib.grade_context.kill_daemon"):
            grade_context.prepare_work(str(work))
        self.assertEqual(sorted(p.name for p in work.iterdir()), ["home", "results", "tmp"])


    def test_a_second_grading_into_the_same_work_directory_does_not_trip_over_the_perf_results(self):
        work = self.sub("work")
        (work / "mutants-perf").mkdir()
        (work / "mutants-perf" / "004.json").write_text("stale", encoding="utf-8")
        with mock.patch("rigor_lib.grade_context.kill_daemon"):
            grade_context.prepare_work(str(work))
        self.assertFalse((work / "mutants-perf").exists())
        out_dir = work / grade_mutants.PERF_DIR
        out_dir.mkdir()
        with open(str(out_dir / "004.json"), "xb") as handle:   # what _copy_perf does: exclusive create
            handle.write(b"{}")


class ChunkedBuild(TempDirTestCase):
    """T115: `build_reports` builds the c_mutants targets in bounded chunks, with a fake `run_buck` and fake reports."""
    N = grade_mutants.MUTANTS_CHUNK
    PIPE = "error: h2 protocol error: error reading a body from connection: Broken pipe"

    def setUp(self):
        super().setUp()
        self.work = self.sub("work")
        self.tree = self.sub("work/tree")
        self.sub("work/tree/buck-out")
        self.calls = []
        self.lock = threading.Lock()
        self.script = {}   # (chunk number, attempt) -> (exit code, stderr, labels that fail)

    def name(self, index):
        return named("//m%d:m" % index)

    def modules(self, count, perf=()):
        return [grade_mutants.Module("//m%d:m" % i, "L3", ("//m%d:t" % i,), (),
                                     (("//m%d:p_perf" % i, "O(1)"),) if i in perf else ()) for i in range(count)]

    def run_build(self, count, perf=()):
        modules = self.modules(count, perf)
        run = grade_build.TreeRun(self.tree, str(self.work), mutants_reports=str(self.work / "mutants-reports"))
        attempts = {}

        def fake_buck(tree, args):
            self.assertEqual(args[0], "build")
            report = args[args.index("--build-report") + 1]
            targets = [a for a in args if a.startswith("//gate-mutants:")]
            number = int(os.path.basename(report).split("-")[-1].split(".")[0])
            with self.lock:
                attempt = attempts[number] = attempts.get(number, -1) + 1
                self.calls.append((number, attempt, targets, os.path.exists(report)))
            code, err, failing = self.script.get((number, attempt), (0, "", ()))
            results = {}
            for target in targets:
                name = target.split(":")[1].split("[")[0]
                if "[" in target or name in failing:
                    continue
                out = os.path.join(tree, "buck-out", name + ".json")
                with open(out, "w") as handle:
                    handle.write('{"label": "%s"}' % name)
                outputs = {"DEFAULT": ["buck-out/%s.json" % name]}
                if target + "[perf]" in args:
                    pout = os.path.join(tree, "buck-out", name + ".perf.json")
                    with open(pout, "w") as handle:
                        handle.write('{"perf": "%s"}' % name)
                    outputs["perf"] = ["buck-out/%s.perf.json" % name]
                results["root" + target] = {"success": "SUCCESS", "outputs": outputs}
            with open(report, "w") as handle:
                handle.write(json.dumps({"results": results}))
            return code, "", err
        with mock.patch("rigor_lib.grade_build.run_buck", side_effect=fake_buck), \
                mock.patch("rigor_lib.grade_build.action_counts", return_value=(3, 5)):
            outcome = grade_mutants.build_reports(run, False, modules)
        self.calls.sort(key=lambda c: c[:2])   # the chunks overlap: only the order of (chunk, attempt) is defined
        return modules, outcome

    def reports(self):
        return sorted(os.listdir(str(self.work / "mutants-reports")))

    def test_chunk_boundaries(self):
        n = self.N
        for count, sizes in ((1, [1]), (n, [n]), (n + 1, [n, 1]), (2 * n + 1, [n, n, 1])):
            self.calls = []
            run_dir = self.work / "mutants-reports"
            if run_dir.exists():
                shutil.rmtree(str(run_dir))
            _, (found, metadata, built) = self.run_build(count)
            self.assertEqual([len(c[2]) for c in self.calls], sizes, count)
            self.assertEqual(metadata["chunks"], len(sizes), count)
            self.assertEqual((found, built), ([], list(range(count))), count)
            self.assertEqual([r for r in self.reports()], ["%03d.json" % i for i in range(count)], count)

    def test_chunk_size_is_in_the_documented_range(self):
        self.assertTrue(8 <= self.N <= 16)

    def test_report_names_keep_the_global_index_and_content(self):
        n = self.N
        self.run_build(n + 2)
        for index in (0, n - 1, n, n + 1):
            text = (self.work / "mutants-reports" / ("%03d.json" % index)).read_text()
            self.assertIn(self.name(index), text)
        self.assertEqual([c[0] for c in self.calls], [0, 1])
        self.assertEqual(self.calls[1][2][0], "//gate-mutants:" + self.name(n))

    def test_a_transient_failure_in_chunk_two_retried_gives_the_output_of_a_clean_run(self):
        n = self.N
        self.script = {(1, 0): (1, self.PIPE, (self.name(n),))}
        _, (found, metadata, built) = self.run_build(2 * n)
        self.assertEqual([(c[0], c[1]) for c in self.calls], [(0, 0), (1, 0), (1, 1)])
        self.assertFalse(self.calls[2][3])   # the retry's report file was removed first
        self.assertEqual((found, built), ([], list(range(2 * n))))
        self.assertEqual(self.reports(), ["%03d.json" % i for i in range(2 * n)])
        self.assertEqual((metadata["exit_code"], metadata["retried"], metadata["chunks"]), (0, [1], 2))
        self.assertNotIn("stderr_tail", metadata)

    def test_a_transient_failure_twice_fails_only_the_modules_of_that_chunk(self):
        n = self.N
        everything = tuple(self.name(i) for i in range(n, 2 * n))
        self.script = {(1, 0): (1, self.PIPE, everything), (1, 1): (1, "Broken pipe again", everything)}
        _, (found, metadata, built) = self.run_build(3 * n)
        self.assertEqual([(c[0], c[1]) for c in self.calls], [(0, 0), (1, 0), (1, 1), (2, 0)])
        self.assertEqual(sorted(f["module"] for f in found), sorted("//m%d:m" % i for i in range(n, 2 * n)))
        self.assertEqual({f["rule"] for f in found}, {"mutants-build-failed"})
        self.assertEqual(built, list(range(n)) + list(range(2 * n, 3 * n)))   # the other chunks' verdicts stand
        self.assertEqual((metadata["exit_code"], metadata["retried"]), (1, [1]))
        self.assertEqual(metadata["stderr_tail"], "Broken pipe again")

    def test_a_real_build_failure_is_not_retried(self):
        self.script = {(0, 0): (1, "error: compilation of m.c failed", (self.name(0),))}
        _, (found, metadata, built) = self.run_build(2)
        self.assertEqual([(c[0], c[1]) for c in self.calls], [(0, 0)])
        self.assertEqual([f["module"] for f in found], ["//m0:m"])
        self.assertEqual((built, metadata["retried"], metadata["exit_code"]), ([1], [], 1))

    def test_a_transport_text_with_every_target_built_is_not_retried(self):
        self.script = {(0, 0): (1, self.PIPE, ())}   # non-zero but every target built
        self.run_build(1)
        self.assertEqual(len(self.calls), 1)

    def test_a_transport_text_with_a_zero_exit_is_not_retried(self):
        self.script = {(0, 0): (0, self.PIPE, (self.name(0),))}   # exit zero, a target missing
        self.run_build(1)
        self.assertEqual(len(self.calls), 1)

    def test_the_metadata_sums_the_chunks_and_every_attempt_and_the_exit_is_the_first_failure(self):
        n = self.N
        self.script = {(0, 0): (1, self.PIPE, (self.name(0),)), (1, 0): (2, "boom", (self.name(n),))}
        _, (_, metadata, _) = self.run_build(2 * n)
        # chunk 0 ran twice (retry), chunk 1 once: 3 builds of (3 executed, 5 cached)
        self.assertEqual((metadata["executed_actions"], metadata["cached_actions"]), (9, 15))
        self.assertEqual(metadata["exit_code"], 2)   # chunk 0 succeeded on retry, so chunk 1's is the first non-zero
        self.assertEqual(metadata["stderr_tail"], "boom")
        self.assertEqual(metadata["retried"], [0])

    def test_perf_labels_are_built_in_their_own_chunk_and_copied_with_the_global_index(self):
        n = self.N
        self.run_build(n + 1, perf=(1, n))
        self.assertEqual(sum(t.endswith("[perf]") for t in self.calls[0][2]), 1)
        self.assertEqual(sum(t.endswith("[perf]") for t in self.calls[1][2]), 1)
        perf = self.work / grade_mutants.PERF_DIR
        self.assertEqual(sorted(os.listdir(str(perf))), ["001.json", "%03d.json" % n])
        self.assertIn(self.name(n), (perf / ("%03d.json" % n)).read_text())

    def test_the_transport_classifier(self):
        for text in ("h2 protocol error: broken", "write: Broken pipe", "Connection reset by peer", "transport error"):
            self.assertTrue(grade_build.transport_failure(text), text)
        for text in ("", "error: undefined reference to `x`", "FAILED: test t", "build failed"):
            self.assertFalse(grade_build.transport_failure(text), text)


class OverlappedChunks(TempDirTestCase):
    """T121: the chunk builds overlap (bounded), and nothing in the outcome depends on who finishes first."""
    N = grade_mutants.MUTANTS_CHUNK

    def setUp(self):
        super().setUp()
        self.work = self.sub("work")
        self.tree = self.sub("work/tree")
        self.sub("work/tree/buck-out")
        self.lock = threading.Lock()

    def modules(self, count):
        return [grade_mutants.Module("//m%d:m" % i, "L3", ("//m%d:t" % i,), ()) for i in range(count)]

    def reports(self):
        return sorted(os.listdir(str(self.work / "mutants-reports")))

    def build_with(self, count, uncached=False, hook=None):
        """build_reports over COUNT modules with a fake Buck2; HOOK(number) runs inside every build."""
        modules = self.modules(count)
        run = grade_build.TreeRun(self.tree, str(self.work), mutants_reports=str(self.work / "mutants-reports"))
        counted = []

        def fake_buck(tree, args):
            report = args[args.index("--build-report") + 1]
            number = int(os.path.basename(report).split("-")[-1].split(".")[0])
            if hook:
                hook(number)
            results = {}
            for target in (a for a in args if a.startswith("//gate-mutants:")):
                name = target.split(":")[1]
                with open(os.path.join(tree, "buck-out", name + ".json"), "w") as handle:
                    handle.write('{"label": "%s"}' % name)
                results["root" + target] = {"success": "SUCCESS", "outputs": {"DEFAULT": ["buck-out/%s.json" % name]}}
            with open(report, "w") as handle:
                handle.write(json.dumps({"results": results, "events": args[args.index("--event-log") + 1]}))
            return 0, "", ""

        def counts(tree, event_log=None):
            counted.append(event_log)
            return 1, 2
        with mock.patch("rigor_lib.grade_build.run_buck", side_effect=fake_buck), \
                mock.patch("rigor_lib.grade_build.action_counts", side_effect=counts):
            return grade_mutants.build_reports(run, uncached, modules), counted

    def test_the_documented_number_of_chunks_is_really_in_flight_together(self):
        k = grade_mutants.MUTANTS_INFLIGHT
        self.assertGreater(k, 1)
        barrier = threading.Barrier(k)   # every build waits for k-1 others: it only passes if they overlap
        (found, metadata, built), _ = self.build_with(k * self.N, hook=lambda number: barrier.wait(timeout=60))
        self.assertEqual((found, built), ([], list(range(k * self.N))))

    def workers_of(self, count, uncached):
        """The `max_workers` the build asked its pool for."""
        asked = []

        def pool(max_workers):
            asked.append(max_workers)
            return ThreadPoolExecutor(max_workers=max_workers)
        with mock.patch.object(grade_mutants, "ThreadPoolExecutor", side_effect=pool):
            self.build_with(count, uncached=uncached)
        return asked

    def test_no_more_than_the_bound_is_in_flight(self):
        self.assertEqual(self.workers_of(6 * self.N, False), [grade_mutants.MUTANTS_INFLIGHT])

    def test_uncached_builds_stay_one_at_a_time(self):
        """`grade_build.run_buck` re-primes the toolchain around an uncached build and reads "the last command"."""
        self.assertEqual(grade_mutants.inflight(True), 1)
        self.assertEqual(self.workers_of(6 * self.N, True), [1])

    def test_one_chunk_needs_one_worker(self):
        self.assertEqual(self.workers_of(self.N, False), [1])

    def test_each_chunk_counts_its_own_event_log(self):
        (_, metadata, _), counted = self.build_with(3 * self.N)
        self.assertEqual(sorted(counted), sorted(str(self.work / ("build-report-mutants-%03d.events.pb.zst" % i)) for i in range(3)))
        self.assertEqual((metadata["executed_actions"], metadata["cached_actions"]), (3, 6))

    def test_the_outcome_is_in_chunk_order_whoever_finishes_first(self):
        gate = threading.Event()   # chunk 0 finishes last
        order = []

        def hook(number):
            if number == 0:
                gate.wait(timeout=60)
            else:
                with self.lock:
                    order.append(number)
                    if len(order) == 2:
                        gate.set()
        (found, metadata, built), _ = self.build_with(3 * self.N, hook=hook)
        self.assertEqual(sorted(order), [1, 2])
        self.assertEqual(built, list(range(3 * self.N)))
        self.assertEqual(self.reports(), ["%03d.json" % i for i in range(3 * self.N)])
        self.assertEqual(metadata["chunks"], 3)

    def test_an_error_in_one_chunk_stops_the_run_and_is_raised(self):
        def hook(number):
            if number == 1:
                raise InternalError("cannot run buck2")
        with self.assertRaises(InternalError):
            self.build_with(5 * self.N, hook=hook)


class Gate(TempDirTestCase):
    def grading(self, status=None, role="implementer"):
        work = self.sub("work")
        tree = self.sub("work/tree")
        product = self.sub("product") / "product.toml"
        (self.sub("product") / "policy.toml").write_text("[global]\ndeny = []\n", encoding="utf-8")   # no perf entries
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\nrole = "%s"\n' % role, encoding="utf-8")
        args = SimpleNamespace(product=str(product), uncached=False, approvals=None, task=str(task),
                               allowed_signers="signers")
        done = {k: "PASS" for k in ("assemble", "buckfiles", "build", "tests-release", "tests-san")}
        done.update(status or {})
        return SimpleNamespace(args=args, work=str(work), tree=str(tree), src=str(work / "src"), head="",
                               status=done)

    def test_it_is_registered_after_the_tests_and_before_the_witness_gates_and_is_in_the_order_file(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[-6:], ["tests-stub", "fuzz", "perf", "mutants", "witness-tests", "mutants-witness"])
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt"))[-6:], ids[-6:])

    def test_it_does_not_run_unless_the_tree_was_built_and_every_test_passed(self):
        for gate in ("assemble", "buckfiles", "build", "tests-release", "tests-san"):
            for value in ("FAIL", None):
                g = self.grading({gate: value})
                with mock.patch.object(grade_mutants, "read_layout") as layout_mock, \
                        mock.patch("rigor_lib.grade_context.kill_daemon"):
                    self.assertIsNone(grade_mutants.mutants_gate(g), (gate, value))
                layout_mock.assert_not_called()

    def test_role_test_author_is_not_applicable_and_runs_nothing(self):
        g = self.grading(role="test-author")
        with mock.patch.object(grade_mutants, "read_layout") as layout_mock, \
                mock.patch("rigor_lib.grade_build.run_buck") as buck:
            result = grade_mutants.mutants_gate(g)
        layout_mock.assert_not_called()
        buck.assert_not_called()
        self.assertEqual(result.status, "PASS")
        self.assertEqual([(f["rule"], f["severity"], f["role"]) for f in result.findings],
                         [("not-applicable", "info", "test-author")])
        self.assertEqual(result.metadata["modules"], {})   # nothing a witness reuse could stand in for

    def test_role_test_author_still_needs_a_clean_build_and_present_tests(self):
        for gate in ("assemble", "buckfiles", "build", "tests-release", "tests-san"):
            self.assertIsNone(grade_mutants.mutants_gate(self.grading({gate: "FAIL"}, role="test-author")), gate)

    def test_a_directory_of_the_product_that_collides_with_the_gate_package_is_an_error(self):
        g = self.grading()
        for name in (grade_mutants.PACKAGE_DIR, "PACKAGE"):
            path = os.path.join(g.tree, name)
            os.makedirs(path) if name == grade_mutants.PACKAGE_DIR else open(path, "w").close()
            lay = layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]})
            with mock.patch.object(grade_mutants, "read_layout", return_value=lay), \
                    mock.patch.object(grade_mutants.grade_policy, "load_levels", return_value={"//a:a": "L3"}), \
                    mock.patch("rigor_lib.grade_context.kill_daemon") as kill:
                with self.assertRaises(InternalError):
                    grade_mutants.mutants_gate(g)
                kill.assert_called_once_with(g.tree)   # the daemon dies on every path
            if name == "PACKAGE":
                os.unlink(path)
            else:
                os.rmdir(path)

    def test_a_plan_with_findings_and_no_module_builds_nothing(self):
        g = self.grading()
        lay = layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]})
        with mock.patch.object(grade_mutants, "read_layout", return_value=lay), \
                mock.patch.object(grade_mutants.grade_policy, "load_levels", return_value={}), \
                mock.patch("rigor_lib.grade_build.run_buck") as buck, \
                mock.patch("rigor_lib.grade_context.kill_daemon") as kill:
            result = grade_mutants.mutants_gate(g)
        buck.assert_not_called()
        kill.assert_called_once_with(g.tree)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(sorted(f["rule"] for f in result.findings), ["level-missing", "no-mutated-modules"])
        self.assertFalse(os.path.exists(os.path.join(g.tree, grade_mutants.PACKAGE_DIR)))

    def test_a_failed_mutants_build_is_a_finding_even_when_buck_exits_zero_without_reports(self):
        g = self.grading()
        lay = layout(libs=["//a:a"], tests={"//a:t": ["//a:a"]})
        report = os.path.join(g.work, "build-report-mutants.json")

        def fake_buck(tree, args):
            if args[0] == "build":
                with open(report, "w") as handle:
                    handle.write('{"results": {}}')
                return 0, "", ""
            return 0, "", ""
        with mock.patch.object(grade_mutants, "read_layout", return_value=lay), \
                mock.patch.object(grade_mutants.grade_policy, "load_levels", return_value={"//a:a": "L3"}), \
                mock.patch("rigor_lib.grade_build.run_buck", side_effect=fake_buck), \
                mock.patch("rigor_lib.grade_build.action_counts", return_value=(0, 0)), \
                mock.patch("rigor_lib.grade_context.kill_daemon"):
            result = grade_mutants.mutants_gate(g)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("mutants-build-failed", [f["rule"] for f in result.findings])


class Judging(TempDirTestCase):
    """`judge` hands `rigor mutants` the gate's own target labels: the extra approval kinds of a module too."""

    def judged(self, **more):
        modules = [grade_mutants.Module("//a:a", "L3", ("//a:t",), ()), grade_mutants.Module("//b:b", "L3", ("//b:t",), ())]
        g = SimpleNamespace(src="repo", head="h", args=SimpleNamespace(approvals=None, allowed_signers="s"))
        run = SimpleNamespace(work=str(self.sub("work")), mutants_reports=str(self.tmp / "reports"))
        result = SimpleNamespace(findings=[], metadata={"modules": {}, "approvals_used": ["x"],
                                                        "approvals_used_by_kind": {"equivalent-mutant": ["x"]}})
        with mock.patch.object(grade_mutants.rigor_mutants, "run", return_value=result) as ran:
            out = grade_mutants.judge(g, run, modules, [0, 1], **more)
        return out, ran.call_args.args, [grade_mutants.target_label(m) for m in modules]

    def test_the_head_gate_passes_one_kind_and_no_extra(self):
        out, args, _ = self.judged()
        self.assertEqual(args[1:], ("equivalent-mutant", {}))
        self.assertEqual(out[2], ["x"])

    def test_extra_kinds_are_keyed_by_the_module_s_target_and_only_for_the_modules_named(self):
        used = {}
        _, args, targets = self.judged(approval_kind="witness-equivalent-mutant",
                                       extra_kinds={"//b:b": ("equivalent-mutant",)}, used_by_kind=used)
        self.assertEqual(args[1:], ("witness-equivalent-mutant", {targets[1]: ("equivalent-mutant",)}))
        self.assertEqual(used, {"equivalent-mutant": ["x"]})


if __name__ == "__main__":
    unittest.main()
