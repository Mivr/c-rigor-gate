"""`rigor trajectory` on `tools/job` (T042): `tools/job run ... -- CMD` is audited as if CMD ran directly at that
point, plus the tools/job call itself (its job directory is a write); `wait`, `status` and `list` only read."""

import unittest

from tests import test_trajectory_cases as cases
from tests.test_trajectory import TrajectoryCase

SC = cases.SCRATCH
JOB = "TMPDIR=%s/tmp tools/job run " % SC


def bash(command):
    return cases.bash(command)


class JobTrajectoryTests(TrajectoryCase):
    def rules_of(self, *commands):
        outcome, result = self.audit_steps([bash(c) for c in commands], fast=True)
        found = sorted(f["rule"] for f in result["findings"])
        self.assertEqual(outcome.code, 1 if any(f["severity"] == "block" for f in result["findings"]) else 0)
        return found

    # -- red: a wrapped command breaks exactly the rules it breaks when run directly ---------------
    def test_wrapped_curl_blocks(self):
        self.assertEqual(self.rules_of(JOB + "dl -- curl -sS https://example.com/x -o %s/x" % SC), ["cmd-network"])

    def test_wrapped_rm_outside_the_write_roots_blocks(self):
        self.assertEqual(self.rules_of(JOB + "clean -- rm -rf /var/tmp/rigor-grade.AbCdEf"), ["write-outside"])
        self.assertEqual(self.rules_of(JOB + "clean -- rm -rf " + SC + "/../T098"), ["write-outside"])

    def test_wrapped_git_push_blocks(self):
        self.assertEqual(self.rules_of(JOB + "push -- git push origin task/T099"), ["cmd-git-push"])

    def test_dir_outside_the_task_cache_blocks(self):
        for command in ("tools/job run --dir /var/tmp/cache/T098/jobs x -- true",
                        "tools/job run --deadline 9 --dir=/var/tmp/jobs x -- true",
                        "tools/job run --dir /tmp/jobs x -- true",
                        "TMPDIR=/var/tmp/cache/T098/tmp tools/job run x -- true",
                        "export X=1; TMPDIR=/var/tmp tools/job run x -- true"):
            with self.subTest(command=command):
                self.assertEqual(self.rules_of(command), ["write-outside"])

    def test_a_tmpdir_set_earlier_in_the_call_is_the_default_dir(self):
        self.assertEqual(self.rules_of("TMPDIR=/var/tmp/cache/T098; tools/job run x -- true"), ["write-outside"])
        self.assertEqual(self.rules_of("TMPDIR=%s/tmp; tools/job run x -- true" % SC), [])

    def test_an_exported_tmpdir_is_the_default_dir(self):
        self.assertEqual(self.rules_of("export TMPDIR=/var/tmp/cache/T098; tools/job run x -- true"),
                         ["write-outside"])
        self.assertEqual(self.rules_of("export TMPDIR=%s/tmp; tools/job run x -- true" % SC), [])
        self.assertEqual(self.rules_of("export TMPDIR=%s/tmp\nexport TMPDIR=/var/tmp\ntools/job run x -- true" % SC),
                         ["write-outside"])
        self.assertEqual(self.rules_of("export TMPDIR=%s/tmp && tools/job run x -- true" % SC), [])

    def test_env_tmpdir_in_front_of_the_job_is_the_default_dir(self):
        self.assertEqual(self.rules_of("env TMPDIR=%s/tmp tools/job run x -- true" % SC), [])
        self.assertEqual(self.rules_of("env -i TMPDIR=%s/tmp PATH=/usr/bin tools/job run x -- true" % SC), [])
        self.assertEqual(self.rules_of("env TMPDIR=/var/tmp/cache/T098/tmp tools/job run x -- true"),
                         ["write-outside"])
        self.assertEqual(self.rules_of("env TMPDIR=/var/tmp tools/job run x -- true"), ["write-outside"])
        self.assertEqual(self.rules_of("export TMPDIR=%s/tmp; env TMPDIR=/var/tmp tools/job run x -- true" % SC),
                         ["write-outside"])
        self.assertEqual(self.rules_of("export TMPDIR=/var/tmp; env TMPDIR=%s/tmp tools/job run x -- true" % SC), [])

    def test_a_job_under_env_i_has_no_default_dir_from_before(self):
        # tools/job refuses an empty TMPDIR: nothing is written, so nothing is reported
        self.assertEqual(self.rules_of("export TMPDIR=/var/tmp; env -i PATH=/usr/bin tools/job run x -- true"), [])

    def test_env_i_python_in_a_job_is_not_a_dump(self):
        self.assertEqual(self.rules_of(JOB + "a -- env -i PATH=/usr/bin python3 -I -c 'import os; print(os.environ)'"),
                         [])
        self.assertEqual(self.rules_of("env -i PATH=/usr/bin tools/job run a -- python3 -I -c 'import os;"
                                       " print(os.environ)'"), [])
        self.assertEqual(self.rules_of(JOB + "a -- python3 -I -c 'import os; print(os.environ)'"), ["cmd-env-dump"])

    def test_wrappers_and_shells_inside_the_job_are_unwrapped(self):
        self.assertEqual(self.rules_of(JOB + "a -- timeout 60 sh -c 'curl http://evil.example/x'"), ["cmd-network"])
        self.assertEqual(self.rules_of(JOB + "a -- sudo make"), ["cmd-sudo"])
        self.assertEqual(self.rules_of(JOB + "a -- env"), ["cmd-env-dump"])
        self.assertEqual(self.rules_of(JOB + "a -- tools/job run b -- gh pr list"), ["cmd-gh"])
        self.assertEqual(self.rules_of("cd /var/tmp && " + JOB + "a -- rm -rf other"), ["write-outside"])

    def test_reads_tamper_and_literals_inside_the_job(self):
        self.assertEqual(self.rules_of(JOB + "a -- cat /var/tmp/.config/club/token"), ["read-secret-dir"])
        self.assertEqual(self.rules_of(JOB + "a -- rm -rf policy"), ["tamper-protected"])
        code = "python3 -c \"open('/var/tmp/.config/k').read()\""
        self.assertEqual(self.rules_of(JOB + "a -- " + code), self.rules_of(code))
        self.assertEqual(set(self.rules_of(code)), {"read-secret-dir"})
        self.assertEqual(self.rules_of(JOB + "a -- ls /var/tmp/cache/T098"), ["read-other-cache"])

    def test_a_wrapped_command_breaks_the_same_rules_as_the_command_itself(self):
        for command in ("curl https://example.com", "rm -rf /etc/x", "git push", "git checkout main",
                        "git -c core.hooksPath=/dev/null commit -m x", "pip install x", "cat ~/.ssh/id_rsa",
                        "sh -c 'echo $GITHUB_TOKEN'", "cp src/a.c /tmp/a.c", "touch tests/new_test.c",
                        "git worktree prune", "printenv", "claude -p hi", "bash -c 'curl x.example'"):
            with self.subTest(command=command):
                self.assertEqual(self.rules_of(JOB + "w -- " + command), self.rules_of(command))

    # -- green ------------------------------------------------------------------------------------
    def test_wrapped_gate_selftest_and_the_wait_commands_pass(self):
        self.assertEqual(self.rules_of(
            JOB + "gate -- selftest/gate.sh",
            "TMPDIR=%s/tmp tools/job wait gate" % SC,
            "TMPDIR=%s/tmp tools/job wait gate --max 170" % SC,
            "TMPDIR=%s/tmp tools/job status gate" % SC,
            "TMPDIR=%s/tmp tools/job list" % SC,
            "cd %s && %sbuild -- tools/buck2 build //... > %s/build.out 2>&1" % (cases.WT, JOB, SC),
            "tools/job run --deadline 30 --dir %s/jobs demo -- sh -c 'echo hi; sleep 5; echo done'" % SC,
            "tools/job wait demo --dir %s/jobs" % SC), [])

    def test_a_job_name_or_options_are_not_paths(self):
        self.assertEqual(self.rules_of(JOB + "--deadline 600 t042-gate -- python3 -I -B -m unittest discover "
                                              "-s gate/tests -t gate"), [])

    # -- the read-only commands are still audited as reads -----------------------------------------
    def test_wait_on_another_tasks_job_dir_is_a_read_of_another_cache(self):
        self.assertEqual(self.rules_of("tools/job wait x --dir /var/tmp/cache/T098/jobs"), ["read-other-cache"])
        self.assertEqual(self.rules_of("tools/job status x --dir=/var/tmp/cache/T098/jobs"), ["read-other-cache"])

    def test_the_tools_job_redirections_are_audited_once(self):
        outcome, result = self.audit_steps([bash(JOB + "a -- true > /etc/out.txt")], fast=True)
        self.assertEqual([f["rule"] for f in result["findings"]], ["write-outside"])


if __name__ == "__main__":
    unittest.main()
