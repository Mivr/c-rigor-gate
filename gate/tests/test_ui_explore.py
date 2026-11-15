"""`rigor ui-explore` end to end against the stub probe (gate/tests/data/ui_explore/stub_probe.py): determinism of the
output, run-twice, coverage, depth, key-too-coarse, event acceptance, replay of every finding, arguments."""

import json

from tests import test_ui_explore_helpers as h
from tests.helpers import run_rigor

PRESS = "tap-press"
AFTER_PRESS = ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
               "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
               "notice\tlabel\tPressed\t8\t90\t56\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"]
SHA = h.sha256_file(h.TOY)


class DeterminismTest(h.ExploreCase):
    def test_the_same_inputs_twice_give_byte_identical_findings(self):
        for mode, code in (("good", 0), ("starve", 1), ("nondet", 1)):
            self.bfs(mode, 3, out="a.json", code=code)
            self.bfs(mode, 3, out="b.json", code=code)
            data = (self.tmp / "a.json").read_bytes()
            self.assertEqual(data, (self.tmp / "b.json").read_bytes(), mode)
            self.assertEqual(bool(data), mode != "good")

    def test_findings_are_sorted_and_carry_a_readable_state(self):
        _, found = self.bfs("starve", 1, code=1)
        ids = [item["id"] for item in found]
        self.assertEqual(ids, sorted(set(ids)))
        for item in found:
            self.assertEqual(sorted(item), ["blame", "check", "evidence", "explanation", "gate", "id", "layer", "observed",
                                            "path", "severity", "state"])
        state = h.by_check(found, "depth-unsaturated")[0]["state"]
        self.assertEqual(state["origin_ms"], 1000)
        self.assertEqual(state["projection"]["nodes"][2]["label"], "Pressed")
        self.assertEqual(state["projection"]["facts"], {"deadline": "within-frame", "env-inputs": []})

    def test_a_nondeterministic_model_names_the_first_differing_step(self):
        _, found = self.bfs("nondet", 2, code=1)
        nondet = h.by_check(found, "model-nondeterministic")
        self.assertEqual([item["id"] for item in nondet],
                         [h.finding_id("model-nondeterministic", [h.STUB_OPEN_KEY, PRESS, "trace"])])
        self.assertEqual(nondet[0]["observed"], {"step": 1, "word": PRESS, "part": "trace", "item": 0})
        self.assertEqual(nondet[0]["path"], [h.OPEN, PRESS])
        self.assertEqual(h.by_check(found, "run-twice-mismatch"), [])

    def test_a_reply_that_differs_outside_the_trace_is_run_twice_mismatch_in_read_order(self):
        _, found = self.replay("mismatch", [[h.OPEN, PRESS]], code=1)
        self.assertEqual([(item["id"], item["observed"]) for item in found],
                         [(h.finding_id("run-twice-mismatch", [h.STUB_OPEN_KEY, PRESS, "semantic"]),
                           {"step": 1, "word": PRESS, "part": "semantic", "item": 2})])

    def test_the_evidence_holds_both_runs_and_the_replay_paths(self):
        _, found = self.bfs("nondet", 1, "--evidence", str(self.tmp / "ev"), code=1)
        item = h.by_check(found, "model-nondeterministic")[0]
        name = item["id"].rsplit("/", 1)[1]
        self.assertEqual(item["evidence"], [name + "/paths.json", name + "/runs.json"])
        runs = json.loads((self.tmp / "ev" / name / "runs.json").read_text())
        self.assertNotEqual(runs["first"], runs["second"])
        self.assertEqual(json.loads((self.tmp / "ev" / name / "paths.json").read_text()),
                         {"schema": "ui-explore-paths/1", "criteria": ["C8"], "paths": [[h.OPEN, PRESS]]})


class CoverageTest(h.ExploreCase):
    def test_sweep_covers_c1(self):
        outcome, found = self.explore("good", "--strategy", "sweep", "--origin-ms", "1000", "--seed", "7", code=0)
        self.assertEqual(found, [])
        self.assertIn("domain_visited: 2", outcome.stdout)
        self.assertIn("evaluated: C1", outcome.stdout)

    def test_a_replay_that_visits_one_entry_of_two_is_a_c1_gap(self):
        _, found = self.replay("good", [[h.OPEN, "domain-at 1"]], criteria=["C1"], code=1)
        self.assertEqual([(item["id"], item["observed"], item["path"]) for item in found],
                         [(h.finding_id("ui-coverage-gap", ["C1", SHA, 0]),
                           {"criterion": "C1", "domain_entry": 0, "domain_count": 2}, [h.OPEN])])

    def test_bfs_saturates_and_reports_states_per_depth(self):
        outcome, found = self.bfs("good", 6, "--summary", str(self.tmp / "s.json"), code=0)
        self.assertEqual(found, [])
        self.assertIn("states_per_depth: [1,2,2,0]", outcome.stdout)
        summary = json.loads((self.tmp / "s.json").read_text())
        self.assertEqual(summary["evaluated"], ["C8"])
        self.assertEqual(summary["events"]["code-empty"], {"accepted_states": 0, "refused_states": 5})
        # the press is accepted only where the notice is hidden: the open state (the stub clears the notice text)
        self.assertEqual(summary["events"][PRESS], {"accepted_states": 1, "refused_states": 4})

    def test_a_too_small_depth_bound_is_depth_unsaturated_with_c8_gaps(self):
        _, found = self.bfs("good", 1, code=1)
        depth = h.by_check(found, "depth-unsaturated")
        self.assertEqual([item["id"] for item in depth], [h.finding_id("depth-unsaturated", ["depth", SHA, 1, 100])])
        self.assertEqual(depth[0]["observed"], {"depth_bound": 1, "max_states": 100, "states_per_depth": [1, 2],
                                                "dropped_states": 0, "reasons": ["last-depth-adds-states"]})
        self.assertEqual(depth[0]["path"], [h.OPEN, PRESS])
        gaps = h.by_check(found, "ui-coverage-gap")
        self.assertEqual(len(gaps), 2 * 11)   # the two unexpanded states x the eleven catalogue events

    def test_the_state_bound_is_reported(self):
        _, found = self.explore("good", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7", "--depth", "6",
                                "--max-states", "2", code=1)
        self.assertEqual(h.by_check(found, "depth-unsaturated")[0]["observed"]["reasons"], ["state-bound"])

    def test_a_key_that_omits_the_label_is_too_coarse(self):
        _, found = self.bfs("good", 3, catalogue=h.TOY_COARSE, code=0)
        coarse = [item for item in h.by_check(found, "key-too-coarse") if item["path"] == [h.OPEN, "env-offline"]]
        self.assertEqual(len(coarse), 1)
        self.assertEqual(coarse[0]["severity"], "info")
        self.assertEqual(coarse[0]["observed"], {"witness_path": [h.OPEN, PRESS], "differs_in": ["nodes"]})

    def test_a_derived_fact_keeps_the_coarse_key_exact(self):
        catalogue = self.catalogue("derived = []", 'derived = [ { name = "notice-text", op = "select", node = "notice", '
                                   'field = "label" } ]', base=h.TOY_COARSE)
        _, found = self.bfs("good", 4, catalogue=catalogue, code=0)
        self.assertEqual(found, [])

    def test_an_undeclared_env_input_is_a_c8_gap(self):
        catalogue = self.catalogue('  { id = "env-offline", env = 1, arg = 0, hex = "", expect = "accept" },\n', "")
        _, found = self.bfs("good", 4, catalogue=catalogue, code=1)
        gaps = [item for item in found if "undeclared_env_input" in item["observed"]]
        self.assertEqual([(item["id"], item["observed"]) for item in gaps],
                         [(h.finding_id("ui-coverage-gap", ["C8-env", h.STUB_OPEN_KEY, [1, 0, ""]]),
                           {"criterion": "C8", "undeclared_env_input": [1, 0]})])

    def test_a_product_that_refuses_everything_is_event_never_accepted(self):
        _, found = self.bfs("refuseall", 3, code=1)
        never = h.by_check(found, "event-never-accepted")
        self.assertEqual(sorted(item["observed"]["event"] for item in never),
                         ["code-non-digit", "code-one-digit", "env-offline", PRESS])
        press = [item for item in never if item["observed"]["event"] == PRESS][0]
        self.assertEqual(press["id"], h.finding_id("event-never-accepted", [SHA, PRESS]))
        self.assertEqual(press["observed"], {"event": PRESS, "expect": "accept", "accepted_states": 0,
                                             "refused_states": 1})

    def test_an_event_declared_refused_that_is_accepted(self):
        catalogue = self.catalogue('hex = "37", expect = "accept"', 'hex = "37", expect = "refuse"')
        _, found = self.bfs("good", 3, catalogue=catalogue, code=1)
        self.assertEqual([item["observed"]["event"] for item in h.by_check(found, "event-accepted")], ["code-one-digit"])

    def test_vacuous_invocations_say_what_they_evaluated(self):
        for args, evaluated in (
                (("--strategy", "walk", "--origin-ms", "1", "--seed", "1", "--walk-seeds", "1", "--walk-length", "2",
                  "--extra-origins", "0"), []),
                (("--strategy", "replay", "--paths", str(h.paths_file(self.tmp, [[h.OPEN]]))), [])):
            outcome, found = self.explore("good", *args, "--summary", str(self.tmp / "s.json"), code=0)
            self.assertEqual(json.loads((self.tmp / "s.json").read_text())["evaluated"], evaluated)
            self.assertIn("evaluated: none", outcome.stdout)
            _, found = self.explore("good", *args, "--require", "C1,C8", code=1)
            self.assertEqual(sorted(item["observed"]["criterion"] for item in found), ["C1", "C8"])
            self.assertEqual({item["observed"]["evaluated"] for item in found}, {False})
        _, found = self.replay("nodomain", [[h.OPEN]], "--summary", str(self.tmp / "s.json"), criteria=["C1"], code=0)
        self.assertEqual(json.loads((self.tmp / "s.json").read_text())["evaluated"], [])
        self.replay("nodomain", [[h.OPEN]], "--require", "C1", criteria=["C1"], code=1)


class ReplayTest(h.ExploreCase):
    def test_every_finding_replays_to_the_same_id(self):
        runs = [("nondet", ("--strategy", "bfs", "--depth", "1", "--max-states", "100"), h.TOY),
                ("starve", ("--strategy", "bfs", "--depth", "1", "--max-states", "100"), h.TOY),
                ("far", ("--strategy", "bfs", "--depth", "1", "--max-states", "100"), h.TOY),
                ("refuseall", ("--strategy", "bfs", "--depth", "1", "--max-states", "100"), h.TOY),
                ("good", ("--strategy", "bfs", "--depth", "3", "--max-states", "100"), h.TOY_COARSE),
                ("good", ("--strategy", "walk", "--walk-seeds", "1,2", "--walk-length", "6", "--extra-origins", "1"),
                 h.TOY_COARSE)]
        replayed = 0
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
                replayed += 1
        self.assertGreater(replayed, 20)

    def test_walks_are_deterministic_and_use_extra_origins(self):
        args = ("--strategy", "walk", "--origin-ms", "1000", "--seed", "7", "--walk-seeds", "3,1", "--walk-length",
                "5", "--extra-origins", "2", "--summary")
        self.explore("good", *(args + (str(self.tmp / "s1.json"),)), out="a.json", code=0)
        self.explore("good", *(args + (str(self.tmp / "s2.json"),)), out="b.json", code=0)
        self.assertEqual((self.tmp / "s1.json").read_bytes(), (self.tmp / "s2.json").read_bytes())
        summary = json.loads((self.tmp / "s1.json").read_text())
        self.assertEqual((summary["runs"], summary["detail"]), (6, {"walks": 6}))


class ArgumentTest(h.ExploreCase):
    def test_strategy_arguments_are_required_and_refused_exactly(self):
        cases = [("bfs", ["--origin-ms", "1", "--seed", "1", "--depth", "2"]),
                 ("sweep", ["--origin-ms", "1", "--seed", "1", "--depth", "2"]),
                 ("replay", ["--paths", "x", "--seed", "1"]),
                 ("walk", ["--origin-ms", "1", "--seed", "1", "--walk-seeds", "1,1", "--walk-length", "2",
                           "--extra-origins", "0"]),
                 ("bfs", ["--origin-ms", "1", "--seed", "1", "--depth", "0", "--max-states", "1"]),
                 ("bfs", ["--origin-ms", "01", "--seed", "1", "--depth", "1", "--max-states", "1"]),
                 ("sweep", ["--origin-ms", "1", "--seed", "1", "--require", "C9"]),
                 ("sweep", ["--origin-ms", "1", "--seed", "1", "--budget-s", "0"])]
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
            outcome, _ = self.explore("good", "--strategy", "replay", "--paths", path, code=2)
            self.assertIn("internal error", outcome.stderr, document)
        (self.tmp / "dup.json").write_text('{"schema":"ui-explore-paths/1","criteria":[],"criteria":[],"paths":[["%s"]]}'
                                           % h.OPEN)
        self.explore("good", "--strategy", "replay", "--paths", self.tmp / "dup.json", code=2)
        (self.tmp / "deep.json").write_text("[" * 100000 + "]" * 100000)
        outcome, _ = self.explore("good", "--strategy", "replay", "--paths", self.tmp / "deep.json", code=2)
        self.assertIn("rigor: internal error: InternalError: paths file", outcome.stderr)

    def test_a_deeply_nested_catalogue_is_the_house_error(self):
        path = self.tmp / "deep.toml"
        path.write_text("x = " + "[" * 100000 + "]" * 100000 + "\n")
        outcome, _ = self.explore("good", "--strategy", "sweep", "--origin-ms", "1", "--seed", "1", catalogue=path,
                                  code=2)
        self.assertIn("rigor: internal error: InternalError: event catalogue", outcome.stderr)
        self.assertNotIn("Traceback", outcome.stderr)

    def test_a_catalogue_with_taps_needs_a_probe_with_the_tap_capability(self):
        catalogue = self.catalogue("[u2]\nevents = []", '[u2]\nevents = [ { id = "probe-1", x = 1, y = 2 } ]')
        outcome, _ = self.bfs("good", 1, catalogue=catalogue, code=2)
        self.assertIn("announces the tap capability", outcome.stderr)
        _, found = self.bfs("tapcap", 1, "--summary", str(self.tmp / "s.json"), catalogue=catalogue)
        self.assertEqual(json.loads((self.tmp / "s.json").read_text())["events"]["probe-1"],
                         {"accepted_states": 0, "refused_states": 1})

    def test_a_probe_that_is_not_executable_or_has_a_bad_format_is_exit_2(self):
        (self.tmp / "plain").write_text("")
        (self.tmp / "junk").write_bytes(b"\x7fELF junk")
        (self.tmp / "junk").chmod(0o755)
        for probe in ("plain", "junk"):
            outcome = run_rigor(["ui-explore", "--probe", self.tmp / probe, "--catalogue", h.TOY, "--strategy",
                                 "sweep", "--origin-ms", "1", "--seed", "1", "--out", self.tmp / "f.json"])
            self.assertExit(outcome, 2)
        self.assertIn("cannot execute the probe", outcome.stderr)

    def test_a_stale_out_and_summary_never_survive_exit_2(self):
        (self.tmp / "f.json").write_text("stale\n")
        (self.tmp / "s.json").write_text("stale\n")
        self.explore("good", "--strategy", "sweep", "--origin-ms", "1", "--seed", "1", "--depth", "1", "--summary",
                     str(self.tmp / "s.json"), code=2)
        self.assertFalse((self.tmp / "f.json").exists())
        self.assertFalse((self.tmp / "s.json").exists())

    def test_evidence_into_a_non_empty_directory_is_refused(self):
        (self.tmp / "ev").mkdir()
        (self.tmp / "ev" / "old").write_text("x")
        self.bfs("good", 1, "--evidence", str(self.tmp / "ev"), code=2)
