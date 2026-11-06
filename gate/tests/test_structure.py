"""Tests of `rigor structure` on hand-made facts: every rule red and green, at every level."""

import json
import os

from rigor_lib import structure_graph, structure_limits
from tests.helpers import TempDirTestCase, read_json, run_rigor

L3 = "L3"


def func(name, file="p/a.c", line=1, key=None, body=5, params=1, nesting=0, cyc=1, stmts=3, calls=(),
         indirect=(), refs=(), macro=False, split=False, static=False):
    return {"name": name, "key": key or name, "static": static, "file": file, "line": line,
            "end_line": line + (body or 1) - 1, "body_lines": None if split else body, "split": split,
            "macro": macro, "params": params, "nesting": nesting, "cyclomatic": cyc, "statements": stmts,
            "calls": [{"to": c[0], "fp_args": c[1] if len(c) > 1 else False, "line": line} for c in
                      [(x,) if isinstance(x, str) else x for x in calls]],
            "indirect": [{"file": file, "line": n} for n in indirect],
            "refs": [{"to": r, "file": file, "line": line} for r in refs]}


def unit(src, functions=(), files=None, refs=()):
    files = files if files is not None else [{"path": src, "lines": 10, "bytes": 100, "longest_line": 40}]
    return {"src": src, "files": files, "functions": list(functions),
            "refs": [{"to": r, "file": src, "line": 1} for r in refs]}


def module(label, units, kind="c_library", deps=()):
    return {"schema": 1, "label": label, "kind": kind, "deps": sorted(deps),
            "srcs": sorted(u["src"] for u in units), "units": units}


def one(label, functions, **kw):
    return module(label, [unit("p/a.c", functions, **kw)])


class StructureCase(TempDirTestCase):
    def run_gate(self, modules, policy=None, expect=None):
        fdir = self.sub("facts")
        for index, document in enumerate(modules):
            (fdir / ("m%d.json" % index)).write_text(json.dumps(document), encoding="utf-8")
        if policy is None:
            policy = "".join('[module."%s"]\nlevel = "%s"\n' % (m["label"], L3) for m in modules)
        pol = self.tmp / "policy.toml"
        pol.write_text(policy, encoding="utf-8")
        out = self.tmp / "structure.json"
        outcome = run_rigor(["structure", "--facts", fdir, "--policy", pol, "--out", out])
        if expect is not None:
            self.assertExit(outcome, expect)
        return outcome, (read_json(out) if out.exists() else None)

    def rules(self, modules, code, **kw):
        outcome, result = self.run_gate(modules, expect=code, **kw)
        return sorted(f["rule"] for f in result["findings"] if f["severity"] == "error")

    def findings(self, modules, code, **kw):
        outcome, result = self.run_gate(modules, expect=code, **kw)
        return result["findings"]

    def at(self, level, modules, code):
        policy = "".join('[module."%s"]\nlevel = "%s"\n' % (m["label"], level) for m in modules)
        return self.rules(modules, code, policy=policy)


class RecursionTest(StructureCase):
    def test_a_function_that_calls_itself(self):
        self.assertEqual(self.rules([one("//p:a", [func("f", calls=["f"])])], 1), ["recursion"])

    def test_mutual_recursion_across_two_files(self):
        a = unit("p/a.c", [func("ping", file="p/a.c", calls=["pong"])])
        b = unit("p/b.c", [func("pong", file="p/b.c", calls=["ping"])])
        found = self.findings([module("//p:a", [a, b])], 1)
        self.assertEqual([f["rule"] for f in found], ["recursion"])
        self.assertEqual(found[0]["cycle"], ["ping (p/a.c:1)", "pong (p/b.c:1)", "ping (p/a.c:1)"])

    def test_a_cycle_across_two_modules(self):
        a = one("//p:a", [func("f", calls=["g"])])
        b = module("//p:b", [unit("p/b.c", [func("g", file="p/b.c", calls=["f"])])], deps=["//p:a"])
        self.assertEqual(self.rules([a, b], 1), ["recursion"])

    def test_a_long_cycle_is_one_finding(self):
        names = ["f%d" % i for i in range(30)]
        funcs = [func(n, line=i + 1, calls=[names[(i + 1) % 30]]) for i, n in enumerate(names)]
        found = self.findings([one("//p:a", funcs)], 1)
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["cycle"]), 31)

    def test_a_chain_and_a_diamond_are_not_cycles(self):
        funcs = [func("a", calls=["b", "c"]), func("b", line=2, calls=["d"]), func("c", line=3, calls=["d"]),
                 func("d", line=4, calls=["strlen"])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 0), [])

    def test_a_callee_the_product_does_not_define_is_a_leaf(self):
        self.assertEqual(self.rules([one("//p:a", [func("f", calls=["qsort", "printf"])])], 0), [])

    def test_static_functions_of_two_files_are_different_functions(self):
        a = unit("p/a.c", [func("helper", key="static:p/a.c:helper", static=True, calls=["g"])])
        b = unit("p/b.c", [func("helper", file="p/b.c", key="static:p/b.c:helper", static=True),
                           func("g", file="p/b.c", line=9, calls=["static:p/b.c:helper"])])
        self.assertEqual(self.rules([module("//p:a", [a, b])], 0), [])

    def test_recursion_fails_at_every_level(self):
        for level in ("L1", "L2", "L3"):
            self.assertEqual(self.at(level, [one("//p:a", [func("f", calls=["f"])])], 1), ["recursion"], level)

    def test_tests_are_not_graded(self):
        test = module("//p:t", [unit("p/t.c", [func("f", calls=["f"], body=999)])], kind="c_test")
        self.assertEqual(self.rules([test], 0), [])


class LimitsTest(StructureCase):
    def boundary(self, field, ok, bad, rule, level=L3, **extra):
        green = [one("//p:a", [func("f", **{field: ok})], **extra)]
        red = [one("//p:a", [func("f", **{field: bad})], **extra)]
        self.assertEqual(self.at(level, green, 0), [], "%s=%s at %s" % (field, ok, level))
        found = self.findings(red, 1, policy='[module."//p:a"]\nlevel = "%s"\n' % level)
        self.assertEqual([f["rule"] for f in found], [rule])
        self.assertEqual((found[0]["value"], found[0]["function"]), (bad, "f"))
        self.assertEqual(found[0]["limit"], ok)

    def test_l3_function_length(self):
        self.boundary("body", 50, 51, "function-length")

    def test_l3_parameters(self):
        self.boundary("params", 6, 7, "parameter-count")

    def test_l3_nesting(self):
        self.boundary("nesting", 4, 5, "nesting-depth")

    def test_l3_cyclomatic(self):
        self.boundary("cyc", 15, 16, "cyclomatic-complexity")

    def test_l3_statements(self):
        self.boundary("stmts", 50, 51, "statement-count")

    def test_l2_limits(self):
        for field, ok, bad, rule in (("body", 80, 81, "function-length"), ("params", 8, 9, "parameter-count"),
                                     ("nesting", 5, 6, "nesting-depth"), ("cyc", 25, 26, "cyclomatic-complexity"),
                                     ("stmts", 80, 81, "statement-count")):
            self.boundary(field, ok, bad, rule, level="L2")

    def test_l1_has_no_limit(self):
        huge = func("f", body=10 ** 5, params=99, nesting=99, cyc=999, stmts=10 ** 5)
        files = [{"path": "p/a.c", "lines": 10 ** 6, "bytes": 1, "longest_line": 10 ** 6}]
        self.assertEqual(self.at("L1", [one("//p:a", [huge], files=files)], 0), [])

    def test_file_length_and_line_length(self):
        def files(lines, longest):
            return [{"path": "p/a.c", "lines": lines, "bytes": 1, "longest_line": longest}]
        self.assertEqual(self.at(L3, [one("//p:a", [], files=files(500, 160))], 0), [])
        self.assertEqual(self.at(L3, [one("//p:a", [], files=files(501, 10))], 1), ["file-length"])
        self.assertEqual(self.at(L3, [one("//p:a", [], files=files(10, 161))], 1), ["line-length"])
        self.assertEqual(self.at("L2", [one("//p:a", [], files=files(800, 240))], 0), [])
        self.assertEqual(self.at("L2", [one("//p:a", [], files=files(801, 241))], 1), ["file-length", "line-length"])

    def test_every_header_the_unit_read_is_checked(self):
        files = [{"path": "p/a.c", "lines": 5, "bytes": 1, "longest_line": 5},
                 {"path": "p/big.h", "lines": 501, "bytes": 1, "longest_line": 5}]
        found = self.findings([one("//p:a", [], files=files)], 1)
        self.assertEqual([(f["rule"], f["file"]) for f in found], [("file-length", "p/big.h")])

    def test_several_failures_in_one_function_are_all_named(self):
        self.assertEqual(self.rules([one("//p:a", [func("f", body=60, params=9, nesting=7)])], 1),
                         ["function-length", "nesting-depth", "parameter-count"])

    def test_a_shared_header_function_is_judged_once_at_the_strictest_level(self):
        header = {"path": "p/h.h", "lines": 5, "bytes": 1, "longest_line": 5}
        shared = func("inl", file="p/h.h", body=60)
        a = module("//p:a", [unit("p/a.c", [shared], files=[{"path": "p/a.c", "lines": 1, "bytes": 1, "longest_line": 1}, header])])
        b = module("//p:b", [unit("p/b.c", [shared], files=[{"path": "p/b.c", "lines": 1, "bytes": 1, "longest_line": 1}, header])])
        policy = '[module."//p:a"]\nlevel = "L2"\n[module."//p:b"]\nlevel = "L3"\n'
        found = self.findings([a, b], 1, policy=policy)
        self.assertEqual([(f["rule"], f["level"]) for f in found], [("function-length", "L3")])

    def test_split_body_and_macro_made_functions(self):
        self.assertEqual(self.rules([one("//p:a", [func("f", split=True)])], 1), ["split-function-body"])
        self.assertEqual(self.at("L2", [one("//p:a", [func("f", split=True)])], 1), ["split-function-body"])
        self.assertEqual(self.at("L1", [one("//p:a", [func("f", split=True)])], 0), [])
        self.assertEqual(self.rules([one("//p:a", [func("f", macro=True)])], 1), ["macro-defined-function"])
        found = self.findings([one("//p:a", [func("f", macro=True)])], 0, policy='[module."//p:a"]\nlevel = "L2"\n')
        self.assertEqual([(f["rule"], f["severity"]) for f in found], [("macro-defined-function", "info")])

    def test_including_a_file_that_is_not_a_header(self):
        files = [{"path": "p/a.c", "lines": 5, "bytes": 1, "longest_line": 5},
                 {"path": "p/b.c", "lines": 5, "bytes": 1, "longest_line": 5}]
        self.assertEqual(self.rules([one("//p:a", [], files=files)], 1), ["included-non-header"])
        self.assertEqual(self.at("L1", [one("//p:a", [], files=files)], 0), [])

    def test_two_definitions_of_one_external_function(self):
        a = unit("p/a.c", [func("f", file="p/a.c")])
        b = unit("p/b.c", [func("f", file="p/b.c")])
        self.assertEqual(self.rules([module("//p:a", [a, b])], 1), ["duplicate-definition"])

    def test_the_same_header_definition_seen_by_two_units_is_one_definition(self):
        h = func("inl", file="p/h.h")
        a = unit("p/a.c", [h, func("fa", file="p/a.c", line=9)])
        b = unit("p/b.c", [h])
        self.assertEqual(self.rules([module("//p:a", [a, b])], 0), [])


class ProgramsTest(StructureCase):
    def test_two_programs_may_both_define_main(self):
        a = module("//p:a", [unit("p/a.c", [func("main", file="p/a.c", calls=["work"])])], kind="c_binary", deps=["//p:lib"])
        b = module("//p:b", [unit("p/b.c", [func("main", file="p/b.c", calls=["work"])])], kind="c_binary", deps=["//p:lib"])
        lib = one("//p:lib", [func("work", file="p/lib.c")])
        self.assertEqual(self.rules([a, b, lib], 0), [])

    def test_a_program_that_defines_a_function_twice_is_refused(self):
        a = module("//p:a", [unit("p/a.c", [func("f", file="p/a.c")]), unit("p/b.c", [func("f", file="p/b.c")])],
                   kind="c_binary")
        self.assertEqual(self.rules([a], 1), ["duplicate-definition"])

    def test_a_hook_the_program_defines_for_a_library_closes_a_cycle(self):
        lib = one("//p:lib", [func("run", calls=["hook"])])
        prog = module("//p:prog", [unit("p/m.c", [func("hook", file="p/m.c", calls=["run"])])], kind="c_binary",
                      deps=["//p:lib"])
        self.assertEqual(self.rules([lib, prog], 1), ["recursion"])

    def test_the_same_names_in_two_programs_are_no_cycle(self):
        a = module("//p:a", [unit("p/a.c", [func("main", file="p/a.c", calls=["helper"]),
                                            func("helper", file="p/a.c", line=9)])], kind="c_binary")
        b = module("//p:b", [unit("p/b.c", [func("main", file="p/b.c", calls=["helper"]),
                                            func("helper", file="p/b.c", line=9, calls=["main"])])], kind="c_binary")
        found = self.findings([a, b], 1)
        self.assertEqual([(f["rule"], f["module"]) for f in found], [("recursion", "//p:b")])


class IndirectTest(StructureCase):
    def test_taking_an_own_address_where_the_function_reaches_the_indirect_call(self):
        funcs = [func("run", calls=[], indirect=[3]), func("handler", line=9, calls=["run"], refs=["handler"])]
        found = self.findings([one("//p:a", funcs)], 1)
        self.assertEqual([f["rule"] for f in found], ["indirect-cycle-possible"])
        self.assertEqual((found[0]["function"], found[0]["caller"]), ("handler", "run"))

    def test_the_function_is_itself_the_caller(self):
        funcs = [func("f", indirect=[2], refs=["f"])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 1), ["indirect-cycle-possible"])

    def test_the_address_taken_function_cannot_reach_the_call_site(self):
        funcs = [func("apply", indirect=[2]), func("twice", line=9), func("use", line=20, calls=["apply"], refs=["twice"])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 0), [])

    def test_a_function_pointer_handed_to_outside_code_is_a_call_site(self):
        funcs = [func("compare", calls=["sorter"]), func("sorter", line=9, calls=[("qsort", True)], refs=["compare"])]
        found = self.findings([one("//p:a", funcs)], 1)
        self.assertEqual(found[0]["sites"], ["p/a.c:9 callback:qsort"])

    def test_a_function_pointer_handed_to_the_product_itself_is_no_site(self):
        funcs = [func("compare", calls=["sorter"]), func("sorter", line=9, calls=[("mysort", True)], refs=["compare"]),
                 func("mysort", line=20)]
        self.assertEqual(self.rules([one("//p:a", funcs)], 0), [])

    def test_the_address_of_another_modules_function_is_not_this_modules_business(self):
        a = one("//p:a", [func("target", calls=["caller"])])
        b = module("//p:b", [unit("p/b.c", [func("caller", file="p/b.c", indirect=[2], refs=["target"])])], deps=["//p:a"])
        self.assertEqual(self.rules([a, b], 0), [])

    def test_levels_l2_info_l1_nothing(self):
        funcs = [func("f", indirect=[2], refs=["f"])]
        found = self.findings([one("//p:a", funcs)], 0, policy='[module."//p:a"]\nlevel = "L2"\n')
        self.assertEqual([(f["rule"], f["severity"]) for f in found], [("indirect-cycle-possible", "info")])
        self.assertEqual(self.at("L1", [one("//p:a", funcs)], 0), [])

    def test_indirect_sites_are_listed_in_the_result(self):
        outcome, result = self.run_gate([one("//p:a", [func("f", indirect=[4, 7])])], expect=0)
        self.assertEqual(result["metadata"]["indirect_sites"], {"f": ["p/a.c:4 pointer", "p/a.c:7 pointer"]})


class ConsistencyTest(StructureCase):
    def test_a_module_in_the_facts_but_not_in_the_policy(self):
        found = self.findings([one("//p:a", [])], 1, policy="")
        self.assertEqual([f["rule"] for f in found], ["module-not-in-policy"])

    def test_a_module_in_the_policy_without_facts_is_never_a_pass(self):
        policy = '[module."//p:a"]\n[module."//p:gone"]\n'
        found = self.findings([one("//p:a", [])], 1, policy=policy)
        self.assertEqual([(f["rule"], f["module"]) for f in found], [("policy-module-without-facts", "//p:gone")])

    def test_trusted_modules_need_no_facts(self):
        policy = '[global]\ntrusted = ["gate//ctest:ctest"]\n[module."//p:a"]\n[module."gate//ctest:ctest"]\n'
        self.assertEqual(self.rules([one("//p:a", [])], 0, policy=policy), [])

    def test_a_dependency_without_facts(self):
        a = module("//p:a", [unit("p/a.c")], deps=["//p:lib", "gate//ctest:ctest", "//ctest:ctest", "//third_party/mbedtls:mbedtls"])
        found = self.findings([a], 1)
        self.assertEqual([(f["rule"], f["dep"]) for f in found], [("missing-dep-facts", "//p:lib")])

    def test_no_level_means_l3_with_a_note(self):
        outcome, result = self.run_gate([one("//p:a", [func("f", body=51)])], policy='[module."//p:a"]\nallow = []\n', expect=1)
        self.assertIn("treated as L3", outcome.stdout)
        self.assertEqual([f["rule"] for f in result["findings"]], ["function-length"])
        self.assertEqual(len(result["metadata"]["notes"]), 1)

    def test_other_policy_keys_are_not_ours(self):
        policy = '[global]\ndeny = ["kill"]\n[module."//p:a"]\nlevel = "L3"\nallow = ["memcpy"]\n'
        self.assertEqual(self.rules([one("//p:a", [])], 0, policy=policy), [])


class MalformedInputTest(StructureCase):
    def exit2(self, facts_text=None, policy='[module."//p:a"]\n', extra=None, remove_first=False):
        fdir = self.sub("facts")
        if facts_text is not None:
            (fdir / "m.json").write_text(facts_text, encoding="utf-8")
        for name, text in (extra or {}).items():
            (fdir / name).write_text(text, encoding="utf-8")
        pol = self.tmp / "policy.toml"
        pol.write_text(policy, encoding="utf-8")
        out = self.tmp / "structure.json"
        out.write_text("{}", encoding="utf-8")
        outcome = run_rigor(["structure", "--facts", fdir, "--policy", pol, "--out", out])
        self.assertExit(outcome, 2)
        return out

    def test_not_json(self):
        self.exit2("{")

    def test_duplicate_keys(self):
        self.exit2('{"schema":1,"schema":1}')

    def test_an_extra_key(self):
        document = one("//p:a", [])
        document["trust_me"] = True
        self.exit2(json.dumps(document))

    def test_a_source_without_a_unit_is_partial(self):
        document = one("//p:a", [])
        document["srcs"].append("p/b.c")
        self.exit2(json.dumps(document))

    def test_a_unit_that_does_not_list_its_own_source(self):
        document = one("//p:a", [], files=[{"path": "p/other.c", "lines": 1, "bytes": 1, "longest_line": 1}])
        self.exit2(json.dumps(document))

    def test_wrong_types(self):
        document = one("//p:a", [func("f")])
        document["units"][0]["functions"][0]["params"] = "7"
        self.exit2(json.dumps(document))
        document["units"][0]["functions"][0]["params"] = True
        self.exit2(json.dumps(document))

    def test_split_and_body_lines_must_agree(self):
        document = one("//p:a", [func("f")])
        document["units"][0]["functions"][0]["body_lines"] = None
        self.exit2(json.dumps(document))

    def test_a_stray_file_and_an_empty_directory(self):
        self.exit2(json.dumps(one("//p:a", [])), extra={"notes.txt": "x"})
        self.exit2(None)

    def test_two_files_for_one_label(self):
        text = json.dumps(one("//p:a", []))
        self.exit2(text, extra={"second.json": text})

    def test_bad_policy(self):
        text = json.dumps(one("//p:a", []))
        self.exit2(text, policy="[module")
        self.exit2(text, policy='[module."//p:a"]\nlevel = "L4"\n')
        self.exit2(text, policy='[module."not a label"]\n')
        self.exit2(text, policy='[global]\ntrusted = "x"\n')

    def test_a_missing_directory(self):
        pol = self.tmp / "policy.toml"
        pol.write_text("", encoding="utf-8")
        self.assertExit(run_rigor(["structure", "--facts", self.tmp / "nope", "--policy", pol]), 2)

    def test_a_stale_result_is_replaced_by_a_failure(self):
        out = self.exit2("{")
        self.assertEqual(read_json(out)["status"], "FAIL")


class GraphTest(StructureCase):
    def test_components(self):
        graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"d"}, "e": {"a", "x"}, "x": set()}
        self.assertEqual(structure_graph.cycles(graph), [["a", "b", "c"], ["d"]])

    def test_deep_chains_do_not_exhaust_the_stack(self):
        graph = {i: {i + 1} for i in range(50000)}
        graph[50000] = {0}
        found = structure_graph.cycles(graph)
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]), 50001)

    def test_cycle_path_returns_to_its_start(self):
        graph = {"a": {"b", "c"}, "b": {"c"}, "c": {"a"}}
        path = structure_graph.cycle_path(graph, ["a", "b", "c"])
        self.assertEqual((path[0], path[-1]), ("a", "a"))
        for here, there in zip(path, path[1:]):
            self.assertIn(there, graph[here])

    def test_reachability_includes_the_start(self):
        self.assertEqual(structure_graph.reaches({"a": {"b"}, "b": {"c"}, "c": set()}, "a"), {"a", "b", "c"})
        self.assertEqual(structure_graph.reaches({}, "z"), {"z"})

    def test_limits_table_is_ordered_by_strictness(self):
        self.assertEqual(structure_limits.strictest(["L1", "L3", "L2"]), "L3")
        self.assertEqual(structure_limits.strictest(["L1", "L2"]), "L2")
        l3, l2 = structure_limits.LIMITS["L3"], structure_limits.LIMITS["L2"]
        self.assertTrue(all(a <= b for a, b in zip(l3, l2)))
        self.assertIsNone(structure_limits.LIMITS["L1"])
