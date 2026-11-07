"""Tests for the tripwire pack (T086): the runner's --root, the green-tripwire message, the daily uncached rotation,
the pack's shape, and its place in tools/affected.py."""

import importlib.util
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("tripwire_runner", ROOT / "canaries" / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
spec = importlib.util.spec_from_file_location("affected_tool", ROOT / "tools" / "affected.py")
affected = importlib.util.module_from_spec(spec)
spec.loader.exec_module(affected)

PACK = ROOT / "tripwires"
GATES = [line.strip() for line in (ROOT / "gate" / "order.txt").read_text().split("\n") if line.strip()]


class PackShape(unittest.TestCase):
    def ids(self):
        return sorted(p.name for p in PACK.iterdir() if (p / "expect.json").is_file())

    def test_every_tripwire_has_the_gate_inputs_and_expects_a_known_gate(self):
        self.assertTrue(self.ids())
        for name in self.ids():
            for f in ("product.toml", "policy.toml", "expected-tests.json", "task.toml", "edit.sh"):
                self.assertTrue((PACK / name / f).is_file(), "%s/%s" % (name, f))
            expect = json.loads((PACK / name / "expect.json").read_text())
            self.assertTrue(expect.get("fail"), name)
            self.assertFalse(expect.get("control") or expect.get("pending"), name)
            self.assertLessEqual(set(expect["fail"]), set(GATES), name)

    def test_every_gate_is_covered_or_explained(self):
        covered = set()
        for name in self.ids():
            covered |= set(json.loads((PACK / name / "expect.json").read_text())["fail"])
        text = (ROOT / "docs" / "tripwires.md").read_text()
        for gate in GATES:
            self.assertTrue(gate in covered or ("`%s`" % gate) in text, gate)


class Messages(unittest.TestCase):
    def test_green_message_names_the_blind_gates(self):
        expect = {"fail": {"tests-san": ["missing-test"], "tests-release": ["missing-test"]}}
        self.assertEqual(runner.green_message("x", expect), "tripwire x is green: tests-release, tests-san is blind")

    def test_only_a_tripwires_root_turns_a_pass_into_a_blind_gate(self):
        old = runner.CANARIES
        try:
            runner.CANARIES = str(PACK)
            self.assertTrue(runner.is_tripwire_root())
            runner.CANARIES = str(ROOT / "canaries")
            self.assertFalse(runner.is_tripwire_root())
        finally:
            runner.CANARIES = old

    def test_uncached_rotates_by_day_over_sorted_ids(self):
        ids = ["c", "a", "b"]
        self.assertEqual([runner.uncached_for_day(ids, d) for d in range(4)], ["a", "b", "c", "a"])
        self.assertIsNone(runner.uncached_for_day([], 5))


class Affected(unittest.TestCase):
    def pick(self, *paths):
        return affected.select(paths, affected.load_rules())[0]

    def test_tripwire_files_select_tripwires_and_canary_paths_select_both(self):
        self.assertIn("tripwires", self.pick("tripwires/x/expect.json"))
        self.assertIn("tripwires", self.pick("selftest/tripwires.sh"))
        self.assertNotIn("canaries", self.pick("tripwires/x/expect.json"))
        self.assertLessEqual({"canaries", "tripwires"}, self.pick("canaries/x/expect.json"))
        self.assertLessEqual({"canaries", "tripwires"}, self.pick("gate/order.txt"))


if __name__ == "__main__":
    unittest.main()
