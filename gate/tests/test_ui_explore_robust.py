"""`rigor ui-explore` against misbehaving stub probes: every failure is its typed finding within seconds, never a
hang, a vacuous pass or a traceback (fix-up 1 of U05: items 1 to 5, 7, 8, 9, 11, 12)."""

import os
import signal
import subprocess
import sys
import time

from tests import test_ui_explore_helpers as h
from tests.helpers import GATE_DIR, base_env

PRESS = "tap-press"
QUICK = ("--deadline-ms", "1000")


class ProbeFailureTest(h.ExploreCase):
    def one(self, mode, observed, check="probe-internal-error", words=(h.OPEN, PRESS), word=PRESS, key=None):
        start = time.monotonic()
        _, found = self.replay(mode, [list(words)], *QUICK, code=1)
        self.assertLess(time.monotonic() - start, 15)
        found = [item for item in found if item["check"] == check]
        before = key if key is not None else (None if word == h.OPEN else h.STUB_OPEN_KEY)
        ident = h.finding_id(check, [observed["kind"], observed["command"], before, word])
        self.assertEqual([(item["id"], item["observed"]) for item in found], [(ident, observed)])
        return found[0]

    def test_a_probe_that_exits_mid_session(self):
        self.one("exit", {"kind": "crash", "command": "apply", "step": 1,
                          "detail": "the probe ended its output (exit status 3)"})

    def test_a_probe_that_hangs_is_a_timeout_within_the_deadline(self):
        self.one("hang", {"kind": "timeout", "command": "apply", "step": 1, "detail": "no complete reply within 1 s"},
                 "ui-explore-timeout")

    def test_an_err_reply(self):
        self.one("errreply", {"kind": "protocol", "command": "apply", "step": 1, "detail": "an err reply"})

    def test_a_malformed_record(self):
        self.one("malformed", {"kind": "protocol", "command": "semantic", "step": 0,
                               "detail": "a semantic record with 2 fields, wanted 14"}, words=(h.OPEN,), word=h.OPEN)

    def test_an_extra_line_after_a_reply_is_not_the_next_reply(self):
        self.one("extra", {"kind": "protocol", "command": "frame", "step": 1,
                           "detail": "output before the command was sent"})

    def test_output_after_ok_quit(self):
        item = self.one("quitgarbage", {"kind": "protocol", "command": "quit", "step": 2,
                                        "detail": "output after ok quit"}, word="quit", key=PRESSED_KEY)
        self.assertEqual(item["path"], [h.OPEN, PRESS])

    def test_a_non_zero_exit_after_quit(self):
        self.one("quitexit1", {"kind": "crash", "command": "quit", "step": 2, "detail": "exit status 1 after quit"},
                 word="quit", key=PRESSED_KEY)

    def test_a_fail_reply_to_a_command_that_never_fails(self):
        self.one("failnext", {"kind": "protocol", "command": "next-due", "step": 0,
                              "detail": "a fail reply to a command that never fails"}, words=(h.OPEN,), word=h.OPEN)

    def test_protocol_bounds_are_protocol_findings(self):
        for mode, command, detail in (
                ("bigid", "env-inputs", "an env input that is not kind 1, a uint32 id, an int32 arg and hex text"),
                ("bigdomain", "domain-count", "a count above 65535"),
                ("bigreply", "semantic", "a reply payload over 65536 bytes")):
            self.one(mode, {"kind": "protocol", "command": command, "step": 0, "detail": detail},
                     words=(h.OPEN,), word=h.OPEN)

    def test_a_refused_input_that_changes_the_model_is_a_contract_error(self):
        self.one("refusechange", {"kind": "contract", "command": "apply", "step": 2,
                                  "detail": "a refused input changed the model: trace"},
                 words=(h.OPEN, PRESS, PRESS), word=PRESS, key=PRESSED_KEY)

    def test_an_unknown_capability_is_a_protocol_error(self):
        self.one("badcap", {"kind": "protocol", "command": "greeting", "step": 0,
                            "detail": "unknown, repeated or unordered capabilities"}, words=(h.OPEN,), word=h.OPEN)

    def test_the_evidence_keeps_the_probe_bytes(self):
        _, found = self.replay("extra", [[h.OPEN, PRESS]], "--evidence", str(self.tmp / "ev"), code=1)
        name = found[0]["id"].rsplit("/", 1)[1]
        self.assertEqual((self.tmp / "ev" / name / "error.json").read_text(), '{"raw":"stray output\\n"}\n')


class TimeTest(h.ExploreCase):
    def test_a_deadline_that_never_moves_is_timer_starvation(self):
        _, found = self.replay("starve", [[h.OPEN, PRESS] + ["settle"] * 4], "--starvation-steps", "3", code=1)
        after = h.toy_key(AFTER, "within-frame", [])
        self.assertEqual([item["id"] for item in found], [h.finding_id("timer-starvation", ["streak", after])])
        self.assertEqual(found[0]["path"], [h.OPEN, PRESS, "settle", "settle", "settle"])
        self.assertEqual(found[0]["observed"]["now_and_next_due"], [[1001, 1002], [1002, 1003], [1003, 1004]])

    def test_until_change_on_a_starving_model_stops_at_the_bound(self):
        start = time.monotonic()
        _, found = self.replay("starve", [[h.OPEN, PRESS, "wait-change"]], "--starvation-steps", "5", code=1)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual([item["check"] for item in found], ["timer-starvation"])
        self.assertEqual(found[0]["observed"]["firings"], 5)

    def test_a_zero_delay_deadline_is_timer_starvation(self):
        for mode in ("duenow", "duenowerr"):
            _, found = self.replay(mode, [[h.OPEN, PRESS]], code=1)
            self.assertEqual([(item["check"], item["observed"]["kind"], item["observed"]["command"]) for item in found],
                             [("timer-starvation", "zero-delay", "next-due")], mode)

    def test_a_far_deadline_is_timer_unreachable_at_once(self):
        start = time.monotonic()
        _, found = self.replay("far", [[h.OPEN, PRESS, "fire-due", "settle", "before-due"]], code=1)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(sorted((item["observed"]["word"], item["observed"]["reason"]) for item in found),
                         [("before-due", "max-wait"), ("fire-due", "max-wait"), ("settle", "max-wait")])
        fire = [item for item in found if item["observed"]["word"] == "fire-due"]
        self.assertEqual(fire[0]["observed"], {"word": "fire-due", "target_ms": 1000 + (1 << 40), "now_ms": 1000,
                                                "max_wait_ms": 600000, "reason": "max-wait"})

    def test_a_deadline_past_the_protocol_clock_is_timer_unreachable(self):
        _, found = self.replay("beyond", [[h.OPEN, PRESS, "fire-due", "at 4503599627370497"]], code=1)
        self.assertEqual(sorted((item["observed"]["word"], item["observed"]["reason"]) for item in found),
                         [("at 4503599627370497", "protocol-limit"), ("fire-due", "protocol-limit")])

    def test_the_run_budget_ends_in_ui_explore_timeout(self):
        start = time.monotonic()
        _, found = self.bfs("hang", 3, "--deadline-ms", "600000", "--budget-s", "2", "--summary",
                            str(self.tmp / "s.json"), code=1)
        self.assertLess(time.monotonic() - start, 15)
        self.assertEqual([(item["check"], item["observed"]["kind"]) for item in found],
                         [("ui-explore-timeout", "budget")])
        self.assertIn('"budget_spent":true', (self.tmp / "s.json").read_text())

    def test_advances_are_split_on_the_frame_grid(self):
        log = self.tmp / "commands.log"
        self.replay("good", [[h.OPEN, "idle-5min", "at 300010"]], log=log, code=0)
        targets = [int(line.split()[1]) for line in log.read_text().splitlines() if line.startswith("advance ")]
        runs = len(targets) // 2
        self.assertEqual(targets[:runs], targets[runs:])
        previous = 1000
        for target in targets[:runs]:
            self.assertLessEqual(target - previous, 64 * 16)
            self.assertTrue((target - 1000) % 16 == 0 or target in (301000, 301010), target)
            previous = target
        self.assertEqual(targets[runs - 2:runs], [301000, 301010])

    def test_settle_ends_on_a_perpetual_tick_and_until_change_is_one_event(self):
        _, found = self.replay("tick", [[h.OPEN, "settle", "settle", PRESS, "until-change"]], "--summary",
                               str(self.tmp / "s.json"), code=0)
        self.assertEqual(found, [])
        catalogue = self.catalogue("max_wait_ms = 600000", "max_wait_ms = 5000")
        catalogue = self.catalogue("ms = 300000", "ms = 4000", base=catalogue)
        catalogue = self.catalogue("offset_ms = 10000", "offset_ms = 4000", base=catalogue)
        start = time.monotonic()
        _, found = self.bfs("tick", 4, catalogue=catalogue, code=0)
        self.assertEqual(found, [])
        self.assertLess(time.monotonic() - start, 30)


AFTER = ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
         "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
         "notice\tlabel\tPressed\t8\t90\t56\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"]
PRESSED_KEY = h.toy_key(AFTER, "pending", [])


class ProcessTest(h.ExploreCase):
    def test_a_grandchild_holding_stdout_is_killed(self):
        log = self.tmp / "orphan.log"
        _, found = self.replay("orphan", [[h.OPEN, PRESS]], "--deadline-ms", "800", log=log, code=1)
        self.assertEqual({item["check"] for item in found}, {"ui-explore-timeout"})
        grandchild = int((self.tmp / "orphan.log.orphan").read_text())
        deadline = time.monotonic() + 5
        while h.alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(h.alive(grandchild))

    def test_sigterm_kills_every_live_probe_group(self):
        log = self.tmp / "hang.log"
        probe = h.stub(self.tmp, "hang", log)
        paths = h.paths_file(self.tmp, [[h.OPEN, PRESS]])
        argv = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor"), "ui-explore", "--probe", str(probe),
                "--catalogue", str(h.TOY), "--strategy", "replay", "--paths", str(paths), "--out",
                str(self.tmp / "f.json"), "--deadline-ms", "600000"]
        proc = subprocess.Popen(argv, env=base_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while not (self.tmp / "hang.log").exists() or "apply" not in (self.tmp / "hang.log").read_text():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        pid = int((self.tmp / "hang.log.pid").read_text())
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 128 + signal.SIGTERM)
        deadline = time.monotonic() + 5
        while h.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(h.alive(pid))
        self.assertFalse(os.path.exists(self.tmp / "f.json"))
