"""T063: `indirect-cycle-possible` resolves calls through a value by function type, and falls back to the untyped
rule (every address-taken function) whenever a type is unknown or a function pointer changes type."""

import json

from rigor_lib import structure_scan, structure_types
from tests.helpers import run_rigor
from tests.test_structure import StructureCase, func, module, one, unit
from tests.test_structure_scan import ScanCase

A = "int ( void * , unsigned_long )"            # one ops-table member type
B = "int ( void * , char * )"                   # another one
PLAIN = "int ( int )"


def typed(name, sig=None, sites=(), taken=(), conv=(), **kw):
    """A function with type facts: `sites` = [(line, type)] calls through a value, `taken` = [(name, type)] the
    addresses it takes, `conv` = [(kind, types)] its function-pointer conversions."""
    base = func(name, indirect=[n for n, _ in sites], refs=[r for r, _ in taken], **kw)
    base["type"] = sig
    for entry, (_, t) in zip(base["indirect"], sites):
        entry["type"] = t
    for entry, (_, t) in zip(base["refs"], taken):
        entry["type"] = t
    base["conversions"] = [{"file": "p/a.c", "line": 40 + i, "kind": k, "types": t} for i, (k, t) in enumerate(conv)]
    return base


def tmodule(funcs, label="//p:a", conversions=(), **kw):
    mod = one(label, funcs, **kw)
    mod["units"][0]["conversions"] = [{"file": "p/a.c", "line": 50, "kind": k, "types": t} for k, t in conversions]
    return mod


class TypedDecisionTest(StructureCase):
    def ports(self, **over):
        """The annas-c shape: two ops tables of different types, the adapter of one calling through the other."""
        funcs = [
            typed("fs_write", A, sites=[(3, A)], line=1),                     # dispatcher of table A
            typed("lazy_write", A, line=10, calls=["sys_write"], taken=[("lazy_write", A)]),
            typed("sys_write", B, sites=[(21, B)], line=20),                  # dispatcher of table B
            typed("posix_write", B, line=30, taken=[("posix_write", B)]),
        ]
        return tmodule(funcs, **over)

    def test_two_tables_of_different_types_are_green(self):
        outcome, result = self.run_gate([self.ports()], expect=0)
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["metadata"]["typing"]["enabled"])

    def test_the_same_shape_without_type_facts_is_the_untyped_rule(self):
        legacy = self.ports()
        for f in legacy["units"][0]["functions"]:
            for key in ("type", "conversions"):
                del f[key]
            for entry in f["indirect"] + f["refs"]:
                del entry["type"]
        del legacy["units"][0]["conversions"]
        found = self.findings([legacy], 1)
        self.assertEqual({f["rule"] for f in found}, {"indirect-cycle-possible"})
        self.assertFalse(any(f["rule"] == "indirect-untyped-fallback" for f in found))

    def test_a_dispatch_table_whose_member_reaches_its_own_dispatcher_is_red(self):
        funcs = [typed("dispatch", A, sites=[(3, A)], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)])]
        found = self.findings([tmodule(funcs)], 1)
        self.assertEqual([f["rule"] for f in found], ["indirect-cycle-possible"])
        self.assertEqual((found[0]["function"], found[0]["caller"], found[0]["path"]),
                         ("member", "dispatch", ["member", "dispatch"]))

    def test_the_cycle_through_a_longer_chain_is_red_and_names_the_chain(self):
        funcs = [typed("dispatch", A, sites=[(3, A)], line=1), typed("mid", PLAIN, line=5, calls=["dispatch"]),
                 typed("member", A, line=10, calls=["mid"], taken=[("member", A)])]
        found = self.findings([tmodule(funcs)], 1)
        self.assertEqual(found[0]["path"], ["member", "mid", "dispatch"])

    def test_a_cast_to_the_other_tables_type_is_red(self):
        funcs = [typed("dispatch", B, sites=[(3, B)], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)],
                       conv=[("cast", [A, "void ( void )"]), ("cast", [B, "void ( void )"])])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])
        outcome, result = self.run_gate([tmodule(funcs)], expect=1)
        fallback = [f for f in result["findings"] if f["rule"] == "indirect-untyped-fallback"]
        self.assertEqual([(f["function"], f["line"], f["severity"]) for f in fallback], [("dispatch", 3, "info")])
        self.assertIn("converted at p/a.c:", fallback[0]["reason"])

    def test_a_conversion_in_a_unit_outside_every_function_counts(self):
        funcs = [typed("dispatch", B, sites=[(3, B)], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)])]
        self.assertEqual(self.rules([tmodule(funcs, conversions=[("cast", [A, B])])], 1), ["indirect-cycle-possible"])

    def test_every_conversion_kind_unties_the_types_it_names(self):
        for kind in ("cast", "union", "copy", "vararg"):
            funcs = [typed("dispatch", B, sites=[(3, B)], line=1),
                     typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)])]
            self.assertEqual(self.rules([tmodule(funcs, conversions=[(kind, [A, B])])], 1),
                             ["indirect-cycle-possible"], kind)

    def test_a_conversion_of_an_unrelated_type_leaves_the_other_sites_typed(self):
        outcome, result = self.run_gate([self.ports(conversions=[("cast", ["void ( char )"])])], expect=0)
        self.assertEqual(result["findings"], [])

    def test_a_conversion_the_scanner_could_not_type_unties_everything(self):
        self.assertEqual(self.rules([self.ports(conversions=[("union", None)])], 1), ["indirect-cycle-possible"])

    def test_a_function_without_conversion_facts_unties_everything(self):
        mod = self.ports()
        del mod["units"][0]["functions"][0]["conversions"]
        self.assertEqual(self.rules([mod], 1), ["indirect-cycle-possible"])

    def test_a_unit_without_conversion_facts_unties_everything(self):
        mod = self.ports()
        other = unit("p/b.c", [typed("other", PLAIN, file="p/b.c")], files=None)
        mod["units"].append(other)
        mod["srcs"] = sorted(u["src"] for u in mod["units"])
        self.assertEqual(self.rules([mod], 1), ["indirect-cycle-possible"])

    def test_an_unprototyped_pointer_type_is_red(self):
        funcs = [typed("dispatch", "int ( )", sites=[(3, "int ( )")], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_an_unprototyped_function_may_be_called_through_any_pointer_type(self):
        funcs = [typed("dispatch", A, sites=[(3, A)], line=1),
                 typed("member", "int ( )", line=10, calls=["dispatch"], taken=[("member", "int ( )")])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_a_variadic_pointer_type_or_function_is_red(self):
        v = "int ( const_char , ... )"
        funcs = [typed("dispatch", v, sites=[(3, v)], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])
        funcs = [typed("dispatch", A, sites=[(3, A)], line=1),
                 typed("member", v, line=10, calls=["dispatch"], taken=[("member", v)])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_a_pointer_of_unknown_type_is_red(self):
        funcs = [typed("dispatch", A, sites=[(3, None)], line=1),
                 typed("member", B, line=10, calls=["dispatch"], taken=[("member", B)])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_a_function_of_unknown_type_is_red(self):
        funcs = [typed("dispatch", A, sites=[(3, A)], line=1),
                 typed("member", None, line=10, calls=["dispatch"], taken=[("member", None)])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_the_type_a_declaration_gives_the_address_counts_as_well_as_the_definition(self):
        funcs = [typed("dispatch", B, sites=[(3, B)], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", B)])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_an_enum_parameter_is_compatible_with_an_integer(self):
        funcs = [typed("dispatch", "int ( enum )", sites=[(3, "int ( enum )")], line=1),
                 typed("member", "int ( unsigned_int )", line=10, calls=["dispatch"],
                       taken=[("member", "int ( unsigned_int )")])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["indirect-cycle-possible"])

    def test_a_qsort_callback_cycle_is_red_as_before(self):
        funcs = [typed("sorter", PLAIN, line=1, calls=[("qsort", True)]),
                 typed("compare", B, line=10, calls=["sorter"], taken=[("compare", B)])]
        found = self.findings([tmodule(funcs)], 1)
        self.assertEqual(found[0]["rule"], "indirect-cycle-possible")
        self.assertEqual(found[0]["sites"], ["p/a.c:1 callback:qsort"])
        self.assertEqual([f["rule"] for f in found], ["indirect-cycle-possible"])

    def test_a_cycle_through_a_function_in_another_module_is_red(self):
        a = tmodule([typed("dispatch", A, sites=[(3, A)], line=1)], label="//p:a")
        b = module("//p:b", [unit("p/b.c", [typed("member", A, file="p/b.c", calls=["dispatch"],
                                                  taken=[("member", A)])])], deps=["//p:a"])
        b["units"][0]["conversions"] = []
        self.assertEqual(self.rules([a, b], 1), ["indirect-cycle-possible"])

    def test_typed_edges_do_not_hide_a_direct_recursion(self):
        funcs = [typed("f", A, calls=["f"])]
        self.assertEqual(self.rules([tmodule(funcs)], 1), ["recursion"])

    def test_at_l2_the_typed_finding_is_an_info_and_so_is_the_fallback(self):
        funcs = [typed("dispatch", A, sites=[(3, A)], line=1),
                 typed("member", A, line=10, calls=["dispatch"], taken=[("member", A)])]
        outcome, result = self.run_gate([tmodule(funcs)], policy='[module."//p:a"]\nlevel = "L2"\n', expect=0)
        self.assertEqual([(f["rule"], f["severity"]) for f in result["findings"]], [("indirect-cycle-possible", "info")])

    def test_a_malformed_type_is_exit_2(self):
        for bad in ("int", "", 7):
            mod = tmodule([typed("f", A)])
            mod["units"][0]["functions"][0]["type"] = bad
            self.run_gate([mod], expect=2)
        mod = tmodule([typed("f", A)], conversions=[("cast", [None])])
        self.run_gate([mod], expect=2)
        mod = tmodule([typed("f", A)], conversions=[("memmove", [A])])
        self.run_gate([mod], expect=2)


class CompatibleTest(StructureCase):
    def test_identical_types_are_compatible_and_different_ones_not(self):
        self.assertTrue(structure_types.compatible(A, A))
        self.assertFalse(structure_types.compatible(A, B))
        self.assertFalse(structure_types.compatible("long ( long )", PLAIN))
        self.assertFalse(structure_types.compatible("int ( int )", "int ( int , int )"))
        self.assertFalse(structure_types.compatible("void ( int )", "int ( int )"))

    def test_unknown_unprototyped_and_variadic_match_everything(self):
        for odd in (None, "int ( )", "int ( int , ... )"):
            self.assertTrue(structure_types.compatible(odd, A))
            self.assertTrue(structure_types.compatible(A, odd))

    def test_void_parameter_list_is_a_prototype(self):
        self.assertFalse(structure_types.wild("int ( void )"))
        self.assertEqual(structure_types.parameters("int ( void )"), [])
        self.assertIsNone(structure_types.parameters("int ( )"))
        self.assertFalse(structure_types.compatible("int ( void )", PLAIN))

    def test_enum_matches_integers_only(self):
        self.assertTrue(structure_types.compatible("enum ( enum )", "unsigned_int ( long )"))
        self.assertFalse(structure_types.compatible("enum ( void * )", "unsigned_int ( long )"))
        self.assertFalse(structure_types.compatible("float ( int )", "enum ( int )"))

    def test_nested_function_pointer_parameters_are_compared_whole(self):
        outer = "int ( int ( * ) ( int ) , int )"
        self.assertTrue(structure_types.compatible(outer, outer))
        self.assertFalse(structure_types.compatible(outer, "int ( int ( * ) ( long ) , int )"))
        self.assertEqual(structure_types.parameters(outer), [["int", "(", "*", ")", "(", "int", ")"], ["int"]])


class CanonicalTypesTest(ScanCase):
    """What the scanner writes, from a real clang AST (test_structure_asts `types`)."""

    def test_the_type_of_a_function_resolves_typedefs_inside_the_parameters(self):
        funcs = self.funcs("types")
        self.assertEqual(funcs["viaops"]["type"], "int ( struct ops * , void * )")
        self.assertEqual(funcs["viaops"]["indirect"][0]["type"], "int ( void * , unsigned_long , char * )")

    def test_function_typedefs_and_pointers_to_them_are_the_same_type(self):
        self.assertEqual(self.funcs("types")["viafn"]["indirect"][0]["type"], "int ( int )")
        self.assertEqual(self.funcs("types")["run"]["indirect"][0]["type"], "int ( int )")

    def test_enum_and_unprototyped_types(self):
        funcs = self.funcs("types")
        self.assertEqual(funcs["byenum"]["indirect"][0]["type"], "enum ( enum )")
        self.assertEqual(funcs["viaunp"]["indirect"][0]["type"], "int ( )")
        self.assertEqual(funcs["grab"]["type"], "int ( int , ... )")

    def test_the_address_of_a_function_carries_the_type_of_the_declaration(self):
        funcs = self.funcs("types")
        self.assertEqual([(r["to"], r["type"]) for r in funcs["hide"]["refs"]], [("hid", "long ( long )")])
        self.assertEqual([(r["to"], r["type"]) for r in self.facts("types")["refs"]], [("hid", "long ( long )")])

    def conversions(self, name):
        return [(c["line"], c["kind"], c["types"]) for c in self.funcs("types")[name]["conversions"]]

    def test_a_cast_through_another_function_pointer_type_is_listed_with_both_types(self):
        got = self.conversions("hide")
        self.assertEqual({(l, k) for l, k, _ in got}, {(18, "cast")})
        self.assertIn(["long ( long )", "void ( void )"], [t for _, _, t in got])
        self.assertIn(["int ( int )", "void ( void )"], [t for _, _, t in got])

    def test_a_cast_to_the_same_type_is_not_a_conversion(self):
        self.assertEqual(self.conversions("same"), [])

    def test_a_copy_of_a_function_pointer_into_bytes_is_a_conversion_but_plain_copies_are_not(self):
        got = self.conversions("copies")
        self.assertEqual({(l, k) for l, k, _ in got}, {(24, "cast"), (24, "copy")})
        self.assertEqual({tuple(t) for _, _, t in got}, {("int ( int )",)})

    def test_va_arg_of_a_function_pointer_is_a_conversion(self):
        self.assertEqual(self.conversions("grab"), [(30, "vararg", ["int ( int )"])])

    def test_a_union_holding_a_function_pointer_and_another_type_is_a_conversion(self):
        facts = self.facts("types")
        unions = [(c["line"], c["types"]) for c in facts["conversions"] if c["kind"] == "union"]
        self.assertEqual(unions, [(9, ["int ( int )"])])

    def test_a_cast_in_a_table_initialiser_is_a_top_level_conversion(self):
        got = [(c["line"], c["kind"]) for c in self.facts("types")["conversions"]]
        self.assertIn((34, "cast"), got)

    def test_functions_without_function_pointers_have_no_conversions(self):
        for name in ("run", "viaops", "use_table"):
            self.assertEqual(self.conversions(name), [], name)

    def test_the_facts_are_read_by_rigor(self):
        one_unit = self.facts("types")
        facts = {"schema": 1, "label": "//t:t", "kind": "c_library", "deps": [], "srcs": [one_unit["src"]],
                 "units": [one_unit]}
        fdir = self.sub("facts")
        (fdir / "t.json").write_text(json.dumps(facts), encoding="utf-8")
        pol = self.tmp / "policy.toml"
        pol.write_text('[module."//t:t"]\nlevel = "L3"\n', encoding="utf-8")
        out = self.tmp / "r.json"
        outcome = run_rigor(["structure", "--facts", fdir, "--policy", pol, "--out", out])
        self.assertIn(outcome.code, (0, 1), outcome.stdout + outcome.stderr)
        meta = json.loads(out.read_text(encoding="utf-8"))["metadata"]["typing"]
        self.assertTrue(meta["enabled"])
        self.assertIn("int ( int ) (", " ".join(meta["converted"]))


class TypesUnitTest(ScanCase):
    """The canonicalisation on hand-made typedef tables."""

    def types(self, **typedefs):
        nodes = [{"kind": "TypedefDecl", "name": n, "type": {"qualType": t}} for n, t in typedefs.items()]
        return structure_scan.Types({"inner": nodes})

    def test_typedefs_chain_and_qualifiers_and_spellings_are_unified(self):
        t = self.types(a="long unsigned int", b="a", cb="int (*)(b)")
        self.assertEqual(t.function("int (*const)(const b, const char *const)", True), "int ( unsigned_long , char * )")
        self.assertEqual(t.function("int (cb, long)", False), "int ( int ( * ) ( unsigned_long ) , long )")

    def test_a_pointer_to_a_function_pointer_typedef_keeps_the_stars_inside(self):
        t = self.types(cb="int (*)(int)")
        self.assertEqual(t.function_types("cb *", False), ["int ( int )"])
        self.assertEqual(t.function("void (cb *)", False), "void ( int ( * * ) ( int ) )")

    def test_a_name_defined_two_ways_is_unknown(self):
        nodes = [{"kind": "TypedefDecl", "name": "t", "type": {"qualType": "int"}},
                 {"kind": "TypedefDecl", "name": "t", "type": {"qualType": "long"}}]
        t = structure_scan.Types({"inner": nodes})
        self.assertIsNone(t.function("int (t)", False))

    def test_array_typedefs_and_unnamed_aggregates_are_unknown(self):
        t = self.types(arr="int[4]")
        self.assertIsNone(t.function("int (arr)", False))
        self.assertIsNone(t.function("int (struct (unnamed struct at /x/a.c:3:5) *)", False))

    def test_records_by_value_hold_their_members_function_types(self):
        root = {"inner": [{"kind": "RecordDecl", "name": "ops", "tagUsed": "struct", "completeDefinition": True,
                           "inner": [{"kind": "FieldDecl", "type": {"qualType": "int (*)(int)"}}]},
                          {"kind": "RecordDecl", "name": "box", "tagUsed": "struct", "completeDefinition": True,
                           "inner": [{"kind": "FieldDecl", "type": {"qualType": "struct ops"}},
                                     {"kind": "FieldDecl", "type": {"qualType": "struct box *"}}]}]}
        t = structure_scan.Types(root)
        self.assertEqual(t.function_types("struct box", True), ["int ( int )"])
        self.assertEqual(t.function_types("struct box *", True), [])
        self.assertEqual(t.function_types("struct box", False), [])
        self.assertIsNone(t.function_types("struct (unnamed struct at /x/a.c:1:1)", True))
