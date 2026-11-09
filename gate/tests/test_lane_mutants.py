"""Unit tests of `rigor lane-mutants` that need no Buck2 (selftest/mutants_lane.sh has the rest)."""

import unittest

from rigor_lib import grade_mutants, lane_mutants
from rigor_lib.errors import InternalError


def module(label, level="L2"):
    return grade_mutants.Module(label, level, ("//a:t",), ())


class LaneMutantsTests(unittest.TestCase):
    def test_package_label_gets_its_default_target(self):
        self.assertEqual(lane_mutants.normalise("//core/util"), "//core/util:util")
        self.assertEqual(lane_mutants.normalise("//core:extra"), "//core:extra")

    def test_bad_labels_are_refused(self):
        for label in ("core:x", "//a b", "//", "x//a:b"):
            with self.assertRaises(InternalError, msg=label):
                lane_mutants.normalise(label)

    def test_select_keeps_the_grade_modules_and_overrides_only_the_level(self):
        planned = [module("//a:a"), module("//b:b", "L3")]
        chosen = lane_mutants.select(planned, ["//b:b"], "L4")
        self.assertEqual(chosen, [module("//b:b", "L4")])
        self.assertEqual(lane_mutants.select(planned, ["//b:b", "//a:a"], None), [planned[1], planned[0]])
        self.assertEqual(grade_mutants.build_file_text(chosen), grade_mutants.build_file_text([planned[1]]))

    def test_unknown_module_names_the_choices(self):
        with self.assertRaisesRegex(InternalError, "not a mutated module.*//a:a"):
            lane_mutants.select([module("//a:a")], ["//c:c"], None)


if __name__ == "__main__":
    unittest.main()
