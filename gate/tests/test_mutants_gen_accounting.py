"""B19: the mutant generator never drops a function silently.

The fixtures in `fixtures/mutate/` are the hermetic clang 19.1.7's own output (the toolchain's flags, `-std=c17
-Xclang -ast-dump=json -fsyntax-only X.c`), recorded next to their sources. They are the shapes in which a function
definition used to be lost or could be: attribute nodes after the body, prototypes before definitions, GNU
statement expressions, nested blocks, `_Generic`, compound literals, designated initializers, asm labels.
"""

import importlib.util
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rigor_lib import cscan, semantic_table

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "mutate"
SPEC = importlib.util.spec_from_file_location("mutate_gen_b19", HERE.parent.parent / "mutate" / "gen.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


def load(name):
    data = (FIXTURES / (name + ".c")).read_bytes()
    ast = json.loads((FIXTURES / (name + ".ast.json")).read_text(encoding="utf-8"))
    return data, ast


def generate(name, roots=()):
    data, ast = load(name)
    return gen.generate(name + ".c", data, ast, roots)


class AttributeShapesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = generate("attributes")
        cls.names = [f["name"] for f in cls.result["functions"]]

    def of(self, function, operator=None):
        return [m for m in self.result["mutants"] if m["function"] == function
                and (operator is None or m["operator"] == operator)]

    def test_the_fixture_has_the_shapes_it_claims(self):
        _, ast = load("attributes")
        trailing = {n["name"] for n in ast["inner"]
                    if n.get("kind") == "FunctionDecl" and n.get("inner")
                    and n["inner"][-1]["kind"].endswith("Attr") and any(c["kind"] == "CompoundStmt" for c in n["inner"])}
        self.assertEqual(trailing, {"after_noinline", "before_noinline", "cold_both", "unused_fn", "used_fn",
                                    "forced", "sectioned", "void_attr", "after_decl_attr"})

    def test_every_definition_is_listed_once_in_order(self):
        self.assertEqual(self.names, ["after_noinline", "before_noinline", "cold_both", "unused_fn", "used_fn",
                                      "forced", "sectioned", "void_attr", "never", "after_decl_attr", "user"])
        self.assertEqual(self.result["definitions"], 11)
        self.assertEqual(self.result["skipped"], [])

    def test_a_function_with_an_attribute_after_its_body_is_mutated(self):
        self.assertEqual([(m["original"], m["replacement"]) for m in self.of("after_noinline", "arithmetic")],
                         [("+", "-")])
        for name in self.names:
            if name != "never":
                self.assertTrue(self.of(name), name)

    def test_every_attribute_order_reaches_the_body(self):
        self.assertEqual([m["replacement"] for m in self.of("cold_both", "arithmetic")], ["/"])
        self.assertEqual([m["replacement"] for m in self.of("void_attr", "compound-assignment")], ["-="])
        self.assertEqual([m["replacement"] for m in self.of("after_decl_attr", "relational")], ["<=", ">="])
        self.assertEqual([m["replacement"] for m in self.of("void_attr", "function-body")], ["{ (void)p; }"])

    def test_a_function_with_nothing_to_mutate_says_so(self):
        self.assertEqual({f["name"]: f["reason"] for f in self.result["functions"] if "reason" in f},
                         {"never": "no-mutable-token"})
        self.assertEqual(self.of("never"), [])

    def test_the_prototype_with_an_attribute_is_not_a_definition(self):
        self.assertEqual(self.names.count("before_noinline"), 1)
        self.assertEqual(self.names.count("unused_fn"), 1)

    def test_the_old_generator_lost_exactly_these_functions(self):
        # Without the fix the trailing attribute hides the body. The accounting check is what catches it.
        with mock.patch.object(gen.Walker, "enter_function", lost_the_body_enter_function_unfixed):
            with self.assertRaises(gen.AccountingError) as caught:
                generate("attributes")
        for name in ("after_noinline", "cold_both", "forced", "void_attr"):
            self.assertIn(name, str(caught.exception))


def lost_the_body_enter_function_unfixed(self, node, ctx):
    """gen.py before B19, verbatim except for the spelling of the surrounding class."""
    body = node["inner"][-1] if node.get("inner") else None
    if not body or body.get("kind") != "CompoundStmt" or node.get("isImplicit"):
        return ctx
    if gen.span_of(node) is None or gen.span_of(body) is None:
        self.skip(node)
        return ctx
    params = [c.get("name") for c in node["inner"] if c.get("kind") == "ParmVarDecl"]
    name = node.get("name", "")
    self.functions.append({"name": name, "line": self.source.line(gen.span_of(node)[0])})
    return {"function": name, "params": [p for p in params if p], "live": True,
            "qual": node.get("type", {}), "body": body}


class MacroPrefixTest(unittest.TestCase):
    """annas-c writes `NOINLINE static int f(void) { ... }` with NOINLINE a macro for the attribute: the node's
    range starts in a macro expansion but its body is plain text, so the function is mutated, not skipped."""

    def test_a_function_whose_range_starts_in_a_macro_but_whose_body_is_plain_is_mutated(self):
        data, ast = load("attributes")
        victim = next(n for n in ast["inner"] if n.get("name") == "after_noinline")
        hidden = {"spellingLoc": {"offset": 900, "tokLen": 8}, "expansionLoc": {"offset": 1, "tokLen": 8}}
        victim["range"] = {"begin": hidden, "end": victim["range"]["end"]}
        result = gen.generate("attributes.c", data, ast)
        self.assertIn("after_noinline", [f["name"] for f in result["functions"]])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["definitions"], 11)
        self.assertEqual([f["line"] for f in result["functions"] if f["name"] == "after_noinline"], [2])


class OtherShapesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = generate("shapes")
        cls.mutants = cls.result["mutants"]

    def of(self, function, operator=None):
        return [m for m in self.mutants if m["function"] == function
                and (operator is None or m["operator"] == operator)]

    def pairs(self, function, operator):
        return [(m["original"], m["replacement"]) for m in self.of(function, operator)]

    def test_every_definition_is_accounted_for(self):
        names = [f["name"] for f in self.result["functions"]]
        self.assertEqual(names, ["proto", "proto2", "local_inline", "plain_inline", "kandr_less", "stmt_expr",
                                 "stmt_calls", "nested", "generic", "literal", "designated", "make_pt", "empty"])
        self.assertEqual(self.result["definitions"], len(names))
        self.assertEqual({f["name"] for f in self.result["functions"] if "reason" in f}, {"make_pt"})

    def test_prototypes_then_definitions_inline_and_static_inline_in_a_source(self):
        self.assertEqual(self.pairs("proto", "arithmetic"), [("+", "-")])
        self.assertEqual(self.pairs("proto2", "arithmetic"), [("*", "/")])
        self.assertEqual(self.pairs("local_inline", "arithmetic"), [("-", "+")])
        self.assertEqual(self.pairs("plain_inline", "arithmetic"), [("+", "-")])
        self.assertEqual(self.pairs("kandr_less", "integer-literal"), [("4", "5")])

    def test_statement_expressions_nested_blocks_generic_literals_designators_are_walked(self):
        self.assertEqual(self.pairs("stmt_expr", "arithmetic"), [("+", "-"), ("*", "/")])
        self.assertEqual(self.pairs("nested", "arithmetic"), [("+", "-"), ("*", "/")])
        self.assertEqual(self.pairs("nested", "compound-assignment"), [("+=", "-=")])
        self.assertEqual(self.pairs("generic", "arithmetic"), [("+", "-")])
        self.assertEqual(self.pairs("literal", "arithmetic"), [("+", "-"), ("+", "-"), ("+", "-"), ("+", "-")])
        self.assertEqual(self.pairs("designated", "arithmetic")[0], ("-", "+"))

    def test_the_value_of_a_statement_expression_is_never_deleted_but_a_statement_in_it_is(self):
        self.assertEqual(self.pairs("stmt_calls", "statement-deletion"), [("sink(x)", "(void)0")])

    def test_ids_stay_unique(self):
        self.assertEqual(len({m["id"] for m in self.mutants}), len(self.mutants))


class AsmLabelTest(unittest.TestCase):
    def test_a_function_with_an_asm_label_is_still_accounted_for(self):
        result = generate("asm_label")
        self.assertEqual([f["name"] for f in result["functions"]], ["renamed", "after_asm"])
        self.assertEqual(result["definitions"], 2)
        self.assertTrue(all(m["function"] in ("renamed", "after_asm") for m in result["mutants"]))

    def test_the_product_checks_refuse_an_asm_label_before_any_mutation(self):
        text = '# 1 "asm_label.c"\n' + (FIXTURES / "asm_label.c").read_text(encoding="utf-8")
        collector = cscan.Collector(())
        collector.scan(text)
        names = {item["name"] for item in collector.result()["identifiers"]}
        self.assertEqual(names, {"__asm__"})
        self.assertEqual(semantic_table.FORBIDDEN_IDENTIFIERS["__asm__"], "inline-asm")

    def test_which_attributes_the_product_checks_allow(self):
        forbidden = {semantic_table.normalise_attribute(a) for a in semantic_table.FORBIDDEN_ATTRIBUTES}
        for refused in ("used", "section"):
            self.assertIn(refused, forbidden)
        for allowed in ("noinline", "cold", "unused", "always_inline", "pure", "noreturn"):
            self.assertNotIn(allowed, forbidden)


class AccountingInvariantTest(unittest.TestCase):
    def test_the_generator_fails_closed_when_its_walker_loses_a_definition(self):
        with mock.patch.object(gen.Walker, "enter_function", lost_the_body_enter_function_unfixed):
            with self.assertRaises(gen.AccountingError):
                generate("attributes")

    def test_main_exits_2_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / "gen.json"
            argv = ["--src", "attributes.c", "--ast", str(FIXTURES / "attributes.ast.json"), "--out", str(out)]
            before = os.getcwd()
            os.chdir(FIXTURES)  # the AST names the source as `attributes.c`
            try:
                with mock.patch.object(gen.Walker, "enter_function", lost_the_body_enter_function_unfixed), \
                        contextlib.redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit) as caught:
                        gen.main(argv)
                self.assertIn("accounting failed", stderr.getvalue())
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse(out.exists())
                gen.main(argv)  # and with the real generator the same call works
                self.assertTrue(out.exists())
            finally:
                os.chdir(before)

    def test_a_definition_dropped_as_if_it_were_toolchain_code_is_caught_by_name(self):
        data, ast = load("attributes")
        def sink(self, node):
            self.system.append(node.get("name", ""))

        with mock.patch.object(gen.Walker, "skip", sink):
            # a macro-made function is "passed over" without being listed: build one from a real definition
            victim = next(n for n in ast["inner"] if n.get("name") == "user")
            victim["loc"] = {"spellingLoc": {"offset": 1, "tokLen": 1}, "expansionLoc": {"offset": 2, "tokLen": 1}}
            victim["range"] = {"begin": victim["loc"], "end": victim["loc"]}
            for child in victim["inner"]:
                if child["kind"] == "CompoundStmt":
                    child["range"] = victim["range"]
            with self.assertRaises(gen.AccountingError) as caught:
                gen.generate("attributes.c", data, ast)
        self.assertIn("user", str(caught.exception))

    def test_two_bodies_are_not_a_body(self):
        data, ast = load("attributes")
        victim = next(n for n in ast["inner"] if n.get("name") == "user")
        victim["inner"].append(dict(victim["inner"][-1]))
        with self.assertRaises(gen.AccountingError):
            gen.generate("attributes.c", data, ast)

    def test_the_audit_counts_without_the_walkers_help(self):
        _, ast = load("attributes")
        outside, inside = gen.audit_definitions(ast, ())
        self.assertEqual(len(outside), 11)
        self.assertEqual(inside, [])
        # the same definitions, now claimed to be in the toolchain's headers
        outside, inside = gen.audit_definitions(ast, ("attributes.c",))
        self.assertEqual((len(outside), len(inside)), (0, 11))

    def test_the_audit_ignores_prototypes_implicit_declarations_and_includers(self):
        node = {"kind": "FunctionDecl", "name": "p", "loc": {"file": "x.h", "includedFrom": {"file": "a.c"}},
                "inner": [{"kind": "ParmVarDecl"}]}
        body = {"kind": "FunctionDecl", "name": "d", "loc": {"offset": 1}, "inner": [{"kind": "CompoundStmt"}]}
        implicit = {"kind": "FunctionDecl", "name": "i", "isImplicit": True, "inner": [{"kind": "CompoundStmt"}]}
        self.assertEqual(gen.audit_definitions({"inner": [node, body, implicit]}, ("a.c",)), (["d"], []))
        self.assertEqual(gen.audit_definitions({"inner": [node, body, implicit]}, ("x.h",)), ([], ["d"]))


if __name__ == "__main__":
    unittest.main()
