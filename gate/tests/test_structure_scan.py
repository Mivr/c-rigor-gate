"""Tests of the structure scanner (rigor_lib/structure_scan.py) on real clang ASTs (data in test_structure_asts)."""

import copy
import json
import os
import subprocess
import sys

from rigor_lib import structure_scan
from tests.helpers import GATE_DIR, TempDirTestCase
from tests.test_structure_asts import CASES

SCAN = GATE_DIR / "rigor_lib" / "structure_scan.py"


class ScanCase(TempDirTestCase):
    def facts(self, name, tamper=None):
        case = CASES[name]
        base = str(self.sub(name))
        for fn, text in case["files"].items():
            with open(os.path.join(base, fn), "w", encoding="utf-8") as handle:
                handle.write(text)
        ast = json.loads(case["ast"].replace("@D@", base))
        if tamper:
            tamper(ast)
        files = structure_scan.Files([])
        return structure_scan.unit_facts("//t:t", os.path.join(base, "SRC.c"), ast,
                                         case["includes"].replace("@D@", base), files)

    def funcs(self, name):
        return {f["name"]: f for f in self.facts(name)["functions"]}

    def short(self, key):
        return key.replace(str(self.tmp), "").replace("/" + "calls", "")


class CallsTest(ScanCase):
    def test_direct_calls_in_every_spelling_are_one_edge_to_the_static_function(self):
        f = self.funcs("calls")["direct"]
        self.assertEqual([c["to"].split(":")[-1] for c in f["calls"]], ["sq"])
        self.assertTrue(f["calls"][0]["to"].startswith("static:"))
        self.assertEqual(f["indirect"], [])

    def test_calls_through_values_are_listed_as_indirect_sites(self):
        funcs = self.funcs("calls")
        for name in ("viaparam", "viamember", "viacond", "takes"):
            self.assertEqual(len(funcs[name]["indirect"]), 1, name)
            self.assertEqual(funcs[name]["calls"], [], name)

    def test_taking_an_address_is_a_reference_but_calling_is_not(self):
        funcs = self.funcs("calls")
        self.assertEqual(sorted(r["to"].split(":")[-1] for r in funcs["viacond"]["refs"]), ["direct", "sq"])
        self.assertEqual([r["to"].split(":")[-1] for r in funcs["takes"]["refs"]], ["sq"])
        self.assertEqual(funcs["direct"]["refs"], [])

    def test_a_function_pointer_handed_to_outside_code_is_marked(self):
        f = self.funcs("calls")["sorts"]
        self.assertEqual([(c["to"], c["fp_args"]) for c in f["calls"]], [("qs", True)])
        self.assertEqual([r["to"] for r in f["refs"]], ["cmp_fn"])

    def test_table_initialisers_outside_functions_are_references_too(self):
        refs = self.facts("calls")["refs"]
        self.assertEqual(sorted(r["to"].split(":")[-1] for r in refs), ["direct", "sq"])

    def test_files_are_measured_from_the_real_bytes(self):
        fact = self.facts("calls")["files"][0]
        self.assertEqual((fact["lines"], fact["path"].rsplit("/", 1)[1]), (13, "SRC.c"))
        self.assertEqual(fact["longest_line"], max(len(l) for l in CASES["calls"]["files"]["SRC.c"].split("\n")))


class MetricsTest(ScanCase):
    def test_else_if_chain_is_flat_and_each_branch_counts(self):
        f = self.funcs("metrics")["flat"]
        self.assertEqual((f["nesting"], f["cyclomatic"]), (1, 4))

    def test_switch_counts_cases_not_default(self):
        f = self.funcs("metrics")["sw"]
        self.assertEqual((f["nesting"], f["cyclomatic"]), (1, 3))

    def test_logical_operators_and_conditionals_count(self):
        self.assertEqual(self.funcs("metrics")["logic"]["cyclomatic"], 4)

    def test_loops_nest(self):
        f = self.funcs("metrics")["loops"]
        self.assertEqual((f["nesting"], f["cyclomatic"]), (2, 4))

    def test_bare_blocks_and_statement_expressions_nest(self):
        funcs = self.funcs("metrics")
        self.assertEqual(funcs["bare"]["nesting"], 4)
        self.assertEqual(funcs["stmtexpr"]["nesting"], 2)

    def test_a_goto_is_a_decision(self):
        self.assertEqual(self.funcs("metrics")["goes"]["cyclomatic"], 2)

    def test_variadic_counts_as_a_parameter(self):
        self.assertEqual(self.funcs("metrics")["va"]["params"], 2)

    def test_statements_are_counted_inside_blocks_and_bodies(self):
        funcs = self.funcs("metrics")
        self.assertEqual(funcs["goes"]["statements"], 3)    # goto, label, the return under the label
        self.assertEqual(funcs["sw"]["statements"], 7)      # the switch, three labels, three returns
        self.assertEqual(funcs["flat"]["statements"], 3 + 4)  # three ifs, one return per branch


class HiddenCallsTest(ScanCase):
    def test_cleanup_attribute_is_a_call(self):
        f = self.funcs("hidden")["guarded"]
        self.assertEqual([c["to"] for c in f["calls"]], ["release"])

    def test_asm_label_and_alias_are_resolved_to_the_function_they_name(self):
        funcs = self.funcs("hidden")
        self.assertEqual([c["to"] for c in funcs["loop_fn"]["calls"]], ["loop_fn"])
        self.assertEqual([c["to"] for c in funcs["real_loop"]["calls"]], ["real_loop"])
        self.assertEqual(funcs["loop_fn"]["key"], "loop_fn")

    def test_calls_made_by_macros_are_calls(self):
        self.assertEqual([c["to"] for c in self.funcs("macro")["walk"]["calls"]], ["walk"])


class LocationsTest(ScanCase):
    def test_a_function_made_by_a_macro_is_flagged_and_measured_by_its_text(self):
        f = self.funcs("macro")["made"]
        self.assertTrue(f["macro"])
        self.assertEqual(f["body_lines"], 3)    # the three lines of the macro definition
        self.assertFalse(self.funcs("macro")["walk"]["macro"])

    def test_line_directive_changes_nothing(self):
        funcs = self.funcs("line")
        after = funcs["after"]
        self.assertTrue(after["file"].endswith("SRC.c"))
        self.assertEqual((after["line"], after["body_lines"], after["end_line"]), (3, 13, 16))

    def test_a_body_that_includes_text_of_another_file_is_split(self):
        facts = self.facts("split")
        f = facts["functions"][0]
        self.assertTrue(f["split"])
        self.assertIsNone(f["body_lines"])
        self.assertEqual(sorted(x["path"].rsplit("/", 1)[1] for x in facts["files"]), ["SRC.c", "mid.h"])

    def test_every_file_the_compiler_read_is_listed_and_functions_are_placed_in_their_file(self):
        facts = self.facts("include")
        self.assertEqual(sorted(x["path"].rsplit("/", 1)[1] for x in facts["files"]), ["SRC.c", "inc.c"])
        inner = next(f for f in facts["functions"] if f["name"] == "inner")
        self.assertTrue(inner["file"].endswith("inc.c"))

    def test_a_line_the_file_does_not_agree_with_stops_the_scan(self):
        def lie(ast):
            for node in ast["inner"]:
                if node.get("name") == "sq" and "line" in node["loc"]:
                    node["loc"]["line"] += 1
        with self.assertRaises(structure_scan.ScanError):
            self.facts("calls", lie)

    def test_a_dump_that_never_names_the_source_is_blind_and_stops_the_scan(self):
        def blind(ast):
            def walk(node):
                for key in ("loc",):
                    if isinstance(node.get(key), dict) and "file" in node[key]:
                        node[key]["file"] = "other.c"
                for part in ("begin", "end"):
                    if isinstance(node.get("range", {}).get(part), dict) and "file" in node["range"][part]:
                        node["range"][part]["file"] = "other.c"
                for child in node.get("inner", []):
                    walk(child)
            walk(ast)
        with self.assertRaises(structure_scan.ScanError):
            self.facts("calls", blind)

    def test_an_offset_outside_the_file_stops_the_scan(self):
        def far(ast):
            for node in ast["inner"]:
                if node.get("name") == "direct":
                    node["loc"]["offset"] = 10 ** 6
        with self.assertRaises(structure_scan.ScanError):
            self.facts("calls", far)


class CommandLineTest(ScanCase):
    def run_scan(self, *args):
        return subprocess.run([sys.executable, "-I", "-B", str(SCAN)] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=60)

    def test_unit_then_combine_write_the_documented_file(self):
        case = CASES["include"]
        base = str(self.sub("cli"))
        for fn, text in case["files"].items():
            (self.tmp / "cli" / fn).write_text(text, encoding="utf-8")
        (self.tmp / "ast.json").write_text(case["ast"].replace("@D@", base), encoding="utf-8")
        (self.tmp / "inc.txt").write_text(case["includes"].replace("@D@", base), encoding="utf-8")
        unit, joined = self.tmp / "unit.json", self.tmp / "structure.json"
        done = self.run_scan("unit", "--label", "//t:t", "--src", base + "/SRC.c", "--out", unit,
                             "--ast", self.tmp / "ast.json", "--include-list", self.tmp / "inc.txt")
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.run_scan("combine", "--label", "//t:t", "--kind", "c_library", "--dep", "//t:d",
                             "--src", base + "/SRC.c", "--out", joined, unit)
        self.assertEqual(done.returncode, 0, done.stderr)
        document = json.loads(joined.read_text(encoding="utf-8"))
        self.assertEqual((document["schema"], document["label"], document["deps"]), (1, "//t:t", ["//t:d"]))
        self.assertEqual(len(document["units"]), 1)

    def test_combine_refuses_a_missing_unit(self):
        (self.tmp / "u.json").write_text('{"src": "a.c"}', encoding="utf-8")
        done = self.run_scan("combine", "--label", "//t:t", "--kind", "c_library", "--src", "a.c", "--src", "b.c",
                             "--out", self.tmp / "o.json", self.tmp / "u.json")
        self.assertEqual(done.returncode, 1)
        self.assertFalse((self.tmp / "o.json").exists())

    def test_unit_needs_a_command_or_an_ast_not_both_nor_neither(self):
        done = self.run_scan("unit", "--label", "//t:t", "--src", "a.c", "--out", self.tmp / "o.json")
        self.assertEqual(done.returncode, 1)
        self.assertIn("give either", done.stderr)

    def test_a_failing_compiler_fails_the_scan(self):
        done = self.run_scan("unit", "--label", "//t:t", "--src", "a.c", "--out", self.tmp / "o.json",
                             "--", sys.executable, "-c", "import sys; sys.exit(3)")
        self.assertEqual(done.returncode, 1)
        self.assertIn("status 3", done.stderr)

    def test_toolchain_and_gate_owned_third_party_files_are_not_the_products(self):
        files = structure_scan.Files(["/usr/include"], ["/art/root/third_party/"])
        self.assertTrue(files.is_system("/usr/include/stdio.h"))
        self.assertTrue(files.is_system("buck-out/v2/art/root/third_party/mbedtls/__h__/0123456789abcdef/buck-headers/ssl.h"))
        self.assertTrue(files.is_system("<built-in>"))
        self.assertFalse(files.is_system("buck-out/v2/art/annas/third_party/x.h"))   # a product dir of that name is not exempt
        self.assertFalse(files.is_system("core/arena.h"))

    def test_display_file_removes_config_hashes(self):
        self.assertEqual(structure_scan.display_file("buck-out/v2/gen/root/0123456789abcdef/p/x.h"),
                         "buck-out/v2/gen/root/~/p/x.h")
        self.assertEqual(structure_scan.display_file("a/b/buck-headers/p/x.h"), "p/x.h")
