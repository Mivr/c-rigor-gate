"""Unit tests for the trajectory precision work of T100 (round 3): the task key and the small helpers."""

import unittest

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_literals as literals
from rigor_lib import trajectory_task as task
from rigor_lib.errors import InternalError


class TaskKeyTests(unittest.TestCase):
    def test_may_merge_defaults_to_nothing_and_reads_a_list_of_refs(self):
        self.assertEqual(task.parse_task('id = "T1"\nallowed = ["a"]\n').may_merge, ())
        self.assertEqual(task.parse_task('id = "T1"\nallowed = ["a"]\nmay_merge = ["main", "dev"]\n').may_merge,
                         ("main", "dev"))

    def test_may_merge_must_be_a_list_of_strings(self):
        for value in ('"main"', "[1]"):
            with self.assertRaises(InternalError):
                task.parse_task('id = "T1"\nallowed = ["a"]\nmay_merge = %s\n' % value)


class KillTargetTests(unittest.TestCase):
    def test_a_negative_number_after_the_signal_is_a_process_group(self):
        self.assertEqual(cmds.kill_targets(["kill", "-9", "-4242"]), ["-4242"])
        self.assertEqual(cmds.kill_targets(["kill", "-TERM", "-4242", "7"]), ["-4242", "7"])
        self.assertEqual(cmds.kill_targets(["kill", "-s", "TERM", "-4242"]), ["-4242"])
        self.assertEqual(cmds.kill_targets(["kill", "-TERM", "--", "-4242"]), ["-4242"])

    def test_a_lone_number_option_is_a_signal_and_signal_zero_signals_nothing(self):
        self.assertEqual(cmds.kill_targets(["kill", "-9"]), [])
        self.assertIsNone(cmds.kill_targets(["kill", "-0", "4242"]))


class StringDataTests(unittest.TestCase):
    def test_strings_and_comments_are_emptied_but_fstrings_and_code_stay(self):
        text = "x = 'os.environ'  # os.environ\nprint(f'{os.environ}')\nos.getenv()\n"
        stripped = literals.without_string_data(text)
        self.assertNotIn("'os.environ'", stripped)
        self.assertEqual(stripped.count("environ"), 1)
        self.assertIn("getenv", stripped)


if __name__ == "__main__":
    unittest.main()
