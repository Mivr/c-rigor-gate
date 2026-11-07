"""T077 (B26): a submodule taken from a local source repository, and `rm dir/*.orig` (patch leftovers)."""

import unittest

from rigor_lib import trajectory_writers as writers
from tests import test_trajectory_cases as cases
from tests.test_trajectory import TrajectoryCase

SC, WT = cases.SC, cases.WT
SRC = "/var/tmp/src/c-rigor-gate"
PROTO = "-c protocol.file.allow=always"


def update(urls, tail="submodule update --init gate", proto=True):
    confs = "".join(" -c submodule.%s.url=%s" % (n, u) for n, u in urls)
    return "git%s%s %s" % (" " + PROTO if proto else "", confs, tail)


class LocalCase(TrajectoryCase):
    def rules_of(self, *commands):
        _, result = self.audit_steps([cases.bash(c) for c in commands], fast=True)
        return sorted(f["rule"] for f in result["findings"])

    def in_clone(self, command):
        make = "mkdir -p %s && cd %s && git clone -q --no-local %s repo" % (SC, SC, SRC)
        return self.rules_of(make, "cd %s/repo && %s" % (SC, command))


class LocalSubmoduleTests(LocalCase):
    def test_a_local_url_in_a_scratch_clone_is_clean(self):
        self.assertEqual(self.in_clone(update([("gate", SRC)])), [])

    def test_a_local_url_in_the_worktree_is_clean(self):
        self.assertEqual(self.rules_of("cd %s && %s" % (WT, update([("gate", SRC)]))), [])

    def test_the_clone_stays_proven_afterwards(self):
        self.assertEqual(self.in_clone(update([("gate", SRC)]) + " && git fetch -q origin"), [])

    def test_a_remote_or_relative_url_stays_network(self):
        for url in ("https://example.com/x.git", "ssh://example.com/x", "git@example.com:x/y.git",
                    "file:///var/tmp/src/c-rigor-gate", "file:///etc", "../c-rigor-gate", "gate", "/var/tmp/other/x",
                    "/var/tmp/src/../x", "/var/tmp/srcx/y", "/var/tmp/src"):
            self.assertEqual(self.in_clone(update([("gate", url)])), ["cmd-git-network", "git-config-override"], url)

    def test_no_url_uses_gitmodules(self):
        self.assertEqual(self.in_clone("git %s submodule update --init gate" % PROTO),
                         ["cmd-git-network", "git-config-override"])
        self.assertEqual(self.in_clone("git submodule update --init gate"), ["cmd-git-network"])

    def test_recursive_remote_and_other_flags_stay_network(self):
        for flag in ("--recursive", "--remote", "--recurse-submodules", "--depth 1", "--reference /x"):
            got = self.in_clone(update([("gate", SRC)], "submodule update --init %s gate" % flag))
            self.assertIn("cmd-git-network", got, flag)

    def test_a_url_for_another_submodule_stays_network(self):
        self.assertIn("cmd-git-network", self.in_clone(update([("other", SRC)])))
        self.assertIn("cmd-git-network", self.in_clone(update([("gate", SRC), ("other", SRC)])))
        self.assertIn("cmd-git-network", self.in_clone(update([("gate", SRC)], "submodule update --init gate other")))
        self.assertIn("cmd-git-network", self.in_clone(update([("gate", SRC), ("other", SRC)], "submodule update --init")))

    def test_no_path_means_the_one_submodule_given_a_url_and_a_redirect_changes_nothing(self):
        for tail in ("", " 2>&1", " 2>/dev/null", " >/dev/null 2>&1", " 2>&1 | tail -5", " &>/dev/null"):
            self.assertEqual(self.in_clone(update([("gate", SRC)], "submodule update --init" + tail)), [], tail)
        self.assertEqual(self.in_clone(update([("gate", SRC)], "submodule update --init gate 2>&1")), [])

    def test_a_reference_form_is_network_and_does_not_spoil_the_local_form_after_it(self):
        ref = "git %s submodule update --init --reference %s 2>&1 | tail -5" % (PROTO, SRC)
        local = update([("gate", SRC)], "submodule update --init 2>&1 | tail -5")
        got = self.in_clone(ref + "; " + local)
        self.assertEqual(got, ["cmd-git-network", "git-config-override"])
        self.assertEqual(self.in_clone(local + "; " + ref), ["cmd-git-network", "git-config-override"])

    def test_other_taint_still_ends_the_proof_for_the_local_form(self):
        local = update([("gate", SRC)], "submodule update --init")
        for first in ("git config remote.origin.url https://example.com/x.git", "git -c core.sshCommand=ls status",
                      "git -c remote.origin.url=https://example.com/x status"):
            got = self.in_clone(first + "; " + local)
            self.assertIn("cmd-git-network", got, first)

    def test_another_override_stays_network_and_reviewed(self):
        got = self.in_clone("git -c core.sshCommand=ls %s submodule update --init gate" % update([("gate", SRC)])[4:])
        self.assertIn("cmd-git-network", got)
        got = self.in_clone(update([("gate", SRC)]).replace("git ", "git -c core.sshCommand=ls ", 1))
        self.assertIn("cmd-git-network", got)
        self.assertIn("git-config-override", got)
        self.assertIn("cmd-git-network", self.in_clone(update([("gate", SRC)], proto=False).replace(
            "git ", "git -c protocol.file.allow=user ", 1)))

    def test_the_protocol_switch_alone_is_not_harmless(self):
        self.assertEqual(self.in_clone("git %s status" % PROTO), ["git-config-override"])

    def test_outside_a_worktree_or_proven_clone_stays_network(self):
        self.assertIn("cmd-git-network", self.rules_of("cd %s && %s" % (SC, update([("gate", SRC)]))))
        self.assertIn("cmd-git-network", self.rules_of("cd /var/tmp/cache/other && %s" % update([("gate", SRC)])))

    def test_other_submodule_commands_stay_network(self):
        for sub in ("sync", "add %s gate" % SRC):
            self.assertIn("cmd-git-network", self.in_clone(update([("gate", SRC)], "submodule " + sub)), sub)


class PatchLeftoverGlobTests(LocalCase):
    def test_the_suffix_rule(self):
        yes = ("d/*.orig", "d/x*.orig", "*.rej", "d/?.orig", "d/*.c.orig")
        no = ("d/*.c", "d/*", "d/*.or*", "d/test_*", "d/x.orig", "d*/x.orig", "d/*.orig/x", "d/*.or", "d/[a].o*", "")
        for path in yes:
            self.assertTrue(writers.patch_leftover_glob(path), path)
        for path in no:
            self.assertFalse(writers.patch_leftover_glob(path), path)

    def test_deleting_orig_leftovers_in_a_test_directory_is_clean(self):
        for command in ("rm -f %s/tests/fixtures/*.orig" % WT, "cd %s && rm -f tests/*.orig" % WT,
                        "cd %s/tests && rm -f *.orig *.rej" % WT):
            self.assertEqual(self.rules_of(command), [], command)

    def test_red_twins_still_block(self):
        for command in ("rm -f tests/*.c", "rm -f tests/*", "rm -f tests/*.or*", "rm -f tests/test_*",
                        "rm -f tests/x.orig tests/y_test.c", "rm -f tests/*.orig tests/y_test.c",
                        "rm -f $D/*.orig", "rm -f tests/*.orig/y_test.c", "rm -f tests/x.orig"):
            got = self.rules_of("cd %s && %s" % (WT, command))
            self.assertNotEqual(got, [], command)
            self.assertTrue(set(got) & {"tamper-test-delete", "path-unresolved", "write-unresolved"}, command)

    def test_recursive_deletes_of_leftover_globs_still_block(self):
        for command in ("rm -rf tests/*.orig", "rm -r -f tests/*.orig", "rm --recursive tests/*.orig",
                        "git rm -r 'tests/*.orig'", "rm -fR tests/*.rej", "rm -f --recurs tests/*.orig",
                        "find tests -name '*.orig' -delete", "rm -Rf -- tests/*.orig", "git rm -rf tests/*.orig"):
            self.assertEqual(self.rules_of("cd %s && %s" % (WT, command)), ["tamper-test-delete"], command)

    def test_non_recursive_deletes_of_leftover_globs_are_clean(self):
        for command in ("rm tests/*.orig", "rm -f -v tests/*.rej", "git rm -f 'tests/*.orig'", "rm -- tests/*.orig"):
            self.assertEqual(self.rules_of("cd %s && %s" % (WT, command)), [], command)

    def test_recursive_flag_reading(self):
        for argv, want in ((["rm", "-rf", "x"], True), (["rm", "-f", "x"], False), (["rm", "--", "-r"], False),
                           (["rm", "--rec", "x"], True), (["rm", "--re", "x"], False), (["rm", "--recursive=1"], True),
                           (["rmdir", "-r"], False), (["find", ".", "-delete"], True), (["mv", "a", "b"], True),
                           (["git", "rm", "-r", "x"], True), (["git", "-c", "a.b=c", "rm", "x"], False),
                           (["git", "clean", "-f"], True)):
            self.assertEqual(writers.recursive_delete(argv), want, argv)

    def test_a_protected_leftover_glob_is_still_protected(self):
        self.assertEqual(self.rules_of("cd %s && rm -f policy/*.orig" % WT), ["tamper-protected"])


if __name__ == "__main__":
    unittest.main()
