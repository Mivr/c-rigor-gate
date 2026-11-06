"""T035: R003 G2 (conditions that contain a toolchain macro such as `NULL`) and G3 (enum constants, string and
character literals) in the mutant generator.

`fixtures/mutate/literals.c` is recorded with `clang -nostdinc -isystem sysinc -std=c17 -Xclang -ast-dump=json
-fsyntax-only literals.c` (clang 18.1.3, as `macros.c`; `sysinc/` plays the toolchain's headers).
"""

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "mutate"
SPEC = importlib.util.spec_from_file_location("mutate_gen_literals", HERE.parent.parent / "mutate" / "gen.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


class LiteralsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (FIXTURES / "literals.c").read_bytes()
        ast = json.loads((FIXTURES / "literals.ast.json").read_text(encoding="utf-8"))
        cls.result = gen.generate("literals.c", cls.data, ast, ["sysinc"])

    def pairs(self, function, operator):
        return [(m["original"], m["replacement"]) for m in self.result["mutants"]
                if m["function"] == function and m["operator"] == operator]

    # -- G2
    def test_a_condition_with_a_toolchain_null_gets_its_condition_mutant(self):
        self.assertEqual(self.pairs("null_guard", "condition"),
                         [("a == SYS_NULL || b == SYS_NULL", "!(a == SYS_NULL || b == SYS_NULL)")])
        self.assertEqual(self.pairs("null_guard", "logical"), [("||", "&&")])
        self.assertEqual(self.pairs("null_guard", "relational"), [("==", "!="), ("==", "!=")])

    def test_a_loop_condition_against_a_toolchain_limit_is_mutated(self):
        self.assertEqual(self.pairs("limit", "condition"), [("x < SYS_MAX", "!(x < SYS_MAX)")])

    def test_an_if_whose_branch_ends_in_a_toolchain_macro_still_has_its_condition_mutant(self):
        self.assertEqual(self.pairs("wrapped_stmt", "condition"), [("a == SYS_NULL", "!(a == SYS_NULL)")])

    def test_returned_toolchain_constants_are_flipped(self):
        self.assertEqual(self.pairs("flag", "return-value"), [("SYS_TRUE", "0"), ("SYS_FALSE", "1")])

    def test_a_condition_built_from_a_product_macro_is_still_not_mutated_and_nothing_new_is_hidden(self):
        self.assertEqual(self.pairs("product_null", "condition"), [])
        self.assertNotIn("product_null", {h["function"] for h in self.result["hidden"]})

    def test_a_toolchain_macro_that_swallows_half_the_condition_is_not_cut(self):
        self.assertEqual(self.pairs("swallowed", "condition"), [])

    def test_no_mutant_lies_inside_a_macro(self):
        for m in self.result["mutants"]:
            self.assertEqual(self.data[m["begin_offset"]:m["end_offset"]].decode("latin-1"), m["original"])
            self.assertFalse(m["original"].startswith("SYS_") and m["operator"] in ("relational", "logical"))

    # -- G3: enum-constant
    def test_an_enumerator_becomes_the_next_one_wrapping(self):
        self.assertEqual(self.pairs("check", "enum-constant"),
                         [("ERR_RANGE", "ERR_NULL"), ("ERR_NULL", "OK"), ("OK", "ERR_RANGE")])

    def test_an_enumerator_in_an_initializer_is_mutated_but_not_under_case_or_in_a_one_value_enum(self):
        self.assertEqual(self.pairs("pick", "enum-constant"), [("BLUE", "RED")])  # not RED, GREEN (cases), not ONLY

    def test_enumerator_values_and_bitfield_widths_are_not_mutated(self):
        self.assertEqual([m for m in self.result["mutants"] if m["line"] in (8, 9, 10)], [])

    # -- G3: string-literal
    def test_a_string_becomes_empty_and_gets_its_first_byte_incremented(self):
        self.assertEqual(self.pairs("name", "string-literal"), [('"range"', '""'), ("r", "s")])

    def test_the_empty_string_is_not_mutated(self):
        self.assertEqual([m for m in self.result["mutants"]
                          if m["operator"] == "string-literal" and m["original"] == '""' and m["function"] == "name"
                          and m["replacement"] != '""'], [])
        self.assertEqual(len(self.pairs("name", "string-literal")), 2)

    def test_strings_are_not_mutated_in_sizes_assertions_attributes_or_macros(self):
        strings = self.pairs("strings", "string-literal")
        self.assertNotIn(('"unsized"', '""'), strings)  # char buf[] = "...": the literal sizes the array
        self.assertNotIn(('"abc"', '""'), strings)  # _Static_assert and sizeof
        self.assertNotIn(('"xy"', '""'), strings)
        self.assertIn(('"ab"', '""'), strings)  # a fixed-size array keeps its size
        self.assertEqual(self.pairs("prod", "string-literal"), [])  # spelled by a product macro
        self.assertEqual(sorted(o for o, _ in self.pairs("deprecated_fn", "string-literal")), ["\"kept\"", "k"])

    def test_escapes_and_a_next_byte_that_would_close_the_literal_get_no_increment(self):
        strings = self.pairs("strings", "string-literal")
        self.assertIn(('"!bang"', '""'), strings)
        self.assertIn(('"\\tesc"', '""'), strings)
        self.assertNotIn(("!", '"'), strings)
        self.assertNotIn(("\\", "]"), strings)
        self.assertIn(('"hello" " world"', '""'), strings)
        self.assertIn(("h", "i"), strings)

    # -- G3: char-literal
    def test_a_character_literal_is_incremented_in_any_spelling(self):
        self.assertEqual(self.pairs("chars", "char-literal"),
                         [("'a'", "('a' + 1)"), ("'\\n'", "('\\n' + 1)"), ("'\\x41'", "('\\x41' + 1)")])  # not 'q' (case)

    def test_every_new_operator_is_a_known_operator_with_a_stable_unique_id(self):
        ids = [m["id"] for m in self.result["mutants"]]
        self.assertEqual(len(ids), len(set(ids)))
        for m in self.result["mutants"]:
            self.assertIn(m["operator"], gen.OPERATORS)


class HelpersTest(unittest.TestCase):
    def test_balanced(self):
        self.assertTrue(gen.balanced(b"f(a[1], ')') > g(\")\")"))
        self.assertFalse(gen.balanced(b"x) > 3"))
        self.assertFalse(gen.balanced(b"f(x"))

    def test_enum_successors_wrap_and_skip_single_valued_enums(self):
        ast = {"inner": [{"kind": "EnumDecl", "inner": [{"kind": "EnumConstantDecl", "id": "1", "name": "A"},
                                                         {"kind": "EnumConstantDecl", "id": "2", "name": "B"}]},
                         {"kind": "EnumDecl", "inner": [{"kind": "EnumConstantDecl", "id": "3", "name": "C"}]}]}
        self.assertEqual(gen.enum_successors(ast), {"1": "B", "2": "A"})


if __name__ == "__main__":
    unittest.main()
