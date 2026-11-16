"""The ui-probe/1 grammar and client of `rigor ui-explore` (rigor_lib.ui_explore_grammar, ui_explore_probe)."""

import time
import unittest

from rigor_lib import ui_explore_grammar as g
from rigor_lib import ui_explore_probe as up
from rigor_lib.errors import InternalError
from tests import test_ui_explore_helpers as h
from tests.helpers import TempDirTestCase


def tearDownModule():
    h.assert_no_stubs()


class GrammarTest(unittest.TestCase):
    def test_unescape(self):
        self.assertEqual(g.unescape(r"a\\b\tc\nd\x01\xff"), b"a\\b\tc\nd\x01\xff")
        self.assertEqual(g.unescape(""), b"")
        for bad in (r"\x41", r"\x09", r"\x0a", r"\xFF", r"\q", "\\", r"\x1", r"\x7f\x"):
            self.assertIsNone(g.unescape(bad), bad)

    def test_records(self):
        record = g.parse_record("trace", "3\tline\t4013")
        self.assertEqual((record.fields, record.values), (("3", "line", "4013"), (b"3", b"line", b"4013")))
        bad = [("trace", "3\tline"), ("trace", "3\tline\t4013\t"), ("trace", "-3\tline\t4013"), ("trace", "03\tl\t1"),
               ("trace", "3\tl\\q\t1"), ("trace", "3\tl\x7f\t1"), ("patches", "a\tb\tc\td"),
               ("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t1\t-\t-\t", "\t2\t-\t-\t")),
               ("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t8\t8\t", "\t-0\t8\t")),
               ("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t8\t8\t", "\t1234567890123456789\t8\t"))]
        for kind, line in bad:
            with self.assertRaises(g.GrammarError, msg=(kind, line)):
                g.parse_record(kind, line)

    def test_frame_lines_are_split_and_unescaped(self):
        line = g.parse_frame_line("obj\tlabel\tA\\tB")
        self.assertEqual((line.raw, line.fields, line.values),
                         ("obj\tlabel\tA\\tB", ("obj", "label", "A\\tB"), (b"obj", b"label", b"A\tB")))
        with self.assertRaises(g.GrammarError):
            g.parse_frame_line("obj\t\\z")

    def test_env_inputs(self):
        self.assertEqual(g.parse_env_inputs("ok env-inputs 0"), ())
        self.assertEqual(g.parse_env_inputs("ok env-inputs 2 1:1:0:- 1:4294967295:-5:41ff"),
                         ((1, 0, ""), (4294967295, -5, "41ff")))
        for bad in ("ok env-inputs 1", "ok env-inputs 1 2:1:0:-", "ok env-inputs 1 1:1:0:4", "ok env-inputs 1 1:1:0:00",
                    "ok env-inputs 1 1:4294967296:0:-", "ok env-inputs 1 1:1:-0:-", "ok env-inputs 01 1:1:0:-",
                    "ok env-inputs 1 1:1:0:41FF", "ok env-input 0", "ok env-inputs 1  1:1:0:-",
                    "ok env-inputs 1 1:%s:0:-" % ("9" * 5000), "ok env-inputs 1 1:1:2147483648:-",
                    "ok env-inputs 65 " + " ".join(["1:1:0:-"] * 65)):
            with self.assertRaises(g.GrammarError, msg=bad[:60]):
                g.parse_env_inputs(bad)


class SessionTest(TempDirTestCase):
    def session(self, mode, deadline=2.0, budget=60):
        session = up.Session([str(h.stub(self.tmp, mode))], deadline, up.Budget(budget))
        self.addCleanup(session.close)
        return session

    def assert_error(self, call, kind, command):
        with self.assertRaises(up.ProbeError) as caught:
            call()
        self.assertEqual((caught.exception.kind, caught.exception.command), (kind, command))
        return caught.exception

    def test_a_clean_session(self):
        session = self.session("good")
        self.assertEqual((session.caps, session.domain_count()), ((), 2))
        session.open(1000, 7)
        self.assertEqual([r.fields[2] for r in session.records("semantic")], ["Toy", "Press", ""])
        self.assertEqual(session.env_inputs(), ((1, 0, ""),))
        self.assertEqual(session.apply(3, 1, 0, ""), "ok")
        self.assertEqual(session.apply(3, 1, 0, ""), "refused")
        self.assertEqual(session.next_due(), 4000)
        session.advance(4000)
        self.assertIsNone(session.next_due())
        self.assertEqual([r.fields[1] for r in session.records("trace")], ["boot", "press", "notice_timeout"])
        self.assertEqual(session.frame(), ())
        session.quit()

    def test_capabilities_and_taps(self):
        session = self.session("tapcap")
        self.assertEqual(session.caps, ("hit-test", "tap"))
        session.open(1000, 7)
        self.assertIsNone(session.hit_test(10, 20))
        self.assertEqual(session.tap(10, 20), (None, None))
        with self.assertRaises(InternalError):
            session.crop(0, 0, 1, 1)
        plain = self.session("good")
        plain.open(1000, 7)
        with self.assertRaises(InternalError):
            plain.tap(1, 1)
        self.assert_error(lambda: self.session("badcap"), "protocol", "greeting")

    def test_typed_errors(self):
        session = self.session("exit")
        session.open(1000, 7)
        self.assertEqual(self.assert_error(lambda: session.apply(3, 1, 0, ""), "crash", "apply").detail,
                         "the probe ended its output (exit status 3)")
        session = self.session("hang", deadline=0.3)
        session.open(1000, 7)
        start = time.monotonic()
        self.assert_error(lambda: session.apply(3, 1, 0, ""), "timeout", "apply")
        self.assertLess(time.monotonic() - start, 5)
        session = self.session("extra")
        session.open(1000, 7)
        session.apply(3, 1, 0, "")
        self.assertIn(self.assert_error(session.frame, "protocol", "frame").raw, ("stray output\n", "stray output"))
        session = self.session("failnext")
        session.open(1000, 7)
        self.assert_error(session.next_due, "protocol", "next-due")
        self.assert_error(self.session("bigdomain").domain_count, "protocol", "domain-count")

    def test_the_run_budget_is_not_a_command_timeout(self):
        session = self.session("hang", deadline=60, budget=0.5)
        session.open(1000, 7)
        with self.assertRaises(up.BudgetSpent):
            session.apply(3, 1, 0, "")

    def greeter(self, line):
        """A probe that only greets with `line` (then reads stdin to its end)."""
        script = self.tmp / "greeter"
        script.write_text("#!/bin/sh\necho '%s'\ncat > /dev/null\n" % line)
        script.chmod(0o755)
        return [str(script)]

    def test_the_pointer_capability_is_known_and_comes_last(self):
        """U05c: `pointer` follows the six capabilities of U05a; anywhere else, or twice, is a protocol error."""
        full = "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop"
        for line, caps in ((full + " pointer", up.CAPABILITIES[:-1]), ("ui-probe/1 ready pointer", ("pointer",)),
                           ("ui-probe/1 ready hit-test tap pointer", ("hit-test", "tap", "pointer"))):
            with self.subTest(line=line):
                session = up.Session(self.greeter(line), 2.0, up.Budget(60))
                self.addCleanup(session.close)
                self.assertEqual(session.caps, caps)
        self.assertEqual(up.CAPABILITIES[-2:], ("pointer", "identity"))   # U24: identity follows pointer
        for line in ("ui-probe/1 ready frame-facts ink hit-test tap apply-missed pointer crop",
                     "ui-probe/1 ready pointer frame-facts", full + " pointer pointer", full + " pointers",
                     full + " Pointer"):
            with self.subTest(line=line):
                self.assert_error(lambda: up.Session(self.greeter(line), 2.0, up.Budget(60)), "protocol", "greeting")

    def test_a_wrong_greeting_and_a_missing_binary(self):
        script = self.tmp / "liar"
        script.write_text("#!/bin/sh\necho 'ui-probe/2 ready'\n")
        script.chmod(0o755)
        self.assert_error(lambda: up.Session([str(script)], 2.0, up.Budget(60)), "protocol", "greeting")
        with self.assertRaises(InternalError):
            up.Session([str(self.tmp / "absent")], 2.0, up.Budget(60))

    def test_a_reply_byte_outside_printable_ascii(self):
        script = self.tmp / "bytes"
        script.write_text("#!/bin/sh\necho 'ui-probe/1 ready'\nread x\nprintf 'ok domain-count 2\\r\\n'\nsleep 5\n")
        script.chmod(0o755)
        session = up.Session([str(script)], 2.0, up.Budget(60))
        self.addCleanup(session.close)
        self.assert_error(session.domain_count, "protocol", "domain-count")

    def test_advance_must_reach_its_target(self):
        script = self.tmp / "short"
        script.write_text("#!/bin/sh\necho 'ui-probe/1 ready'\nread x\necho 'ok open'\nread x\necho 'ok advance 1001'\n"
                          "sleep 5\n")
        script.chmod(0o755)
        session = up.Session([str(script)], 2.0, up.Budget(60))
        self.addCleanup(session.close)
        session.open(1000, 7)
        self.assert_error(lambda: session.advance(1002), "protocol", "advance")
