"""The soak of `rigor sim` (T2G6, P330 §1.6, §1.7): the soak result file, `soak-too-short`, the assertions with their day,
what a soak must have checked, the merge tier that runs none, and the binding of the soak to the run."""

import json
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_sim, sim_judge, sim_policy
from tests import test_grade_sim
from tests import test_sim_judge_helpers as h
from tests.helpers import TempDirTestCase
from tests.test_sim_judge import SimJudgeCase

CAPACITY = '[soak.capacity.snapshot_pool]\nevent = "snapshot upload"\nbound = 6\nrate_per_day = 2\n'
POLICY = "[sim]\n[sim.seeds]\nmerge = 1\nnightly = 1\n[sim.soak_days]\nmerge = 0\nnightly = 50\n" + CAPACITY


class SoakFile(SimJudgeCase):
    def test_a_soak_that_ran_the_days_and_checked_everything_passes(self):
        h.write_run(self.results)
        h.write_soak(self.results, days=50)
        self.judge(0, policy=POLICY)
        self.assertEqual(self.doc()["metadata"]["targets"][h.SIM]["soak_days"], 50)

    def test_the_failed_assertions_are_reported_with_their_day(self):
        h.write_run(self.results)
        h.write_soak(self.results, days=50, failures=[("I12", 3), ("I13", 4), ("I11", 5)])
        self.judge(1, policy=POLICY)
        items = h.findings(self.out, "soak-assertion")
        self.assertEqual(sorted((i["day"], i["assertion"]) for i in items), [(3, "I12"), (4, "I13"), (5, "I11")])

    def test_a_soak_shorter_than_the_sizing_rule_is_too_short_even_when_the_tier_asks_for_less(self):
        policy = "[sim]\n[sim.seeds]\nnightly = 1\n[sim.soak_days]\nnightly = 2\n" + CAPACITY
        h.write_run(self.results)
        h.write_soak(self.results, days=5)       # ceil(2 * 6 / 2) = 6 days of events are needed
        self.judge(1, policy=policy)
        (item,) = h.findings(self.out, "soak-too-short")
        self.assertEqual((item["required_days"], item["days"]), (6, 5))
        h.write_soak(self.results, days=6)
        self.judge(0, policy=policy)

    def test_no_soak_file_at_a_tier_that_demands_one_is_too_short(self):
        h.write_run(self.results)
        self.judge(1, policy=POLICY)
        (item,) = h.findings(self.out, "soak-too-short")
        self.assertEqual((item["required_days"], item["days"]), (50, 0))

    def test_the_merge_tier_runs_no_soak_and_asks_for_none(self):
        h.write_run(self.results)
        self.judge(0, policy=POLICY, tier="merge")
        self.assertEqual(self.rules(), [])

    def test_a_soak_result_at_the_merge_tier_is_exit_2(self):
        h.write_run(self.results)
        h.write_soak(self.results)
        self.judge(2, policy=POLICY, tier="merge")

    def test_a_policy_that_asks_for_a_merge_soak_gets_one_judged_like_any_other(self):
        policy = "[sim]\n[sim.seeds]\nmerge = 1\n[sim.soak_days]\nmerge = 4\n"
        h.write_run(self.results)
        self.judge(1, policy=policy, tier="merge")       # asked for, not there
        self.assertEqual(h.findings(self.out, "soak-too-short")[0]["required_days"], 4)
        h.write_soak(self.results, days=4)
        self.judge(0, policy=policy, tier="merge")

    def test_a_world_that_stopped_is_an_assertion_and_a_short_soak(self):
        h.write_run(self.results)
        h.write_soak(self.results, days=9, failures=[("sim-timeout", 10)])
        self.judge(1, policy=POLICY)
        self.assertEqual(sorted(set(self.rules())), ["soak-assertion", "soak-too-short"])


class SoakChecksNothing(SimJudgeCase):
    def test_a_soak_that_never_evaluated_the_capacity_gauge_is_vacuous(self):
        h.write_run(self.results)
        h.write_soak(self.results, checked={"I11": 50, "I12": 0, "I13": 50})
        self.judge(1, policy=POLICY)      # the capacity rows demand I12
        (item,) = h.findings(self.out, "sim-vacuous")
        self.assertEqual((item["soak"], item["count"]), ("I12", 0))

    def test_every_invariant_the_spec_lists_must_have_been_checked_by_the_soak(self):
        policy = "[sim]\n[sim.seeds]\nnightly = 1\n[sim.soak_days]\nnightly = 3\n"
        h.write_run(self.results, invariants={"I11": {"checked": 1, "violated": 0}, "I13": {"checked": 1, "violated": 0}})
        h.write_soak(self.results, days=3, checked={"I11": 0, "I12": 0, "I13": 3})
        self.judge(1, policy=policy, spec='invariants = ["I11", "I13"]\n')
        self.assertEqual([i["soak"] for i in h.findings(self.out, "sim-vacuous")], ["I11"])   # I12 is not asked for

    def test_without_capacity_rows_or_spec_the_soak_may_check_nothing(self):
        h.write_run(self.results)
        h.write_soak(self.results, days=3, checked={"I11": 0, "I12": 0, "I13": 0})
        self.judge(0, policy="[sim]\n[sim.seeds]\nnightly = 1\n[sim.soak_days]\nnightly = 3\n")


class SoakBinding(SimJudgeCase):
    def test_a_soak_of_another_world_or_salt_is_exit_2(self):
        h.write_run(self.results)
        for override in ({"world_sha256": "cd" * 32}, {"salt_sha256": "00" * 32}):
            with self.subTest(override=override):
                h.write_soak(self.results, **override)
                self.judge(2, policy=POLICY)

    def test_a_soak_seed_that_is_not_the_derivation_is_exit_2(self):
        h.write_run(self.results)
        h.write_soak(self.results, seed="0123456789abcdef")
        self.judge(2, policy=POLICY)
        h.write_soak(self.results, seed=h.row(0)[0])   # the seed of an ordinary index is not the soak's
        self.judge(2, policy=POLICY)

    def test_the_soak_enters_the_seed_digest(self):
        h.write_run(self.results)
        self.judge(1, policy=POLICY)
        before = self.doc()["metadata"]["seed_digest"]
        h.write_soak(self.results, days=50)
        self.judge(0, policy=POLICY)
        with_soak = self.doc()["metadata"]["seed_digest"]
        h.write_soak(self.results, days=50, state_hash="%016x" % 8)
        self.judge(0, policy=POLICY)
        self.assertEqual(len({before, with_soak, self.doc()["metadata"]["seed_digest"]}), 3)

    def test_a_soak_in_the_stats_and_a_soak_file_is_exit_2(self):
        h.write_run(self.results, soak={"days": 50, "failures": []})
        h.write_soak(self.results)
        self.judge(2, policy=POLICY)

    def test_the_soak_file_is_part_of_the_directory(self):
        h.write_run(self.results)
        h.write_soak(self.results, ident="t000")
        (self.results / "t001.soak.json").write_text("{}")      # an id the index does not name
        self.judge(2, policy=POLICY)


class SoakFileDefects(SimJudgeCase):
    def test_every_malformed_soak_file_is_exit_2(self):
        good = json.loads(self.soak_text())
        cases = {"not json": "{", "not an object": "[]", "missing key": {k: v for k, v in good.items() if k != "uploads"},
                 "extra key": dict(good, extra=1), "schema": dict(good, schema="sim-soak/2"),
                 "negative days": dict(good, days=-1), "bool days": dict(good, days=True),
                 "checked keys": dict(good, checked={"I11": 1}), "checked value": dict(good, checked={"I11": 1, "I12": -1, "I13": 1}),
                 "failures": dict(good, failures={}), "failure shape": dict(good, failures=[{"assertion": "I11"}]),
                 "failure empty": dict(good, failures=[{"assertion": "", "day": 1}]),
                 "failure day": dict(good, failures=[{"assertion": "I11", "day": -2}]),
                 "hash": dict(good, state_hash="XYZ"), "world": dict(good, world_sha256="ab"), "uploads": dict(good, uploads="7")}
        for name, doc in cases.items():
            with self.subTest(name):
                h.write_run(self.results)
                (self.results / "t000.soak.json").write_text(doc if isinstance(doc, str) else json.dumps(doc))
                self.judge(2, policy=POLICY)

    def soak_text(self):
        h.write_soak(self.tmp)
        return (self.tmp / "t000.soak.json").read_text()


class Arithmetic(SimJudgeCase):
    def test_the_capacity_rule_is_ceil_of_twice_the_bound_over_the_rate(self):
        row = sim_policy.Capacity("snapshot_pool", "snapshot upload", 6, 2)
        self.assertEqual(row.days, 6)
        row = sim_policy.Capacity("snapshot_pool", "snapshot upload", 131070, 1440)
        self.assertEqual(row.days, 183)
        self.assertEqual(sim_judge.SOAK_CHECKS, ("I11", "I12", "I13"))


class GradeSoak(TempDirTestCase):
    """The grade builds `<target>[soak]` in the san build only, only for the tier that demands days, and collects it."""

    POLICY = test_grade_sim.Step.POLICY + "[sim]\ntarget = \"//p:sim\"\n[sim.seeds]\nmerge = 1\nnightly = 1\n" \
        "[sim.soak_days]\nmerge = 0\nnightly = 7\n"
    grading = test_grade_sim.Step.grading

    def run_step(self, tier, policy=None, labels=("root//p:sim",)):
        facts = SimpleNamespace(directory=str(h.facts(self.tmp / "facts")))
        calls = []

        def fake_buck(tree, args):
            calls.append(args)
            return (0, "\n".join(labels) + "\n", "") if args[0] == "uquery" else (1, "", "")

        g = self.grading(self.POLICY if policy is None else policy)
        g.args.tier = tier
        with mock.patch.object(grade_sim.grade_build, "run_buck", side_effect=fake_buck), \
                mock.patch.object(grade_sim.grade_build, "action_counts", return_value=(0, 0)), \
                mock.patch.object(grade_sim.grade_build, "read_report", return_value={}), \
                mock.patch.object(grade_sim.grade_checks, "build_facts", return_value=facts):
            grade_sim.sim_gate_step(g)
        return [c for c in calls if c[0] == "build"]

    def test_the_nightly_tier_builds_the_soak_of_the_policy_target_in_san_with_the_days_as_config(self):
        san, release = self.run_step("nightly")
        self.assertIn("root//p:sim[soak]", san)
        self.assertNotIn("root//p:sim[soak]", release)
        for call in (san, release):
            self.assertEqual(call[call.index("-c") + 1], "rigor.sim_soak_days=7")

    def test_the_merge_tier_builds_no_soak_and_passes_no_days(self):
        for call in self.run_step("merge"):
            self.assertFalse([a for a in call if a.endswith("[soak]") or a.startswith("rigor.sim_soak")], call)
            self.assertNotIn("-c", call)

    def test_only_the_policy_target_has_a_soak(self):
        san, _ = self.run_step("nightly", labels=("root//p:other", "root//p:sim"))
        self.assertEqual([a for a in san if a.endswith("[soak]")], ["root//p:sim[soak]"])

    def test_a_policy_without_a_target_soaks_every_target(self):
        policy = test_grade_sim.Step.POLICY + "[sim]\n[sim.seeds]\nnightly = 1\n[sim.soak_days]\nnightly = 7\n"
        san, _ = self.run_step("nightly", policy=policy, labels=("root//p:other", "root//p:sim"))
        self.assertEqual([a for a in san if a.endswith("[soak]")], ["root//p:other[soak]", "root//p:sim[soak]"])

    def test_the_capacity_rule_can_demand_more_days_than_the_tier(self):
        policy = self.POLICY + '[soak.capacity.pool]\nevent = "upload"\nbound = 100\nrate_per_day = 10\n'
        san, _ = self.run_step("nightly", policy=policy)
        self.assertEqual(san[san.index("-c") + 1], "rigor.sim_soak_days=20")

    def collected(self, soak):
        tree = self.sub("tree")
        label = "root//p:sim"
        san = test_grade_sim.outputs_in(tree, "san", test_grade_sim.SAN + (("soak",) if soak else ()))
        release = test_grade_sim.outputs_in(tree, "release", ("hashes",))
        ok = {"success": "SUCCESS"}
        return str(tree), ({label: dict(ok, outputs=san)}, {label: dict(ok, outputs=release)})

    def test_a_soak_is_collected_when_it_was_asked_for(self):
        tree, built = self.collected(soak=True)
        directory = str(self.tmp / "sim")
        failed, index = grade_sim.collect(tree, ["root//p:sim"], built, directory, soak=("root//p:sim",))
        self.assertEqual((failed, index), ([], {"//p:sim": "t000"}))
        self.assertTrue((self.tmp / "sim" / "t000.soak.json").is_file())

    def test_a_soak_that_was_asked_for_and_is_missing_fails_the_target(self):
        tree, built = self.collected(soak=False)
        failed, index = grade_sim.collect(tree, ["root//p:sim"], built, str(self.tmp / "sim"), soak=("root//p:sim",))
        self.assertEqual((failed, index), (["root//p:sim"], {}))

    def test_a_soak_nobody_asked_for_is_not_collected(self):
        tree, built = self.collected(soak=True)
        directory = str(self.tmp / "sim")
        grade_sim.collect(tree, ["root//p:sim"], built, directory)
        self.assertFalse((self.tmp / "sim" / "t000.soak.json").exists())
