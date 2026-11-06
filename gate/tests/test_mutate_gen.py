"""Tests of the mutant generator (mutate/gen.py) on a real clang AST.

`data/gen_sample.ast.json` is the pinned clang 19.1.7's output for `data/gen_sample.c`:
    clang-19 --target=x86_64-unknown-linux-gnu -nostdinc -std=c17 -Xclang -ast-dump=json \
        -fsyntax-only gen_sample.c
The pipeline test (selftest/mutate.sh) runs the generator on RE against the real thing; these tests
pin what it does with each construct.
"""

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mutate_gen", HERE.parent.parent / "mutate" / "gen.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


def sample():
    data = (HERE / "data" / "gen_sample.c").read_bytes()
    ast = json.loads((HERE / "data" / "gen_sample.ast.json").read_text(encoding="utf-8"))
    return data, ast


class SampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data, ast = sample()
        cls.data = data
        cls.result = gen.generate("gen_sample.c", data, ast)
        cls.mutants = cls.result["mutants"]

    def of(self, function, operator=None):
        return [m for m in self.mutants if m["function"] == function
                and (operator is None or m["operator"] == operator)]

    def pairs(self, function, operator):
        return [(m["original"], m["replacement"]) for m in self.of(function, operator)]

    def test_every_mutant_is_an_exact_text_replacement_in_the_main_file(self):
        for m in self.mutants:
            self.assertEqual(self.data[m["begin_offset"]:m["end_offset"]].decode("latin-1"), m["original"])
            self.assertNotEqual(m["original"], m["replacement"])
            self.assertEqual(self.data[:m["begin_offset"]].count(b"\n") + 1, m["line"])
            self.assertEqual(m["file"], "gen_sample.c")

    def test_functions_are_listed_and_ids_are_unique(self):
        names = [f["name"] for f in self.result["functions"]]
        self.assertEqual(names, ["ptr_math", "macros", "switcher", "caller", "make", "bits", "loops",
                                 "wide", "negate"])
        self.assertEqual(len({m["id"] for m in self.mutants}), len(self.mutants))

    def test_output_is_sorted_by_position(self):
        keys = [(m["begin_offset"], m["end_offset"], m["replacement"]) for m in self.mutants]
        self.assertEqual(keys, sorted(keys))

    def test_macro_expansions_are_skipped(self):
        # `if (IS_NEG(x))` and `x > LIMIT` have no relational, condition or literal mutants.
        for operator in ("relational", "condition"):
            self.assertEqual(self.of("macros", operator), [])
        self.assertEqual([m["line"] for m in self.of("macros", "integer-literal")], [17, 19])
        text = b"".join(m["original"].encode("latin-1") for m in self.of("macros", "relational"))
        self.assertEqual(text, b"")

    def test_pointer_arithmetic_is_not_mutated_but_integer_arithmetic_is(self):
        self.assertEqual(self.pairs("ptr_math", "arithmetic"), [("+", "-")])
        self.assertEqual(self.of("ptr_math", "arithmetic")[0]["line"], 11)

    def test_case_labels_and_static_assert_literals_are_skipped(self):
        literals = [m["original"] for m in self.of("switcher", "integer-literal")]
        self.assertEqual(literals, ["5", "3"])
        self.assertEqual([m for m in self.mutants if m["line"] in (4, 5, 6)], [])

    def test_calls_with_unused_results_are_deleted_but_a_void_cast_is_not(self):
        self.assertEqual(self.pairs("caller", "statement-deletion"),
                         [("sink(v)", "(void)0"), ("sink(v + 1)", "(void)0")])

    def test_struct_returns_get_no_return_or_body_mutant(self):
        self.assertEqual(self.of("make", "return-value"), [])
        self.assertEqual(self.of("make", "function-body"), [])

    def test_whole_body_keeps_parameters_used(self):
        self.assertEqual([m["replacement"] for m in self.of("ptr_math", "function-body")],
                         ["{ (void)p; (void)q; (void)n; return 0; }"])
        self.assertEqual([m["replacement"] for m in self.of("caller", "function-body")], ["{ (void)v; }"])

    def test_return_keeps_evaluating_the_expression_and_casts_to_its_type(self):
        self.assertEqual(self.pairs("bits", "return-value"),
                         [("(a & b) | (a ^ b)", "((void)((a & b) | (a ^ b)), (unsigned int)0)")])
        self.assertEqual(self.pairs("macros", "return-value")[1], ("2", "0"))

    def test_operator_families(self):
        self.assertEqual(self.pairs("bits", "compound-assignment"), [("<<=", ">>="), ("^=", "&=")])
        self.assertEqual(self.pairs("bits", "arithmetic"), [("&", "|"), ("|", "&"), ("^", "&")])
        self.assertEqual(self.pairs("loops", "relational"),
                         [("<=", "<"), ("<=", ">"), ("<", "<="), ("<", ">=")])
        self.assertEqual(self.pairs("loops", "increment"), [("--", "++"), ("++", "--")])
        self.assertEqual(self.pairs("negate", "not-removal"), [("!", "")])

    def test_loop_and_if_conditions_are_negated_and_an_empty_for_condition_is_left_alone(self):
        self.assertEqual(self.pairs("loops", "condition"),
                         [("n-- <= 0", "!(n-- <= 0)"), ("s < 0", "!(s < 0)")])

    def test_literals_keep_their_notation_and_suffix(self):
        self.assertEqual(self.pairs("wide", "integer-literal"), [("0x10", "0x11"), ("7u", "8u")])

    def test_zero_becomes_one_and_one_becomes_zero(self):
        self.assertEqual(self.pairs("loops", "integer-literal")[:1], [("0", "1")])
        self.assertIn(("1", "0"), self.pairs("macros", "integer-literal"))

    def test_sizeof_operand_is_not_a_literal_target_but_its_neighbour_is(self):
        self.assertEqual(self.pairs("negate", "integer-literal"), [("0", "1"), ("3", "4")])


def loc(offset, file=None, tok=1):
    item = {"offset": offset, "col": 1, "tokLen": tok}
    if file:
        item["file"] = file
    return item


def function(name, begin, end, where, macro=None):
    """A FunctionDecl with a body; `where` names the file of its `loc`, `macro` the file of its expansion."""
    if macro:
        place = {"spellingLoc": loc(begin + 4, where), "expansionLoc": loc(end + 50, macro)}
        edge = {"spellingLoc": loc(begin, where), "expansionLoc": loc(end + 50, macro)}
        tail = {"spellingLoc": loc(end, where), "expansionLoc": loc(end + 50, macro)}
    else:
        place, edge, tail = loc(begin + 4, where), loc(begin, where), loc(end, where)
    body = {"kind": "CompoundStmt", "range": {"begin": dict(edge), "end": dict(tail)}}
    return {"kind": "FunctionDecl", "name": name, "loc": place, "range": {"begin": edge, "end": tail},
            "type": {"qualType": "int (void)"}, "inner": [body]}


class UnreachableTest(unittest.TestCase):
    SOURCE = b"int a(void) { return 1; }\n" + b" " * 200

    def skipped(self, nodes, roots=()):
        return gen.generate("a.c", self.SOURCE, {"inner": nodes}, roots)["skipped"]

    def test_a_product_header_function_and_a_macro_made_function_are_listed(self):
        nodes = [function("h", 0, 30, "inc/p.h"), function("a", 0, 24, "a.c"),
                 function("m", 0, 24, "a.c", macro="a.c")]
        self.assertEqual(self.skipped(nodes, ["sys/include"]),
                         [{"name": "h", "file": "inc/p.h", "reason": "header"},
                          {"name": "m", "file": "a.c", "reason": "macro"}])

    def test_a_function_of_the_toolchain_headers_is_not(self):
        nodes = [function("s", 0, 30, "sys/include/bits/x.h"), function("a", 0, 24, "a.c")]
        self.assertEqual(self.skipped(nodes, ["sys/include"]), [])
        self.assertEqual(self.skipped(nodes, ["sys/inc"]), [{"name": "s", "file": "sys/include/bits/x.h",
                                                            "reason": "header"}])

    def test_a_macro_defined_in_a_header_but_expanded_in_the_source_is_a_macro_function(self):
        nodes = [function("m", 0, 24, "inc/p.h", macro="a.c"), function("a", 0, 24, "a.c")]
        self.assertEqual(self.skipped(nodes), [{"name": "m", "file": "a.c", "reason": "macro"}])

    def test_an_ast_that_never_names_the_source_file_is_a_blind_generator_and_an_error(self):
        with self.assertRaises(SystemExit):
            gen.generate("a.c", self.SOURCE, {"inner": [function("a", 0, 24, "other.c")]})
        self.assertEqual(gen.generate("a.c", b"  \n", {"inner": []})["mutants"], [])


class IdTest(unittest.TestCase):
    def make(self, offset, **fields):
        item = {"begin_offset": offset, "end_offset": offset + 1, "original": "<", "replacement": "<=",
                "operator": "relational", "function": "f", "line": 1, "file": "a.c"}
        item.update(fields)
        return item

    def test_ids_do_not_depend_on_offsets_or_lines(self):
        first = gen.assign_ids([self.make(10), self.make(30)], "a.c")
        moved = gen.assign_ids([self.make(110, line=9), self.make(130, line=11)], "a.c")
        self.assertEqual([m["id"] for m in first], [m["id"] for m in moved])

    def test_equal_mutants_of_one_function_are_told_apart_by_ordinal(self):
        ids = [m["id"] for m in gen.assign_ids([self.make(10), self.make(30)], "a.c")]
        self.assertEqual(len(set(ids)), 2)

    def test_function_file_and_replacement_are_part_of_the_id(self):
        base = gen.assign_ids([self.make(10)], "a.c")[0]["id"]
        for changed in (gen.assign_ids([self.make(10)], "b.c"),
                        gen.assign_ids([self.make(10, function="g")], "a.c"),
                        gen.assign_ids([self.make(10, replacement=">=")], "a.c"),
                        gen.assign_ids([self.make(10, operator="logical")], "a.c")):
            self.assertNotEqual(changed[0]["id"], base)

    def test_two_operators_proposing_the_same_text_change_leave_one_mutant(self):
        a = self.make(10, operator="relational")
        b = self.make(10, operator="condition")
        self.assertEqual(len(gen.assign_ids([a, b], "a.c")), 1)


class ReturnClassTest(unittest.TestCase):
    def test_classes(self):
        cases = {"int (int, int)": "scalar", "void (void)": "void", "const char *(int)": "scalar",
                 "struct S (int)": None, "int (*(int))(int)": None, "static inline unsigned long (void)": "scalar",
                 "double _Complex (int)": None, "int": None, "": None}
        for text, want in cases.items():
            self.assertEqual(gen.return_class(text), want, text)


class TokenTest(unittest.TestCase):
    def test_token_between_skips_blanks_and_comments_but_nothing_else(self):
        src = gen.Source(b"a /* x */ < // c\n b MACRO")
        self.assertEqual(src.token_between(1, 17, b"<"), 10)
        self.assertIsNone(src.token_between(1, 17, b"<="))
        self.assertIsNone(src.token_between(0, 22, b"<"))
        self.assertIsNone(gen.Source(b"a OP b").token_between(1, 5, b"<"))


if __name__ == "__main__":
    unittest.main()
