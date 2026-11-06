"""T050: R003 G4 and G5, functions that return a struct or union (directly or through typedefs) get mutants.

`fixtures/mutate/records.c` is recorded with `clang -nostdinc -std=c17 -Xclang -ast-dump=json -fsyntax-only
records.c` (clang 18.1.3).
"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "mutate"
SPEC = importlib.util.spec_from_file_location("mutate_gen_records", HERE.parent.parent / "mutate" / "gen.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


class RecordReturnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (FIXTURES / "records.c").read_bytes()
        ast = json.loads((FIXTURES / "records.ast.json").read_text(encoding="utf-8"))
        cls.result = gen.generate("records.c", cls.data, ast)

    def pairs(self, function, operator):
        return [m["replacement"] for m in self.result["mutants"]
                if m["function"] == function and m["operator"] == operator]

    def test_every_record_returning_function_has_mutants_and_no_reason(self):
        listed = {f["name"]: f for f in self.result["functions"]}
        for name in ("make_pair", "make_box", "make_span", "make_span2", "make_const_box", "get_box", "make_num"):
            self.assertNotIn("reason", listed[name], name)

    def test_the_body_becomes_a_zero_literal_of_the_declared_type(self):
        self.assertEqual(self.pairs("make_pair", "function-body"), ["{ (void)a; (void)b; return (struct pair){0}; }"])
        self.assertEqual(self.pairs("make_box", "function-body"), ["{ (void)a; return (box_t){0}; }"])
        self.assertEqual(self.pairs("make_span", "function-body"), ["{ (void)len; return (span_t){0}; }"])
        self.assertEqual(self.pairs("make_num", "function-body"), ["{ (void)i; return (union num){0}; }"])

    def test_a_typedef_chain_is_followed_and_qualifiers_are_dropped(self):
        self.assertEqual(self.pairs("make_span2", "function-body"), ["{ (void)len; return (span2_t){0}; }"])
        self.assertEqual(self.pairs("make_const_box", "function-body"), ["{ (void)a; return (box_t){0}; }"])
        self.assertEqual(self.pairs("get_box", "function-body"), ["{ (void)p; return (box_t){0}; }"])

    def test_a_returned_value_is_still_evaluated_and_replaced(self):
        self.assertEqual(self.pairs("make_pair", "return-value"), ["((void)(p), (struct pair){0})"])
        self.assertEqual(self.pairs("make_box", "return-value"), ["((void)(b), (box_t){0})"])
        self.assertEqual(self.pairs("get_box", "return-value"), ["((void)(*p), (box_t){0})"])
        self.assertEqual(self.pairs("make_const_box", "return-value"), ["((void)((box_t){ a }), (box_t){0})"])

    def test_a_return_that_already_is_the_zero_literal_gets_no_return_mutant(self):
        self.assertEqual(self.pairs("zero_box", "return-value"), [])
        self.assertEqual(self.pairs("zero_box", "function-body"), ["{ return (box_t){0}; }"])

    def test_a_scalar_typedef_is_still_scalar_and_a_complex_one_has_no_body_mutant(self):
        self.assertEqual(self.pairs("make_count", "function-body"), ["{ (void)a; return 0; }"])
        self.assertEqual(self.pairs("make_count", "return-value"), ["((void)(a), (int)0)"])
        self.assertEqual(self.pairs("make_cplx", "function-body"), [])
        # the returned expression is a double: the scalar return mutant stays (it compiles)
        self.assertEqual(self.pairs("make_cplx", "return-value"), ["((void)(a), (cplx_t)0)"])

    def test_return_class_resolves_typedefs(self):
        kinds = {"a": "record", "b": "a", "c": "other", "d": "complex", "loop": "loop"}
        self.assertEqual(gen.return_class("b (int)", kinds), "struct")
        self.assertEqual(gen.return_class("const a (int)", kinds), "struct")
        self.assertEqual(gen.return_class("c (int)", kinds), "scalar")
        self.assertIsNone(gen.return_class("d (int)", kinds))
        self.assertEqual(gen.return_class("loop (int)", kinds), "scalar")
        self.assertEqual(gen.return_class("a (int)"), "scalar")

    def test_the_mutated_text_is_a_precise_byte_replacement(self):
        for m in self.result["mutants"]:
            self.assertEqual(self.data[m["begin_offset"]:m["end_offset"]].decode("latin-1"), m["original"])


class NoMutableTokenSeverityTest(unittest.TestCase):
    """`no-mutable-token` is an error from L3 on (the level is passed in), info below and without a level."""

    @staticmethod
    def findings(level):
        sys.path.insert(0, str(HERE.parent))
        try:
            from rigor_lib import mutants_verdict
        finally:
            sys.path.pop(0)
        source = types.SimpleNamespace(file="a.c", functions=("f",), skipped=(), definitions=1, unmutated=("f",),
                                       hidden=())
        report = types.SimpleNamespace(label="//m:x", sources=[source], mutants=[])
        return [(f["rule"], f["severity"]) for f in mutants_verdict.accounting_findings(report, level)]

    def test_severity_follows_the_level(self):
        self.assertEqual(self.findings("L3"), [("no-mutable-token", "error")])
        self.assertEqual(self.findings("L5"), [("no-mutable-token", "error")])
        self.assertEqual(self.findings("L2"), [("no-mutable-token", "info")])
        self.assertEqual(self.findings(None), [("no-mutable-token", "info")])


if __name__ == "__main__":
    unittest.main()
