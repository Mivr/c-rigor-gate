"""U05e fix-up 1, after the merge with U24 (scene identity): boot seeds and prefixes read identity on every step as
any path does; identity is never part of a tap's change parts; a run the budget cuts runs no end-of-run judge
(no checks-examined, check-vacuous, check-blocked); and SIGTERM never waits inside the signal handler (it deadlocked
when it arrived while the main flow was inside Popen.wait)."""

import signal
import subprocess
import sys
import threading
import time

from rigor_lib import ui_explore
from rigor_lib import ui_explore_probe as up
from rigor_lib.ui_explore_words import changes, snapshot_of
from tests import test_ui_explore_helpers as h
from tests.helpers import RIGOR, base_env
from tests.test_ui_explore_scene import CANARY, SceneCase, scene_stub

ARGS = ("--contract", CANARY, "--today", "2026-11-16")
SEEDED = '\n[boot]\nseeds = [7, 8]\nprovenance = "design:P004#4.3"\n\n[[prefix]]\nname = "tick"\n' \
         'words = ["one-frame"]\nprovenance = "design:P004#4.3"\n'


def tearDownModule():
    h.assert_no_stubs()


class IdentityTest(SceneCase):
    def test_boot_seeds_and_the_prefix_read_identity_on_every_step(self):
        catalogue = self.tmp / "seeded.toml"
        catalogue.write_text(h.TOY.read_text() + SEEDED)
        log = self.tmp / "log"
        _, found = self.explore("ident", "--strategy", "bfs", "--origin-ms", "1000", "--boot-seeds", "catalogue",
                                "--prefix", "tick", "--depth", "1", "--max-states", "5", "--judges", "ui-scene",
                                *ARGS, catalogue=catalogue, log=log)
        commands = log.read_text().splitlines()
        opens = [i for i, c in enumerate(commands) if c.startswith("open ")]
        self.assertEqual({commands[i] for i in opens}, {"open 1000 7", "open 1000 8"})
        for start, end in zip(opens, opens[1:] + [len(commands)]):
            run = commands[start:end]
            prefix = run.index("advance 1016")          # the prefix word one-frame, in every run of both seeds
            self.assertIn("identity", run[:prefix])
            self.assertIn("identity", run[prefix:])
        self.assertEqual(h.by_check(found, "run-twice-mismatch") + h.by_check(found, "check-blocked"), [])
        self.assertTrue(all(item["path"][1] == "one-frame" for item in found if len(item["path"]) > 1))

    def test_identity_is_never_a_change_part_of_a_tap(self):
        obs = {"frame": (), "semantic": (), "due": None, "env": (), "identity": ("a",)}
        before = snapshot_of(obs)
        after = snapshot_of(dict(obs, identity=("b",)))
        self.assertNotIn("identity", before)
        step = type("S", (), {"acc_patches": [], "acc_trace": []})()
        self.assertEqual(changes(step, (0, 0), before, after), [])


class BudgetCutTest(SceneCase):
    def test_a_cut_bfs_runs_no_end_of_run_judge(self):
        _, found, summary = self.run_scene("slow", "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7",
                                           "--depth", "3", "--max-states", "50", "--budget-s", "4",
                                           "--judges", "ui-scene", *ARGS, code=1)
        checks = {item["check"] for item in found}
        self.assertIn("depth-unsaturated", checks)
        self.assertFalse(checks & {"checks-examined", "check-vacuous", "check-blocked", "exception-unused",
                                   "ui-coverage-gap", "event-never-accepted", "event-accepted"}, checks)
        self.assertEqual((summary["budget_spent"], summary["evaluated"]), (True, []))


class SignalTest(SceneCase):
    def test_the_handler_kills_without_waiting_while_popen_wait_holds_its_lock(self):
        session = up.Session([str(scene_stub(self.tmp, "plain"))], 5.0, up.Budget(60))
        lock = session._proc._waitpid_lock
        lock.acquire()                                  # as the main flow does inside Popen.wait
        try:
            exits = []

            def stop():
                try:
                    ui_explore._stop(signal.SIGTERM, None)
                except SystemExit as done:
                    exits.append(done.code)
            killer = threading.Thread(target=stop, daemon=True)
            killer.start()
            killer.join(5)
            self.assertFalse(killer.is_alive(), "the signal path waited on Popen's lock")
            self.assertEqual(exits, [128 + signal.SIGTERM])
        finally:
            lock.release()
        session.close()
        self.assertIsNotNone(session._proc.returncode)

    def test_sigterm_during_a_run_exits_128_plus_15_and_leaves_no_probe(self):
        argv = [sys.executable, "-I", "-B", str(RIGOR), "ui-explore", "--probe", str(scene_stub(self.tmp, "slow")),
                "--catalogue", str(h.REPO / "gate/tests/data/ui_explore/scene.events.toml"), "--out",
                str(self.tmp / "f.json"), "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7", "--depth", "3",
                "--max-states", "50", "--budget-s", "120"]
        for delay in (0.0, 0.5, 1.3):
            with self.subTest(delay=delay):
                proc = subprocess.Popen(argv, env=base_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                end = time.monotonic() + 15
                while not h.live_stubs() and time.monotonic() < end:     # the handler is in place once a probe runs
                    time.sleep(0.02)
                time.sleep(delay)
                for _ in range(3):                       # repeated signals land in other places of the run
                    proc.send_signal(signal.SIGTERM)
                    time.sleep(0.05)
                self.assertEqual(proc.wait(timeout=20), 128 + signal.SIGTERM)
                self.assertFalse((self.tmp / "f.json").exists())
        h.assert_no_stubs()
