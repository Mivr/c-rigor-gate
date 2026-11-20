"""T137: the tier of a grade: which modules tier `merge` defers, and what the gates do with the rest (no Buck2)."""

import json
import os
import unittest
from types import SimpleNamespace

from rigor_lib import grade_mutants, grade_tier, profiles
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase

POLICY = """
[module."//a:plain"]
level = "L2"
[module."//b:profiled"]
level = "L2"
profile = "safety"
[module."//c:many"]
level = "L3"
profile = ["adapter", "wiring"]
"""


def grading(tier, policy):
    return SimpleNamespace(args=SimpleNamespace(tier=tier, product=os.path.join(policy, "product.toml")))


def module(label, level):
    return grade_mutants.Module(label, level, ("//t:t",), ())


class Deferral(unittest.TestCase):
    def test_without_profiles_exactly_level_l2_is_deferred(self):
        self.assertIsNotNone(grade_tier.deferral("L2", None))
        for level in ("L3", "L4", "L5"):
            self.assertIsNone(grade_tier.deferral(level, None), level)

    def test_with_profiles_the_matrix_decides_for_every_profile_and_level(self):
        for profile in profiles.PROFILES:
            for level in ("L2", "L3", "L4"):
                gates = profiles.required((profile,), level).get("mutation_zero_survivors") == profiles.GATE
                self.assertEqual(grade_tier.deferral(level, (profile,)) is None, gates, (profile, level))

    def test_the_cells_of_the_matrix_as_written(self):
        # P003 4.1: pure and parser gate from L3, safety at every level; adapter and concurrent only report;
        # wiring, ui have no mutation cell.
        for profile in ("pure", "parser"):
            self.assertIsNotNone(grade_tier.deferral("L2", (profile,)))
            self.assertIsNone(grade_tier.deferral("L3", (profile,)))
            self.assertIsNone(grade_tier.deferral("L4", (profile,)))
        for profile in ("adapter", "concurrent", "wiring", "ui"):
            for level in ("L2", "L3", "L4"):
                self.assertIsNotNone(grade_tier.deferral(level, (profile,)), (profile, level))
        for level in ("L2", "L3", "L4"):
            self.assertIsNone(grade_tier.deferral(level, ("safety",)))

    def test_one_gating_profile_among_several_keeps_the_module(self):
        self.assertIsNone(grade_tier.deferral("L2", ("adapter", "safety")))
        self.assertIsNotNone(grade_tier.deferral("L2", ("adapter", "wiring")))

    def test_an_unknown_profile_or_level_is_never_deferred(self):
        self.assertIsNone(grade_tier.deferral("L3", ("nonsense",)))
        self.assertIsNone(grade_tier.deferral("L9", ("pure",)))

    def test_the_reason_names_the_profile_and_the_level(self):
        self.assertIn("adapter at L3", grade_tier.deferral("L3", ("adapter",)))
        self.assertIn("L2", grade_tier.deferral("L2", None))


class Split(TempDirTestCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "policy.toml").write_text(POLICY)
        self.modules = [module("//a:plain", "L2"), module("//b:profiled", "L2"), module("//c:many", "L3")]

    def test_nightly_defers_nothing_and_is_the_default(self):
        for tier in ("nightly", None):
            kept, deferred = grade_tier.split(grading(tier, str(self.tmp)), self.modules)
            self.assertEqual((kept, deferred), (self.modules, []))
            self.assertEqual(grade_tier.metadata(grading(tier, str(self.tmp)), deferred), {})
        self.assertEqual(grade_tier.tier_of(SimpleNamespace(args=SimpleNamespace())), "nightly")

    def test_merge_defers_the_report_only_modules_and_says_why(self):
        g = grading("merge", str(self.tmp))
        kept, deferred = grade_tier.split(g, self.modules)
        self.assertEqual([m.label for m in kept], ["//b:profiled"])
        self.assertEqual([m.label for m, _ in deferred], ["//a:plain", "//c:many"])
        found = grade_tier.findings(deferred)
        self.assertEqual([(f["rule"], f["severity"], f["module"], f["level"]) for f in found],
                         [("mutation-deferred", "info", "//a:plain", "L2"),
                          ("mutation-deferred", "info", "//c:many", "L3")])
        self.assertTrue(all(f["reason"] for f in found))
        self.assertEqual(grade_tier.metadata(g, deferred), {"tier": "merge", "deferred": 2})

    def test_a_bad_profile_shape_is_exit_two(self):
        (self.tmp / "policy.toml").write_text('[module."//a:x"]\nlevel = "L2"\nprofile = 3\n')
        with self.assertRaises(InternalError):
            grade_tier.split(grading("merge", str(self.tmp)), self.modules)


class Parser(unittest.TestCase):
    def test_the_tiers_and_the_default(self):
        self.assertEqual(grade_tier.TIERS, ("merge", "nightly"))
        self.assertEqual(grade_tier.DEFAULT, "nightly")


if __name__ == "__main__":
    unittest.main()
