"""Command line behaviour shared by every subcommand."""

from tests.helpers import TempDirTestCase, run_rigor

SUBCOMMANDS = ("contract", "suppressions", "tests", "ratchet", "verdict", "approve")


class CliTests(TempDirTestCase):
    def test_help_exits_0_for_every_subcommand(self):
        for name in SUBCOMMANDS:
            with self.subTest(name=name):
                outcome = run_rigor([name, "--help"])
                self.assertExit(outcome, 0)
                self.assertIn("usage", outcome.stdout)

    def test_top_level_help_lists_every_subcommand(self):
        outcome = run_rigor(["--help"])
        self.assertExit(outcome, 0)
        for name in SUBCOMMANDS:
            self.assertIn(name, outcome.stdout)

    def test_unknown_option_is_exit_2(self):
        self.assertExit(run_rigor(["verdict", "--bogus"]), 2)

    def test_missing_required_option_is_exit_2(self):
        for name in SUBCOMMANDS:
            with self.subTest(name=name):
                self.assertExit(run_rigor([name]), 2)

    def test_abbreviated_option_is_refused(self):
        order = self.tmp / "o.txt"
        order.write_text("a\n")
        outcome = run_rigor(["verdict", "--ord", order, "--results", self.sub("r"),
                             "--out", self.tmp / "v.json"])
        self.assertExit(outcome, 2)

    def test_unwritable_gate_output_is_exit_2(self):
        results = self.sub("results")
        expected = self.tmp / "e.json"
        expected.write_text('{"ids": ["s/one"]}')
        outcome = run_rigor(["tests", "--results", results, "--expected", expected,
                             "--out", self.tmp / "no" / "dir" / "out.json"])
        self.assertExit(outcome, 2)

    def test_stdout_summary_names_the_gate_and_status(self):
        results = self.sub("results")
        expected = self.tmp / "e.json"
        expected.write_text('{"ids": ["s/one"]}')
        outcome = run_rigor(["tests", "--results", results, "--expected", expected])
        self.assertExit(outcome, 1)
        self.assertTrue(outcome.stdout.startswith("tests: FAIL"))
