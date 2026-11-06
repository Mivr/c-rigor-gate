"""impl paths, test surface and the witness scope W (P002, "Terms"), on the canary product's layout.

canaries/_base/product: `//core:core` (L3) with `//core:core_test`; `//util:util` (L2, depends on core)
with `//util:util_test`; and `//util:core_test`, which lives in util but lists `//core:core` directly.
"""

import unittest

from rigor_lib import grade_mutants, witness_scope as ws
from rigor_lib.errors import InternalError

CORE, UTIL = "//core:core", "//util:util"
LEVELS = {CORE: "L3", UTIL: "L2"}
IMPL = {CORE: ["core/core.c"], UTIL: ["util/util.c"]}


def layout(libs=(CORE, UTIL), binaries=(), tests=None, deps=None):
    tests = tests if tests is not None else {"//core:core_test": (CORE,), "//util:util_test": (UTIL,),
                                             "//util:core_test": (UTIL, CORE)}
    graph = {CORE: (), UTIL: (CORE,)}
    graph.update(deps or {})
    graph.update(tests)
    for label in tuple(libs) + tuple(binaries):
        graph.setdefault(label, ())
    return grade_mutants.Layout(frozenset(libs), frozenset(binaries), frozenset(tests), graph)


def policy(**impl):
    return {"module": {label: {"level": "L3", "impl": globs} for label, globs in impl.items()}}


class ImplMap(unittest.TestCase):
    def test_globs_per_module(self):
        document = {"global": {"deny": ["kill"]},
                    "module": {CORE: {"level": "L3", "allow": [], "impl": ["core/core.c"]},
                               UTIL: {"level": "L2", "impl": ["util/util.c", "util/x/**"]},
                               "//core:core_test": {"allow": []}}}
        mapping, found = ws.impl_map(document, LEVELS)
        self.assertEqual(mapping, {CORE: ["core/core.c"], UTIL: ["util/util.c", "util/x/**"]})
        self.assertEqual(found, [])

    def test_impl_missing_is_an_error_from_l3_and_info_at_l2(self):
        levels = {"//a:l1": "L1", "//a:l2": "L2", "//a:l3": "L3", "//a:l4": "L4", "//a:l5": "L5"}
        mapping, found = ws.impl_map({"module": {}}, levels)
        self.assertEqual(mapping, {})
        self.assertEqual([(f["module"], f["level"], f["severity"], f["rule"]) for f in found],
                         [("//a:l2", "L2", "info", "impl-missing"), ("//a:l3", "L3", "error", "impl-missing"),
                          ("//a:l4", "L4", "error", "impl-missing"), ("//a:l5", "L5", "error", "impl-missing")])

    def test_a_policy_without_modules_is_fine_when_no_module_has_a_level(self):
        self.assertEqual(ws.impl_map({}, {}), ({}, []))

    def test_malformed_impl_values_are_internal_errors(self):
        for value in ("core/core.c", [], [1], ["core/core.c", "core/core.c"], ["../x"], ["a**"], {"a": 1}, None):
            with self.assertRaises(InternalError, msg=repr(value)):
                ws.impl_map({"module": {CORE: {"impl": value}}}, LEVELS)

    def test_malformed_policy_and_levels_are_internal_errors(self):
        for document in ([], {"module": []}, {"module": {CORE: "x"}}, {"module": {"core": {"impl": ["a"]}}}):
            with self.assertRaises(InternalError, msg=repr(document)):
                ws.impl_map(document, LEVELS)
        for levels in ([], {CORE: "L6"}, {CORE: 3}, {"core": "L3"}):
            with self.assertRaises(InternalError, msg=repr(levels)):
                ws.impl_map({}, levels)


class TestSurface(unittest.TestCase):
    ALL = ["core/BUCK", "core/core.c", "core/core.h", "core/core_test.c", "util/BUCK", "util/util.c",
           "util/util.h", "util/util_core_test.c", "util/util_test.c", "README.md"]

    def test_surface_of_each_module(self):
        surface = ws.test_surface(layout(), IMPL, self.ALL)
        self.assertEqual(surface[CORE], ["core/BUCK", "core/core.h", "core/core_test.c", "util/BUCK",
                                         "util/util.h", "util/util_core_test.c", "util/util_test.c"])
        self.assertEqual(surface[UTIL], ["util/BUCK", "util/util.h", "util/util_core_test.c", "util/util_test.c"])

    def test_impl_paths_of_any_module_are_not_test_surface(self):
        surface = ws.test_surface(layout(), {CORE: ["core/core.c"]}, ["util/util.c", "core/core.c"])
        self.assertEqual(surface[CORE], ["util/util.c"])  # util has no impl: its source counts, never fewer
        self.assertEqual(ws.test_surface(layout(), IMPL, ["util/util.c", "core/core.c"]), {CORE: [], UTIL: []})

    def test_the_deepest_package_owns_a_path(self):
        lay = layout(libs=("//a:a", "//a/b:b"), tests={"//a:t": ("//a:a",), "//a/b:t": ("//a/b:b",)})
        surface = ws.test_surface(lay, {}, ["a/b/x.h", "a/y.h", "a/c/z.h"])
        self.assertEqual(surface, {"//a:a": ["a/c/z.h", "a/y.h"], "//a/b:b": ["a/b/x.h"]})

    def test_the_root_package(self):
        lay = layout(libs=("//:root",), tests={"//t:t": ("//:root",)})
        surface = ws.test_surface(lay, {}, ["root.h", "t/t.c", "other/x.c"])
        self.assertEqual(surface, {"//:root": ["other/x.c", "root.h", "t/t.c"]})

    def test_paths_outside_every_package_are_nobody_s(self):
        self.assertEqual(ws.test_surface(layout(), IMPL, ["README.md", "docs/x.md"]), {CORE: [], UTIL: []})

    def test_a_package_with_only_tests_counts_for_the_module_it_tests(self):
        lay = layout(tests={"//core:core_test": (CORE,), "//kit:kit_test": (CORE,)})
        self.assertEqual(ws.test_surface(lay, IMPL, ["kit/fake.h"])[CORE], ["kit/fake.h"])

    def test_binaries_are_modules_too(self):
        lay = layout(binaries=("//app:app",), tests={"//app:app_test": ("//app:app",)})
        self.assertEqual(ws.test_surface(lay, IMPL, ["app/main.h"])["//app:app"], ["app/main.h"])

    def test_malformed_inputs_are_internal_errors(self):
        for args in ((object(), IMPL, []), (layout(), IMPL, "core/core.h"), (layout(), IMPL, ["../x"]),
                     (layout(), IMPL, [b"core/core.h"]), (layout(), {CORE: []}, []), (layout(), [], []),
                     (grade_mutants.Layout(frozenset([CORE]), frozenset(), frozenset(), {}), {}, [])):
            with self.assertRaises(InternalError, msg=repr(args)):
                ws.test_surface(*args)


class Scope(unittest.TestCase):
    def w(self, changed, role="implementer", lay=None, impl=IMPL, levels=LEVELS):
        return ws.scope(role, changed, lay or layout(), impl, levels)

    def test_a_header_only_change(self):
        self.assertEqual(self.w(["core/core.h"]), [CORE])

    def test_a_build_file_change(self):
        self.assertEqual(self.w(["core/BUCK"]), [CORE])

    def test_a_change_only_to_a_test_in_another_package(self):
        # util/util_core_test.c is //util:core_test, which tests //core:core directly
        self.assertEqual(self.w(["util/util_core_test.c"]), [CORE, UTIL])

    def test_a_change_to_util_test_only(self):
        # util's package holds //util:core_test, so any util test-surface file is core's too
        self.assertEqual(self.w(["util/util_test.c"]), [CORE, UTIL])

    def test_a_pure_impl_change_is_empty(self):
        self.assertEqual(self.w(["core/core.c", "util/util.c"]), [])

    def test_no_change_is_empty(self):
        for role in ("implementer", "test-author"):
            self.assertEqual(self.w([], role=role), [])

    def test_test_author_with_a_stubbed_module_whose_test_surface_is_unchanged(self):
        self.assertEqual(self.w(["core/core.c"], role="test-author"), [CORE])
        self.assertEqual(self.w(["core/core.c"], role="implementer"), [])

    def test_test_author_adds_the_stubbed_modules_to_the_surface_ones(self):
        self.assertEqual(self.w(["util/util.c", "core/core.h"], role="test-author"), [CORE, UTIL])

    def test_audit_is_every_judged_module_with_tests(self):
        lay = layout(libs=(CORE, UTIL, "//lone:lone", "//low:low"),
                     tests={"//core:core_test": (CORE,), "//util:util_test": (UTIL,), "//low:t": ("//low:low",)})
        levels = dict(LEVELS, **{"//lone:lone": "L3", "//low:low": "L1"})
        self.assertEqual(self.w([], role="audit", lay=lay, levels=levels), [CORE, UTIL])
        self.assertEqual(self.w(["core/core.h"], role="audit", lay=lay, levels=levels), [CORE, UTIL])

    def test_a_new_module(self):
        new = "//fmt:fmt"
        lay = layout(libs=(CORE, UTIL, new), tests={"//core:core_test": (CORE,), "//fmt:fmt_test": (new,)},
                     deps={new: (CORE,)})
        levels = dict(LEVELS, **{new: "L3"})
        impl = dict(IMPL, **{new: ["fmt/fmt.c"]})
        changed = ["fmt/BUCK", "fmt/fmt.c", "fmt/fmt.h", "fmt/fmt_test.c"]
        self.assertEqual(self.w(changed, lay=lay, impl=impl, levels=levels), [new])
        self.assertEqual(self.w(changed, role="test-author", lay=lay, impl=impl, levels=levels), [new])

    def test_modules_below_l2_or_without_a_level_are_never_in_scope(self):
        self.assertEqual(self.w(["util/util.h"], levels={CORE: "L3", UTIL: "L1"}), [CORE])
        self.assertEqual(self.w(["util/util.h"], levels={CORE: "L3"}), [CORE])
        self.assertEqual(self.w(["core/core.h"], levels={UTIL: "L2"}), [])

    def test_levels_of_labels_outside_the_layout_are_ignored(self):
        self.assertEqual(self.w(["core/core.h"], levels=dict(LEVELS, **{"//gone:gone": "L3"})), [CORE])

    def test_an_unknown_role_is_an_internal_error(self):
        for role in ("Implementer", "", None, "stub"):
            with self.assertRaises(InternalError):
                self.w(["core/core.h"], role=role)

    def test_malformed_inputs_are_internal_errors(self):
        for kwargs in ({"changed": "core/core.h"}, {"changed": ["core//x"]}, {"changed": [""]},
                       {"changed": ["core/core.h"], "levels": {CORE: "L9"}},
                       {"changed": ["core/core.h"], "impl": {CORE: "core/core.c"}}):
            with self.assertRaises(InternalError, msg=repr(kwargs)):
                self.w(**kwargs)


if __name__ == "__main__":
    unittest.main()
