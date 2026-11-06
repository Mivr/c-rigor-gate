"""Glob semantics: `**` = any depth, `*` = within one segment, everything else literal."""

import unittest

from rigor_lib import globs, paths
from rigor_lib.errors import InternalError


def matches(pattern, path):
    return globs.matches(globs.compile_glob(pattern), path)


class GlobMatchTests(unittest.TestCase):
    def test_double_star_suffix_matches_any_depth(self):
        self.assertTrue(matches("src/**", "src/a.c"))
        self.assertTrue(matches("src/**", "src/a/b/c.c"))

    def test_double_star_suffix_needs_something_below(self):
        self.assertFalse(matches("src/**", "src"))

    def test_double_star_suffix_does_not_match_sibling_prefix(self):
        self.assertFalse(matches("src/**", "srcx/a.c"))
        self.assertFalse(matches("src/**", "other/src/a.c"))

    def test_double_star_prefix_matches_root_and_nested(self):
        for path in ("BUCK", "a/BUCK", "a/b/BUCK"):
            self.assertTrue(matches("**/BUCK", path), path)

    def test_double_star_prefix_is_exact_on_name(self):
        self.assertFalse(matches("**/BUCK", "a/BUCK2"))
        self.assertFalse(matches("**/BUCK", "a/xBUCK"))

    def test_double_star_in_middle_matches_zero_or_more_dirs(self):
        for path in ("docs/x.md", "docs/a/x.md", "docs/a/b/x.md"):
            self.assertTrue(matches("docs/**/x.md", path), path)
        self.assertFalse(matches("docs/**/x.md", "docs/a/y.md"))

    def test_single_star_stays_within_a_segment(self):
        self.assertTrue(matches("*.c", "a.c"))
        self.assertFalse(matches("*.c", "d/a.c"))
        self.assertTrue(matches("src/*.c", "src/a.c"))
        self.assertFalse(matches("src/*.c", "src/x/a.c"))

    def test_single_star_matches_spaces_and_newlines(self):
        self.assertTrue(matches("src/*", "src/a b"))
        self.assertTrue(matches("src/*", "src/a\nb"))

    def test_other_characters_are_literal(self):
        self.assertTrue(matches("a+b.c", "a+b.c"))
        self.assertFalse(matches("a+b.c", "aab.c"))
        self.assertFalse(matches("a.c", "abc"))
        self.assertTrue(matches("a?b", "a?b"))
        self.assertFalse(matches("a?b", "axb"))
        self.assertTrue(matches("[x]", "[x]"))
        self.assertFalse(matches("[x]", "x"))

    def test_matching_is_case_sensitive(self):
        self.assertFalse(matches("src/**", "SRC/a.c"))

    def test_exact_path(self):
        self.assertTrue(matches("a/b.c", "a/b.c"))
        self.assertFalse(matches("a/b.c", "a/b.c/d"))
        self.assertFalse(matches("a/b.c", "a"))

    def test_lone_double_star_matches_everything(self):
        self.assertTrue(matches("**", "a"))
        self.assertTrue(matches("**", "a/b/c"))


class GlobValidationTests(unittest.TestCase):
    def test_bad_patterns_are_refused(self):
        for pattern in ("", "/abs", "a/../b", "..", "a//b", "./x", "a/./b", "a/", "a**b",
                        "**x", "x**", "a/\x00b"):
            with self.assertRaises(InternalError, msg=repr(pattern)):
                globs.compile_glob(pattern)


class PathSafetyTests(unittest.TestCase):
    def test_good_paths(self):
        for path in ("a", "a/b.c", "a b/c d", "a\nb/c", ".hidden/x"):
            self.assertIsNone(paths.unsafe_path_reason(path), path)

    def test_unsafe_paths(self):
        for path in ("", "/abs", "a/../b", "../a", "a/./b", "a//b", "a/", "a\x00b"):
            self.assertIsNotNone(paths.unsafe_path_reason(path), repr(path))

    def test_display_escapes_undecodable_bytes(self):
        self.assertEqual(paths.display_path(b"ok/\xff.c"), "ok/\\xff.c")

    def test_match_text_keeps_undecodable_bytes_distinct(self):
        self.assertNotEqual(paths.match_text(b"a\xff"), paths.match_text(b"a\xfe"))
