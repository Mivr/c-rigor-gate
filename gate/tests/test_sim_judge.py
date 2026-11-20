"""`rigor sim`: every finding of P330 §1.8, on hand-made facts and synthetic result directories."""

import json

from tests import test_sim_judge_helpers as h
from tests.helpers import TempDirTestCase, run_rigor

SPEC = """invariants = ["I1", "I3"]
faults = ["disk_full"]
screens = ["welcome", "opened"]
zero_counters = ["rx_push_lost"]
"""
LIGHT = "[sim.seeds]\nmerge = 1\nnightly = 1\n[sim.soak_days]\nmerge = 0\nnightly = 0\n"
GOOD_STATS = {"invariants": {"I1": {"checked": 5, "violated": 0}, "I3": {"checked": 9, "violated": 0}},
              "faults": {"disk_full": {"fired": 2, "observed": 2}}, "screens": ["welcome", "opened", "choose"],
              "counters": {"rx_push_lost": 0}}


class SimJudgeCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.facts = h.facts(self.tmp / "facts")
        self.results = self.tmp / "results"
        self.out = self.tmp / "out.json"
        self.salt = self.tmp / "salt"
        self.salt.write_text(h.SALT.hex() + "\n")

    def judge(self, code, policy="", spec=None, tier=None, regressions=None, salt="default", salt_id=None, results=None):
        policy_path = h.policy_file(self.tmp / "policy.toml", policy)
        args = ["sim", "--results", results or self.results, "--policy", policy_path, "--facts", self.facts,
                "--out", self.out]
        if salt == "default":
            salt = self.salt
        if salt is not None:
            args += ["--salt", salt]
        if spec is not None:
            args += ["--spec", h.policy_file(self.tmp / "sim.toml", spec)]
        if tier is not None:
            args += ["--tier", tier]
        if regressions is not None:
            args += ["--regressions", h.policy_file(self.tmp / "reg.json", json.dumps(regressions))]
        if salt_id is not None:
            args += ["--salt-id", salt_id]
        outcome = run_rigor(args)
        self.assertExit(outcome, code)
        return outcome

    def doc(self):
        return json.loads(self.out.read_text())

    def rules(self):
        return h.rules(self.out)


class FindingTests(SimJudgeCase):
    def test_a_clean_run_passes_and_reports_what_it_bound(self):
        h.write_run(self.results)
        self.judge(0)
        self.assertEqual(self.rules(), [])
        meta = self.doc()["metadata"]
        self.assertEqual((meta["tier"], meta["required_seeds"], meta["targets"][h.SIM]["seeds_run"]), ("nightly", 1, 12))
        self.assertEqual(meta["salt_id"], h.sim_policy.jsonio.sha256_hex(h.SALT))
        self.assertIsNone(meta["spec_sha256"])
        self.assertRegex(meta["seed_digest"], "^[0-9a-f]{64}$")

    def test_a_clean_run_against_a_full_spec(self):
        h.write_run(self.results, **GOOD_STATS)
        self.judge(0, spec=SPEC)
        self.assertEqual(self.rules(), [])
        self.assertRegex(self.doc()["metadata"]["spec_sha256"], "^[0-9a-f]{64}$")

    def test_every_rule_a_runner_failure_can_carry_is_a_finding(self):
        for rule in ("sim-crash", "sim-timeout", "sim-nondeterministic", "sim-deadlock", "sim-init-failed",
                     "sim-world-error", "sim-model-divergence"):
            with self.subTest(rule=rule):
                h.write_run(self.tmp / rule, failures=[h.failure(3, rule)])
                self.judge(1, results=self.tmp / rule)
                (item,) = h.findings(self.out, rule)
                self.assertEqual((item["target"], item["index"], item["detail"]), (h.SIM, 3, 11))
                self.assertEqual(item["seed"], h.row(3)[0])

    def test_an_invariant_violation_carries_its_place(self):
        failing = h.failure(2, "sim-invariant-violated", invariant="I3", step=40, at_ms=1250, detail="two coils on")
        stats = dict(GOOD_STATS, invariants={"I1": {"checked": 5, "violated": 0}, "I3": {"checked": 9, "violated": 1}})
        h.write_run(self.results, failures=[failing], **stats)
        self.judge(1, spec=SPEC)
        (item,) = h.findings(self.out, "sim-invariant-violated")
        self.assertEqual((item["invariant"], item["step"], item["at_ms"]), ("I3", 40, 1250))

    def test_a_violation_count_without_a_failure_row_is_still_a_finding(self):
        h.write_run(self.results, invariants={"I1": {"checked": 5, "violated": 2}})
        self.judge(1)
        (item,) = h.findings(self.out, "sim-invariant-violated")
        self.assertEqual((item["invariant"], item["count"]), ("I1", 2))

    def test_a_workload_that_reaches_nothing_is_vacuous(self):
        h.write_run(self.results, trace="%016x" % 7, distinct=1)
        self.judge(1)
        (item,) = h.findings(self.out, "sim-vacuous")
        self.assertEqual((item["what"], item["seeds"], item["distinct"]), ("seeds", 12, 1))

    def test_an_invariant_that_never_checked_anything_is_vacuous(self):
        stats = dict(GOOD_STATS, invariants={"I1": {"checked": 0, "violated": 0}})
        h.write_run(self.results, **stats)
        self.judge(1, spec=SPEC)
        self.assertEqual(sorted((f["invariant"], f["count"]) for f in h.findings(self.out, "sim-vacuous")), [("I1", 0), ("I3", 0)])

    def test_the_coverage_floor_of_the_spec_applies(self):
        h.write_run(self.results, **GOOD_STATS)
        self.judge(1, spec=SPEC + "[coverage]\nmin_checked = 6\n")
        self.assertEqual([f["invariant"] for f in h.findings(self.out, "sim-vacuous")], ["I1"])

    def test_a_screen_never_reached_is_vacuous(self):
        h.write_run(self.results, **dict(GOOD_STATS, screens=["welcome"]))
        self.judge(1, spec=SPEC)
        (item,) = h.findings(self.out, "sim-vacuous")
        self.assertEqual(item["screen"], "opened")

    def test_a_fault_that_fired_and_was_not_seen_is_not_observed(self):
        h.write_run(self.results, **dict(GOOD_STATS, faults={"disk_full": {"fired": 3, "observed": 0}}))
        self.judge(1, spec=SPEC)
        (item,) = h.findings(self.out, "fault-not-observed")
        self.assertEqual((item["fault"], item["fired"], item["observed"]), ("disk_full", 3, 0))

    def test_a_fault_that_never_fired_is_not_observed(self):
        h.write_run(self.results, **{k: v for k, v in GOOD_STATS.items() if k != "faults"})
        self.judge(1, spec=SPEC)
        self.assertEqual(self.rules(), ["fault-not-observed"])

    def test_a_runtime_counter_that_must_stay_zero(self):
        h.write_run(self.results, **dict(GOOD_STATS, counters={"rx_push_lost": 4}))
        self.judge(1, spec=SPEC)
        (item,) = h.findings(self.out, "sim-stats-counter")
        self.assertEqual((item["counter"], item["value"]), ("rx_push_lost", 4))

    def test_a_counter_the_stats_do_not_name_is_a_finding(self):
        h.write_run(self.results, **dict(GOOD_STATS, counters={}))
        self.judge(1, spec=SPEC)
        self.assertEqual(h.findings(self.out, "sim-stats-counter")[0]["value"], -1)

    def test_too_few_seeds_for_the_tier(self):
        h.write_run(self.results)
        policy = "[sim]\n[sim.seeds]\nmerge = 12\nnightly = 2000\n"
        self.judge(0, policy=policy, tier="merge")
        self.judge(1, policy=policy)
        (item,) = h.findings(self.out, "sim-seeds-short")
        self.assertEqual((item["required"], item["count"]), (2000, 12))

    def test_seeds_that_did_not_all_run(self):
        h.write_run(self.results, count=12, stats=h.stats_doc(12, seeds_run=10), san={i: h.row(i) for i in range(10)})
        self.judge(1)
        self.assertEqual(self.rules(), ["sim-seeds-short"])

    def test_the_default_budget_of_a_policy_is_the_spec_table(self):
        h.write_run(self.results)
        self.judge(1, policy="[sim]\n", tier="merge")
        self.assertEqual(h.findings(self.out, "sim-seeds-short")[0]["required"], 200)

    def test_a_required_sim_without_a_target(self):
        self.facts = h.facts(self.tmp / "nofacts", sims=())
        self.results.mkdir()
        (self.results / "index.json").write_text("{}")
        self.judge(1, policy="[sim]\nrequired = true\n")
        self.assertEqual(self.rules(), ["sim-missing-target"])

    def test_a_required_sim_whose_named_target_is_missing(self):
        h.write_run(self.results)
        self.judge(1, policy='[sim]\nrequired = true\ntarget = "//p:other"\n')
        self.assertEqual(h.findings(self.out, "sim-missing-target")[0]["target"], "//p:other")

    def test_a_target_without_results_was_not_run(self):
        self.results.mkdir()
        (self.results / "index.json").write_text("{}")
        self.judge(1)
        self.assertEqual(self.rules(), ["sim-not-run"])

    def test_a_module_with_a_profile_that_no_sim_reaches(self):
        self.facts = h.facts(self.tmp / "f2", extra=[("//p:ui", "c_library")])
        h.write_run(self.results)
        policy = '[sim]\nprofiles = ["ui"]\n' + LIGHT + '[module."//p:ui"]\nprofile = ["ui"]\n[module."//p:wire"]\nprofile = ["wiring"]\n'
        self.judge(1, policy=policy)
        (item,) = h.findings(self.out, "sim-module-unreached")
        self.assertEqual(item["module"], "//p:ui")

    def test_a_module_in_the_closure_is_reached_and_one_that_never_ran_is_unexercised(self):
        h.write_run(self.results, unexercised=["//p:wire"])
        policy = '[sim]\nprofiles = ["wiring"]\n' + LIGHT + '[module."//p:wire"]\nprofile = ["wiring"]\n'
        self.judge(1, policy=policy)
        self.assertEqual(self.rules(), ["sim-module-unexercised"])

    def test_the_release_run_must_equal_the_san_run_on_seeds_0_to_9(self):
        release = {i: h.row(i) for i in range(12)}
        release[4] = (release[4][0], "%016x" % 0xbad, release[4][2])
        h.write_run(self.results, release=release)
        self.judge(1)
        (item,) = h.findings(self.out, "sim-nondeterministic")
        self.assertEqual(item["index"], 4)

    def test_a_seed_beyond_the_tenth_may_differ(self):
        release = {i: h.row(i) for i in range(12)}
        release[11] = (release[11][0], "%016x" % 0xbad, release[11][2])
        h.write_run(self.results, release=release)
        self.judge(0)

    def test_a_seed_the_release_run_lacks(self):
        h.write_run(self.results, release={i: h.row(i) for i in range(12) if i != 2})
        self.judge(1)
        self.assertEqual(h.findings(self.out, "sim-nondeterministic")[0]["why"], "missing in the release run")

    def test_a_listed_regression_seed_must_have_run(self):
        h.write_run(self.results)
        self.judge(0, regressions={h.SIM: [h.row(5)[0]]})
        self.judge(1, regressions={h.SIM: ["0123456789abcdef"]})
        self.assertEqual(h.findings(self.out, "sim-regression-missing")[0]["seed"], "0123456789abcdef")

    def test_the_soak_the_tier_demands(self):
        h.write_run(self.results)
        policy = "[sim]\n[sim.seeds]\nmerge = 1\nnightly = 1\n[sim.soak_days]\nnightly = 400\n"
        self.judge(0, policy=policy, tier="merge")
        self.judge(1, policy=policy)
        self.assertEqual(h.findings(self.out, "soak-too-short")[0]["required_days"], 400)

    def test_a_soak_shorter_than_the_capacity_rule(self):
        capacity = '[soak.capacity.pool]\nevent = "snapshot upload"\nbound = 131070\nrate_per_day = 1440\n'
        policy = "[sim]\n[sim.seeds]\nnightly = 1\n[sim.soak_days]\nnightly = 100\n" + capacity
        h.write_run(self.results, soak={"days": 100, "failures": []})
        self.judge(1, policy=policy)
        self.assertEqual(h.findings(self.out, "soak-too-short")[0]["required_days"], 183)   # ceil(2 * 131070 / 1440)
        h.write_run(self.results, soak={"days": 400, "failures": []})
        self.judge(0, policy=policy)

    def test_a_soak_assertion_that_failed(self):
        h.write_run(self.results, soak={"days": 400, "failures": [{"assertion": "pool_slots_free", "day": 91}]})
        self.judge(1, policy="[sim]\n[sim.seeds]\nnightly = 1\n[sim.soak_days]\nnightly = 0\n")
        (item,) = h.findings(self.out, "soak-assertion")
        self.assertEqual((item["assertion"], item["day"]), ("pool_slots_free", 91))

    def test_a_salt_swap_changes_the_digest_and_the_salt_id(self):
        other = b"\x09" * 4
        h.write_run(self.results)
        self.judge(0)
        first = self.doc()["metadata"]
        h.write_run(self.tmp / "other", salt=other)
        self.salt.write_text(other.hex())
        self.judge(0, results=self.tmp / "other")
        second = self.doc()["metadata"]
        self.assertNotEqual(first["seed_digest"], second["seed_digest"])
        self.assertNotEqual(first["salt_id"], second["salt_id"])

    def test_the_digest_is_stable_for_the_same_results(self):
        h.write_run(self.results)
        self.judge(0)
        first = self.doc()["metadata"]["seed_digest"]
        self.judge(0)
        self.assertEqual(first, self.doc()["metadata"]["seed_digest"])

    def test_a_run_made_with_no_salt_is_judged_without_one(self):
        h.write_run(self.results, salt=b"")
        self.judge(0, salt=None)

    def test_shards_that_disagree_about_the_world_leave_the_runners_own_rule(self):
        stats = {k: v for k, v in h.stats_doc(12).items() if k not in ("run_ms", "salt_sha256", "world_sha256")}
        h.write_run(self.results, stats=stats, verdict="fail sim-world-error", san={})
        self.judge(1)
        self.assertEqual(self.rules(), ["sim-world-error"])
