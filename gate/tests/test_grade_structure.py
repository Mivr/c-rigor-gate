"""Unit tests of the `structure` and `mode-divergence` steps of `rigor grade` that need no Buck2
(selftest/grade.sh and the canaries run the real thing)."""

import os
import tomllib
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_pipeline, grade_structure, structure
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase


def facts_entry(kind="c_library", srcs=("a.c",), deps=(), unit=None, name="a"):
    return {"kind": kind, "srcs": list(srcs), "facts_deps": list(deps), "facts_name": name,
            "unit": unit or "root//p:" + name}


class Parsing(unittest.TestCase):
    def test_modules_come_from_the_c_facts_attributes(self):
        facts = {"root//p:a_facts": facts_entry(deps=["root//q:b", "gate//ctest:ctest", "other//x:y"]),
                 "root//q:b_facts": facts_entry(srcs=["b.c", "c.c"], name="b")}
        mutsrc = {"root//p:a_mutsrc": {"headers": ["root//p/a.h"]}}
        modules, every = grade_structure.parse_modules(facts, mutsrc)
        self.assertEqual(every, {"//p:a", "//q:b"})
        first = modules[0]
        self.assertEqual((first.label, first.unit, first.kind, first.srcs, first.headers),
                         ("//p:a", "//p:a", "c_library", ("a.c",), ("a.h",)))
        self.assertEqual(first.deps, ("//q:b", "gate//ctest:ctest"))   # a third cell is not ours to graph
        self.assertEqual(modules[1].headers, ())

    def test_a_header_only_module_has_no_target_and_is_no_dependency(self):
        facts = {"root//p:h_facts": facts_entry(srcs=[], name="h"),
                 "root//p:a_facts": facts_entry(deps=["root//p:h"])}
        modules, every = grade_structure.parse_modules(facts, {})
        self.assertEqual([m.label for m in modules], ["//p:a"])
        self.assertEqual(modules[0].deps, ())
        self.assertEqual(every, {"//p:a", "//p:h"})   # but the policy may still name it

    def test_a_fuzz_target_is_known_by_its_name_and_compiled_through_its_unit(self):
        facts = {"root//p:f_facts": facts_entry(kind="c_fuzz", name="f", unit="root//p:f__facts_unit")}
        modules, _ = grade_structure.parse_modules(facts, {})
        self.assertEqual((modules[0].label, modules[0].unit), ("//p:f", "//p:f__facts_unit"))
        self.assertIn('module = ":f__facts_unit"', grade_structure.call_text(modules[0]))
        self.assertIn('facts_name = "f"', grade_structure.call_text(modules[0]))

    def test_odd_query_output_is_an_internal_error(self):
        for facts, mutsrc in (
                ([], {}), ({}, []),
                ({"root//p:a_facts": []}, {}),
                ({"root//p:a_facts": dict(facts_entry(), kind="c_other")}, {}),
                ({"root//p:a_facts": dict(facts_entry(), srcs="a.c")}, {}),
                ({"root//p:a_facts": dict(facts_entry(), unit=None)}, {}),
                ({"other//p:a_facts": facts_entry()}, {}),
                ({"root//p:a_facts": facts_entry()}, {"root//p:a_other": {"headers": []}}),
                ({"root//p:a_facts": facts_entry()}, {"root//p:a_mutsrc": {"headers": ["root//q/a.h"]}}),
                ({"root//p:a_facts": facts_entry()}, {"root//p:a_mutsrc": {"headers": ["root//p/"]}})):
            with self.subTest(facts=facts, mutsrc=mutsrc), self.assertRaises(InternalError):
                grade_structure.parse_modules(facts, mutsrc)

    def test_a_root_package_file_has_no_directory(self):
        mutsrc = {"root//:a_mutsrc": {"headers": ["root//a.h"]}}
        modules, _ = grade_structure.parse_modules({"root//:a_facts": facts_entry()}, mutsrc)
        self.assertEqual(modules[0].headers, ("a.h",))
        self.assertEqual(grade_structure.package_of(modules[0]), "")


class Policy(unittest.TestCase):
    def modules(self):
        facts = {"root//p:a_facts": facts_entry(), "root//p:t_facts": facts_entry(kind="c_test", name="t"),
                 "root//p:f_facts": facts_entry(kind="c_fuzz", name="f"),
                 "root//p:n_facts": facts_entry(name="n")}
        return grade_structure.parse_modules(facts, {})[0]

    def test_levels_map_to_the_structure_limits_and_tests_have_none(self):
        for level, expected in (("L1", "L1"), ("L2", "L2"), ("L3", "L3"), ("L4", "L3"), ("L5", "L3"), (None, None)):
            self.assertEqual(grade_structure.structure_level(level), expected)
        text = grade_structure.policy_text(self.modules(), {"//p:a": "L5", "//p:t": "L1", "//p:f": "L2"})
        document = tomllib.loads(text)["module"]
        self.assertEqual(document, {"//p:a": {"level": "L3"}, "//p:f": {}, "//p:n": {}, "//p:t": {}})

    def test_the_policy_text_is_what_rigor_structure_reads(self):
        text = grade_structure.policy_text(self.modules(), {"//p:a": "L2"})
        levels = tomllib.loads(text)["module"]
        self.assertEqual(levels["//p:a"], {"level": "L2"})
        self.assertEqual(structure.GATE_ID, grade_structure.structure.GATE_ID)


class Targets(TempDirTestCase):
    def module(self, **kwargs):
        facts = {"root//p:a_facts": facts_entry(**kwargs)}
        return grade_structure.parse_modules(facts, {"root//p:a_mutsrc": {"headers": ["root//p/a.h"]}})[0]

    def buck(self):
        return str(self.tmp / "p" / "BUCK")

    def package(self, text=b"c_library(name = 'a')\n"):
        os.makedirs(str(self.tmp / "p"))
        with open(self.buck(), "wb") as handle:
            handle.write(text)
        os.chmod(self.buck(), 0o444)

    def test_the_target_is_appended_beside_the_module_and_the_file_comes_back_byte_for_byte(self):
        self.package()
        modules = self.module(deps=["root//q:b"])
        originals = grade_structure.extend_build_files(str(self.tmp), modules)
        with open(self.buck(), "rb") as handle:
            text = handle.read().decode("utf-8")
        self.assertTrue(text.startswith('load("@gate//rules:structure.bzl", "c_structure")\n'))
        self.assertIn("c_library(name = 'a')\n", text)
        self.assertIn('name = "a__structure"', text)
        self.assertIn('srcs = ["a.c"]', text)
        self.assertIn('headers = ["a.h"]', text)
        self.assertIn('deps = ["//q:b"]', text)
        self.assertEqual(grade_structure.target_label(modules[0]), "//p:a__structure")
        grade_structure.restore_build_files(originals)
        with open(self.buck(), "rb") as handle:
            self.assertEqual(handle.read(), b"c_library(name = 'a')\n")
        self.assertEqual(os.stat(self.buck()).st_mode & 0o777, 0o444)

    def test_a_package_without_a_build_file_is_refused(self):
        with self.assertRaises(InternalError):
            grade_structure.extend_build_files(str(self.tmp), self.module())

    def test_a_unit_outside_the_package_is_refused_and_nothing_is_left_changed(self):
        self.package()
        with self.assertRaises(InternalError):
            grade_structure.extend_build_files(str(self.tmp), self.module(unit="root//q:a"))
        with open(self.buck(), "rb") as handle:
            self.assertEqual(handle.read(), b"c_library(name = 'a')\n")


class Gating(unittest.TestCase):
    def grading(self, **status):
        return SimpleNamespace(status=status, tree="/nonexistent")

    def test_both_gates_need_a_clean_build(self):
        for gate in (grade_structure.structure_gate, grade_structure.modes_gate):
            for status in ({}, {"assemble": "PASS"}, {"assemble": "PASS", "build": "FAIL"},
                           {"assemble": "FAIL", "build": "PASS"}):
                self.assertIsNone(gate(self.grading(**status)))

    def test_both_gates_come_after_build_and_before_the_tests(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("build") + 1:ids.index("tests-release")], ["structure", "mode-divergence"])

    def test_san_twins(self):
        self.assertEqual(grade_structure.san_twin("root//p:a_facts"), "root//p:a_facts_san")


class ModesFindings(TempDirTestCase):
    def test_a_missing_twin_is_a_finding_and_no_comparison_is_made(self):
        grading = SimpleNamespace(status={"assemble": "PASS", "build": "PASS"}, tree="/t", work=str(self.tmp),
                                  args=SimpleNamespace(uncached=False))
        labels = {"c_facts": ["root//p:a_facts", "root//p:b_facts"], "c_san_facts": ["root//p:a_facts_san"]}
        with mock.patch.object(grade_structure, "query_labels", lambda tree, expr: labels[expr.split("(")[1].split(",")[0]]), \
                mock.patch.object(grade_structure, "_build_mode", lambda *a: ([], {"executed_actions": 0, "cached_actions": 0})), \
                mock.patch.object(grade_structure.facts_modes, "run") as compare:
            result = grade_structure._modes(grading)
        compare.assert_not_called()
        rules = sorted((f["rule"], f["target"], f.get("mode")) for f in result.findings)
        self.assertEqual(rules[0], ("missing-san-twin", "root//p:b_facts", None))
        self.assertEqual(result.status, "FAIL")


if __name__ == "__main__":
    unittest.main()
