"""T2G1: the shard merge and the release-vs-san identity comparison of `c_sim` (gate/rigor_lib/sim_merge.py)."""

import json
import subprocess
import sys

from rigor_lib import sim_merge
from tests.helpers import GATE_DIR, TempDirTestCase

WORLD = "w" * 64
SALT = "s" * 64


def shard(first, count, rule=None, ran=None, world=WORLD, hashes=None):
    ran = count if ran is None else ran
    rows = {index: ("%016x" % (index + 1), "%016x" % (0xa0 + index), "%016x" % (0xb0 + index))
            for index in range(first, first + ran)}
    if hashes:
        rows.update(hashes)
    failures = [] if rule is None else [{"detail": 11, "index": first, "rule": rule, "seed": "%016x" % (first + 1)}]
    text = "".join("%d %s %s %s\n" % ((i,) + rows[i]) for i in sorted(rows))
    return {"stats": {"count": count, "distinct_hashes": len({r[1] for r in rows.values()}), "failures": failures,
                      "first": first, "run_ms": 5, "salt_sha256": SALT, "schema": "sim-stats/1",
                      "seeds_run": ran, "world_sha256": world},
            "hashes": text, "verdict": "pass\n" if rule is None else "fail %s\n" % rule}


class MergeCase(TempDirTestCase):
    def test_two_good_shards_pass(self):
        verdict, stats, hashes = sim_merge.merge([shard(0, 3), shard(3, 3)], 6)
        self.assertEqual(verdict, "pass\n")
        self.assertEqual((stats["seeds_run"], stats["distinct_hashes"], stats["shards"], stats["failures"]), (6, 6, 2, []))
        self.assertEqual(len(hashes.splitlines()), 6)

    def test_a_failing_shard_fails_the_target_with_its_rule(self):
        for rule in ("sim-crash", "sim-timeout", "sim-nondeterministic", "sim-deadlock"):
            with self.subTest(rule=rule):
                verdict, stats, _ = sim_merge.merge([shard(0, 3), shard(3, 3, rule=rule)], 6)
                self.assertEqual(verdict, "fail %s\n" % rule)
                self.assertEqual([f["rule"] for f in stats["failures"]], [rule])

    def test_zero_seeds_is_no_seeds_never_a_pass(self):
        self.assertEqual(sim_merge.merge([shard(0, 0)], 0)[0], "fail sim-no-seeds\n")
        self.assertEqual(sim_merge.merge([shard(0, 0)], 5)[0], "fail sim-no-seeds\n")
        self.assertEqual(sim_merge.merge([], 5)[0], "fail sim-no-seeds\n")

    def test_a_shard_that_ran_fewer_seeds_than_asked_fails(self):
        self.assertEqual(sim_merge.merge([shard(0, 3), shard(3, 3, ran=2)], 6)[0], "fail sim-no-seeds\n")

    def test_fewer_seeds_than_expected_fails(self):
        self.assertEqual(sim_merge.merge([shard(0, 3), shard(3, 2)], 6)[0], "fail sim-no-seeds\n")

    def test_shards_of_different_worlds_fail(self):
        self.assertEqual(sim_merge.merge([shard(0, 3), shard(3, 3, world="x" * 64)], 6)[0], "fail sim-world-error\n")

    def test_equal_trace_hashes_over_the_seeds_are_vacuous(self):
        same = {index: ("%016x" % (index + 1), "00", "00") for index in range(6)}
        parts = [shard(0, 3, hashes=same), shard(3, 3, hashes=same)]
        self.assertEqual(sim_merge.merge(parts, 6)[0], "fail sim-vacuous\n")

    def test_a_malformed_hashes_file_is_an_error(self):
        for text in ("1 2 3\n", "x 1 2 3\n", "0 a b c\n0 a b c\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sim_merge.parse_hashes(text)

    def test_the_stats_file_is_canonical_json(self):
        run = subprocess.run([sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "sim_merge.py"), "--expect", "3",
                              "--out-stats", str(self.tmp / "s"), "--out-hashes", str(self.tmp / "h"),
                              "--out-verdict", str(self.tmp / "v")] + self.shard_args(shard(0, 3)),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        text = (self.tmp / "s").read_text()
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual((self.tmp / "v").read_text(), "pass\n")

    def shard_args(self, part):
        (self.tmp / "in.stats").write_text(json.dumps(part["stats"]))
        (self.tmp / "in.hashes").write_text(part["hashes"])
        (self.tmp / "in.verdict").write_text(part["verdict"])
        return ["--shard", str(self.tmp / "in.stats"), str(self.tmp / "in.hashes"), str(self.tmp / "in.verdict")]


class ModesCase(TempDirTestCase):
    def test_equal_hashes_have_no_finding(self):
        text = shard(0, 12)["hashes"]
        self.assertEqual(sim_merge.compare_modes(text, text), [])

    def test_a_different_hash_of_seeds_0_to_9_is_nondeterministic(self):
        left = shard(0, 12)["hashes"]
        right = left.replace("%016x" % 0xa3, "%016x" % 0xff)
        found = sim_merge.compare_modes(left, right)
        self.assertEqual([(f["index"], f["rule"]) for f in found], [(3, "sim-nondeterministic")])

    def test_a_difference_after_seed_9_is_not_compared(self):
        left = shard(0, 12)["hashes"]
        self.assertEqual(sim_merge.compare_modes(left, left.replace("%016x" % 0xab, "%016x" % 0xff)), [])

    def test_a_missing_seed_in_one_mode_is_a_finding(self):
        left = shard(0, 12)["hashes"]
        right = "".join(line for line in left.splitlines(True) if not line.startswith("4 "))
        self.assertEqual([f["index"] for f in sim_merge.compare_modes(left, right)], [4])
        self.assertEqual([f["index"] for f in sim_merge.compare_modes(right, left)], [4])
        self.assertEqual(len(sim_merge.compare_modes("", left)), 10)

    def test_the_command_line(self):
        (self.tmp / "a").write_text(shard(0, 10)["hashes"])
        (self.tmp / "b").write_text(shard(0, 10)["hashes"].replace("%016x" % 0xa1, "%016x" % 0xee))
        script = str(GATE_DIR / "rigor_lib" / "sim_merge.py")
        same = subprocess.run([sys.executable, "-I", "-B", script, "compare", str(self.tmp / "a"), str(self.tmp / "a")],
                              capture_output=True, text=True, timeout=60)
        diff = subprocess.run([sys.executable, "-I", "-B", script, "compare", str(self.tmp / "a"), str(self.tmp / "b")],
                              capture_output=True, text=True, timeout=60)
        bad = subprocess.run([sys.executable, "-I", "-B", script, "compare", str(self.tmp / "a"), str(self.tmp / "none")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual((same.returncode, diff.returncode, bad.returncode), (0, 1, 2))
        self.assertEqual(json.loads(diff.stdout)["index"], 1)
