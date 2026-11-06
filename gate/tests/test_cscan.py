"""Tests for the fact scanner on hand-written `clang -E -dD` text (no compiler involved)."""

import json
import os
import stat
import subprocess
import sys

from rigor_lib import cscan, semantic_table
from tests.helpers import GATE_DIR, TempDirTestCase

ROOT = "buck-out/v2/art/toolchains/0123456789abcdef/__sysroot__/tree/usr/include"


def scan(text, roots=(ROOT,)):
    collector = cscan.Collector(roots)
    collector.scan(text)
    return collector.result()


def mark(path, line=1, flags=""):
    return '# %d "%s"%s\n' % (line, path, flags)


class ScanCase(TempDirTestCase):
    def names(self, text, key="attributes"):
        return sorted(item["name"] for item in scan(text)[key])

    def test_clean_text_has_no_facts(self):
        result = scan(mark("a.c") + "int f(void) { return 1; }\n")
        self.assertEqual(result, {"pragmas": [], "attributes": [], "identifiers": [], "line_directives": []})

    def test_pragma_line_with_location(self):
        result = scan(mark("a.c") + "int x;\n#pragma clang diagnostic ignored \"-Wall\"\n")
        self.assertEqual(result["pragmas"], [{"file": "a.c", "line": 2,
                                              "text": "clang diagnostic ignored \"-Wall\""}])

    def test_pragma_spelling_with_spaces(self):
        self.assertEqual(len(scan(mark("a.c") + "  #  pragma once\n")["pragmas"]), 1)

    def test_pragma_inside_a_string_is_not_a_pragma(self):
        self.assertEqual(scan(mark("a.c") + 'const char *s = "#pragma once";\n')["pragmas"], [])

    def test_definitions_are_not_expansions(self):
        text = mark("a.c") + '#define A(x) __attribute__((x))\n#define ASM __asm__\n#undef ASM\n'
        self.assertEqual(scan(text), {"pragmas": [], "attributes": [], "identifiers": [], "line_directives": []})

    def test_attribute_names_inside_gnu_lists(self):
        text = mark("a.c") + "__attribute__((optnone)) int f(void);\n"
        self.assertEqual(self.names(text), ["optnone"])

    def test_attribute_extra_parentheses_and_arguments(self):
        text = mark("a.c") + '__attribute__(((section("s"), __used__))) int v;\n'
        self.assertEqual(self.names(text), ["__used__", "section"])

    def test_attribute_across_lines(self):
        text = mark("a.c") + "__attribute__((\n  weak,\n  alias(\"x\")\n)) int f(void);\nint after;\n"
        self.assertEqual(self.names(text), ["alias", "weak"])

    def test_single_underscore_keyword_form(self):
        self.assertEqual(self.names(mark("a.c") + "__attribute((weak)) int f(void);\n"), ["weak"])

    def test_bracket_attributes(self):
        text = mark("a.c") + '[[clang::no_sanitize("undefined")]] int f(void);\n'
        self.assertEqual(self.names(text), ["clang", "no_sanitize"])

    def test_identifiers_after_an_attribute_are_not_collected(self):
        text = mark("a.c") + "__attribute__((noreturn)) void die(int weak);\n"
        self.assertEqual(self.names(text), ["noreturn"])

    def test_array_indexing_is_not_a_bracket_attribute(self):
        text = mark("a.c") + "int g(int *a, int **b) { return a[b[0][1]] + a[ b[2] ]; }\n"
        self.assertEqual(self.names(text), [])

    def test_watched_identifiers(self):
        text = mark("a.c") + "void f(void) { __asm__(\"\"); asm(\"\"); __builtin_trap(); __builtin_unreachable(); }\n"
        self.assertEqual(self.names(text, "identifiers"),
                         ["__asm__", "__builtin_trap", "__builtin_unreachable", "asm"])

    def test_identifiers_in_strings_and_chars_are_ignored(self):
        text = mark("a.c") + "const char *s = \"asm __asm__ \\\" __builtin_trap\"; int c = 'a'; int d = '\"';\nint __asm;\n"
        self.assertEqual(self.names(text, "identifiers"), ["__asm"])

    def test_prefixed_string_literals(self):
        text = mark("a.c") + 'const char *a = u8"asm"; const int *b = L"asm";\n'
        self.assertEqual(self.names(text, "identifiers"), [])

    def test_system_header_text_is_skipped(self):
        text = (mark("a.c") + mark(ROOT + "/stdio.h", 1, " 1 3") + "extern int f(void) __asm__(\"g\");\n"
                + "#pragma GCC system_header\n__attribute__((weak)) int h;\n" + mark("a.c", 5, " 2")
                + "int x;\n")
        self.assertEqual(scan(text), {"pragmas": [], "attributes": [], "identifiers": [], "line_directives": []})

    def test_system_flag_alone_does_not_hide_text(self):
        # A product header that says `#pragma GCC system_header` is flagged 3 by the compiler,
        # but its path is not a toolchain path.
        text = mark("p/h.h", 1, " 1 3") + "__attribute__((weak)) int h;\n"
        self.assertEqual(self.names(text), ["weak"])

    def test_path_tricks_do_not_make_a_product_file_a_system_file(self):
        for path in (ROOT + "x/stdio.h", "evil/" + ROOT + "/stdio.h", ROOT[:-1] + "/stdio.h"):
            with self.subTest(path=path):
                self.assertEqual(self.names(mark(path) + "__attribute__((weak)) int h;\n"), ["weak"])

    def test_dotdot_into_the_root_is_normalised(self):
        path = "p/../" + ROOT + "/stdio.h"
        self.assertEqual(self.names(mark(path) + "__attribute__((weak)) int h;\n"), [])

    PREAMBLE = (mark("a.c") + mark("<built-in>", 1, " 1") + mark("<built-in>", 1, " 3")
                + "#define __x 1\n" + mark("<command line>", 1, " 1") + mark("<built-in>", 1, " 2")
                + mark("a.c", 1, " 2"))
    EVIL = '__attribute__((optnone)) int f(void) { __asm__(""); return 0; }\n'

    def assert_still_scanned(self, text, directives):
        result = scan(text)
        self.assertEqual(len(result["line_directives"]), directives, msg=result)
        self.assertEqual([a["name"] for a in result["attributes"]], ["optnone"])
        self.assertEqual([a["name"] for a in result["identifiers"]], ["__asm__"])

    def test_the_compilers_own_preamble_is_not_a_line_directive(self):
        result = scan(self.PREAMBLE + "int x;\n" + mark("b.h", 1, " 1") + "int y;\n" + mark("a.c", 3, " 2"))
        self.assertEqual(result["line_directives"], [])

    def test_forward_resync_marker_is_the_compilers(self):
        self.assertEqual(scan(self.PREAMBLE + "int x;\n" + mark("a.c", 90))["line_directives"], [])

    def test_line_directive_naming_a_system_header_is_reported_and_does_not_hide_text(self):
        text = self.PREAMBLE + "int x;\n" + mark(ROOT + "/stdio.h") + self.EVIL
        self.assert_still_scanned(text, 1)
        found = scan(text)["line_directives"][0]
        self.assertEqual((found["name"], found["file"]), (ROOT + "/stdio.h", "a.c"))

    def test_line_directive_naming_the_compilers_own_regions_is_reported(self):
        for name in ("<built-in>", "<command line>"):
            with self.subTest(name=name):
                self.assert_still_scanned(self.PREAMBLE + "int x;\n" + mark(name) + self.EVIL, 1)

    def test_line_directive_that_only_goes_back_in_the_same_file_is_reported(self):
        self.assert_still_scanned(self.PREAMBLE + "int x;\nint y;\nint z;\n" + mark("a.c") + self.EVIL, 1)

    def test_return_marker_must_name_the_file_it_returns_to(self):
        text = self.PREAMBLE + mark("b.h", 1, " 1") + mark(ROOT + "/stdio.h", 5, " 2") + self.EVIL
        self.assert_still_scanned(text, 1)   # the bogus return did not make the rest "system"

    def test_a_flagless_marker_is_only_the_compilers_first_one(self):
        text = mark("a.c") + mark("b.c") + "int x;\n"
        self.assertEqual(len(scan(text)["line_directives"]), 1)

    def test_builtin_and_command_line_regions_are_not_the_product(self):
        text = mark("<built-in>", 1, " 3") + "typedef int v __attribute__((address_space(1)));\n"
        self.assertEqual(scan(text)["attributes"], [])

    def test_line_numbers_follow_markers(self):
        text = mark("a.c", 10) + "int a;\nint b __attribute__((weak));\n" + mark("b.h", 40, " 1") + "__asm__;\n"
        result = scan(text)
        self.assertEqual([(a["file"], a["line"]) for a in result["attributes"]], [("a.c", 11)])
        self.assertEqual([(a["file"], a["line"]) for a in result["identifiers"]], [("b.h", 40)])

    def test_config_hashes_are_removed_from_paths(self):
        hashed = "buck-out/v2/art/root/ctest/__ctest__/622b8f6c42a7c1ef/buck-headers/ctest/ctest.h"
        self.assertEqual(cscan.display_file(hashed), "ctest/ctest.h")
        self.assertEqual(cscan.display_file("buck-out/v2/art/root/e2375fbe4e23c7fb/a/b.c"),
                         "buck-out/v2/art/root/~/a/b.c")
        self.assertEqual(cscan.display_file("p/a.c"), "p/a.c")

    def test_scanner_table_covers_every_identifier_the_decision_names(self):
        decided = set(semantic_table.FORBIDDEN_IDENTIFIERS) | set(semantic_table.GUARDED_BUILTINS)
        self.assertEqual(decided, set(cscan.WATCHED_IDENTIFIERS))

    def test_scanner_script_runs_standalone_and_is_deterministic(self):
        pre = self.tmp / "a.c.i"
        pre.write_text(mark("p/a.c") + "int f(void) { __asm__(\"\"); return 0; }\n", encoding="utf-8")
        obj = self.tmp / "a.o"
        obj.write_text("object", encoding="utf-8")
        nm = self.tmp / "fake-nm"
        nm.write_text("#!/bin/sh\nprintf 'f T 0 0\\nkill U\\nweakone W 0 0\\nm w\\n'\n", encoding="utf-8")
        nm.chmod(nm.stat().st_mode | stat.S_IXUSR)
        outputs = []
        for index in range(2):
            out = self.tmp / ("f%d.json" % index)
            argv = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "cscan.py"),
                    "--label", "//p:a", "--kind", "c_library", "--dep", "//q:b", "--dep", "//q:b",
                    "--nm", str(nm), "--system-root", ROOT, "--unit", "a.c.o", str(pre), str(obj),
                    "--out", str(out)]
            done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, msg=done.stderr)
            outputs.append(out.read_bytes())
        self.assertEqual(outputs[0], outputs[1])
        document = json.loads(outputs[0])
        unit = document["units"][0]
        self.assertEqual((document["deps"], unit["defined"], unit["weak"], unit["undefined"]),
                         (["//q:b"], ["f", "weakone"], ["weakone"], ["kill", "m"]))
        self.assertEqual(unit["identifiers"][0]["name"], "__asm__")

    def test_scanner_fails_when_nm_fails(self):
        pre = self.tmp / "a.i"
        pre.write_text(mark("a.c"), encoding="utf-8")
        nm = self.tmp / "bad-nm"
        nm.write_text("#!/bin/sh\necho boom >&2\nexit 1\n", encoding="utf-8")
        nm.chmod(nm.stat().st_mode | stat.S_IXUSR)
        argv = [sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "cscan.py"), "--label", "//p:a",
                "--kind", "c_library", "--nm", str(nm), "--unit", "a.c.o", str(pre), str(pre),
                "--out", str(self.tmp / "o.json")]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(os.path.exists(self.tmp / "o.json"))
