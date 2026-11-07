"""Tests for canaries/runner.py scheduling and the miss check (T025). The verdict logic is unchanged."""

import importlib.util
import os
import subprocess
import tempfile
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
        controls = [i for i in ids if runner.load_expect(i).get("control")]
        self.assertTrue(controls)
        self.assertEqual(sorted(first), sorted(controls))
        self.assertNotIn(runner.UNCACHED_DEFAULT, first)
        self.assertEqual(slow, [runner.UNCACHED_DEFAULT])

    def test_rest_is_longest_first(self):
        _, _, rest = runner.schedule(runner.list_ids(), runner.UNCACHED_DEFAULT)
        costs = [runner.cost(i) for i in rest]
        self.assertEqual(costs, sorted(costs, reverse=True))

    def test_uncached_not_selected_is_not_forced_in(self):
        first, slow, rest = runner.schedule(["nolint", "inline-asm"], runner.UNCACHED_DEFAULT)
        self.assertEqual((first, slow, sorted(rest)), ([], [], ["inline-asm", "nolint"]))


class WitnessCase(unittest.TestCase):
    def test_own_bundle_else_shared_base_bundle(self):
        base = str(ROOT / "canaries" / "_base" / "witness")
        self.assertEqual(runner.witness_dir("control"), base)
        self.assertEqual(runner.witness_dir("witness-missing"), str(ROOT / "canaries" / "witness-missing" / "witness"))

    def test_every_bundle_is_a_manifest_and_files(self):
        for canary_id in runner.list_ids() + ["_base"]:
            bundle = Path(runner.witness_dir(canary_id)) if canary_id != "_base" else ROOT / "canaries" / "_base" / "witness"
            self.assertEqual(sorted(p.name for p in bundle.iterdir()), ["files", "witness.toml"], canary_id)


class MissCase(unittest.TestCase):
    def test_errored_and_absent_are_misses_pending_is_not(self):
        outcomes = [outcome("a"), outcome("b", ok=False), outcome("c", ok=False, pending="T1")]
        self.assertEqual(runner.misses(outcomes, ["a", "b", "c", "d"]), ["b", "d"])

    def test_all_ok_is_clean(self):
        self.assertEqual(runner.misses([outcome("a"), outcome("b")], ["a", "b"]), [])


class LeakCase(unittest.TestCase):
    def test_process_in_tree_is_found_and_outside_is_not(self):
        with tempfile.TemporaryDirectory() as tree, tempfile.TemporaryDirectory() as other:
            inside = subprocess.Popen(["sleep", "30"], cwd=os.path.join(tree))
            outside = subprocess.Popen(["sleep", "30"], cwd=other)
            try:
                found = runner.find_daemons(tree)
                self.assertEqual([pid for pid, _ in found], [inside.pid])
                self.assertEqual(runner.find_daemons(os.path.join(tree, "nothing")), [])
            finally:
                inside.kill()
                outside.kill()
                inside.wait()
                outside.wait()
            self.assertEqual(runner.find_daemons(tree), [])

    def test_leak_fails_the_canary_even_when_the_verdict_is_right(self):
        with tempfile.TemporaryDirectory() as work:
            verdict = os.path.join(work, "verdict.json")
            with open(verdict, "w", encoding="utf-8") as handle:
                handle.write('{"core": {"overall": "PASS", "gates": []}}')
            expect = {"control": True}
            clean = runner.judge(expect, 0, os.path.join(work, "grade"), verdict, work)
            self.assertTrue(clean["ok"], clean)
            daemon = subprocess.Popen(["sleep", "30"], cwd=work)
            try:
                leaked = runner.judge(expect, 0, os.path.join(work, "grade"), verdict, work)
            finally:
                daemon.kill()
                daemon.wait()
            self.assertFalse(leaked["ok"])
            self.assertIn("still running", leaked["why"][0])
            self.assertIn(str(daemon.pid), leaked["why"][0])

    def test_leak_is_reported_without_a_verdict_too(self):
        with tempfile.TemporaryDirectory() as work:
            daemon = subprocess.Popen(["sleep", "30"], cwd=work)
            try:
                result = runner.judge({"control": True}, 1, work, os.path.join(work, "none.json"), work)
            finally:
                daemon.kill()
                daemon.wait()
            self.assertEqual(result["why"][0], "no verdict.json")
            self.assertIn("still running", result["why"][1])


if __name__ == "__main__":
    unittest.main()
