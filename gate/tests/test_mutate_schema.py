"""The schema generator (mutate/schema/schema.py, T124): eligibility from the AST, nesting, rendering, bisection.

The AST fixtures are the ones of the mutant generator's own tests (`fixtures/mutate/literals.ast.json`, recorded with
clang; `sysinc/` plays the toolchain's headers). The compile step is replaced by a fake that fails for chosen mutants.
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUTATE = HERE.parent.parent / "mutate"
FIXTURES = HERE / "fixtures" / "mutate"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load(MUTATE / "gen.py", "mutate_gen_for_schema")
schema = load(MUTATE / "schema" / "schema.py", "mutate_schema")


def fixture(name):
    data = (FIXTURES / (name + ".c")).read_bytes()
    ast = json.loads((FIXTURES / (name + ".ast.json")).read_text(encoding="utf-8"))
    return data, ast


def plan_of(name, roots=("sysinc",)):
    data, ast = fixture(name)
    listing = gen.generate(name + ".c", data, json.loads(json.dumps(ast)), list(roots))
    index = schema.AstIndex(gen, ast, name + ".c", data, list(roots))
    anchors, rejected = schema.Planner(index).plan(listing["mutants"])
    return data, listing["mutants"], anchors, rejected


def anchor(order, kind, begin, end, arm=b"X", **extra):
    mutant = {"id": "m%d" % order, "operator": "relational", "replacement": "{ return 0; }", "function": "f", "line": 1}
    return schema.Anchor(mutant, order, kind, begin, end, {}, arm=arm, **extra)


class LiteralTypeTest(unittest.TestCase):
    def test_c17_types_on_lp64(self):
        cases = {"0": "int", "2147483647": "int", "2147483648": "long", "0x7fffffff": "int", "0x80000000": "unsigned int",
                 "5u": "unsigned int", "4294967296u": "unsigned long", "3l": "long", "7ul": "unsigned long",
                 "0xffffffffffffffff": "unsigned long"}
        for text, want in cases.items():
            self.assertEqual(schema.literal_type(text), want, text)
        self.assertIsNone(schema.literal_type("9223372036854775808"))  # decimal without suffix: no type holds it

    def test_a_literal_whose_successor_has_another_type_changes_the_type(self):
        change = {"operator": "integer-literal", "original": "2147483647", "replacement": "2147483648"}
        same = {"operator": "integer-literal", "original": "5", "replacement": "6"}
        self.assertTrue(schema.types_differ(change))
        self.assertFalse(schema.types_differ(same))
        self.assertTrue(schema.types_differ({"operator": "char-literal", "original": "u'x'", "replacement": "(u'x' + 1)"}))
        self.assertFalse(schema.types_differ({"operator": "char-literal", "original": "'x'", "replacement": "('x' + 1)"}))


class EligibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.mutants, cls.anchors, cls.rejected = plan_of("literals")
        cls.by_id = {m["id"]: m for m in cls.mutants}

    def reasons(self, function):
        return sorted(r for i, r in self.rejected.items() if self.by_id[i]["function"] == function)

    def test_every_mutant_is_an_anchor_or_has_a_reason_and_none_is_lost(self):
        self.assertEqual(len(self.anchors) + len(self.rejected), len(self.mutants))
        self.assertNotIn(schema.NO_ANCHOR, self.rejected.values())

    def test_a_string_that_initialises_an_array_is_not_eligible_but_one_passed_to_a_call_is(self):
        self.assertEqual(self.reasons("strings"), ["array-string-init"] * 2)  # `fixed[8] = "ab"`: "" and its first byte
        ok = [a for a in self.anchors if a.mutant["function"] == "strings" and a.mutant["operator"] == "string-literal"]
        self.assertGreaterEqual(len(ok), 3)  # "!bang", "\tesc" and "hello" " world" are arguments

    def test_conditions_with_toolchain_macros_and_enum_constants_are_anchored(self):
        kinds = {(a.mutant["function"], a.mutant["operator"]): a.kind for a in self.anchors}
        self.assertEqual(kinds[("null_guard", "condition")], "cond")
        self.assertEqual(kinds[("check", "enum-constant")], "expr")
        self.assertEqual(kinds[("check", "function-body")], "insert")

    def test_the_range_of_a_function_body_guard_is_the_position_after_its_brace(self):
        for a in self.anchors:
            if a.kind == "insert":
                self.assertEqual(self.data[a.begin - 1:a.begin], b"{")
                self.assertEqual(a.begin, a.end)


class NodeContextTest(unittest.TestCase):
    """The AST-parent predicates on hand-made nodes (the shapes clang prints)."""

    def chain(self, *kinds, **attrs):
        """Nodes from the outermost kind to the innermost, parent-linked; returns the innermost."""
        parent = None
        for kind in kinds:
            node = {"kind": kind, "inner": [], "_parent": parent}
            node.update(attrs.get(kind, {}))
            if parent is not None:
                parent["inner"].append(node)
            parent = node
        return parent

    def index(self):
        class Fake:
            gen = gen

            @staticmethod
            def ancestors(node):
                node = node.get("_parent")
                while node is not None:
                    yield node
                    node = node.get("_parent")

            @staticmethod
            def outer_of(node):
                child, parent = node, node.get("_parent")
                while parent is not None and parent.get("kind") in schema.TRANSPARENT:
                    child, parent = parent, parent.get("_parent")
                return parent, child
        return Fake

    def test_constant_contexts(self):
        index = self.index()
        for kind in ("ConstantExpr", "StaticAssertDecl", "EnumConstantDecl", "FieldDecl", "DesignatedInitExpr"):
            leaf = self.chain("FunctionDecl", "CompoundStmt", kind, "IntegerLiteral")
            self.assertTrue(schema.constant_context(index, leaf), kind)
        static = self.chain("FunctionDecl", "CompoundStmt", "DeclStmt", "VarDecl", "BinaryOperator", "IntegerLiteral",
                            VarDecl={"storageClass": "static"})
        self.assertTrue(schema.constant_context(index, static))
        plain = self.chain("FunctionDecl", "CompoundStmt", "DeclStmt", "VarDecl", "IntegerLiteral")
        self.assertFalse(schema.constant_context(index, plain))

    def test_a_file_scope_initialiser_above_the_function_does_not_count_for_a_local(self):
        outer = self.chain("TranslationUnitDecl", "VarDecl", "FunctionDecl", "CompoundStmt", "IntegerLiteral",
                           VarDecl={"storageClass": "static"})
        self.assertFalse(schema.constant_context(self.index(), outer))

    def test_a_string_directly_in_a_declaration_or_a_brace_list_initialises_an_array(self):
        index = self.index()
        self.assertTrue(schema.array_string_init(index, self.chain("VarDecl", "StringLiteral")))
        self.assertTrue(schema.array_string_init(index, self.chain("InitListExpr", "StringLiteral")))
        self.assertFalse(schema.array_string_init(index, self.chain("VarDecl", "ImplicitCastExpr", "StringLiteral")))
        self.assertFalse(schema.array_string_init(index, self.chain("CallExpr", "ImplicitCastExpr", "StringLiteral")))

    def test_truthy_contexts_are_the_ones_that_only_test_for_zero(self):
        index = self.index()
        cond = self.chain("IfStmt", "ImplicitCastExpr", "UnaryOperator")
        self.assertTrue(schema.truthy_context(index, cond))
        self.assertTrue(schema.truthy_context(index, self.chain("BinaryOperator", "UnaryOperator",
                                                                BinaryOperator={"opcode": "&&"})))
        self.assertFalse(schema.truthy_context(index, self.chain("BinaryOperator", "UnaryOperator",
                                                                 BinaryOperator={"opcode": "+"})))
        self.assertFalse(schema.truthy_context(index, self.chain("VarDecl", "UnaryOperator")))
        body = self.chain("IfStmt", "CompoundStmt", "UnaryOperator")  # a statement of the body, not the condition
        self.assertFalse(schema.truthy_context(index, body))


class RenderTest(unittest.TestCase):
    def test_no_anchors_gives_the_source_after_the_prologue(self):
        self.assertEqual(schema.render(b"int x;\n", []), schema.PROLOGUE.encode() + b"int x;\n")

    def test_an_expression_is_wrapped_with_its_mutated_and_its_original_text(self):
        data = b"a < b"
        text = schema.render(data, [anchor(0, "expr", 0, 5, arm=b"a <= b")])
        self.assertTrue(text.endswith(b"(rigor_hit(0) ? (a <= b) : (a < b))"))

    def test_an_inner_range_goes_inside_the_outer_ones_original_arm(self):
        data = b"a + b * c"
        outer = anchor(0, "expr", 0, 9, arm=b"a - b * c")
        inner = anchor(1, "expr", 4, 9, arm=b"b / c")
        innermost = anchor(2, "expr", 8, 9, arm=b"d")
        for number, a in enumerate((outer, inner, innermost)):
            a.index = number + 1
        body = schema.render(b"a + b * c", [innermost, outer, inner])[len(schema.PROLOGUE):]
        self.assertEqual(body, b"(rigor_hit(1) ? (a - b * c) : (a + (rigor_hit(2) ? (b / c) : (b * (rigor_hit(3) ? (d) : (c))))))")

    def test_equal_ranges_chain_in_the_order_of_the_list(self):
        first, second = anchor(0, "expr", 0, 5, arm=b"p"), anchor(1, "expr", 0, 5, arm=b"q")
        first.index, second.index = 1, 2
        body = schema.render(b"a < b", [second, first])[len(schema.PROLOGUE):]
        self.assertEqual(body, b"(rigor_hit(1) ? (p) : ((rigor_hit(2) ? (q) : (a < b))))")

    def test_the_other_wrappers(self):
        cond, stmt = anchor(0, "cond", 4, 9), anchor(1, "stmt", 0, 4, arm=b"")
        cond.index, stmt.index = 1, 2
        self.assertEqual(schema.render(b"if (a < b) f();", [cond])[len(schema.PROLOGUE):],
                         b"if (((a < b) ? !rigor_hit(1) : rigor_hit(1))) f();")
        self.assertEqual(schema.render(b"f(); g();", [stmt])[len(schema.PROLOGUE):],
                         b"if (!rigor_hit(2)) { f(); } g();")

    def test_a_function_body_guard_comes_first_and_a_void_body_gets_its_return(self):
        guard = anchor(0, "insert", 1, 1)
        guard.mutant = dict(guard.mutant, replacement="{ (void)p; }")
        guard.index = 1
        stmt = anchor(1, "stmt", 1, 5, arm=b"")
        stmt.index = 2
        body = schema.render(b"{f();}", [stmt, guard])[len(schema.PROLOGUE):]
        self.assertEqual(body, b"{if (rigor_hit(1)) { (void)p; return; }if (!rigor_hit(2)) { f(); }}")
        value = anchor(0, "insert", 1, 1)
        value.index = 3
        self.assertIn(b"if (rigor_hit(3)) { return 0; }", schema.render(b"{}", [value]))

    def test_partial_overlaps_are_found_and_nesting_is_not_one(self):
        nested = [anchor(0, "expr", 0, 9), anchor(1, "expr", 4, 9), anchor(2, "expr", 0, 9)]
        self.assertEqual(schema.Planner.overlapping(nested), [])
        partial = [anchor(0, "expr", 0, 6), anchor(1, "expr", 4, 9)]
        self.assertEqual([a.order for a in schema.Planner.overlapping(partial)], [1])
        adjacent = [anchor(0, "expr", 0, 4), anchor(1, "expr", 4, 9)]
        self.assertEqual(schema.Planner.overlapping(adjacent), [])

    def test_rendering_every_anchor_of_a_fixture_keeps_the_text_balanced_and_the_hits_numbered_once_per_wrapper(self):
        data, _, anchors, _ = plan_of("literals")
        for number, a in enumerate(anchors):
            a.index = number + 1
        text = schema.render(data, anchors)
        self.assertTrue(gen.balanced(text))
        for a in anchors:
            self.assertGreaterEqual(len(re.findall(rb"rigor_hit\(%d\)" % a.index, text)), 1)


class FakeCompiler:
    """ok() is False while any of the `bad` ids, or any of the `pairs` together, is in the anchor list."""

    def __init__(self, bad=(), pairs=()):
        self.bad, self.pairs, self.count, self.last_error = set(bad), [set(p) for p in pairs], 0, ""

    def ok(self, data, anchors, obj=None):
        self.count += 1
        ids = {a.mutant["id"] for a in anchors}
        return not (ids & self.bad) and not any(p <= ids for p in self.pairs)


class BisectionTest(unittest.TestCase):
    def anchors(self, count):
        return [anchor(i, "expr", i, i + 1) for i in range(count)]

    def test_all_good_costs_one_compile(self):
        fake = FakeCompiler()
        kept, left = schema.bisect_unviable(fake, b"", self.anchors(20))
        self.assertEqual((len(kept), left, fake.count), (20, [], 1))

    def test_every_offender_is_found_and_the_rest_compile(self):
        anchors = self.anchors(40)
        fake = FakeCompiler(bad={"m3", "m4", "m31"})
        kept, left = schema.bisect_unviable(fake, b"", anchors)
        self.assertEqual(sorted(a.mutant["id"] for a in left), ["m3", "m31", "m4"])
        self.assertEqual(len(kept), 37)
        self.assertTrue(fake.ok(b"", kept))
        self.assertLess(fake.count, 3 * 7 + 2)  # k offenders cost about k log2 n compiles

    def test_two_mutants_that_only_fail_together_cost_one_of_them(self):
        fake = FakeCompiler(pairs=[{"m2", "m9"}])
        kept, left = schema.bisect_unviable(fake, b"", self.anchors(12))
        self.assertEqual(len(left), 1)
        self.assertTrue(fake.ok(b"", kept))

    def test_the_result_does_not_depend_on_the_run(self):
        first = schema.bisect_unviable(FakeCompiler(bad={"m5"}), b"", self.anchors(10))
        second = schema.bisect_unviable(FakeCompiler(bad={"m5"}), b"", self.anchors(10))
        self.assertEqual([a.order for a in first[0]], [a.order for a in second[0]])


class TableTest(unittest.TestCase):
    def test_a_fixture_is_numbered_from_the_first_index_and_the_unviable_are_listed(self):
        data, ast = fixture("literals")
        listing = gen.generate("literals.c", data, json.loads(json.dumps(ast)), ["sysinc"])
        index = schema.AstIndex(gen, ast, "literals.c", data, ["sysinc"])
        live = {m["id"] for m in listing["mutants"]}
        first = next(m["id"] for m in listing["mutants"] if m["function"] == "check" and m["operator"] == "enum-constant")
        fake = FakeCompiler(bad={first})
        table = schema.build_table("literals.c", listing["mutants"], live, schema.Planner(index), fake, data, 100, "o")
        self.assertEqual(table["unviable"], [first])
        indices = [e["index"] for e in table["entries"]]  # numbered before the compile: the left-out one leaves a gap
        self.assertEqual(indices, sorted(set(indices)))
        self.assertEqual((indices[0], indices[-1]), (100, 100 + table["static_eligible"] - 1))
        self.assertEqual(len(indices) + 1, table["static_eligible"])
        self.assertEqual(table["live"], len(live))
        self.assertEqual(table["eligible"] + len(table["ineligible"]) + 1, len(live))
        self.assertEqual(table["reasons"]["schema-unviable"], 1)
        self.assertEqual(sum(table["reasons"].values()), len(table["ineligible"]) + 1)

    def test_only_the_live_mutants_are_planned(self):
        data, ast = fixture("literals")
        listing = gen.generate("literals.c", data, json.loads(json.dumps(ast)), ["sysinc"])
        index = schema.AstIndex(gen, ast, "literals.c", data, ["sysinc"])
        some = {m["id"] for m in listing["mutants"][:5]}
        table = schema.build_table("literals.c", listing["mutants"], some, schema.Planner(index), FakeCompiler(), data, 1, "o")
        self.assertEqual(table["live"], 5)
        self.assertLessEqual(table["eligible"], 5)
        self.assertTrue({e["id"] for e in table["entries"]} <= some)

    def test_too_many_mutants_for_the_runtime_is_an_error(self):
        data, ast = fixture("literals")
        listing = gen.generate("literals.c", data, json.loads(json.dumps(ast)), ["sysinc"])
        index = schema.AstIndex(gen, ast, "literals.c", data, ["sysinc"])
        live = {m["id"] for m in listing["mutants"]}
        with self.assertRaises(SystemExit):
            schema.build_table("literals.c", listing["mutants"], live, schema.Planner(index), FakeCompiler(), data,
                               schema.MAX_INDEX, "o")


if __name__ == "__main__":
    unittest.main()
