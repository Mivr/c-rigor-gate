"""Tests for tools/job (T042): background jobs that an agent waits on with one blocking call.

Every test drives the real executable as a subprocess. Job directories must be inside /var/tmp/cache/, so
each test works in a fresh directory under $TMPDIR when that is there, else under /var/tmp/cache/.
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from rigor_lib import trajectory_cmds as cmds

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "job"
CACHE = "/var/tmp/cache"

_loader = importlib.machinery.SourceFileLoader("job_tool", str(TOOL))
_spec = importlib.util.spec_from_loader("job_tool", _loader)
job_tool = importlib.util.module_from_spec(_spec)
_loader.exec_module(job_tool)

ENV_DIGEST = ("import hashlib, os; print('env', hashlib.sha256(repr(sorted(os.environ.items())).encode()).hexdigest()); "
              "print('cwd', os.getcwd())")


def scratch_base():
    tmp = os.path.realpath(os.environ.get("TMPDIR", "") or "/nonexistent")
    if tmp.startswith(CACHE + "/") and os.path.isdir(tmp):
        return tmp
    return CACHE


class JobCase(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="rigor-job-test.", dir=scratch_base()))
        self.jobs = os.path.join(self.base, "jobs")
        self.env = dict(os.environ, TMPDIR=self.base)

    def tearDown(self):
        for record in Path(self.base).glob("**/job.json"):
            if record.with_name("exit.json").exists():
                continue  # finished: its pids may belong to someone else by now
            data = json.loads(record.read_text(encoding="utf-8"))
            for pid, kill in ((data.get("pid"), os.killpg), (data.get("runner_pid"), os.kill)):
                if isinstance(pid, int):
                    try:
                        kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
        shutil.rmtree(self.base, ignore_errors=True)

    def job(self, *args, env=None, cwd=None, timeout=60):
        done = subprocess.run([str(TOOL)] + [str(a) for a in args], env=self.env if env is None else env,
                              cwd=cwd or self.base, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout, done.stderr

    def run_ok(self, name, *cmd, deadline=None):
        extra = ["--deadline", str(deadline)] if deadline else []
        code, out, err = self.job("run", *extra, name, "--", *cmd)
        self.assertEqual(code, 0, msg=err)
        return out

    def record(self, name):
        return json.loads(Path(self.jobs, name, "job.json").read_text(encoding="utf-8"))


class RunAndWaitTests(JobCase):
    def test_demo_runs_detached_and_wait_prints_the_exit_and_the_log(self):
        out = self.run_ok("demo", "sh", "-c", "echo hi; sleep 1; echo done", deadline=30)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("demo", out)
        self.assertIn("pid %d" % self.record("demo")["pid"], out)
        self.assertIn("sh -c 'echo hi; sleep 1; echo done'", out)
        code, out, _ = self.job("wait", "demo")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertRegex(lines[0], r"\Aexit 0 after [0-9]+ s\Z")
        self.assertEqual(lines[-2:], ["hi", "done"])

    def test_run_returns_at_once_and_does_not_hold_the_callers_output(self):
        started = time.monotonic()
        self.run_ok("long", "sleep", "120")
        self.assertLess(time.monotonic() - started, 60)  # had run kept its stdout pipe, this would take 120 s
        code, out, _ = self.job("wait", "long", "--max", "1")
        self.assertEqual(code, 124)
        self.assertRegex(out, r"\Arunning [0-9]+s\n\Z")  # exactly one status line

    def test_status_is_wait_with_max_zero(self):
        self.run_ok("s", "sleep", "30")
        for args in (["status", "s"], ["wait", "s", "--max", "0"]):
            with self.subTest(args=args):
                code, out, _ = self.job(*args)
                self.assertEqual(code, 124)
                self.assertRegex(out, r"\Arunning [0-9]+s\n\Z")

    def test_the_exit_code_of_the_job_is_the_exit_code_of_wait(self):
        self.run_ok("seven", "sh", "-c", "echo bye; exit 7")
        code, out, _ = self.job("wait", "seven")
        self.assertEqual(code, 7)
        self.assertTrue(out.startswith("exit 7 after "))
        self.assertEqual(self.job("status", "seven")[0], 7)

    def test_a_job_ended_by_a_signal_reports_128_plus_the_signal(self):
        self.run_ok("sig", "sh", "-c", "kill -TERM $$")
        code, out, _ = self.job("wait", "sig")
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertIn("(signal %d)" % signal.SIGTERM, out.splitlines()[0])

    def test_the_deadline_kills_the_whole_process_group(self):
        self.run_ok("slow", "sh", "-c", "sleep 60 & sleep 60; wait", deadline=1)
        code, out, _ = self.job("wait", "slow")
        self.assertRegex(out.splitlines()[0], r"\AKILLED after [0-9]+ s \(deadline 1s, exit 143\)\Z")
        self.assertEqual(code, 128 + signal.SIGTERM)
        with self.assertRaises(ProcessLookupError):
            os.killpg(self.record("slow")["pid"], 0)
        exit_record = json.loads(Path(self.jobs, "slow", "exit.json").read_text(encoding="utf-8"))
        self.assertTrue(exit_record["killed"])

    def test_a_job_that_ignores_sigterm_is_killed(self):
        self.run_ok("stubborn", "sh", "-c", "trap '' TERM; sleep 60", deadline=1)
        code, out, _ = self.job("wait", "stubborn")
        self.assertEqual(code, 128 + signal.SIGKILL)
        self.assertTrue(out.startswith("KILLED after "))

    def test_the_log_tail_is_the_last_30_lines_without_ansi_escapes(self):
        script = "for i in $(seq 1 40); do printf '\\033[1;31mline %s\\033[0m\\n' $i; done; printf 'x\\rprogress 9\\r\\n'"
        self.run_ok("color", "sh", "-c", script)
        code, out, _ = self.job("wait", "color")
        tail = out.splitlines()[2:]
        self.assertEqual(code, 0)
        self.assertEqual(tail, ["line %d" % i for i in range(12, 41)] + ["progress 9"])
        self.assertNotIn("\x1b", out)

    def test_a_running_name_is_refused_and_a_finished_one_is_replaced(self):
        self.run_ok("once", "sleep", "30")
        code, _, err = self.job("run", "once", "--", "true")
        self.assertEqual(code, 2)
        self.assertIn("still running", err)
        self.run_ok("twice", "sh", "-c", "echo first")
        self.assertEqual(self.job("wait", "twice")[0], 0)
        self.run_ok("twice", "sh", "-c", "echo second")
        code, out, _ = self.job("wait", "twice")
        self.assertEqual(out.splitlines()[-1], "second")
        self.assertNotIn("first", out)

    def test_a_job_whose_runner_died_is_lost_not_running(self):
        self.run_ok("orphan", "sleep", "30")
        os.kill(self.record("orphan")["runner_pid"], signal.SIGKILL)
        code, out, _ = self.job("wait", "orphan", "--max", "20")
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("LOST after "), out)
        self.assertEqual(self.job("status", "orphan")[0], 2)

    def test_list_shows_every_job_with_its_state_and_argv(self):
        self.run_ok("a", "sh", "-c", "exit 3")
        self.job("wait", "a")
        self.run_ok("b", "sleep", "30")
        code, out, _ = self.job("list")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in lines], ["a", "b"])
        self.assertIn("exit 3 after", lines[0])
        self.assertIn("running", lines[1])
        self.assertTrue(lines[1].endswith("sleep 30"))

    def test_a_command_that_cannot_start_is_an_error_and_records_127(self):
        code, _, err = self.job("run", "missing", "--", os.path.join(self.base, "no-such-program"))
        self.assertEqual(code, 2)
        self.assertIn("did not start", err)
        self.assertEqual(self.job("wait", "missing")[0], 127)


class ExecutionTests(JobCase):
    def test_cwd_and_environment_are_the_callers_unchanged(self):
        here = os.path.join(self.base, "sub dir")
        os.mkdir(here)
        env = dict(self.env, JOB_TEST_MARK="x y", PATH=os.environ.get("PATH", ""))
        code, _, err = self.job("run", "env", "--", sys.executable, "-I", "-c", ENV_DIGEST, env=env, cwd=here)
        self.assertEqual(code, 0, msg=err)
        _, out, _ = self.job("wait", "env")
        digest = hashlib.sha256(repr(sorted(env.items())).encode()).hexdigest()
        self.assertIn("env " + digest, out.splitlines())
        self.assertIn("cwd " + here, out.splitlines())
        self.assertEqual(self.record("env")["cwd"], here)

    def test_stdin_is_dev_null_and_the_job_has_its_own_session(self):
        code_text = "import os, sys; print(repr(sys.stdin.read())); print(os.getsid(0) == os.getpid())"
        self.run_ok("io", sys.executable, "-I", "-c", code_text)
        _, out, _ = self.job("wait", "io")
        self.assertEqual(out.splitlines()[-2:], ["''", "True"])

    def test_the_command_is_an_argv_never_a_shell_string(self):
        self.run_ok("argv", "echo", "$HOME;", "a  b", "`id`")
        _, out, _ = self.job("wait", "argv")
        self.assertEqual(out.splitlines()[-1], "$HOME; a  b `id`")
        self.assertEqual(self.record("argv")["argv"], ["echo", "$HOME;", "a  b", "`id`"])


class DirectoryTests(JobCase):
    def refused(self, *args, env=None):
        code, out, err = self.job(*args, env=env)
        self.assertEqual(code, 2, msg=out + err)
        self.assertIn("tools/job: error:", err)
        return err

    def test_dir_defaults_to_tmpdir_jobs(self):
        self.run_ok("d", "true")
        self.assertTrue(Path(self.base, "jobs", "d", "log").is_file())

    def test_without_tmpdir_or_dir_it_refuses(self):
        env = {k: v for k, v in self.env.items() if k != "TMPDIR"}
        self.assertIn("TMPDIR is not set", self.refused("run", "x", "--", "true", env=env))
        self.assertIn("TMPDIR is not set", self.refused("list", env=env))

    def test_a_dir_outside_the_cache_root_is_refused(self):
        for directory in ("/var/tmp/jobs-x", "/tmp/jobs", CACHE, CACHE + "/../jobs", CACHE + "/./../tmp/jobs"):
            with self.subTest(directory=directory):
                self.assertIn("not inside", self.refused("run", "--dir", directory, "x", "--", "true"))
        self.assertIn("not inside", self.refused("run", "x", "--", "true", env=dict(self.env, TMPDIR="/var/tmp")))

    def test_a_symlink_anywhere_in_the_path_is_refused(self):
        os.mkdir(os.path.join(self.base, "real"))
        os.symlink(os.path.join(self.base, "real"), os.path.join(self.base, "link"))
        for directory in (os.path.join(self.base, "link"), os.path.join(self.base, "link", "jobs")):
            with self.subTest(directory=directory):
                self.assertIn("symlink", self.refused("run", "--dir", directory, "x", "--", "true"))
        os.makedirs(self.jobs)
        os.symlink(os.path.join(self.base, "real"), os.path.join(self.jobs, "named"))
        self.assertIn("symlink", self.refused("run", "named", "--", "true"))

    def test_an_explicit_dir_inside_the_cache_is_used(self):
        other = os.path.join(self.base, "elsewhere")
        code, _, err = self.job("run", "--dir=" + other, "e", "--", "true")
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.job("wait", "e", "--dir", other)[0], 0)
        self.refused("wait", "e")  # not in the default directory


class UsageTests(JobCase):
    def test_bad_usage_is_exit_2(self):
        for args in (["run", "x"], ["run", "x", "--"], ["run", "--", "true"], ["run", "a", "b", "--", "true"],
                     ["run", "--deadline", "0", "x", "--", "true"], ["run", "--deadline", "1.5", "x", "--", "true"],
                     ["run", "--frob", "x", "--", "true"], ["run", "../x", "--", "true"], ["wait"],
                     ["wait", "x", "--max", "171"], ["wait", "x", "--max", "-1"], ["status", "x", "--max", "1"],
                     ["frob"], [], ["wait", "never-ran"]):
            with self.subTest(args=args):
                self.assertEqual(self.job(*args)[0], 2)

    def test_the_wait_default_fits_inside_the_bash_tool_default_timeout(self):
        self.assertLessEqual(job_tool.WAIT_DEFAULT, 120 - 10)
        self.assertLess(job_tool.WAIT_LIMIT, 180)


class TrajectoryMirrorTests(unittest.TestCase):
    """rigor_lib.trajectory_cmds.job_run must read `run` arguments exactly as tools/job does."""

    ARGVS = (
        ["run", "n", "--", "curl", "x"],
        ["run", "--deadline", "5", "--dir", "/var/tmp/cache/T1/j", "n", "--", "rm", "-rf", "/"],
        ["run", "--dir=/var/tmp/cache/T1/j", "n", "--", "git", "push"],
        ["run", "--dir", "--", "n", "--", "true"],
        ["run", "n", "--deadline", "3", "--", "sh", "-c", "a -- b"],
        ["run", "n", "--", "--", "x"],
    )

    def test_the_audit_and_the_tool_agree_on_dir_and_command(self):
        for args in self.ARGVS:
            with self.subTest(args=args):
                _, directory, _, command = job_tool.parse_run(args[1:])
                argv = ["tools/job"] + args
                dir_index, cut = cmds.job_run(argv)
                self.assertEqual(argv[cut + 1:], command)
                shown = None if dir_index is None else argv[dir_index]
                self.assertEqual(shown if shown is None or not shown.startswith("--dir=") else shown[6:], directory)

    def test_only_run_with_a_command_is_a_wrapper(self):
        for argv in (["tools/job", "wait", "n"], ["tools/job", "status", "n"], ["tools/job", "list"],
                     ["tools/job", "run", "n"], ["tools/job", "run", "n", "--"], ["tools/jobs", "run", "n", "--", "x"]):
            with self.subTest(argv=argv):
                self.assertIsNone(cmds.job_run(argv))


if __name__ == "__main__":
    unittest.main()
