"""`rigor sim`: every malformed input is exit 2 and never a PASS."""

import json

from tests import test_sim_judge_helpers as h
from tests.test_sim_judge import SimJudgeCase


class MalformedTests(SimJudgeCase):
    def run_file(self, name):
        return self.results / name

    def test_a_missing_results_directory_or_index(self):
        self.judge(2, results=self.tmp / "nowhere")
        self.results.mkdir()
        self.judge(2)

    def test_a_bad_index(self):
        h.write_run(self.results)
        for text in ("[]", '{"//p:sim": 3}', '{"bad": "t000"}', '{"//p:sim": "../x"}', '{"//p:sim": "t000", "//p:b": "t000"}'):
            with self.subTest(text=text):
                self.run_file("index.json").write_text(text)
                self.judge(2)

    def test_a_stray_file_or_a_link(self):
        h.write_run(self.results)
        self.run_file("note.txt").write_text("x")
        self.judge(2)
        self.run_file("note.txt").unlink()
        self.run_file("t000.report").unlink()
        self.run_file("t000.report").symlink_to(self.run_file("t000.verdict"))
        self.judge(2)

    def test_a_missing_file_of_a_target(self):
        for suffix in (".stats.json", ".verdict", ".report", ".hashes", ".release.hashes"):
            with self.subTest(suffix=suffix):
                h.write_run(self.results)
                self.run_file("t000" + suffix).unlink()
                self.judge(2)

    def test_a_failure_trace_is_optional_and_capped(self):
        h.write_run(self.results)
        self.run_file("t000.failure.trace").write_text("x" * 100)
        self.judge(0)
        self.run_file("t000.failure.trace").write_text("x" * 70000)
        self.judge(2)

    def test_a_result_for_something_that_is_not_a_c_sim_target(self):
        h.write_run(self.results, label="//p:wire")
        self.judge(2)

    def test_bad_stats(self):
        base = h.stats_doc(12)
        cases = {"unknown key": dict(base, bogus=1), "wrong schema": dict(base, schema="sim-stats/2"),
                 "negative count": dict(base, count=-1), "string count": dict(base, count="12"),
                 "bool count": dict(base, count=True), "partial world keys": {k: v for k, v in base.items() if k != "run_ms"},
                 "uppercase sha": dict(base, world_sha256="AB" * 32), "missing key": {k: v for k, v in base.items() if k != "shards"},
                 "failures not a list": dict(base, failures={}),
                 "failure without seed": dict(base, failures=[{"index": 1, "rule": "sim-crash"}]),
                 "unknown failure rule": dict(base, failures=[h.failure(1, "sim-bogus")]),
                 "failure with a stray key": dict(base, failures=[h.failure(1, extra=1)]),
                 "a list": [], "not json": "{"}
        for name, doc in cases.items():
            with self.subTest(name=name):
                h.write_run(self.results, stats=doc)
                if name == "not json":
                    self.run_file("t000.stats.json").write_text(doc)
                self.judge(2)

    def test_a_bad_verdict(self):
        for text in ("", "ok", "fail", "pass extra", "FAIL sim-crash", "fail rc=1"):
            with self.subTest(text=text):
                h.write_run(self.results, verdict=text)
                self.judge(2)

    def test_a_verdict_that_contradicts_the_stats(self):
        h.write_run(self.results, failures=[h.failure(1)], verdict="pass")
        self.judge(2)
        h.write_run(self.results, failures=[h.failure(1)], verdict="fail sim-timeout")
        self.judge(2)

    def test_bad_hashes(self):
        for text in ("x\n", "0 a b\n", "0 %s %s %s" % (("0" * 16,) * 3), "0 %s %s %s\n0 %s %s %s\n" % (("0" * 16,) * 6),
                     "0 ZZ%s %s %s\n" % (("0" * 14), "0" * 16, "0" * 16)):
            with self.subTest(text=text):
                h.write_run(self.results)
                self.run_file("t000.hashes").write_text(text)
                self.judge(2)

    def test_hashes_that_do_not_name_the_derived_seeds(self):
        san = {i: h.row(i) for i in range(12)}
        san[5] = ("0" * 16,) + san[5][1:]
        h.write_run(self.results, san=san)
        self.judge(2)

    def test_hashes_for_another_salt(self):
        h.write_run(self.results, salt=b"\x07")
        self.run_file("t000.stats.json").write_text(json.dumps(h.stats_doc(12)))   # claims the grader's salt
        self.judge(2)

    def test_a_run_made_with_another_salt_than_the_graders(self):
        h.write_run(self.results, salt=b"\x07")
        self.judge(2)

    def test_hashes_with_a_gap_a_repeat_or_an_overlap_with_a_failure(self):
        h.write_run(self.results, san={i: h.row(i) for i in range(12) if i != 6})
        self.judge(2)
        h.write_run(self.results, failures=[h.failure(6)], san={i: h.row(i) for i in range(12)})
        self.judge(2)
        h.write_run(self.results, failures=[h.failure(6), h.failure(6)])
        self.judge(2)

    def test_a_distinct_count_that_is_not_the_files(self):
        h.write_run(self.results, distinct=3)
        self.judge(2)

    def test_a_policy_defect(self):
        h.write_run(self.results)
        for text in ("[sim]\nbogus = 1\n", "[sim]\nrequired = 1\n", '[sim]\ntarget = "x"\n', "[sim]\nprofiles = [1]\n",
                     '[sim]\nprofiles = ["a", "a"]\n', "[sim.seeds]\nmerge = 0\n", "[sim.seeds]\nweekly = 5\n",
                     "[sim.soak_days]\nnightly = -1\n", "[sim.seeds]\nmerge = true\n",
                     '[soak.capacity.x]\nevent = "e"\nbound = 5\nrate_per_day = 1\n',
                     '[sim]\n[soak.capacity.x]\nevent = "e"\nbound = 0\nrate_per_day = 1\n',
                     '[sim]\n[soak.capacity.x]\nbound = 5\nrate_per_day = 1\n',
                     '[sim]\n[soak.capacity.x]\nevent = "e"\nbound = 5\nrate_per_day = 1\nextra = 1\n', "[sim\n",
                     '[sim]\nprofiles = ["x"]\n[module."//p:nope"]\nprofile = ["x"]\n'):
            with self.subTest(text=text):
                self.judge(2, policy=text)

    def test_a_spec_defect(self):
        h.write_run(self.results)
        for text in ("bogus = 1\n", 'invariants = "I1"\n', 'invariants = ["I1", "I1"]\n', "invariants = [1]\n",
                     "[coverage]\nmin_checked = 0\n", "[coverage]\nbogus = 1\n", 'coverage = "x"\n', "invariants = [\n"):
            with self.subTest(text=text):
                self.judge(2, spec=text)

    def test_a_salt_defect(self):
        h.write_run(self.results)
        for text in ("ABCD", "abc", "zz", "ab" * 65, "ab\ncd"):
            with self.subTest(text=text):
                self.salt.write_text(text)
                self.judge(2)
        self.salt.write_bytes(b"\xff")
        self.judge(2)

    def test_a_salt_id_that_is_not_the_files(self):
        h.write_run(self.results)
        self.judge(2, salt_id="0" * 64)
        self.judge(0, salt_id=h.sim_policy.jsonio.sha256_hex(h.SALT))

    def test_a_regressions_defect(self):
        h.write_run(self.results)
        for value in ([], {"//p:sim": "abc"}, {"//p:sim": ["xyz"]}, {"//p:sim": ["0" * 16, "0" * 16]}, {"bad": []},
                      {"//p:other": []}):
            with self.subTest(value=value):
                self.judge(2, regressions=value)

    def test_bad_stats_extras(self):
        base = {"invariants": {"I1": {"checked": 1}}}
        cases = [base, {"invariants": {"I1": {"checked": -1, "violated": 0}}}, {"screens": "welcome"}, {"counters": {"a": -1}},
                 {"soak": {"days": 1}}, {"soak": {"days": 1, "failures": [{"assertion": "a"}]}}, {"unexercised": ["x"]},
                 {"faults": {"f": {"fired": 1}}}]
        for extra in cases:
            with self.subTest(extra=extra):
                h.write_run(self.results, **extra)
                self.judge(2, spec='invariants = ["I1"]\nfaults = ["f"]\n', policy="[sim]\n[sim.soak_days]\nnightly = 1\n")

    def test_a_module_without_facts(self):
        h.write_run(self.results)
        self.judge(2, policy='[sim]\nprofiles = ["x"]\n[module."//p:ghost"]\nprofile = ["x"]\n')

    def test_arguments(self):
        from tests.helpers import run_rigor
        self.assertExit(run_rigor(["sim", "--bogus"]), 2)
        self.assertExit(run_rigor(["sim"]), 2)
        self.assertExit(run_rigor(["sim", "--results", "x", "--policy", "y", "--facts", "z", "--tier", "weekly"]), 2)
