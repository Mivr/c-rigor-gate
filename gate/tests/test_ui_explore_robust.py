"""`rigor ui-explore` against misbehaving stub probes: every failure is its typed finding within seconds, never a
hang, a vacuous pass or a traceback, and no stub outlives the tests (U05 fix-ups 1 and 2)."""

import os
import signal
import subprocess
import sys
import time

from tests import test_ui_explore_helpers as h
from tests.helpers import GATE_DIR, base_env

PRESS = "tap-press"
SLOW = ("--deadline-ms", "2000")         # only for the stubs that hang; every other test keeps the 10 s default
AFTER = ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
         "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
         "notice\tlabel\tPressed\t8\t90\t56\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"]
PRESSED_KEY = h.toy_key(AFTER, "pending", [])
STARVED_KEY = h.toy_key(AFTER, "within-frame", [])


def tearDownModule():
    h.assert_no_stubs()


class ProbeFailureTest(h.ExploreCase):
    def one(self, mode, observed, check="probe-internal-error", words=(h.OPEN, PRESS), word=PRESS, key=None,
            extra=()):
        start = time.monotonic()
        _, found = self.replay(mode, [list(words)], *extra, code=1)
        self.assertLess(time.monotonic() - start, 20)
        found = [item for item in found if item["check"] == check]
        before = key if key is not None else (None if word == h.OPEN else h.STUB_OPEN_KEY)
        ident = h.finding_id(check, [observed["kind"], observed["command"], before, word])
        self.assertEqual([(item["id"], item["observed"]) for item in found], [(ident, observed)])
        return found[0]

    def test_a_probe_that_exits_mid_session(self):
        self.one("exit", {"kind": "crash", "command": "apply", "step": 1,
                          "detail": "the probe ended its output (exit status 3)"})

    def test_a_probe_that_hangs_is_a_timeout_within_the_deadline(self):
        self.one("hang", {"kind": "timeout", "command": "apply", "step": 1, "detail": "no complete reply within 2 s"},
                 "ui-explore-timeout", extra=SLOW)

    def test_an_err_reply(self):
        self.one("errreply", {"kind": "protocol", "command": "apply", "step": 1, "detail": "an err reply"})

    def test_a_malformed_record(self):
        self.one("malformed", {"kind": "protocol", "command": "semantic", "step": 0,
                               "detail": "a semantic record with 2 fields, wanted 14"}, words=(h.OPEN,), word=h.OPEN)

    def test_a_line_that_is_not_the_reply_has_one_identity_whatever_the_timing(self):
        for mode in ("extra", "extraframe"):
            outputs = set()
            for number in range(4):
                self.one(mode, {"kind": "protocol", "command": None, "step": 1,
                                "detail": "a line that is not the reply to this command"})
                outputs.add((self.tmp / "f.json").read_bytes())
            self.assertEqual(len(outputs), 1, mode)

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
                ("bigreply", "semantic", "a reply payload over 65536 bytes"),
                ("longline", "semantic", "a reply line longer than 65536 bytes")):
            self.one(mode, {"kind": "protocol", "command": command, "step": 0, "detail": detail},
                     words=(h.OPEN,), word=h.OPEN)

    def test_a_refused_input_that_changes_the_model_is_a_contract_error(self):
        for mode, part in (("refusechange", "trace"), ("refuseframe", "frame")):
            self.one(mode, {"kind": "contract", "command": "apply", "step": 2,
                            "detail": "a refused input changed the model: " + part},
                     words=(h.OPEN, PRESS, PRESS), word=PRESS, key=PRESSED_KEY)

    def test_a_refused_pad_digit_that_changes_the_model_is_caught_at_that_digit(self):
        catalogue = self.pad_catalogue("19", "accept")
        _, found = self.replay("paddigit", [[h.OPEN, "pad-code"]], catalogue=catalogue, code=1)
        self.assertEqual([(item["observed"]["kind"], item["observed"]["detail"]) for item in found],
                         [("contract", "a refused input changed the model: patches")])

    def pad_catalogue(self, digits, expect):
        return self.catalogue('  { id = "code-empty",', '  { id = "pad-code", boundary = "max", via = "pad", digits = "%s", '
                              'digit_intent = 10, enter_intent = 11, expect = "%s" },\n  { id = "code-empty",'
                              % (digits, expect))

    def test_a_pad_macro_is_accepted_only_when_its_enter_is(self):
        accept, refuse = self.pad_catalogue("12", "accept"), self.pad_catalogue("12", "refuse")
        _, found = self.bfs("padenter", 3, catalogue=accept, code=1)
        self.assertEqual([item["observed"]["event"] for item in h.by_check(found, "event-never-accepted")], ["pad-code"])
        _, found = self.bfs("padenter", 3, catalogue=refuse, code=0)
        self.assertEqual(found, [])
        _, found = self.bfs("good", 3, catalogue=refuse, code=1)
        self.assertEqual([item["observed"]["event"] for item in h.by_check(found, "event-accepted")], ["pad-code"])

    def test_capabilities_that_change_between_launches(self):
        log = self.tmp / "flip.log"
        _, found = self.replay("capflip", [[h.OPEN]], log=log, code=1)
        errors = h.by_check(found, "probe-internal-error")
        self.assertEqual([(item["observed"]["command"], item["observed"]["detail"]) for item in errors],
                         [("greeting", "capabilities differ from the first launch of this probe")])

    def test_an_unknown_capability_is_a_protocol_error(self):
        self.one("badcap", {"kind": "protocol", "command": "greeting", "step": 0,
                            "detail": "unknown, repeated or unordered capabilities"}, words=(h.OPEN,), word=h.OPEN)

    def test_a_probe_that_never_greets_is_a_finding_not_exit_2(self):
        catalogue = self.catalogue("[u2]\nevents = []", '[u2]\nevents = [ { id = "probe-1", x = 1, y = 2 } ]')
        _, found = self.replay("nogreet", [[h.OPEN]], *SLOW, catalogue=catalogue, code=1)
        self.assertEqual([(item["check"], item["observed"]["command"]) for item in found],
                         [("ui-explore-timeout", "greeting")])

    def test_the_evidence_keeps_the_probe_bytes(self):
        _, found = self.replay("extra", [[h.OPEN, PRESS]], "--evidence", str(self.tmp / "ev"), code=1)
        name = found[0]["id"].rsplit("/", 1)[1]
        text = (self.tmp / "ev" / name / "error.json").read_text()
        self.assertIn('"raw":"stray output', text)


class TimeTest(h.ExploreCase):
    def test_more_than_32_firings_within_a_window_is_timer_starvation(self):
        _, found = self.replay("starve", [[h.OPEN, PRESS] + ["settle"] * 40], code=1)
        self.assertEqual([item["id"] for item in found], [h.finding_id("timer-starvation", ["window", STARVED_KEY])])
        self.assertEqual(found[0]["path"], [h.OPEN, PRESS] + ["settle"] * 33)
        self.assertEqual(found[0]["observed"], {"firings": 33, "limit": 32, "window_ms": 1024, "first_ms": 1001,
                                                "last_ms": 1033})

    def test_alternating_1_ms_and_17_ms_deadlines_starve_too(self):
        _, found = self.replay("alt", [[h.OPEN, PRESS] + ["settle"] * 40], code=1)
        self.assertEqual([item["check"] for item in found], ["timer-starvation"])
        self.assertEqual(found[0]["observed"]["firings"], 33)
        _, found = self.bfs("alt", 1, code=1)
        self.assertEqual(len(h.by_check(found, "timer-starvation")), 1)

    def test_until_change_on_a_starving_model_stops_at_the_limit(self):
        start = time.monotonic()
        _, found = self.replay("starve", [[h.OPEN, PRESS, "wait-change"]], code=1)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual([(item["check"], item["path"]) for item in found],
                         [("timer-starvation", [h.OPEN, PRESS, "wait-change"])])

    def test_the_starvation_limit_comes_from_the_catalogue(self):
        catalogue = self.catalogue("drain_ms = 1024\n", 'drain_ms = 1024\nstarvation = { firings = 5, window_frames = 4, '
                                   'provenance = "owner:D99" }\n')
        _, found = self.replay("starve", [[h.OPEN, PRESS] + ["settle"] * 10], catalogue=catalogue, code=1)
        self.assertEqual(found[0]["observed"], {"firings": 6, "limit": 5, "window_ms": 64, "first_ms": 1001,
                                                "last_ms": 1006})

    def test_a_zero_delay_deadline_is_timer_starvation(self):
        for mode in ("duenow", "duenowerr"):
            _, found = self.replay(mode, [[h.OPEN, PRESS]], code=1)
            self.assertEqual([(item["check"], item["observed"]["kind"], item["observed"]["command"]) for item in found],
                             [("timer-starvation", "zero-delay", "next-due")], mode)

    def test_a_far_deadline_is_timer_unreachable_for_every_time_word(self):
        start = time.monotonic()
        _, found = self.replay("far", [[h.OPEN, PRESS, "fire-due", "settle", "before-due", "wait-change", "until-change"]],
                               code=1)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(sorted((item["observed"]["word"], item["observed"]["reason"]) for item in found),
                         [("before-due", "max-wait"), ("fire-due", "max-wait"), ("settle", "max-wait"),
                          ("until-change", "max-wait"), ("wait-change", "max-wait")])
        fire = [item for item in found if item["observed"]["word"] == "fire-due"]
        self.assertEqual(fire[0]["observed"], {"word": "fire-due", "target_ms": 1000 + (1 << 40), "now_ms": 1000,
                                               "max_wait_ms": 10000, "reason": "max-wait"})

    def test_a_deadline_past_the_protocol_clock_is_timer_unreachable(self):
        for mode in ("beyond", "huge"):
            _, found = self.replay(mode, [[h.OPEN, PRESS, "fire-due", "at 4503599627370497"]], code=1)
            self.assertEqual(sorted((item["observed"]["word"], item["observed"]["reason"]) for item in found),
                             [("at 4503599627370497", "protocol-limit"), ("fire-due", "protocol-limit")], mode)

    def test_the_run_budget_ends_in_ui_explore_timeout(self):
        for mode in ("hang", "nogreet"):
            start = time.monotonic()
            _, found = self.replay(mode, [[h.OPEN, PRESS]], "--deadline-ms", "600000", "--budget-s", "2", "--summary",
                                   str(self.tmp / "s.json"), code=1)
            self.assertLess(time.monotonic() - start, 15)
            self.assertEqual([(item["check"], item["observed"]["kind"]) for item in found],
                             [("ui-explore-timeout", "budget")], mode)
            self.assertIn('"budget_spent":true', (self.tmp / "s.json").read_text())

    def test_a_run_that_could_exceed_the_budget_is_refused_up_front(self):
        outcome, found = self.bfs("good", 64, "--budget-s", "60", code=2)
        self.assertIn("could take", outcome.stderr)
        self.assertIsNone(found)

    def test_advances_are_split_on_the_frame_grid_and_drain_the_logs(self):
        log = self.tmp / "commands.log"
        self.replay("good", [[h.OPEN, "idle-10s", "at 10010"]], log=log, code=0)
        lines = log.read_text().splitlines()
        targets = [int(line.split()[1]) for line in lines if line.startswith("advance ")]
        runs = len(targets) // 2
        self.assertEqual(targets[:runs], targets[runs:])
        self.assertEqual(targets[:runs], [1000 + 1024 * k for k in range(1, 10)] + [11000, 11010])
        first = lines.index("advance 2024")
        self.assertEqual(lines[first:first + 4], ["advance 2024", "patches", "trace", "advance 3048"])

    def test_typed_time_outcomes_are_in_the_summary(self):
        self.replay("good", [[h.OPEN, "at 10", "at 5", "before-due", PRESS, "before-due", "before-due"]], "--summary",
                    str(self.tmp / "s.json"), code=0)
        outcomes = h.json.loads((self.tmp / "s.json").read_text())["outcomes"]
        self.assertEqual(outcomes["at"], {"now": 1, "past": 1})
        self.assertEqual(outcomes["before-due"], {"no-deadline": 1, "now": 1, "deadline-within-a-frame": 1})

    def test_settle_ends_on_a_perpetual_tick_and_until_change_is_one_event(self):
        _, found = self.replay("tick", [[h.OPEN, "settle", "settle", PRESS, "until-change"]], code=0)
        self.assertEqual(found, [])
        start = time.monotonic()
        _, found = self.bfs("tick", 4, code=0)
        self.assertEqual(found, [])
        self.assertLess(time.monotonic() - start, 60)


class ProcessTest(h.ExploreCase):
    def test_a_grandchild_holding_stdout_is_killed(self):
        log = self.tmp / "orphan.log"
        _, found = self.replay("orphan", [[h.OPEN, PRESS]], *SLOW, log=log, code=1)
        self.assertEqual({item["check"] for item in found}, {"ui-explore-timeout"})
        grandchild = int((self.tmp / "orphan.log.orphan").read_text())
        end = time.monotonic() + 5
        while h.alive(grandchild) and time.monotonic() < end:
            time.sleep(0.05)
        self.assertFalse(h.alive(grandchild))

    def test_sigterm_and_sighup_kill_every_live_probe_group(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            log = self.tmp / ("hang%d.log" % sig)
            probe = h.stub(self.tmp, "hang", log)
            paths = h.paths_file(self.tmp, [[h.OPEN, PRESS]])
            argv = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor"), "ui-explore", "--probe", str(probe),
                    "--catalogue", str(h.TOY), "--strategy", "replay", "--paths", str(paths), "--out",
                    str(self.tmp / "f.json"), "--deadline-ms", "600000"]
            proc = subprocess.Popen(argv, env=base_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(self.kill_stubs, proc)
            end = time.monotonic() + 20
            while not log.exists() or "apply" not in log.read_text():
                self.assertLess(time.monotonic(), end)
                time.sleep(0.05)
            pid = int((self.tmp / (log.name + ".pid")).read_text())
            proc.send_signal(sig)
            self.assertEqual(proc.wait(timeout=10), 128 + sig)
            end = time.monotonic() + 5
            while h.alive(pid) and time.monotonic() < end:
                time.sleep(0.05)
            self.assertFalse(h.alive(pid))
            self.assertFalse(os.path.exists(self.tmp / "f.json"))

    @staticmethod
    def kill_stubs(proc):
        """Cleanup even when the test failed early: the explorer and every stub it started."""
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for pid in h.live_stubs():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
