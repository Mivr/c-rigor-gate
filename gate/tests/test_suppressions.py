"""Tests for `rigor suppressions`."""

import os
from pathlib import Path

from rigor_lib import patterns
from tests.helpers import Repo, Signer, TempDirTestCase, read_json, run_rigor

# One red sample per pattern id (text that must be flagged) and green near-misses.
RED = {
    "pragma-diagnostic": ['#pragma clang diagnostic ignored "-Wall"', '#  pragma GCC optimize ("O0")',
                          "#pragma GCC system_header", "#pragma clang system_header"],
    "pragma-operator": ['_Pragma("x")', '_Pragma  ("x")'],
    "nolint": ["x(); // NOLINT", "// NOLINTNEXTLINE(foo)"],
    "wno-flag": ["CFLAGS=-Wno-error", "cc -Wno-unused x.c"],
    "w-flag": ["cc -w x.c", 'flags = ["-w"]', "CFLAGS=-w", "-w"],
    "no-sanitize": ['__attribute__((no_sanitize("address")))', "no_sanitize_memory"],
    "attribute-optnone": ["__attribute__((optnone))", "__attribute__ (( no_instrument_function ))",
                          "__attribute__((  optnone))"],
    "define-ndebug-assert": ["#define NDEBUG", "# undef assert", "#define assert(x) ((void)0)",
                             "#undef NDEBUG", "#  define   NDEBUG 1"],
    "sanitize-address-macro": ["#ifdef __SANITIZE_ADDRESS__"],
    "has-feature-sanitizer": ["__has_feature(address_sanitizer)", "__has_feature( thread_sanitizer)",
                              "__has_feature(sanitizer)"],
    "getenv-gate": ['getenv("CI")', 'getenv ( "GATE_X")', 'getenv("TESTING")', 'getenv("BUCK_ID")',
                    'getenv("RIGOR")', 'getenv("GATE")'],
    "llvm-profile": ["LLVM_PROFILE_FILE", "__llvm_profile_write_file()"],
    "fuzzer-entry": ["int LLVMFuzzerTestOneInput(void)", "LLVMFuzzerCustomMutator"],
    "fno-sanitize": ["-fno-sanitize=address", "cc -fno-sanitize-recover x.c"],
    "sanitizer-options": ["ASAN_OPTIONS=detect_leaks=0", "UBSAN_OPTIONS=x", "LSAN_OPTIONS=x"],
}

GREEN = [
    "#pragma once", "#pragma GCC poison gets", "#pragma pack(1)", "my_pragma_thing",
    "// nolint", "NO LINT", "-Wall -Werror -Wextra", "-width", "ro-w", "--w", "-wrapper",
    "sanitize_ok", "ok_sanitizer_here",
    "__attribute__((noreturn))", "__attribute__((unused))", "#define NDEBUG_FOO 1",
    "#define assertion 1", "#ifdef NDEBUG", "__SANITIZE_X", "__has_feature(c_atomic)",
    'getenv("HOME")', "getenv(name)", "LLVM_PROF", "-fsanitize=address", "MSAN_OPTIONS=x",
    "ASAN_OPT", "int x = 0;", "",
]


def scope_of(path, line, pattern_id):
    return "%s:%d-%s" % (path, line, pattern_id)


class SuppressionCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("src/a.c", "int a;\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.repo.write("README.md", "hello\n")
        self.base = self.repo.commit("base")
        self.repo.branch("task")

    def grade(self, extra=(), base=None, head=None):
        head = head or self.repo.commit("work")
        out = self.tmp / "out.json"
        outcome = run_rigor(["suppressions", "--repo", self.repo.root, "--base", base or self.base,
                             "--head", head, "--out", out] + list(extra))
        return outcome, (read_json(out) if out.exists() else None)

    def triples(self, result):
        return sorted((f["rule"], f.get("path"), f.get("line"), f.get("pattern"))
                      for f in result["findings"])

    def assertClean(self, **kw):
        outcome, result = self.grade(**kw)
        self.assertExit(outcome, 0)
        self.assertEqual(result["findings"], [])

    def assertFlags(self, expected, **kw):
        outcome, result = self.grade(**kw)
        self.assertExit(outcome, 1)
        self.assertEqual(self.triples(result), sorted(expected))
        return result


class PatternTableTests(TempDirTestCase):
    def test_every_pattern_has_a_red_sample_and_the_tables_agree(self):
        ids = [p.pattern_id for p in patterns.FORBIDDEN_PATTERNS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(RED))

    def test_red_samples_match_their_own_pattern(self):
        for pattern in patterns.FORBIDDEN_PATTERNS:
            for sample in RED[pattern.pattern_id]:
                hits = patterns.matching_pattern_ids("src/x.c", sample)
                self.assertIn(pattern.pattern_id, hits, sample)

    def test_green_samples_match_nothing(self):
        for sample in GREEN:
            self.assertEqual(patterns.matching_pattern_ids("src/x.c", sample), [], sample)

    def test_fuzzer_entry_is_exempt_only_in_underscore_fuzz_c_files(self):
        line = "int LLVMFuzzerTestOneInput(void)"
        self.assertEqual(patterns.matching_pattern_ids("src/parse_fuzz.c", line), [])
        self.assertEqual(patterns.matching_pattern_ids("parse_fuzz.c", line), [])
        for name in ("src/fuzz.c", "src/parse_fuzz.h", "src/parse_fuzz.cc", "src/x_fuzz.c.txt",
                     "src/parse_fuzz.c/other"):
            self.assertEqual(patterns.matching_pattern_ids(name, line), ["fuzzer-entry"], name)

    def test_artifact_suffixes(self):
        for name in ("a.o", "lib/a.a", "x/y.so", "p.profdata", "p.profraw"):
            self.assertTrue(patterns.is_binary_artifact_name(name), name)
        for name in ("a.c", "a.os", "a.so.txt", "so", "a.object", "o", "profraw"):
            self.assertFalse(patterns.is_binary_artifact_name(name), name)


class SuppressionRedGreenTests(SuppressionCase):
    def test_each_red_sample_is_flagged_with_pattern_id_and_line(self):
        for pattern_id, samples in sorted(RED.items()):
            for sample in samples:
                with self.subTest(pattern=pattern_id, sample=sample):
                    self.repo.git("reset", "-q", "--hard", self.base)
                    self.repo.write("src/a.c", "int a;\nint b;\n%s\nint d;\nint e;\nint f;\n" % sample)
                    outcome, result = self.grade()
                    self.assertExit(outcome, 1)
                    self.assertIn(("forbidden-pattern", "src/a.c", 3, pattern_id),
                                  self.triples(result))

    def test_green_samples_are_clean(self):
        for sample in GREEN:
            with self.subTest(sample=sample):
                self.repo.git("reset", "-q", "--hard", self.base)
                self.repo.write("src/a.c", "int a;\nint b;\n%s\nint d;\nint e;\nint f;\n" % sample)
                outcome, _ = self.grade()
                self.assertExit(outcome, 0)

    def test_fuzzer_entry_allowed_in_fuzz_c_file(self):
        self.repo.write("src/parse_fuzz.c", "int LLVMFuzzerTestOneInput(void) { return 0; }\n")
        self.assertClean()

    def test_fuzzer_entry_flagged_elsewhere(self):
        self.repo.write("src/parse.c", "int LLVMFuzzerTestOneInput(void) { return 0; }\n")
        self.assertFlags([("forbidden-pattern", "src/parse.c", 1, "fuzzer-entry")])

    def test_any_file_type_is_scanned(self):
        for name in ("Makefile", "BUCK", "tools/x.toml", "README.md", "script.sh", "noext"):
            with self.subTest(name=name):
                self.repo.git("reset", "-q", "--hard", self.base)
                self.repo.write(name, "x\nCFLAGS += -Wno-error\n")
                self.assertFlags([("forbidden-pattern", name, 2, "wno-flag")])

    def test_several_patterns_on_one_line_give_several_findings(self):
        self.repo.write("src/a.c", "int a; // NOLINT -Wno-error\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 1, "nolint"),
                          ("forbidden-pattern", "src/a.c", 1, "wno-flag")])

    def test_line_numbers_across_hunks(self):
        self.repo.write("src/a.c", "int a; // NOLINT\nint b;\nint c;\nint d;\nint e;\n"
                                   "int f;\n// NOLINT\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 1, "nolint"),
                          ("forbidden-pattern", "src/a.c", 7, "nolint")])

    def test_line_number_after_an_earlier_deletion(self):
        self.repo.write("src/a.c", "int a;\nint c;\nint d;\nint e; // NOLINT\nint f;\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 4, "nolint")])

    def test_new_file_lines_start_at_one(self):
        self.repo.write("src/new.c", "// NOLINT\n")
        self.assertFlags([("forbidden-pattern", "src/new.c", 1, "nolint")])

    def test_existing_bad_line_that_is_untouched_is_not_flagged(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("src/a.c", "int a; // NOLINT\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        new_base = self.repo.commit("legacy bad line")
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.write("src/a.c", "int a; // NOLINT\nint b;\nint c;\nint d;\nint e;\nint f2;\n")
        self.assertClean(base=new_base)

    def test_editing_a_bad_line_flags_it_again(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("src/a.c", "int a; // NOLINT\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        new_base = self.repo.commit("legacy bad line")
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.write("src/a.c", "int a2; // NOLINT\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 1, "nolint")], base=new_base)

    def test_removed_bad_lines_and_deleted_files_are_clean(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("src/a.c", "int a; // NOLINT\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.repo.write("src/gone.c", "// NOLINT\n")
        new_base = self.repo.commit("legacy bad lines")
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.write("src/a.c", "int a;\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.repo.remove("src/gone.c")
        self.assertClean(base=new_base)

    def test_bad_line_only_on_base_side_is_not_attributed(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("README.md", "// NOLINT\n")
        main_tip = self.repo.commit("main moves on")
        self.repo.git("checkout", "-q", "task")
        self.repo.write("src/a.c", "int a2;\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.assertClean(base=main_tip)

    def test_plus_plus_plus_content_line_is_still_scanned(self):
        self.repo.write("src/a.c", "int a;\n++ NOLINT\nint c;\nint d;\nint e;\nint f;\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 2, "nolint")])

    def test_minus_minus_minus_content_line_is_still_scanned(self):
        self.repo.write("src/a.c", "int a;\n-- NOLINT\nint c;\nint d;\nint e;\nint f;\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 2, "nolint")])

    def test_hunk_header_lookalike_content_is_still_scanned(self):
        self.repo.write("src/a.c", "int a;\n@@ -1 +1 @@\n// NOLINT\nint d;\nint e;\nint f;\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 3, "nolint")])

    def test_crlf_line_endings(self):
        self.repo.write("src/a.c", "int a;\r\n// NOLINT\r\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 2, "nolint")])

    def test_non_utf8_content_is_scanned(self):
        self.repo.write("src/a.c", b"int a; /* \xff\xfe */\n// NOLINT\n")
        self.assertFlags([("forbidden-pattern", "src/a.c", 2, "nolint")])

    def test_nul_bytes_do_not_hide_content(self):
        self.repo.write("src/blob.dat", b"\x00\x01\x02\n// NOLINT\n\x00\n")
        self.assertFlags([("forbidden-pattern", "src/blob.dat", 2, "nolint")])

    def test_gitattributes_cannot_hide_content_as_binary(self):
        self.repo.write(".gitattributes", "* -diff\n*.c binary\n")
        self.repo.write("src/a.c", "int a;\n// NOLINT\nint c;\nint d;\nint e;\nint f;\n")
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertIn(("forbidden-pattern", "src/a.c", 2, "nolint"), self.triples(result))

    def test_symlink_target_text_is_scanned(self):
        self.repo.symlink("src/lnk", "-Wno-error")
        self.assertFlags([("forbidden-pattern", "src/lnk", 1, "wno-flag")])

    def test_odd_file_names_are_reported_escaped(self):
        self.repo.write("src/we\nird.c", "// NOLINT\n")
        self.repo.write(b"src/bad\xff.c", "// NOLINT\n")
        self.assertFlags([("forbidden-pattern", "src/bad\\xff.c", 1, "nolint"),
                          ("forbidden-pattern", "src/we\nird.c", 1, "nolint")])

    def test_findings_are_identical_on_rerun(self):
        self.repo.write("src/a.c", "// NOLINT\n-Wno-x\n")
        head = self.repo.commit("work")
        _, first = self.grade(head=head)
        _, second = self.grade(head=head)
        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(len(first["findings"]), 2)


class BinaryArtifactTests(SuppressionCase):
    def test_added_artifacts_are_flagged(self):
        for name in ("build/x.o", "lib/a.a", "lib/b.so", "cov/p.profdata", "p.profraw"):
            with self.subTest(name=name):
                self.repo.git("reset", "-q", "--hard", self.base)
                self.repo.write(name, b"\x7fELF")
                self.assertFlags([("binary-artifact", name, None, None)])

    def test_modified_existing_artifact_is_flagged(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("lib/a.a", b"1")
        new_base = self.repo.commit("legacy artifact")
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.write("lib/a.a", b"2")
        self.assertFlags([("binary-artifact", "lib/a.a", None, None)], base=new_base)

    def test_deleting_an_artifact_is_fine(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("lib/a.a", b"1")
        new_base = self.repo.commit("legacy artifact")
        self.repo.git("checkout", "-q", "task")
        self.repo.git("merge", "-q", "--ff-only", "main")
        self.repo.remove("lib/a.a")
        self.assertClean(base=new_base)

    def test_lookalike_names_are_fine(self):
        for name in ("src/object.c", "src/a.os", "src/a.so.txt", "src/so"):
            self.repo.write(name, "int x;\n")
        self.assertClean()


class SuppressionApprovalTests(SuppressionCase):
    def setUp(self):
        super().setUp()
        self.signer = Signer(self.tmp / "keys")
        self.allowed = self.signer.write_allowed_signers(self.tmp / "allowed_signers")
        self.dir = self.sub("approvals")
        self.repo.write("src/a.c", "int a; // NOLINT\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.head = self.repo.commit("work")

    def approve(self, scope, kind="suppression", repo_sha=None, signer=None):
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", "ok",
                             "--repo-sha", repo_sha or self.base, "--key",
                             (signer or self.signer).key, "--out", self.dir])
        self.assertExit(outcome, 0)

    def grade_with_approvals(self):
        return self.grade(["--approvals", self.dir, "--allowed-signers", self.allowed],
                          head=self.head)

    def test_without_approvals_it_fails(self):
        outcome, _ = self.grade(head=self.head)
        self.assertExit(outcome, 1)

    def test_exact_scope_approval_turns_it_green(self):
        self.approve(scope_of("src/a.c", 1, "nolint"))
        outcome, result = self.grade_with_approvals()
        self.assertExit(outcome, 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["metadata"]["approvals_used"]), 1)

    def test_approval_for_other_line_does_not_cover(self):
        self.approve(scope_of("src/a.c", 2, "nolint"))
        outcome, result = self.grade_with_approvals()
        self.assertExit(outcome, 1)
        self.assertEqual(self.triples(result), [("forbidden-pattern", "src/a.c", 1, "nolint")])

    def test_approval_for_other_pattern_does_not_cover(self):
        self.approve(scope_of("src/a.c", 1, "wno-flag"))
        outcome, _ = self.grade_with_approvals()
        self.assertExit(outcome, 1)

    def test_approval_for_other_file_does_not_cover(self):
        self.approve(scope_of("src/b.c", 1, "nolint"))
        outcome, _ = self.grade_with_approvals()
        self.assertExit(outcome, 1)

    def test_approval_of_another_kind_does_not_cover(self):
        self.approve(scope_of("src/a.c", 1, "nolint"), kind="test-removal")
        outcome, _ = self.grade_with_approvals()
        self.assertExit(outcome, 1)

    def test_approval_whose_commit_is_not_an_ancestor_does_not_cover(self):
        self.approve(scope_of("src/a.c", 1, "nolint"), repo_sha="a" * 40)
        outcome, result = self.grade_with_approvals()
        self.assertExit(outcome, 1)
        self.assertEqual(self.triples(result), [("forbidden-pattern", "src/a.c", 1, "nolint")])

    def test_approval_signed_by_unlisted_key_is_forged_and_does_not_cover(self):
        attacker = Signer(self.tmp / "evil", name="evil")
        self.approve(scope_of("src/a.c", 1, "nolint"), signer=attacker)
        outcome, result = self.grade_with_approvals()
        self.assertExit(outcome, 1)
        rules = sorted(f["rule"] for f in result["findings"])
        self.assertEqual(rules, ["forbidden-pattern", "forged-approval"])

    def test_forged_approval_fails_even_when_nothing_else_is_wrong(self):
        self.repo.write("src/a.c", "int a;\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.head = self.repo.commit("clean again")
        (self.dir / ("ab" * 32 + ".json")).write_text("{}\n")
        outcome, result = self.grade_with_approvals()
        self.assertExit(outcome, 1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["forged-approval"])

    def test_valid_but_unused_approval_is_harmless(self):
        self.repo.write("src/a.c", "int a;\nint b;\nint c;\nint d;\nint e;\nint f;\n")
        self.head = self.repo.commit("clean again")
        self.approve(scope_of("src/a.c", 1, "nolint"))
        outcome, result = self.grade_with_approvals()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["approvals_used"], [])

    def test_approval_lookalike_inside_graded_repo_fails(self):
        name = "docs/" + "ef" * 32 + ".json"
        self.repo.write(name, "{}\n")
        self.head = self.repo.commit("lookalike")
        outcome, result = self.grade(head=self.head)
        self.assertExit(outcome, 1)
        self.assertIn(("approval-in-repo", name, None, None), self.triples(result))

    def test_missing_ssh_keygen_with_approvals_is_exit_2(self):
        self.approve(scope_of("src/a.c", 1, "nolint"))
        outcome = run_rigor(["suppressions", "--repo", self.repo.root, "--base", self.base,
                             "--head", self.head, "--approvals", self.dir,
                             "--allowed-signers", self.allowed], path=str(self.sub("nobin")))
        self.assertExit(outcome, 2)

    def test_missing_approvals_directory_is_exit_2(self):
        outcome, _ = self.grade(["--approvals", self.tmp / "nope",
                                 "--allowed-signers", self.allowed], head=self.head)
        self.assertExit(outcome, 2)

    def test_default_allowed_signers_is_the_gate_file_and_trusts_nobody(self):
        self.approve(scope_of("src/a.c", 1, "nolint"))
        outcome, result = self.grade(["--approvals", self.dir], head=self.head)
        self.assertExit(outcome, 1)
        self.assertIn("forged-approval", [f["rule"] for f in result["findings"]])


class SuppressionErrorTests(SuppressionCase):
    def test_unknown_revision_is_exit_2(self):
        outcome = run_rigor(["suppressions", "--repo", self.repo.root, "--base", "nope",
                             "--head", "task"])
        self.assertExit(outcome, 2)

    def test_missing_git_is_exit_2(self):
        outcome = run_rigor(["suppressions", "--repo", self.repo.root, "--base", self.base,
                             "--head", "task"], path=str(self.sub("nobin")))
        self.assertExit(outcome, 2)

    def test_not_a_repository_is_exit_2(self):
        outcome = run_rigor(["suppressions", "--repo", self.sub("empty"), "--base", "a",
                             "--head", "b"])
        self.assertExit(outcome, 2)

    def test_malformed_patch_is_an_internal_error(self):
        from rigor_lib import diffparse
        from rigor_lib.errors import InternalError
        for patch in (b"@@ garbage @@\n+x\n", b"@@ -1 +1 @@\nXbad\n", b"@@ -1 +1 @@\n\n"):
            with self.assertRaises(InternalError, msg=patch):
                diffparse.added_lines(patch)

    def test_parser_returns_added_lines_with_numbers(self):
        from rigor_lib import diffparse
        patch = (b"diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -2,1 +2,2 @@\n-old\n+new\n+newer\n"
                 b"\\ No newline at end of file\n")
        self.assertEqual(diffparse.added_lines(patch), [(2, b"new"), (3, b"newer")])
