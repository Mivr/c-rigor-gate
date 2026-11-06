"""R002 F1 and F3: the mutant generator and code that macros write.

`fixtures/mutate/macros.c` is recorded with `clang -nostdinc -isystem sysinc -std=c17 -Xclang -ast-dump=json
-fsyntax-only macros.c` (`sysinc/` plays the toolchain's headers: the roots passed are `sysinc`). The fixture
was recorded with clang 18.1.3 (the one on the authoring host); the JSON shapes used here (`spellingLoc`,
`expansionLoc`, ranges) are the same as the pinned 19.1.7's, which `selftest/mutate.sh` and the canaries
exercise on RE.
"""

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "mutate"
SPEC = importlib.util.spec_from_file_location("mutate_gen_macros", HERE.parent.parent / "mutate" / "gen.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


class RealAstTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = (FIXTURES / "macros.c").read_bytes()
        ast = json.loads((FIXTURES / "macros.ast.json").read_text(encoding="utf-8"))
        cls.result = gen.generate("macros.c", data, ast, ["sysinc"])
        cls.hidden = {h["function"]: h for h in cls.result["hidden"]}

    def operators(self, function):
        return {m["operator"] for m in self.result["mutants"] if m["function"] == function}

    # -- F3: a macro-typed return is not a macro-made function
    def test_a_function_returning_a_macro_type_is_mutated_like_any_other(self):
        self.assertIn("is_pos", [f["name"] for f in self.result["functions"]])
        self.assertLessEqual({"relational", "return-value", "function-body"}, self.operators("is_pos"))
        self.assertNotIn("is_pos", self.hidden)

    # -- F3 red twins: the name or the whole body comes from a macro
    def test_a_function_whose_body_or_name_comes_from_a_macro_is_skipped_as_macro(self):
        self.assertEqual(self.result["skipped"],
                         [{"name": "made_by_macro", "file": "macros.c", "reason": "macro"},
                          {"name": "renamed", "file": "macros.c", "reason": "macro"}])
        self.assertEqual(self.result["definitions"], len(self.result["functions"]) + 2)

    # -- F1: product macros
    def test_a_statement_macro_defined_in_the_source_is_reported_with_its_name_and_use_line(self):
        self.assertEqual(self.hidden["backdoor"], {"function": "backdoor", "macro": "LOCAL_FAST", "line": 21,
                                                   "defined_in": "macros.c"})

    def test_a_macro_defined_in_a_product_header_names_that_header(self):
        self.assertEqual((self.hidden["header_macro"]["macro"], self.hidden["header_macro"]["defined_in"]),
                         ("PROD_FAST", "./inc/prod.h"))

    def test_function_like_macros_that_write_code_are_reported(self):
        for function, macro in (("sum_macro", "SUM"), ("call_macro", "CALL")):
            self.assertEqual(self.hidden[function]["macro"], macro)

    def test_an_operator_that_a_macro_supplies_between_two_plain_operands_is_reported(self):
        self.assertEqual(self.hidden["operator_macro"]["macro"], "PLUS")
        self.assertEqual(self.hidden["pasted"]["macro"], "GLUE")

    def test_nothing_is_reported_twice_for_one_use(self):
        uses = [(h["function"], h["macro"], h["line"]) for h in self.result["hidden"]]
        self.assertEqual(len(uses), len(set(uses)))

    # -- not findings
    def test_macros_of_the_toolchain_and_plain_arguments_are_not_findings(self):
        for function in ("is_pos", "uses_system", "args_only", "nested_system", "plain"):
            self.assertNotIn(function, self.hidden)

    def test_a_constant_macro_is_not_a_finding_and_the_operator_next_to_it_is_mutated(self):
        self.assertNotIn("constant", self.hidden)
        self.assertIn("relational", self.operators("constant"))
        self.assertIn("relational", self.operators("uses_system"))

    def test_an_operator_between_a_variable_and_a_macro_argument_is_mutated(self):
        self.assertIn("relational", self.operators("args_only"))

    def test_without_the_roots_the_toolchain_headers_are_the_products(self):
        data = (FIXTURES / "macros.c").read_bytes()
        ast = json.loads((FIXTURES / "macros.ast.json").read_text(encoding="utf-8"))
        result = gen.generate("macros.c", data, ast, [])
        self.assertIn("args_only", {h["function"] for h in result["hidden"]})

    def test_every_mutant_is_still_an_exact_replacement_of_main_file_text(self):
        data = (FIXTURES / "macros.c").read_bytes()
        for m in self.result["mutants"]:
            self.assertEqual(data[m["begin_offset"]:m["end_offset"]].decode("latin-1"), m["original"])


def loc(offset, file=None, tok=1):
    item = {"offset": offset, "col": 1, "tokLen": tok}
    if file:
        item["file"] = file
    return item


def pasted(file, offset, name_len=3):
    """A location whose token was made by `##` inside a macro used at `offset`."""
    return {"spellingLoc": loc(0, file), "expansionLoc": loc(offset, "a.c", name_len)}


class PastedTokenTest(unittest.TestCase):
    # b"int a(void) { SYS(1); }": the use of SYS starts at 14
    SOURCE = b"int a(void) { SYS(1); OTH(2); }"

    def program(self, *uses):
        calls = [{"kind": "CallExpr", "range": {"begin": place, "end": place}} for place in uses]
        body = {"kind": "CompoundStmt", "range": {"begin": loc(13, "a.c"), "end": loc(30)}, "inner": calls}
        function = {"kind": "FunctionDecl", "name": "a", "loc": loc(4, "a.c"),
                    "range": {"begin": loc(0), "end": loc(30)}, "type": {"qualType": "int (void)"},
                    "inner": [body]}
        return gen.generate("a.c", self.SOURCE, {"inner": [function]}, ["sys"])["hidden"]

    def test_a_token_pasted_by_an_unproven_macro_is_a_finding(self):
        found = self.program(pasted("<scratch space>", 14))
        self.assertEqual([(h["macro"], h["line"], h["defined_in"]) for h in found],
                         [("SYS", 1, "<scratch space>")])

    def test_a_pasted_token_of_a_macro_that_another_token_shows_to_be_the_toolchains_is_not(self):
        self.assertEqual(self.program(pasted("<scratch space>", 14), pasted("sys/x.h", 14)), [])

    def test_the_proof_is_about_that_macro_only(self):
        found = self.program(pasted("<scratch space>", 14), pasted("sys/x.h", 22))
        self.assertEqual([h["macro"] for h in found], ["SYS"])

    def test_builtin_tokens_and_command_line_macros_differ(self):
        self.assertEqual(self.program(pasted("<built-in>", 14)), [])
        self.assertEqual([h["defined_in"] for h in self.program(pasted("<command line>", 14))],
                         ["<command line>"])


if __name__ == "__main__":
    unittest.main()
