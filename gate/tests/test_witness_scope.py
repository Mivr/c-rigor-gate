"""impl paths, test surface and the witness scope W (P002, "Terms"), on the canary product's layout.

canaries/_base/product: `//core:core` (L3) with `//core:core_test`; `//util:util` (L2, depends on core)
with `//util:util_test`; and `//util:core_test`, which lives in util but lists `//core:core` directly.
A module's test surface is its own package plus the packages of the unjudged libraries (kits) its own-package
tests link: `//util:core_test` is not core's test (it cannot kill a core mutant), so util's package is not
core's test surface.
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

    CORE_OWN = ["core/BUCK", "core/core.h", "core/core_test.c"]
    UTIL_OWN = ["util/BUCK", "util/util.h", "util/util_core_test.c", "util/util_test.c"]

    def test_surface_of_each_module_is_its_own_package(self):
        surface = ws.test_surface(layout(), IMPL, self.ALL, LEVELS)
        self.assertEqual(surface[CORE], self.CORE_OWN)   # not util's package: //util:core_test is not core's test
        self.assertEqual(surface[UTIL], self.UTIL_OWN)   # not core's package: core is judged on its own (L3)

    def test_the_package_of_an_unjudged_library_the_own_tests_link_is_test_surface_too(self):
        """A test kit in another package: no gate judges it, and a change to it changes what the tests check."""
        kit = "//kits:fake"
        lay = layout(libs=(CORE, UTIL, kit),
                     tests={"//core:core_test": (CORE, kit), "//util:util_test": (UTIL,), "//util:core_test": (UTIL, CORE)})
        paths = self.ALL + ["kits/fake.c", "kits/fake.h", "kits/BUCK"]
        for levels in (dict(LEVELS, **{kit: "L1"}), LEVELS):   # L1, or no level at all
            surface = ws.test_surface(lay, IMPL, paths, levels)
            self.assertEqual(surface[CORE], self.CORE_OWN + ["kits/BUCK", "kits/fake.c", "kits/fake.h"])
            self.assertEqual(surface[UTIL], self.UTIL_OWN)   # //util:core_test lists core, not the kit
        judged = ws.test_surface(lay, IMPL, paths, dict(LEVELS, **{kit: "L2"}))
        self.assertEqual(judged[CORE], self.CORE_OWN)        # a judged library is in W through its own package

    def test_a_kit_reached_through_another_library_counts(self):
        kit, mid = "//kits:fake", "//mid:mid"
        lay = layout(libs=(CORE, UTIL, kit, mid), deps={mid: (kit,)},
                     tests={"//core:core_test": (CORE, mid), "//util:util_test": (UTIL,)})
        surface = ws.test_surface(lay, IMPL, ["kits/fake.h", "mid/mid.h"], dict(LEVELS, **{mid: "L3", kit: "L1"}))
        self.assertEqual(surface[CORE], ["kits/fake.h"])     # mid is judged (L3): its header is mid's surface
        self.assertEqual(surface[mid], ["mid/mid.h"])

    def test_a_kit_only_a_foreign_test_links_does_not_count(self):
        kit = "//kits:fake"
        lay = layout(libs=(CORE, UTIL, kit),
                     tests={"//core:core_test": (CORE,), "//util:util_test": (UTIL,), "//util:core_test": (UTIL, CORE, kit)})
        surface = ws.test_surface(lay, IMPL, ["kits/fake.h"], LEVELS)
        self.assertEqual((surface[CORE], surface[UTIL]), ([], ["kits/fake.h"]))

    def test_without_levels_every_linked_library_counts_as_a_kit(self):
        surface = ws.test_surface(layout(), IMPL, self.ALL)
        self.assertEqual(surface[CORE], self.CORE_OWN)
        self.assertEqual(surface[UTIL], self.CORE_OWN + self.UTIL_OWN)   # util's tests link core: more, never fewer

    def test_impl_paths_of_any_module_are_not_test_surface(self):
        surface = ws.test_surface(layout(), {CORE: ["core/core.c"]}, ["util/util.c", "core/core.c"], LEVELS)
        self.assertEqual(surface, {CORE: [], UTIL: ["util/util.c"]})  # util has no impl here: its source counts
        self.assertEqual(ws.test_surface(layout(), IMPL, ["util/util.c", "core/core.c"]), {CORE: [], UTIL: []})

    def test_the_deepest_package_owns_a_path(self):
        lay = layout(libs=("//a:a", "//a/b:b"), tests={"//a:t": ("//a:a",), "//a/b:t": ("//a/b:b",)})
        surface = ws.test_surface(lay, {}, ["a/b/x.h", "a/y.h", "a/c/z.h"])
        self.assertEqual(surface, {"//a:a": ["a/c/z.h", "a/y.h"], "//a/b:b": ["a/b/x.h"]})

    def test_the_root_package(self):
        lay = layout(libs=("//:root",), tests={"//t:t": ("//:root",)})
        surface = ws.test_surface(lay, {}, ["root.h", "t/t.c", "other/x.c"])
        self.assertEqual(surface, {"//:root": ["other/x.c", "root.h"]})   # t/t.c: another package's test

    def test_paths_outside_every_package_are_nobody_s(self):
        self.assertEqual(ws.test_surface(layout(), IMPL, ["README.md", "docs/x.md"]), {CORE: [], UTIL: []})

    def test_a_package_with_only_tests_of_the_module_is_not_its_test_surface(self):
        lay = layout(tests={"//core:core_test": (CORE,), "//kit:kit_test": (CORE,)})
        self.assertEqual(ws.test_surface(lay, IMPL, ["kit/fake.h"], LEVELS)[CORE], [])

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
        # util/util_core_test.c is //util:core_test, which lists //core:core directly but is not core's test:
        # it cannot kill a core mutant, so changing it cannot weaken core
        self.assertEqual(self.w(["util/util_core_test.c"]), [UTIL])
        self.assertEqual(self.w(["util/util_core_test.c"], role="test-author"), [UTIL])

    def test_a_change_to_util_test_only(self):
        self.assertEqual(self.w(["util/util_test.c"]), [UTIL])

    def test_a_header_of_a_judged_module_does_not_put_its_dependents_in_scope(self):
        # util's tests link core, but core is L3: the header is core's own test surface
        self.assertEqual(self.w(["core/core.h"]), [CORE])

    def test_a_change_to_a_kit_puts_every_module_whose_own_tests_link_it_in_scope(self):
        kit = "//kits:fake"
        lay = layout(libs=(CORE, UTIL, kit),
                     tests={"//core:core_test": (CORE, kit), "//util:util_test": (UTIL, kit), "//util:core_test": (UTIL, CORE)})
        levels = dict(LEVELS, **{kit: "L1"})
        for role in ("implementer", "test-author"):
            self.assertEqual(self.w(["kits/fake.c"], role=role, lay=lay, levels=levels), [CORE, UTIL])
        self.assertEqual(self.w(["kits/fake.c"], lay=lay, levels=dict(LEVELS, **{kit: "L3"})), [kit])

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
        self.assertEqual(self.w(["util/util.h"], levels={CORE: "L3", UTIL: "L1"}), [])   # core's tests do not link util
        self.assertEqual(self.w(["util/util.h"], levels={CORE: "L3"}), [])
        self.assertEqual(self.w(["core/core.h"], levels={CORE: "L3", UTIL: "L1"}), [CORE])
        # core without a level is judged by nobody, and util's own tests link it: its header is util's surface
        self.assertEqual(self.w(["core/core.h"], levels={UTIL: "L2"}), [UTIL])

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
