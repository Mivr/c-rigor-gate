"""`rigor ui-explore` end to end against the stub probe (gate/tests/data/ui_explore/stub_probe.py): determinism of the
output, every check of the explorer with its exact finding id, replay of a finding's paths, and argument checks."""

import json
import time
from pathlib import Path

from tests import test_ui_explore_helpers as h
from tests.helpers import TempDirTestCase, run_rigor

PRESS = "tap-press"


class ExploreCase(TempDirTestCase):
    def explore(self, mode, *args, catalogue=h.TOY, out="f.json", code=None):
        probe = h.stub(self.tmp, mode)
        argv = ["ui-explore", "--probe", probe, "--catalogue", catalogue, "--out", self.tmp / out] + list(args)
        outcome = run_rigor(argv)
        if code is not None:
            self.assertExit(outcome, code)
        return outcome, (h.findings(self.tmp / out) if (self.tmp / out).exists() else None)

    def bfs(self, mode, depth, *extra, **kw):
        return self.explore(mode, "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7", "--depth", str(depth),
                            "--max-states", "100", *extra, **kw)

    def replay(self, mode, paths, *extra, criteria=(), **kw):
        path = h.paths_file(self.tmp, paths, criteria, name="p%d.json" % time.monotonic_ns())
        return self.explore(mode, "--strategy", "replay", "--paths", path, *extra, **kw)


class DeterminismTest(ExploreCase):
    def test_the_same_inputs_twice_give_byte_identical_findings(self):
        for mode, code in (("good", 0), ("starve", 1)):
            self.bfs(mode, 3, out="a.json", code=code)
            self.bfs(mode, 3, out="b.json", code=code)
            self.assertEqual((self.tmp / "a.json").read_bytes(), (self.tmp / "b.json").read_bytes(), mode)

    def test_findings_are_sorted_by_id_and_one_per_line(self):
        _, found = self.bfs("starve", 1, code=1)
        ids = [item["id"] for item in found]
        self.assertEqual(ids, sorted(set(ids)))
        for item in found:
            self.assertEqual(sorted(item), ["blame", "check", "evidence", "explanation", "gate", "id", "layer", "observed",
                                            "path", "severity", "state"])
            self.assertIsNone(item["explanation"])
            self.assertEqual(item["gate"], "ui-explore")

    def test_a_nondeterministic_model_names_the_first_differing_step(self):
        _, found = self.bfs("nondet", 2, code=1)
        nondet = h.by_check(found, "model-nondeterministic")
        self.assertEqual([item["id"] for item in nondet],
                         [h.finding_id("model-nondeterministic", [h.STUB_OPEN_KEY, PRESS, "trace"])])
        self.assertEqual(nondet[0]["observed"], {"step": 1, "word": PRESS, "part": "trace", "item": 0})
        self.assertEqual(nondet[0]["path"], [h.OPEN, PRESS])
        self.assertEqual(nondet[0]["layer"], "L0")
        self.assertEqual(h.by_check(found, "run-twice-mismatch"), [])

    def test_a_reply_that_differs_outside_the_trace_is_run_twice_mismatch(self):
        _, found = self.replay("mismatch", [[h.OPEN, PRESS]], code=1)
        self.assertEqual([(item["id"], item["observed"]) for item in found],
                         [(h.finding_id("run-twice-mismatch", [h.STUB_OPEN_KEY, PRESS, "semantic"]),
                           {"step": 1, "word": PRESS, "part": "semantic", "item": 2})])

    def test_the_evidence_holds_both_runs_and_the_replay_paths(self):
        self.bfs("nondet", 1, "--evidence", str(self.tmp / "ev"), code=1)
        _, found = self.explore("nondet", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7", "--depth", "1",
                                "--max-states", "100", "--evidence", str(self.tmp / "ev2"), out="g.json", code=1)
        item = h.by_check(found, "model-nondeterministic")[0]
        name = item["id"].rsplit("/", 1)[1]
        self.assertEqual(item["evidence"], [name + "/paths.json", name + "/runs.json"])
        runs = json.loads((self.tmp / "ev2" / name / "runs.json").read_text())
        self.assertNotEqual(runs["first"], runs["second"])
        self.assertTrue(runs["first"][0].startswith("1\tpress-"))
        replay = json.loads((self.tmp / "ev2" / name / "paths.json").read_text())
        self.assertEqual(replay, {"schema": "ui-explore-paths/1", "criteria": ["C8"], "paths": [[h.OPEN, PRESS]]})


class TimeTest(ExploreCase):
    def test_a_deadline_that_never_moves_is_timer_starvation(self):
        _, found = self.replay("starve", [[h.OPEN, PRESS] + ["settle"] * 4], "--starvation-steps", "3", code=1)
        after_press = h.toy_key(["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
                                 "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
                                 "notice\tlabel\tPressed\t8\t90\t56\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"],
                                "within-frame", [])
        self.assertEqual([item["id"] for item in found], [h.finding_id("timer-starvation", [after_press])])
        self.assertEqual(found[0]["path"], [h.OPEN, PRESS, "settle", "settle", "settle"])
        self.assertEqual(found[0]["observed"], {"firings": 3, "frame_ms": 16,
                                                "now_and_next_due": [[1001, 1002], [1002, 1003], [1003, 1004]]})

    def test_a_timer_that_ends_is_not_starvation(self):
        _, found = self.replay("good", [[h.OPEN, PRESS] + ["settle"] * 4], "--starvation-steps", "2", code=0)
        self.assertEqual(found, [])

    def test_bfs_appends_settle_words_and_finds_starvation(self):
        _, found = self.bfs("starve", 1, code=1)
        starve = h.by_check(found, "timer-starvation")
        self.assertEqual(len(starve), 1)
        self.assertEqual(starve[0]["path"], [h.OPEN, PRESS] + ["settle"] * 32)


class ProbeFailureTest(ExploreCase):
    def check_failure(self, mode, check, observed):
        start = time.monotonic()
        _, found = self.replay(mode, [[h.OPEN, PRESS]], "--deadline-ms", "400", code=1)
        self.assertLess(time.monotonic() - start, 30)
        ident = h.finding_id(check, [observed["kind"], observed["command"], h.STUB_OPEN_KEY, PRESS])
        self.assertEqual([(item["id"], item["observed"], item["path"]) for item in found],
                         [(ident, observed, [h.OPEN, PRESS])])

    def test_a_probe_that_exits_mid_session(self):
        self.check_failure("exit", "probe-internal-error", {"kind": "crash", "command": "apply", "step": 1,
                                                            "detail": "the probe ended its output (exit status 3)"})

    def test_a_probe_that_hangs_is_a_timeout_within_the_deadline(self):
        self.check_failure("hang", "ui-explore-timeout", {"kind": "timeout", "command": "apply", "step": 1,
                                                          "detail": "no complete reply within 0.4 s"})

    def test_an_err_reply(self):
        self.check_failure("errreply", "probe-internal-error",
                           {"kind": "protocol", "command": "apply", "step": 1,
                            "detail": "the probe replied 'err apply bad-arguments'"})

    def test_a_malformed_record(self):
        _, found = self.replay("malformed", [[h.OPEN]], code=1)
        self.assertEqual([(item["id"], item["observed"], item["state"]) for item in found],
                         [(h.finding_id("probe-internal-error", ["protocol", "semantic", None, h.OPEN]),
                           {"kind": "protocol", "command": "semantic", "step": 0,
                            "detail": "a record with 2 fields, wanted 14"}, None)])


class CoverageTest(ExploreCase):
    def test_sweep_covers_c1(self):
        outcome, found = self.explore("good", "--strategy", "sweep", "--origin-ms", "1000", "--seed", "7", code=0)
        self.assertEqual(found, [])
        self.assertIn("domain_visited: 2", outcome.stdout)

    def test_a_replay_that_visits_one_entry_of_two_is_a_c1_gap(self):
        _, found = self.replay("good", [[h.OPEN, "domain-at 1"]], criteria=["C1"], code=1)
        self.assertEqual([(item["id"], item["observed"], item["path"]) for item in found],
                         [(h.finding_id("ui-coverage-gap", ["C1", 0]),
                           {"criterion": "C1", "domain_entry": 0, "domain_count": 2}, [h.OPEN])])

    def test_bfs_saturates_and_reports_states_per_depth(self):
        outcome, found = self.bfs("good", 6, code=0)
        self.assertEqual(found, [])
        self.assertIn("states_per_depth: [1,2,2,0]", outcome.stdout)

    def test_a_too_small_depth_bound_is_depth_unsaturated_with_c8_gaps(self):
        _, found = self.bfs("good", 1, code=1)
        depth = h.by_check(found, "depth-unsaturated")
        self.assertEqual([item["id"] for item in depth], [h.finding_id("depth-unsaturated", [1, 100])])
        self.assertEqual(depth[0]["observed"], {"depth_bound": 1, "max_states": 100, "states_per_depth": [1, 2],
                                                "dropped_states": 0, "reasons": ["last-depth-adds-states"]})
        self.assertEqual(depth[0]["path"], [h.OPEN, PRESS])
        gaps = h.by_check(found, "ui-coverage-gap")
        self.assertEqual(len(gaps), 2 * 9)   # the two unexpanded states x the nine catalogue events
        self.assertEqual({item["observed"]["criterion"] for item in gaps}, {"C8"})

    def test_the_state_bound_is_reported(self):
        _, found = self.explore("good", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7", "--depth", "6",
                                "--max-states", "2", code=1)
        depth = h.by_check(found, "depth-unsaturated")
        # S0 admitted; depth 1 finds pressed (admitted) and offline (dropped); depth 2 from pressed finds the
        # within-a-frame state (dropped) and S0 again; nothing is left to expand.
        self.assertEqual(depth[0]["observed"], {"depth_bound": 6, "max_states": 2, "states_per_depth": [1, 2, 1],
                                                "dropped_states": 2, "reasons": ["state-bound"]})

    def test_a_key_that_omits_the_label_is_too_coarse(self):
        _, found = self.bfs("good", 3, catalogue=h.TOY_COARSE, code=0)
        coarse = h.by_check(found, "key-too-coarse")
        self.assertEqual(len(coarse), 1)
        self.assertEqual(coarse[0]["severity"], "info")
        self.assertEqual(coarse[0]["path"], [h.OPEN, "env-offline"])
        self.assertEqual(coarse[0]["observed"]["witness_path"], [h.OPEN, PRESS])
        self.assertEqual(coarse[0]["observed"]["first_differing_node"], 2)
        self.assertEqual([coarse[0]["observed"]["witness_node"][2], coarse[0]["observed"]["node"][2]],
                         ["Pressed", "Offline"])

    def test_an_undeclared_env_input_is_a_c8_gap(self):
        text = h.TOY.read_text().replace('{ id = "env-offline", env = 1, arg = 0, hex = "" },', "")
        catalogue = self.tmp / "noenv.toml"
        catalogue.write_text(text)
        _, found = self.bfs("good", 4, catalogue=catalogue, code=1)
        gaps = [item for item in found if "undeclared_env_input" in item["observed"]]
        self.assertEqual([(item["id"], item["observed"]) for item in gaps],
                         [(h.finding_id("ui-coverage-gap", ["C8-env", h.STUB_OPEN_KEY, [1, 0, ""]]),
                           {"criterion": "C8", "undeclared_env_input": [1, 0, ""]})])


class ReplayTest(ExploreCase):
    def test_every_finding_replays_to_the_same_id(self):
        runs = [("nondet", ("--strategy", "bfs", "--depth", "1", "--max-states", "100"), h.TOY),
                ("starve", ("--strategy", "bfs", "--depth", "1", "--max-states", "100"), h.TOY),
                ("good", ("--strategy", "bfs", "--depth", "3", "--max-states", "100"), h.TOY_COARSE),
                ("good", ("--strategy", "walk", "--walk-seeds", "1,2", "--walk-length", "6", "--extra-origins", "1"),
                 h.TOY_COARSE)]
        for number, (mode, args, catalogue) in enumerate(runs):
            ev = self.tmp / ("ev%d" % number)
            _, found = self.explore(mode, "--origin-ms", "1000", "--seed", "7", "--evidence", str(ev), *args,
                                    catalogue=catalogue, out="f%d.json" % number)
            for item in found:
                if item["check"] == "depth-unsaturated":
                    continue      # a property of the bounded search, not of a path (docs/ui-explore.md)
                name = item["id"].rsplit("/", 1)[1]
                outcome = run_rigor(["ui-explore", "--probe", h.stub(self.tmp, mode), "--catalogue", catalogue,
                                     "--strategy", "replay", "--paths", ev / name / "paths.json",
                                     "--out", self.tmp / "r.json"])
                self.assertIn(outcome.code, (0, 1), outcome.stderr)
                self.assertIn(item["id"], [r["id"] for r in h.findings(self.tmp / "r.json")], (mode, item))

    def test_walks_are_deterministic_and_use_extra_origins(self):
        args = ("--strategy", "walk", "--origin-ms", "1000", "--seed", "7", "--walk-seeds", "3,1", "--walk-length",
                "5", "--extra-origins", "2", "--summary")
        self.explore("good", *(args + (str(self.tmp / "s1.json"),)), out="a.json", code=0)
        self.explore("good", *(args + (str(self.tmp / "s2.json"),)), out="b.json", code=0)
        self.assertEqual((self.tmp / "s1.json").read_bytes(), (self.tmp / "s2.json").read_bytes())
        summary = json.loads((self.tmp / "s1.json").read_text())
        self.assertEqual((summary["runs"], summary["detail"]), (6, {"walks": 6}))


class ArgumentTest(ExploreCase):
    def test_strategy_arguments_are_required_and_refused_exactly(self):
        cases = [("bfs", ["--origin-ms", "1", "--seed", "1", "--depth", "2"]),
                 ("sweep", ["--origin-ms", "1", "--seed", "1", "--depth", "2"]),
                 ("replay", ["--paths", "x", "--seed", "1"]),
                 ("walk", ["--origin-ms", "1", "--seed", "1", "--walk-seeds", "1,1", "--walk-length", "2",
                           "--extra-origins", "0"]),
                 ("bfs", ["--origin-ms", "1", "--seed", "1", "--depth", "0", "--max-states", "1"]),
                 ("bfs", ["--origin-ms", "01", "--seed", "1", "--depth", "1", "--max-states", "1"])]
        for strategy, args in cases:
            outcome, found = self.explore("good", "--strategy", strategy, *args, code=2)
            self.assertIsNone(found, (strategy, args))

    def test_a_bad_paths_file_is_exit_2(self):
        bad = [{"schema": "ui-explore-paths/1", "criteria": [], "paths": []},
               {"schema": "ui-explore-paths/1", "criteria": ["C9"], "paths": [[h.OPEN]]},
               {"schema": "ui-explore-paths/1", "criteria": ["C1", "C1"], "paths": [[h.OPEN]]},
               {"schema": "ui-explore-paths/2", "criteria": [], "paths": [[h.OPEN]]},
               {"schema": "ui-explore-paths/1", "criteria": [], "paths": [[h.OPEN]], "extra": 1},
               {"schema": "ui-explore-paths/1", "criteria": [], "paths": [["tap-press"]]},
               {"schema": "ui-explore-paths/1", "criteria": [], "paths": [[h.OPEN, "no-such-event"]]},
               {"schema": "ui-explore-paths/1", "criteria": [], "paths": [[h.OPEN, h.OPEN]]},
               {"schema": "ui-explore-paths/1", "criteria": [], "paths": [["open 01 7"]]}]
        for number, document in enumerate(bad):
            path = self.tmp / ("bad%d.json" % number)
            path.write_text(json.dumps(document))
            outcome, found = self.explore("good", "--strategy", "replay", "--paths", path, code=2)
            self.assertIn("internal error", outcome.stderr, document)
        (self.tmp / "dup.json").write_text('{"schema":"ui-explore-paths/1","criteria":[],"criteria":[],"paths":[["%s"]]}'
                                           % h.OPEN)
        self.explore("good", "--strategy", "replay", "--paths", self.tmp / "dup.json", code=2)

    def test_a_catalogue_with_taps_is_refused(self):
        text = h.TOY.read_text().replace("[u2]\nevents = []", '[u2]\nevents = [ { id = "probe-1", x = 1, y = 2 } ]')
        catalogue = self.tmp / "taps.toml"
        catalogue.write_text(text)
        outcome, _ = self.bfs("good", 1, catalogue=catalogue, code=2)
        self.assertIn("ui-probe/1 does not have", outcome.stderr)

    def test_a_probe_that_is_not_executable_is_exit_2(self):
        Path(self.tmp / "plain").write_text("")
        outcome = run_rigor(["ui-explore", "--probe", self.tmp / "plain", "--catalogue", h.TOY, "--strategy", "sweep",
                             "--origin-ms", "1", "--seed", "1", "--out", self.tmp / "f.json"])
        self.assertExit(outcome, 2)

    def test_evidence_into_a_non_empty_directory_is_refused(self):
        (self.tmp / "ev").mkdir()
        (self.tmp / "ev" / "old").write_text("x")
        self.bfs("good", 1, "--evidence", str(self.tmp / "ev"), code=2)
