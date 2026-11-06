"""Tests for `rigor contract`."""

import os

from tests.helpers import Repo, TempDirTestCase, read_json, run_rigor

SHA_A = "a" * 40


class ContractCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("src/a.c", "int a;\n")
        self.repo.write("src/sub/b.c", "int b;\n")
        self.repo.write("gate/rules.bzl", "# rules\n")
        self.repo.write("docs/x.md", "x\n")
        self.repo.write("tool.sh", "#!/bin/sh\n")
        self.repo.symlink("src/link", "a.c")
        self.base = self.repo.commit("base")
        self.repo.branch("task")

    def contract_file(self, allowed, protected=None, max_files=None, extra=""):
        lines = ['id = "T999"', "allowed = [%s]" % ", ".join('"%s"' % g for g in allowed)]
        if protected is not None:
            lines.append("protected = [%s]" % ", ".join('"%s"' % g for g in protected))
        if max_files is not None:
            lines.append("max_files = %d" % max_files)
        path = self.tmp / "contract.toml"
        path.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
        return path

    def grade(self, allowed, protected=None, max_files=None, base=None, head=None):
        head = head or self.repo.commit("work")
        out = self.tmp / "out.json"
        outcome = run_rigor([
            "contract", "--repo", self.repo.root, "--base", base or self.base, "--head", head,
            "--contract", self.contract_file(allowed, protected, max_files), "--out", out])
        result = read_json(out) if out.exists() else None
        return outcome, result

    def rules(self, result):
        return sorted((f["rule"], f.get("path")) for f in result["findings"])

    def assertPass(self, allowed, **kw):
        outcome, result = self.grade(allowed, **kw)
        self.assertExit(outcome, 0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["findings"], [])
        return result

    def assertFails(self, allowed, expected, **kw):
        outcome, result = self.grade(allowed, **kw)
        self.assertExit(outcome, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(self.rules(result), sorted(expected))
        return result


class ContractGreenTests(ContractCase):
    def test_modify_inside_allowed(self):
        self.repo.write("src/a.c", "int a2;\n")
        self.assertPass(["src/**"])

    def test_add_nested_file_inside_allowed(self):
        self.repo.write("src/new/deep/c.c", "int c;\n")
        self.assertPass(["src/**"])

    def test_filename_with_spaces_inside_allowed(self):
        self.repo.write("src/has space.c", "int s;\n")
        self.assertPass(["src/**"])

    def test_filename_with_newline_inside_allowed(self):
        self.repo.write("src/we\nird.c", "int w;\n")
        self.assertPass(["src/**"])

    def test_non_utf8_filename_inside_allowed(self):
        self.repo.write(b"src/bad\xff.c", "int w;\n")
        self.assertPass(["src/**"])

    def test_delete_inside_allowed(self):
        self.repo.remove("src/sub/b.c")
        self.assertPass(["src/**"])

    def test_mode_change_inside_allowed(self):
        os.chmod(self.repo.abs("src/a.c"), 0o755)
        self.assertPass(["src/**"])

    def test_empty_change_passes(self):
        self.assertPass(["src/**"])

    def test_max_files_equal_to_count_passes(self):
        self.repo.write("src/a.c", "1\n")
        self.repo.write("src/sub/b.c", "2\n")
        self.assertPass(["src/**"], max_files=2)

    def test_several_allowed_globs(self):
        self.repo.write("src/a.c", "1\n")
        self.repo.write("docs/x.md", "2\n")
        self.assertPass(["src/**", "docs/*.md"])

    def test_protected_that_does_not_match_changes_is_fine(self):
        self.repo.write("src/a.c", "1\n")
        self.assertPass(["src/**"], protected=["gate/**"])

    def test_changes_only_on_base_side_are_not_attributed(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("tool.sh", "#!/bin/sh\necho main\n")
        main_tip = self.repo.commit("main moves on")
        self.repo.git("checkout", "-q", "task")
        self.repo.write("src/a.c", "1\n")
        self.assertPass(["src/**"], base=main_tip)

    def test_findings_are_identical_on_rerun(self):
        self.repo.write("tool.sh", "x\n")
        self.repo.write("zzz.txt", "x\n")
        head = self.repo.commit("work")
        _, first = self.grade(["src/**"], head=head)
        _, second = self.grade(["src/**"], head=head)
        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(len(first["findings"]), 2)


class ContractHostileConfigTests(ContractCase):
    """Settings inside the graded repository's own git config must not change the verdict."""

    def hostile_config(self):
        self.repo.git("config", "diff.ignoreSubmodules", "all")
        self.repo.git("config", "diff.renames", "copies")
        self.repo.git("config", "diff.external", "/bin/false")
        self.repo.git("config", "core.attributesFile", "/dev/null")

    def test_submodule_still_flagged_when_config_ignores_submodules(self):
        self.hostile_config()
        self.repo.add_gitlink("src/vendor", "b" * 40)
        head = self.repo.commit("add gitlink", add_all=False)
        outcome, result = self.grade(["src/**"], head=head)
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("submodule", "src/vendor")])

    def test_rename_still_reports_both_names_when_config_detects_copies(self):
        self.hostile_config()
        self.repo.git("mv", "docs/x.md", "docs/y.md")
        outcome, result = self.grade(["src/**"])
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("outside-allowed", "docs/x.md"),
                                              ("outside-allowed", "docs/y.md")])


class ContractRedTests(ContractCase):
    def test_modify_outside_allowed(self):
        self.repo.write("tool.sh", "changed\n")
        self.assertFails(["src/**"], [("outside-allowed", "tool.sh")])

    def test_add_outside_allowed(self):
        self.repo.write("new.txt", "x\n")
        self.assertFails(["src/**"], [("outside-allowed", "new.txt")])

    def test_delete_outside_allowed(self):
        self.repo.remove("docs/x.md")
        self.assertFails(["src/**"], [("outside-allowed", "docs/x.md")])

    def test_protected_wins_over_allowed_on_modify(self):
        self.repo.write("src/a.c", "changed\n")
        self.assertFails(["src/**"], [("protected", "src/a.c")], protected=["src/a.c"])

    def test_delete_of_protected_file(self):
        self.repo.remove("gate/rules.bzl")
        self.assertFails(["**"], [("protected", "gate/rules.bzl")], protected=["gate/**"])

    def test_rename_out_of_allowed_reports_new_name(self):
        self.repo.git("mv", "src/a.c", "other.c")
        self.assertFails(["src/**"], [("outside-allowed", "other.c")])

    def test_rename_out_of_protected_reports_old_name(self):
        self.repo.git("mv", "gate/rules.bzl", "src/rules.bzl")
        self.assertFails(["src/**", "gate/**"], [("protected", "gate/rules.bzl")],
                         protected=["gate/**"])

    def test_rename_into_protected_reports_new_name(self):
        self.repo.git("mv", "src/a.c", "gate/a.c")
        self.assertFails(["src/**", "gate/**"], [("protected", "gate/a.c")],
                         protected=["gate/**"])

    def test_rename_outside_to_outside_reports_both_names(self):
        self.repo.git("mv", "docs/x.md", "docs/y.md")
        self.assertFails(["src/**"], [("outside-allowed", "docs/x.md"),
                                      ("outside-allowed", "docs/y.md")])

    def test_mode_change_outside_allowed(self):
        os.chmod(self.repo.abs("tool.sh"), 0o755)
        self.assertFails(["src/**"], [("outside-allowed", "tool.sh")])

    def test_newline_in_name_cannot_hide_an_outside_path(self):
        self.repo.write("evil\nsrc/a.c", "x\n")
        result = self.assertFails(["src/**"], [("outside-allowed", "evil\nsrc/a.c")])
        self.assertEqual(len(result["findings"]), 1)

    def test_non_utf8_name_outside_allowed_is_reported_escaped(self):
        self.repo.write(b"bad\xff.c", "x\n")
        self.assertFails(["src/**"], [("outside-allowed", "bad\\xff.c")])

    def test_symlink_into_protected_is_refused(self):
        self.repo.symlink("src/sneaky", "../gate/rules.bzl")
        self.assertFails(["src/**"], [("symlink", "src/sneaky")], protected=["gate/**"])

    def test_symlink_pointing_outside_repo_is_refused(self):
        self.repo.symlink("src/abs", "/etc/passwd")
        self.assertFails(["src/**"], [("symlink", "src/abs")])

    def test_modifying_an_existing_symlink_is_refused(self):
        self.repo.remove("src/link")
        self.repo.symlink("src/link", "../gate/rules.bzl")
        self.assertFails(["src/**"], [("symlink", "src/link")])

    def test_deleting_an_existing_symlink_is_refused(self):
        self.repo.remove("src/link")
        self.assertFails(["src/**"], [("symlink", "src/link")])

    def test_replacing_a_file_with_a_symlink_is_refused(self):
        self.repo.remove("src/a.c")
        self.repo.symlink("src/a.c", "sub/b.c")
        self.assertFails(["src/**"], [("symlink", "src/a.c")])

    def test_new_submodule_is_refused(self):
        self.repo.add_gitlink("src/vendor", "b" * 40)
        self.repo.commit("add gitlink", add_all=False)
        outcome, result = self.grade(["src/**"], head=self.repo.git("rev-parse", "HEAD"))
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("submodule", "src/vendor")])

    def test_submodule_bump_is_refused(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.add_gitlink("src/vendor", "b" * 40)
        new_base = self.repo.commit("gitlink on main", add_all=False)
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.add_gitlink("src/vendor", "c" * 40)
        head = self.repo.commit("bump", add_all=False)
        outcome, result = self.grade(["src/**"], base=new_base, head=head)
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("submodule", "src/vendor")])

    def test_too_many_files(self):
        self.repo.write("src/a.c", "1\n")
        self.repo.write("src/sub/b.c", "2\n")
        outcome, result = self.grade(["src/**"], max_files=1)
        self.assertExit(outcome, 1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["too-many-files"])
        self.assertEqual(result["findings"][0]["count"], 2)
        self.assertEqual(result["findings"][0]["max"], 1)

    def test_rename_counts_as_two_files_for_max_files(self):
        self.repo.git("mv", "src/a.c", "src/z.c")
        outcome, result = self.grade(["src/**"], max_files=1)
        self.assertExit(outcome, 1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["too-many-files"])

    def test_approval_lookalike_file_in_repo_is_refused(self):
        name = "src/" + "ab" * 32 + ".json"
        self.repo.write(name, "{}\n")
        self.assertFails(["src/**"], [("approval-in-repo", name)])

    def test_approval_signature_lookalike_in_repo_is_refused(self):
        name = "src/" + "ab" * 32 + ".json.sig"
        self.repo.write(name, "x\n")
        self.assertFails(["src/**"], [("approval-in-repo", name)])

    def test_approval_lookalike_already_in_base_is_still_refused(self):
        self.repo.git("checkout", "-q", "main")
        name = "docs/" + "cd" * 32 + ".json"
        self.repo.write(name, "{}\n")
        new_base = self.repo.commit("lookalike on main")
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.write("src/a.c", "1\n")
        head = self.repo.commit("work")
        outcome, result = self.grade(["src/**"], base=new_base, head=head)
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), [("approval-in-repo", name)])


class ContractErrorTests(ContractCase):
    def run_contract(self, contract_text=None, base=None, head=None, repo=None, path=None):
        contract = self.tmp / "c.toml"
        if contract_text is not None:
            contract.write_text(contract_text, encoding="utf-8")
        return run_rigor([
            "contract", "--repo", repo or self.repo.root, "--base", base or self.base,
            "--head", head or "task", "--contract", contract], path=path)

    GOOD = 'id = "T"\nallowed = ["src/**"]\n'

    def test_baseline_good_contract_passes(self):
        self.assertExit(self.run_contract(self.GOOD), 0)

    def test_unknown_contract_key_is_exit_2(self):
        self.assertExit(self.run_contract(self.GOOD + 'allow_all = true\n'), 2)

    def test_missing_id_is_exit_2(self):
        self.assertExit(self.run_contract('allowed = ["src/**"]\n'), 2)

    def test_missing_allowed_is_exit_2(self):
        self.assertExit(self.run_contract('id = "T"\n'), 2)

    def test_wrong_types_are_exit_2(self):
        for text in ('id = 1\nallowed = ["a"]\n',
                     'id = "T"\nallowed = "src/**"\n',
                     'id = "T"\nallowed = [1]\n',
                     'id = "T"\nallowed = ["a"]\nprotected = "x"\n',
                     'id = "T"\nallowed = ["a"]\nmax_files = "3"\n',
                     'id = "T"\nallowed = ["a"]\nmax_files = true\n',
                     'id = "T"\nallowed = ["a"]\nmax_files = -1\n'):
            self.assertExit(self.run_contract(text), 2)

    def test_bad_glob_is_exit_2(self):
        self.assertExit(self.run_contract('id = "T"\nallowed = ["../x"]\n'), 2)
        self.assertExit(self.run_contract('id = "T"\nallowed = ["a"]\nprotected = ["a**b"]\n'), 2)

    def test_malformed_toml_is_exit_2(self):
        self.assertExit(self.run_contract("this is = = not toml"), 2)

    def test_missing_contract_file_is_exit_2(self):
        self.assertExit(self.run_contract(None), 2)

    def test_unknown_revision_is_exit_2(self):
        self.assertExit(self.run_contract(self.GOOD, base="no-such-rev"), 2)

    def test_option_like_revision_is_exit_2(self):
        self.assertExit(self.run_contract(self.GOOD, base="--help"), 2)

    def test_not_a_repository_is_exit_2(self):
        self.assertExit(self.run_contract(self.GOOD, repo=self.sub("empty")), 2)

    def test_missing_git_is_exit_2(self):
        self.assertExit(self.run_contract(self.GOOD, path=str(self.sub("nobin"))), 2)

    def test_unrelated_histories_are_exit_2(self):
        self.repo.git("checkout", "-q", "--orphan", "other")
        self.repo.write("zzz", "x\n")
        orphan = self.repo.commit("orphan")
        self.assertExit(self.run_contract(self.GOOD, head=orphan), 2)


class ContractUnitTests(TempDirTestCase):
    """Paths git itself refuses to create are checked directly on the rule function."""

    def contract(self):
        from rigor_lib import contract, globs
        return contract.Contract("T", [("**", globs.compile_glob("**"))], [], None)

    def entry(self, path, new_mode="100644"):
        from rigor_lib.gitrun import ChangedEntry
        return ChangedEntry("100644", new_mode, "M", path)

    def rules(self, entry):
        from rigor_lib import contract
        return [f["rule"] for f in contract.entry_findings(self.contract(), entry)]

    def test_dot_dot_segment_is_a_bad_path_even_when_everything_is_allowed(self):
        self.assertEqual(self.rules(self.entry(b"src/../gate/x")), ["bad-path"])

    def test_absolute_path_is_a_bad_path(self):
        self.assertEqual(self.rules(self.entry(b"/etc/passwd")), ["bad-path"])

    def test_empty_segment_is_a_bad_path(self):
        self.assertEqual(self.rules(self.entry(b"src//x")), ["bad-path"])

    def test_unknown_mode_is_refused(self):
        self.assertEqual(self.rules(self.entry(b"src/x", "100664")), ["unsupported-mode"])

    def test_plain_modes_are_accepted(self):
        self.assertEqual(self.rules(self.entry(b"src/x", "100755")), [])
