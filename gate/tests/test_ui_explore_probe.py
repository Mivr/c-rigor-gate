"""The ui-probe/1 client of `rigor ui-explore` (rigor_lib.ui_explore_probe): record grammar, reply parsing, and the typed
errors of a probe that exits, hangs or misbehaves."""

import time
import unittest

from rigor_lib import ui_explore_probe as up
from tests import test_ui_explore_helpers as h
from tests.helpers import TempDirTestCase


class GrammarTest(unittest.TestCase):
    def test_unescape(self):
        self.assertEqual(up.unescape(r"a\\b\tc\nd\x01\xff"), b"a\\b\tc\nd\x01\xff")
        self.assertEqual(up.unescape(""), b"")
        for bad in (r"\x41", r"\x09", r"\x0a", r"\xFF", r"\q", "\\", r"\x1", r"\x7f\x"):
            self.assertIsNone(up.unescape(bad), bad)
        self.assertEqual(up.unescape(r"\x7f"), b"\x7f")

    def test_records(self):
        record = up.parse_record("trace", "3\tline\t4013")
        self.assertEqual((record.fields, record.values), (("3", "line", "4013"), (b"3", b"line", b"4013")))
        semantic = up.parse_record("semantic", h.STUB_OPEN_SEMANTIC[2])
        self.assertEqual(semantic.values[2], b"")
        self.assertEqual(up.parse_record("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t8\t8\t", "\t-8\t8\t")).fields[3],
                         "-8")
        bad = [("trace", "3\tline"), ("trace", "3\tline\t4013\t"), ("trace", "-3\tline\t4013"), ("trace", "03\tl\t1"),
               ("trace", "3\tl\\q\t1"), ("trace", "3\tl\x7f\t1"), ("patches", "a\tb\tc\td"),
               ("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t1\t-\t-\t", "\t2\t-\t-\t")),
               ("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t8\t8\t", "\t-0\t8\t")),
               ("semantic", h.STUB_OPEN_SEMANTIC[0].replace("\t8\t8\t", "\t1234567890123456789\t8\t"))]
        for kind, line in bad:
            with self.assertRaises(up.ProbeError, msg=(kind, line)) as caught:
                up.parse_record(kind, line)
            self.assertEqual(caught.exception.kind, "protocol")

    def test_env_inputs(self):
        self.assertEqual(up.parse_env_inputs("ok env-inputs 0"), ())
        self.assertEqual(up.parse_env_inputs("ok env-inputs 2 1:1:0:- 1:4294967295:-5:41ff"),
                         ((1, 0, ""), (4294967295, -5, "41ff")))
        for bad in ("ok env-inputs 1", "ok env-inputs 1 2:1:0:-", "ok env-inputs 1 1:1:0:4", "ok env-inputs 1 1:1:0:00",
                    "ok env-inputs 1 1:4294967296:0:-", "ok env-inputs 1 1:1:-0:-", "ok env-inputs 01 1:1:0:-",
                    "ok env-inputs 1 1:1:0:41FF", "ok env-input 0", "ok env-inputs 1  1:1:0:-"):
            with self.assertRaises(up.ProbeError, msg=bad):
                up.parse_env_inputs(bad)


class SessionTest(TempDirTestCase):
    def session(self, mode, deadline=2.0):
        session = up.Session([str(h.stub(self.tmp, mode))], deadline)
        self.addCleanup(session.close)
        return session

    def test_a_clean_session(self):
        session = self.session("good")
        self.assertEqual(session.domain_count(), 2)
        session.open(1000, 7)
        self.assertEqual([r.fields[2] for r in session.records("semantic")], ["Toy", "Press", ""])
        self.assertEqual(session.env_inputs(), ((1, 0, ""),))
        self.assertTrue(session.apply(3, 1, 0, ""))
        self.assertFalse(session.apply(3, 1, 0, ""))
        self.assertEqual(session.next_due(), 4000)
        session.advance(4000)
        self.assertIsNone(session.next_due())
        self.assertEqual([r.fields[1] for r in session.records("trace")], ["boot", "press", "notice_timeout"])
        self.assertEqual(session.frame(), ())
        session.quit()

    def assert_error(self, call, kind, command):
        with self.assertRaises(up.ProbeError) as caught:
            call()
        self.assertEqual((caught.exception.kind, caught.exception.command), (kind, command))
        return caught.exception

    def test_a_probe_that_exits_mid_session(self):
        session = self.session("exit")
        session.open(1000, 7)
        error = self.assert_error(lambda: session.apply(3, 1, 0, ""), "crash", "apply")
        self.assertEqual(error.detail, "the probe ended its output (exit status 3)")

    def test_a_probe_that_hangs_times_out_within_the_deadline(self):
        session = self.session("hang", deadline=0.3)
        session.open(1000, 7)
        start = time.monotonic()
        self.assert_error(lambda: session.apply(3, 1, 0, ""), "timeout", "apply")
        self.assertLess(time.monotonic() - start, 5)

    def test_a_malformed_reply(self):
        session = self.session("malformed")
        session.open(1000, 7)
        self.assert_error(lambda: session.records("semantic"), "protocol", "semantic")

    def test_an_err_reply(self):
        session = self.session("errreply")
        session.open(1000, 7)
        self.assert_error(lambda: session.apply(3, 1, 0, ""), "protocol", "apply")

    def test_a_wrong_greeting_and_a_missing_binary(self):
        script = self.tmp / "liar"
        script.write_text("#!/bin/sh\necho 'ui-probe/2 ready'\n")
        script.chmod(0o755)
        self.assert_error(lambda: up.Session([str(script)], 2.0), "protocol", "greeting")
        self.assert_error(lambda: up.Session([str(self.tmp / "absent")], 2.0), "crash", "start")

    def test_a_non_zero_exit_after_quit(self):
        script = self.tmp / "bad-exit"
        script.write_text("#!/bin/sh\necho 'ui-probe/1 ready'\nread x\necho 'ok quit'\nexit 1\n")
        script.chmod(0o755)
        session = up.Session([str(script)], 2.0)
        self.addCleanup(session.close)
        self.assert_error(session.quit, "crash", "quit")

    def test_a_reply_byte_outside_printable_ascii(self):
        script = self.tmp / "bytes"
        script.write_text("#!/bin/sh\necho 'ui-probe/1 ready'\nread x\nprintf 'ok domain-count 2\\r\\n'\nsleep 5\n")
        script.chmod(0o755)
        session = up.Session([str(script)], 2.0)
        self.addCleanup(session.close)
        self.assert_error(session.domain_count, "protocol", "domain-count")

    def test_advance_must_reach_its_target(self):
        script = self.tmp / "short"
        script.write_text("#!/bin/sh\necho 'ui-probe/1 ready'\nread x\necho 'ok open'\nread x\necho 'ok advance 1001'\n"
                          "sleep 5\n")
        script.chmod(0o755)
        session = up.Session([str(script)], 2.0)
        self.addCleanup(session.close)
        session.open(1000, 7)
        self.assert_error(lambda: session.advance(1002), "protocol", "advance")
