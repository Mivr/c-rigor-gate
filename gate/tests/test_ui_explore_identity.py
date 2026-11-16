"""The scene identity in the explorer (U24, docs/ui-explore.md "Scene identity"): the reply grammar, the capability, the
`identity` command read once per judged step only when ui-scene needs it and the probe announces it, run-twice over it,
a reply that breaks the grammar, names a key the scene does not have or twice, or changes the model
(probe-internal-error, the last three of kind `contract`), and `check-blocked`
for a probe without the capability; `requires` may name identity."""

import unittest

from rigor_lib import ui_explore_catalogue as cat
from rigor_lib import ui_explore_probe as up
from rigor_lib.ui_explore_grammar import GrammarError, check_identity_keys, parse_identity, parse_record
from rigor_lib.ui_explore_run import Config, execute
from tests import test_ui_explore_helpers as h
from tests.test_ui_judge_helpers import CANARY_CONTRACT

ARGS = ("--contract", CANARY_CONTRACT, "--today", "2026-11-16")


def tearDownModule():
    h.assert_no_stubs()


class GrammarTest(unittest.TestCase):
    def test_one_state_line_first_then_node_lines_with_counted_arguments(self):
        records = parse_identity(["state\tmain", "node\tk\ttitle\tm\t2\t=8\t=", "node\tj\t-\tn\t0",
                                  "node\ti\tbody\t-\t0", "node\th\te\\x01\tm\\t1\t1\t=\\xd0\\x99"])
        self.assertEqual([r.fields[0] for r in records], ["state", "node", "node", "node", "node"])
        self.assertEqual((records[1].values[5], records[1].values[6], records[4].values[5]),
                         (b"=8", b"=", b"=\xd0\x99"))
        self.assertEqual(len(parse_identity(["state\tmain", "node\tk\te\tm\t16" + "\t=" * 16])), 2)

    def test_every_violation_is_refused(self):
        for lines in ([], ["state\t-"], ["state\t"], ["state\tmain\tx"], ["node\tk\te\tm\t0", "state\tmain"],
                      ["state\tmain", "state\tmain"], ["state\tmain", "node\tk\t-\t-\t0"],
                      ["state\tmain", "node\tk\te\t-\t1\t=x"], ["state\tmain", "node\tk\te\tm\t1"],
                      ["state\tmain", "node\tk\te\tm\t0\t=x"], ["state\tmain", "node\tk\te\tm\t1\tx"],
                      ["state\tmain", "node\tk\te\tm\t01\t=x"], ["state\tmain", "node\t\te\tm\t0"],
                      ["state\tmain", "node\tk\te\\q\tm\t0"], ["state\tmain", "label\tk\te\tm\t0"],
                      ["state\tmain", "node\tk\te\tm\t17" + "\t=" * 17], ["state\tmain", "node\tk\te\tm"]):
            with self.subTest(lines=lines), self.assertRaises(GrammarError):
                parse_identity(lines)

    def test_a_repeated_or_unknown_key_is_the_models_breach_not_the_grammars(self):
        semantic = [parse_record("semantic", line) for line in h.STUB_OPEN_SEMANTIC]
        twice = parse_identity(["state\tmain", "node\ttitle\te\tm\t0", "node\ttitle\tf\tm\t0"])
        ghost = parse_identity(["state\tmain", "node\tghost\te\tm\t0"])
        good = parse_identity(["state\tmain", "node\ttitle\te\tm\t0", "node\tbutton\tf\tm\t0"])
        self.assertEqual([check_identity_keys(r, semantic) for r in (twice, ghost, good)],
                         ["an identity reply that names a node key twice",
                          "an identity node line names a key no semantic record of the scene has", None])


class SessionTest(h.ExploreCase):
    def test_the_capability_comes_last_and_the_command_needs_it(self):
        session = up.Session([str(h.stub(self.tmp, "ident"))], 2.0, up.Budget(60))
        self.addCleanup(session.close)
        self.assertEqual(session.caps, ("frame-facts", "ink", "hit-test", "tap", "apply-missed", "crop", "identity"))
        session.open(1000, 7)
        records = session.identity()
        self.assertEqual([r.raw for r in records], ["state\tmain", "node\ttitle\ttitle\ttoy.title\t1\t=Toy",
                                                    "node\tbutton\t-\ttoy.press\t0"])
        plain = up.Session([str(h.stub(self.tmp, "facts"))], 2.0, up.Budget(60))
        self.addCleanup(plain.close)
        plain.open(1000, 7)
        with self.assertRaises(up.InternalError):
            plain.identity()

    def test_a_reply_that_breaks_the_grammar_is_a_protocol_error(self):
        session = up.Session([str(h.stub(self.tmp, "identbad"))], 2.0, up.Budget(60))
        self.addCleanup(session.close)
        session.open(1000, 7)
        with self.assertRaises(up.ProbeError) as caught:
            session.identity()
        self.assertEqual((caught.exception.kind, caught.exception.command), ("protocol", "identity"))


class StepTest(h.ExploreCase):
    def test_exactly_one_identity_per_observed_step_and_the_model_rechecked_after_it(self):
        log = self.tmp / "log"
        config = Config(probe=str(h.stub(self.tmp, "ident", log)), deadline_s=10.0, catalogue=cat.load(h.TOY),
                        budget=up.Budget(60), identity=True)
        run = execute(config, [h.OPEN, "tap-press", "fire-due"], settle=True)
        self.assertIsNone(run.error)
        observed = [step for step in run.steps if step.key is not None]
        commands = log.read_text().splitlines()
        self.assertEqual(commands.count("identity"), len(observed))
        self.assertTrue(all("identity" in step.obs for step in observed))
        after = [commands[i + 1:i + 3] for i, c in enumerate(commands) if c == "identity"]
        self.assertEqual(after, [["next-due", "semantic"]] * len(observed))
        plain = Config(probe=str(h.stub(self.tmp, "ident", self.tmp / "log2")), deadline_s=10.0,
                       catalogue=cat.load(h.TOY), budget=up.Budget(60))
        self.assertFalse(any("identity" in step.obs for step in execute(plain, [h.OPEN, "tap-press"]).steps))
        self.assertNotIn("identity", (self.tmp / "log2").read_text().splitlines())


class CliTest(h.ExploreCase):
    def run_judges(self, mode, judges="ui-scene", code=1, **kw):
        log = self.tmp / ("log-%s-%s" % (mode, judges))
        outcome, found = self.bfs(mode, 1, "--judges", judges, *ARGS, code=code, log=log, **kw)
        return outcome, found, log.read_text().splitlines() if log.exists() else []

    def test_ui_scene_reads_identity_once_per_step_of_both_runs_and_nothing_is_blocked(self):
        _outcome, found, commands = self.run_judges("ident")
        self.assertEqual(h.by_check(found, "check-blocked"), [])
        self.assertEqual(h.by_check(found, "probe-internal-error"), [])
        # read last in every step's observation (after env-inputs), at least once per run (open), never elsewhere
        self.assertGreaterEqual(commands.count("identity"), len([c for c in commands if c.startswith("open ")]))
        self.assertEqual({commands[i - 1] for i, c in enumerate(commands) if c == "identity"}, {"env-inputs"})
        self.assertEqual(h.by_check(found, "run-twice-mismatch"), [])

    def test_without_ui_scene_no_identity_is_read(self):
        _outcome, found, commands = self.run_judges("ident", judges="ui-fit")
        self.assertNotIn("identity", commands)
        self.assertEqual(h.by_check(found, "check-blocked"), [])

    def test_a_probe_without_identity_gives_check_blocked_per_identity_check(self):
        _outcome, found, commands = self.run_judges("facts")
        self.assertNotIn("identity", commands)
        self.assertEqual(sorted(f["observed"]["check"] for f in h.by_check(found, "check-blocked")),
                         ["raw-text", "required-element-missing", "value-split"])
        blocked = h.by_check(found, "check-blocked")
        self.assertTrue(all(f["severity"] == "error" and f["state"] is None for f in blocked))

    def test_a_bad_reply_or_an_unknown_key_ends_the_run_as_probe_internal_error(self):
        for mode, kind in (("identbad", "protocol"), ("identkey", "contract"), ("identdup", "contract"),
                           ("identmut", "contract")):
            with self.subTest(mode=mode):
                _outcome, found, _commands = self.run_judges(mode)
                errors = h.by_check(found, "probe-internal-error")
                self.assertTrue(errors)
                self.assertEqual({(f["observed"]["kind"], f["observed"]["command"]) for f in errors},
                                 {(kind, "identity")})

    def test_a_catalogue_may_require_identity(self):
        catalogue = self.catalogue('schema = "ui-events/1"', 'schema = "ui-events/1"\nrequires = ["identity"]')
        outcome, _found = self.bfs("facts", 1, catalogue=catalogue, code=2)
        self.assertIn("identity", outcome.stderr)
        self.bfs("ident", 1, catalogue=catalogue, code=1)   # accepted: the toy's ordinary findings, exit 1


if __name__ == "__main__":
    unittest.main()
