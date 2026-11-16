"""U05c: `ui/model/probe_session.py`, the gate-owned runner of `c_ui_probe_session`, against fake probes.

A fake probe is a shell script written per test: it prints fixed bytes, may write to stderr, exit with any status or
kill itself. The runner's verdict, its report (the first differing line with its number) and its results file (the
`ctest` JSON Lines, parsed by the gate's own parser) are asserted exactly.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from rigor_lib import results_parse

GATE = Path(__file__).resolve().parent.parent
RUNNER = GATE.parent / "ui" / "model" / "probe_session.py"
ID = "ui_probe_session/pkg.sub:s"
LABEL = "root//pkg/sub:s"
GREETING = b"ui-probe/1 ready\n"
SESSION = b"open 0 1\nquit\n"
WANT = GREETING + b"ok open\nok quit\n"


class Runner(unittest.TestCase):
    def setUp(self):
        import tempfile
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)

    def probe(self, body):
        path = self.dir / "probe.sh"
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        return path

    def printing(self, data, extra=""):
        """A probe that reads all of stdin, prints `data` (bytes) and then runs `extra`."""
        (self.dir / "stdout.bin").write_bytes(data)
        return self.probe('cat > /dev/null\ncat "%s"\n%s' % (self.dir / "stdout.bin", extra))

    def run_runner(self, probe, session=SESSION, want=WANT, *extra):
        (self.dir / "s.in").write_bytes(session)
        (self.dir / "s.out").write_bytes(want)
        args = [sys.executable, "-I", "-B", str(RUNNER), "--probe", str(probe), "--session", str(self.dir / "s.in"),
                "--expected", str(self.dir / "s.out"), "--id", ID, "--label", LABEL, "--out", str(self.dir / "r.jsonl"),
                "--report", str(self.dir / "report.txt"), "--verdict", str(self.dir / "verdict")] + list(extra)
        done = subprocess.run(args, capture_output=True, timeout=120, env={})
        return done.returncode, done.stderr

    def outcome(self):
        """(verdict, report lines, the one parsed test record)."""
        parsed = results_parse.parse_file("r.jsonl", (self.dir / "r.jsonl").read_bytes())
        self.assertEqual(parsed.problems, [])
        self.assertEqual(len(parsed.records), 1)
        return ((self.dir / "verdict").read_text(), (self.dir / "report.txt").read_text().splitlines(),
                parsed.records[0])

    def failing(self, probe, *problems, session=SESSION, want=WANT):
        code, err = self.run_runner(probe, session, want)
        self.assertEqual((code, err), (0, b""))
        verdict, report, record = self.outcome()
        self.assertEqual(verdict, "fail\n")
        self.assertEqual(report, ["c_ui_probe_session %s: FAIL" % LABEL] + ["  " + p for p in problems])
        self.assertEqual((record.test_id, record.status, record.asserts), (ID, "fail", 4))
        reason = json.loads((self.dir / "r.jsonl").read_text().splitlines()[0])["reason"]
        self.assertEqual(reason, problems[0])

    def test_a_matching_session_passes(self):
        code, err = self.run_runner(self.printing(WANT))
        self.assertEqual((code, err), (0, b""))
        verdict, report, record = self.outcome()
        self.assertEqual(verdict, "pass\n")
        self.assertEqual(report, ["c_ui_probe_session %s: PASS (%d bytes, 3 lines match %s)" % (LABEL, len(WANT),
                                                                                                  self.dir / "s.out")])
        self.assertEqual((record.test_id, record.status, record.asserts), (ID, "pass", 4))
        self.assertEqual((self.dir / "r.jsonl").read_text(),
                         '{"asserts": 4, "id": "%s", "status": "pass"}\n{"summary": {"passed": 1, "total": 1}}\n' % ID)

    def test_one_byte_of_stdout_differs_and_the_first_differing_line_is_named(self):
        self.failing(self.printing(GREETING + b"ok open\nok quiT\n"),
                     "stdout line 3 differs: got b'ok quiT\\n', want b'ok quit\\n'")

    def test_a_missing_and_a_surplus_line_and_a_missing_line_feed(self):
        self.failing(self.printing(GREETING + b"ok open\n"),
                     "stdout line 3 differs: got the end of the output, want b'ok quit\\n'")
        self.failing(self.printing(WANT + b"x\n"), "stdout line 4 differs: got b'x\\n', want the end of the file")
        self.failing(self.printing(WANT[:-1]), "stdout line 3 differs: got b'ok quit', want b'ok quit\\n'")

    def test_a_long_line_is_shown_with_how_much_of_it_is_left_out(self):
        long = b"a" * 600
        self.failing(self.printing(GREETING + long + b"\n"),
                     "stdout line 2 differs: got %r (the first 512 of 601 bytes), want b'ok open\\n'" % long[:512])

    def test_anything_on_stderr_fails(self):
        self.failing(self.printing(WANT, "echo oops >&2"), "stderr is not empty (5 bytes): b'oops'")

    def test_the_exit_status_must_be_zero_and_a_signal_is_a_failure(self):
        self.failing(self.printing(WANT, "exit 1"), "exit status 1, want 0")
        self.failing(self.printing(WANT, "kill -9 $$"), "the probe was killed by signal 9")

    def test_a_session_that_does_not_end_in_quit_fails_even_with_a_matching_transcript(self):
        quit_first = "the session does not end with the line `quit` (a checked session is a clean one: exit 0)"
        for session in (b"open 0 1\n", b"open 0 1\nquit", b"open 0 1\nquit\n\n", b"quit\nopen 0 1\n", b"", b"xquit\n"):
            with self.subTest(session=session):
                self.failing(self.printing(WANT), quit_first, session=session)
        code, _ = self.run_runner(self.printing(WANT), b"quit\n", WANT)
        self.assertEqual((code, self.outcome()[0]), (0, "pass\n"))

    def test_every_failed_check_is_reported_in_order(self):
        self.failing(self.printing(GREETING, "echo e >&2; exit 3"),
                     "the session does not end with the line `quit` (a checked session is a clean one: exit 0)",
                     "exit status 3, want 0", "stderr is not empty (2 bytes): b'e'",
                     "stdout line 2 differs: got the end of the output, want b'ok open\\n'", session=b"open 0 1\n")

    def test_the_probe_sees_the_session_on_stdin_and_only_the_sanitizer_environment(self):
        probe = self.probe('cat > "%s"\nenv | sort > "%s"\nprintf "%%s" "$(cat "%s")"' % (
            self.dir / "seen.in", self.dir / "env.txt", self.dir / "stdout.bin"))
        (self.dir / "stdout.bin").write_bytes(WANT)
        (self.dir / "s.in").write_bytes(SESSION)
        env = {"ASAN_OPTIONS": "a=1", "HOME": "/nowhere", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        done = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), "--probe", str(probe), "--session",
                               str(self.dir / "s.in"), "--expected", str(self.dir / "s.in"), "--id", ID, "--label", LABEL,
                               "--out", str(self.dir / "r.jsonl"), "--report", str(self.dir / "report.txt"),
                               "--verdict", str(self.dir / "verdict")], capture_output=True, timeout=120, env=env)
        self.assertEqual(done.returncode, 0)
        self.assertEqual((self.dir / "seen.in").read_bytes(), SESSION)
        names = [line.split("=", 1)[0] for line in (self.dir / "env.txt").read_text().splitlines()]
        self.assertEqual([n for n in names if n not in ("PWD", "SHLVL", "_", "OLDPWD")], ["ASAN_OPTIONS"])

    def test_output_past_its_cap_kills_the_probe_and_fails(self):
        """stdout may exceed the expected transcript by 64 KiB, stderr may hold 64 KiB: past that the probe is killed and
        the session fails with the reason, whatever the probe would still have written (it writes forever here)."""
        loud = self.probe('cat > /dev/null\nwhile :; do printf "%%01024d" 0; done')
        self.failing(loud, "the probe wrote more than %d bytes on stdout (killed)" % (len(WANT) + 65536))
        noisy = self.probe('cat > /dev/null\nwhile :; do printf "%%01024d" 0 >&2; done')
        self.failing(noisy, "the probe wrote more than 65536 bytes on stderr (killed)")

    def test_a_probe_that_does_not_end_is_killed_at_the_deadline(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("probe_session_runner", RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        runner.TIMEOUT_S = 1
        (self.dir / "s.in").write_bytes(SESSION)
        stuck = self.probe("exec sleep 30")
        self.assertEqual(runner.run_probe(str(stuck), str(self.dir / "s.in"), len(WANT)),
                         "the probe did not end within 1 s (killed)")
        quiet = self.probe("exec 1>&- 2>&-; exec sleep 30")   # its pipes closed, it still does not exit
        self.assertEqual(runner.run_probe(str(quiet), str(self.dir / "s.in"), len(WANT)),
                         "the probe did not end within 1 s (killed)")

    def test_usage_and_io_errors_are_exit_2_and_write_nothing(self):
        code, err = self.run_runner(self.dir / "no-such-probe")
        self.assertEqual(code, 2)
        self.assertIn(b"cannot run the probe", err)
        self.assertFalse((self.dir / "verdict").exists())
        code, err = self.run_runner(self.printing(WANT), SESSION, WANT, "--surplus")
        self.assertEqual(code, 2)
        (self.dir / "s.out").unlink()
        done = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), "--probe", "x", "--session", "x", "--expected",
                               str(self.dir / "s.out"), "--id", "no id", "--label", "l", "--out", "o", "--report", "r",
                               "--verdict", "v"], capture_output=True, timeout=60, env={})
        self.assertEqual((done.returncode, done.stderr), (2, b"probe_session: bad test id 'no id'\n"))


if __name__ == "__main__":
    unittest.main()
