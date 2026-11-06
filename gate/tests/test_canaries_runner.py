"""Tests for canaries/runner.py scheduling and the miss check (T025). The verdict logic is unchanged."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("canary_runner", ROOT / "canaries" / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def outcome(canary_id, ok=True, pending=None):
    return {"id": canary_id, "ok": ok, "pending": pending}


class ScheduleCase(unittest.TestCase):
    def test_every_canary_once_control_and_uncached_first(self):
        ids = runner.list_ids()
        first, slow, rest = runner.schedule(ids, runner.UNCACHED_DEFAULT)
        self.assertEqual(sorted(first + slow + rest), sorted(ids))
        self.assertEqual(first, ["control"])
        self.assertEqual(slow, [runner.UNCACHED_DEFAULT])

    def test_rest_is_longest_first(self):
        _, _, rest = runner.schedule(runner.list_ids(), runner.UNCACHED_DEFAULT)
        costs = [runner.cost(i) for i in rest]
        self.assertEqual(costs, sorted(costs, reverse=True))

    def test_uncached_not_selected_is_not_forced_in(self):
        first, slow, rest = runner.schedule(["nolint", "inline-asm"], runner.UNCACHED_DEFAULT)
        self.assertEqual((first, slow, sorted(rest)), ([], [], ["inline-asm", "nolint"]))


class MissCase(unittest.TestCase):
    def test_errored_and_absent_are_misses_pending_is_not(self):
        outcomes = [outcome("a"), outcome("b", ok=False), outcome("c", ok=False, pending="T1")]
        self.assertEqual(runner.misses(outcomes, ["a", "b", "c", "d"]), ["b", "d"])

    def test_all_ok_is_clean(self):
        self.assertEqual(runner.misses([outcome("a"), outcome("b")], ["a", "b"]), [])


if __name__ == "__main__":
    unittest.main()
