"""Unit tests of the `mutants` step of `rigor grade` that need no Buck2 (selftest/grade.sh has the rest).

The step decides three things the product must not be able to influence: which modules are mutated
(the gate-owned policy levels), which tests run against a module's mutants (the product's tests that
depend on it directly, found by a query in the tree), and whether "nothing was mutated" passes (never).
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import facts_policy, grade_context, grade_mutants, grade_pipeline, grade_policy, verdict
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
    def test_tests_are_the_ones_that_depend_on_the_module_directly(self):
        lay = layout(libs=["//a:a", "//b:b"],
                     tests={"//a:t1": ["//a:a"], "//b:t2": ["//b:b"], "//b:t3": ["//a:a", "//b:b"]},
                     deps={"//b:b": ("//a:a",)})
        plan = grade_mutants.plan(lay, {"//a:a": "L3", "//b:b": "L2"})
        self.assertEqual(plan.findings, [])
        by_label = {m.label: m for m in plan.modules}
        self.assertEqual(by_label["//a:a"].tests, ("//a:t1", "//b:t3"))   # not //b:t2: it needs b, not a
        self.assertEqual(by_label["//b:b"].tests, ("//b:t2", "//b:t3"))

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
            'c_mutants(\n    name = "m000_core_core",\n    module = "//core:core",\n'
            '    tests = [\n        "//core:t",\n        "//url:t",\n    ],\n    deps = [\n        "//url:url",\n    ],\n)\n\n'
            'c_mutants(\n    name = "m001_url_url",\n    module = "//url:url",\n'
            '    tests = [\n        "//url:t",\n    ],\n    deps = [\n        "//core:core",\n    ],\n)\n'))

    def test_names_and_policy_labels_follow_the_modules(self):
        modules = self.modules()
        self.assertEqual([grade_mutants.target_label(i, m) for i, m in enumerate(modules)],
                         ["//gate-mutants:m000_core_core", "//gate-mutants:m001_url_url"])
        self.assertEqual(grade_mutants.policy_text(modules),
                         '[module."//gate-mutants:m000_core_core"]\nlevel = "L3"\n\n'
                         '[module."//gate-mutants:m001_url_url"]\nlevel = "L2"\n')


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


class Gate(TempDirTestCase):
    def grading(self, status=None, role="implementer"):
        work = self.sub("work")
        tree = self.sub("work/tree")
        product = self.sub("product") / "product.toml"
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
        self.assertEqual(ids[-5:], ["tests-san", "tests-stub", "mutants", "witness-tests", "mutants-witness"])
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt"))[-5:], ids[-5:])

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


if __name__ == "__main__":
    unittest.main()
