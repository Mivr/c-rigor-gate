"""T131: the gate-cell flag of identifier facts, the reserved name `rigor_require`, the guard facts and `rigor guards`."""

import json
import unittest

from rigor_lib import cscan, facts_data, guards_gate, facts_third_party
from tests.helpers import TempDirTestCase, read_json, run_rigor
from tests.test_cscan import ROOT, mark, scan
from tests.test_facts import facts, unit

GATE_HEADER = "buck-out/v2/gen/gate/0123456789abcdef/rt/__require__/buck-headers/rt/require.h"
OWN_HEADER = "buck-out/v2/gen/root/0123456789abcdef/p/__lib__/buck-headers/rt/require.h"
GATE_ART = "/work/buck-out/v2/art/gate/0123456789abcdef/rt/__require__/buck-headers/rt/require.h"

HEADER_BODY = ("static inline void rigor_require(_Bool cond) {\n    if (!cond) {\n        __builtin_trap();\n    }\n}\n")


def with_header(header, body, extra=""):
    """a.c includes `header`, whose text is HEADER_BODY, and then has `body`."""
    return (mark("a.c") + mark(header, 1, " 1") + HEADER_BODY + mark("a.c", 2, " 2") + extra + body)


def by_name(result, name):
    return [i for i in result["identifiers"] if i["name"] == name]


class GatePath(unittest.TestCase):
    def test_the_gate_cell_is_not_the_product_cell(self):
        self.assertTrue(cscan.is_gate_path(GATE_HEADER))
        self.assertTrue(cscan.is_gate_path(GATE_ART))
        self.assertFalse(cscan.is_gate_path(OWN_HEADER))

    def test_other_layouts_are_not_the_gates(self):
        for path in ("a.c", "p/rt/require.h", "rt/require.h", "buck-out/v2/gen", "buck-out/v2/tmp/gate/x/rt/require.h",
                     "gate/buck-out/rt/require.h", "x/gen/gate/rt/require.h"):
            with self.subTest(path=path):
                self.assertFalse(cscan.is_gate_path(path))


PRODUCT_MARKER = "/gate/rt/__require__/"       # a product grade: the gate is the cell `gate`
ROOT_MARKER = "/root/rt/__require__/"          # the gate's own selftests: the gate is the root cell
ROOT_GATE = "buck-out/v2/art/root/rt/__require__/0123456789abcdef/buck-headers/rt/require.h"
SPOOF = "buck-out/v2/art/root/x/gate/rt/__require__/0123456789abcdef/buck-headers/rt/require.h"
SPOOF_ROOT = "buck-out/v2/art/root/x/root/rt/__require__/0123456789abcdef/buck-headers/rt/require.h"


class Anchored(unittest.TestCase):
    """The gate marker matches only right after the output kind (T131 review)."""

    def test_the_real_gate_header_in_a_product_grade(self):
        self.assertTrue(cscan.is_gate_path(GATE_HEADER, [PRODUCT_MARKER]))
        self.assertTrue(cscan.is_gate_path(GATE_HEADER))

    def test_the_gate_header_when_the_gate_is_the_root_cell(self):
        self.assertTrue(cscan.is_gate_path(ROOT_GATE, [ROOT_MARKER]))
        self.assertFalse(cscan.is_gate_path(ROOT_GATE))

    def test_a_product_directory_named_like_the_gate_is_not_the_gate(self):
        for marker, path in ((PRODUCT_MARKER, SPOOF), (ROOT_MARKER, SPOOF_ROOT)):
            with self.subTest(path=path):
                self.assertFalse(cscan.is_gate_path(path, [marker]))

    def test_no_recognisable_layout_is_the_products(self):
        for path in ("a/gate/rt/__require__/x/rt/require.h", "buck-out/v2/tmp/root/rt/__require__/x/rt/require.h",
                     "buck-out/v2/art/root", "buck-out/a/b/c/art/root/rt/__require__/x/h.h", "rt/__require__/rt/require.h"):
            with self.subTest(path=path):
                self.assertFalse(cscan.is_gate_path(path, [PRODUCT_MARKER, ROOT_MARKER]))

    def test_a_define_in_a_spoofed_header_is_reserved(self):
        text = (mark("a.c") + mark(SPOOF, 1, " 1") + "#define rigor_require(x) ((void)0)\n" + mark("a.c", 2, " 2")
                + "int f(void) { return 1; }\n")
        collector = cscan.Collector((ROOT,), (), [PRODUCT_MARKER])
        collector.scan(text)
        names = [i["name"] for i in collector.result()["identifiers"]]
        self.assertEqual(names, ["#define rigor_require"])

    def test_the_same_define_in_the_real_gate_header_is_not_reported(self):
        text = mark("a.c") + mark(GATE_HEADER, 1, " 1") + "#define rigor_require(x) ((void)0)\n" + mark("a.c", 2, " 2")
        collector = cscan.Collector((ROOT,), (), [PRODUCT_MARKER])
        collector.scan(text)
        self.assertEqual(collector.result()["identifiers"], [])


class Flag(unittest.TestCase):
    def test_the_trap_in_the_gate_header_is_flagged(self):
        result = scan(with_header(GATE_HEADER, "int f(void) { return 1; }\n"))
        self.assertEqual([(i["file"], i["gate"]) for i in by_name(result, "__builtin_trap")],
                         [("rt/require.h", True)])

    def test_a_product_header_of_the_same_name_is_not(self):
        result = scan(with_header(OWN_HEADER, "int f(void) { return 1; }\n"))
        self.assertEqual([(i["file"], i["gate"]) for i in by_name(result, "__builtin_trap")],
                         [("rt/require.h", False)])

    def test_both_at_one_place_is_the_products(self):
        text = (mark("a.c") + mark(GATE_HEADER, 1, " 1") + "void a(void){__builtin_trap();}\n" + mark("a.c", 2, " 2")
                + mark(OWN_HEADER, 7, " 1") + "void b(void){__builtin_trap();}\n")
        self.assertEqual([i["gate"] for i in by_name(scan(text), "__builtin_trap")], [True, False])
        same = (mark("a.c") + mark(GATE_HEADER, 5, " 1") + "void a(void){__builtin_trap();}\n" + mark("a.c", 2, " 2")
                + mark(OWN_HEADER, 5, " 1") + "void b(void){__builtin_trap();}\n")
        self.assertEqual([i["gate"] for i in by_name(scan(same), "__builtin_trap")], [False])

    def test_a_user_line_directive_does_not_make_a_gate_file(self):
        text = mark("a.c") + mark(GATE_HEADER, 1) + "void a(void){__builtin_trap();}\n"
        self.assertEqual([i["gate"] for i in by_name(scan(text), "__builtin_trap")], [False])


class Reserved(unittest.TestCase):
    def reserved(self, body):
        result = scan(with_header(GATE_HEADER, body))
        return sorted((i["name"], i["line"]) for i in result["identifiers"] if "rigor_require" in i["name"])

    def test_calling_it_is_the_only_use(self):
        body = "int f(int x) {\n    rigor_require(x > 0);\n    if (x) rigor_require(x < 4);\n    else rigor_require(1);\n    return x;\n}\n"
        self.assertEqual(self.reserved(body), [])

    def test_the_gates_own_definition_is_not_a_use(self):
        self.assertEqual(self.reserved(""), [])

    def test_a_declaration_a_definition_an_address_and_an_object(self):
        for body in ("void rigor_require(int);\n", "static inline void rigor_require(int c) { (void)c; }\n",
                     "int rigor_require;\n", "void (*p)(_Bool) = rigor_require;\n", "void (*p)(_Bool) = &rigor_require;\n",
                     "int f(void) { int rigor_require = 1; return rigor_require; }\n", "void (*rigor_require)(int);\n",
                     "int f(int x) { return x ? 1 : (int)rigor_require; }\n", "int g(void) { return rigor_require; }\n"):
            with self.subTest(body=body):
                found = self.reserved(body)
                self.assertTrue(found and all(name == "rigor_require" for name, _ in found), found)

    def test_define_and_undef(self):
        self.assertEqual(self.reserved("#define rigor_require(c) ((void)0)\n"), [("#define rigor_require", 2)])
        self.assertEqual(self.reserved("#undef rigor_require\n"), [("#undef rigor_require", 2)])

    def test_the_gate_file_may_define_it(self):
        text = mark("a.c") + mark(GATE_HEADER, 1, " 1") + "#define rigor_require x\n" + mark("a.c", 2, " 2")
        self.assertEqual(by_name(scan(text), "#define rigor_require"), [])

    def test_a_product_file_of_the_header_name_may_not(self):
        text = mark("a.c") + mark(OWN_HEADER, 1, " 1") + HEADER_BODY + mark("a.c", 2, " 2")
        self.assertEqual([i["name"] for i in scan(text)["identifiers"] if "rigor_require" in i["name"]],
                         ["rigor_require"])

    def test_a_name_that_only_contains_it_is_not_it(self):
        self.assertEqual(self.reserved("int my_rigor_require(void);\nint rigor_required;\n"), [])


class Sites(unittest.TestCase):
    def guards(self, body):
        return [(g["file"], g["line"], g["function"]) for g in scan(mark("a.c") + body)["guards"]]

    def test_call_sites_with_their_function(self):
        body = ("int f(int x) {\n    rigor_require(x > 0);\n    return x;\n}\n"
                "static int g(int x)\n{\n    if (x) {\n        rigor_require(x < 9);\n    }\n"
                "    for (;;) rigor_require(1);\n}\n")
        self.assertEqual(self.guards(body), [("a.c", 2, "f"), ("a.c", 8, "g"), ("a.c", 10, "g")])

    def test_a_call_in_a_macro_is_at_the_expansion_line(self):
        self.assertEqual(self.guards("int f(int x) { { rigor_require(x); } return x; }\n"), [("a.c", 1, "f")])

    def test_the_call_after_a_struct_and_an_initialiser_belongs_to_the_next_function(self):
        body = ("struct s { int a; };\nstatic const int t[2] = {1, 2};\nint h(int x) {\n    rigor_require(x);\n    return x;\n}\n")
        self.assertEqual(self.guards(body), [("a.c", 4, "h")])

    def test_the_gates_header_has_no_site(self):
        self.assertEqual(scan(with_header(GATE_HEADER, ""))["guards"], [])

    def test_no_guard_no_fact(self):
        self.assertEqual(self.guards("int f(void) { return 1; }\n"), [])


class Reader(TempDirTestCase):
    def read(self, mutate):
        document = facts("//p:lib", [unit(identifiers=[("x", 1)])])
        mutate(document)
        path = self.tmp / "f.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return facts_data.parse_facts(str(path), path.read_bytes())

    def test_older_facts_stay_readable(self):
        got = self.read(lambda d: None)
        self.assertEqual((got.units[0].guards, got.units[0].gate_identifiers), ((), frozenset()))

    def test_guards_and_the_flag(self):
        def add(d):
            d["units"][0]["guards"] = [{"file": "p/a.c", "line": 3, "function": "f"}]
            d["units"][0]["identifiers"][0]["gate"] = True
        got = self.read(add)
        self.assertEqual(got.units[0].guards, (("p/a.c", 3, "f"),))
        self.assertEqual(got.units[0].gate_identifiers, frozenset({("x", "p/a.c", 1)}))

    def test_padding_is_refused(self):
        from rigor_lib.errors import InternalError
        for mutate in (lambda d: d["units"][0].update(guards=[{"file": "a", "line": 1}]),
                       lambda d: d["units"][0].update(guards=[{"file": "a", "line": 1, "function": "f", "x": 1}]),
                       lambda d: d["units"][0]["identifiers"][0].update(extra=1)):
            with self.subTest():
                with self.assertRaises(InternalError):
                    self.read(mutate)


def structure(label, srcs, kind="c_library"):
    """srcs: name -> lines"""
    files = [{"path": name, "lines": lines, "bytes": lines * 10, "longest_line": 20} for name, lines in srcs.items()]
    return {"schema": 1, "label": label, "kind": kind, "deps": [], "srcs": sorted(srcs),
            "units": [{"src": name, "files": [f for f in files if f["path"] == name], "functions": [], "refs": []}
                      for name in sorted(srcs)]}


def guarded(label, sites, kind="c_library"):
    return facts(label, [dict(unit(name="a.c.o"), guards=[{"file": f, "line": n, "function": "f"} for f, n in sites])],
                 kind=kind)


class Judge(TempDirTestCase):
    def run_guards(self, modules, structures, policy, code=None):
        fdir, sdir = self.sub("facts"), self.sub("structure")
        for index, doc in enumerate(modules):
            (fdir / ("f%d.json" % index)).write_text(json.dumps(doc), encoding="utf-8")
        for index, doc in enumerate(structures):
            (sdir / ("s%d.json" % index)).write_text(json.dumps(doc), encoding="utf-8")
        (self.tmp / "p.toml").write_text(policy, encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["guards", "--facts", fdir, "--structure", sdir, "--policy", self.tmp / "p.toml", "--out", out])
        if code is not None:
            self.assertEqual(outcome.code, code, msg=outcome.stdout + outcome.stderr)
        return outcome, read_json(out)

    def rules(self, doc, severity="error"):
        return sorted((f["rule"], f["module"]) for f in doc["findings"] if f["severity"] == severity)

    def one(self, declared, sites, lines, code):
        policy = '[module."//p:lib"]\nguards = %d\n' % declared if declared is not None else '[module."//p:lib"]\nlevel = "L3"\n'
        _, doc = self.run_guards([guarded("//p:lib", [("p/a.c", n + 1) for n in range(sites)])],
                                 [structure("//p:lib", {"p/a.c": lines})], policy, code)
        return doc

    def test_within_budget_and_cap_passes(self):
        doc = self.one(2, 3, 120, 0)
        self.assertEqual(self.rules(doc), [])
        info = [f for f in doc["findings"] if f["rule"] == "guards"]
        self.assertEqual([(f["module"], f["sites"], f["declared"], f["cap"]) for f in info], [("//p:lib", 3, 2, 3)])

    def test_absent_means_zero(self):
        doc = self.one(None, 2, 10, 0)
        self.assertEqual([(f["declared"], f["sites"], f["cap"]) for f in doc["findings"]], [(0, 2, 0)])

    def test_over_sites(self):
        self.assertEqual(self.rules(self.one(3, 2, 400, 1)), [("guard-budget-over-sites", "//p:lib")])

    def test_over_cap(self):
        self.assertEqual(self.rules(self.one(4, 6, 159, 1)), [("guard-budget-over-cap", "//p:lib")])
        self.assertEqual(self.rules(self.one(4, 6, 160, 0)), [])
        self.assertEqual(guards_gate.DENSITY_LINES, 40)

    def test_both_findings_can_fire(self):
        self.assertEqual(self.rules(self.one(5, 1, 40, 1)),
                         [("guard-budget-over-cap", "//p:lib"), ("guard-budget-over-sites", "//p:lib")])

    def test_only_own_source_files_count(self):
        # a guard in a header (not a src) is not a site; the header's lines are not the module's lines
        _, doc = self.run_guards([guarded("//p:lib", [("p/a.h", 3)])], [structure("//p:lib", {"p/a.c": 400})],
                                 '[module."//p:lib"]\nguards = 1\n', 1)
        self.assertEqual(self.rules(doc), [("guard-budget-over-sites", "//p:lib")])

    def test_a_policy_module_without_facts_declaring_guards_fails(self):
        _, doc = self.run_guards([guarded("//p:other", [])], [structure("//p:other", {"p/o.c": 40})],
                                 '[module."//p:gone"]\nguards = 1\n', 1)
        self.assertEqual(self.rules(doc), [("guard-budget-over-sites", "//p:gone"), ("structure-missing", "//p:gone")])

    def test_sites_without_structure_fail_closed(self):
        _, doc = self.run_guards([guarded("//p:lib", [("p/a.c", 1)])], [structure("//p:x", {"p/x.c": 40})],
                                 '[module."//p:lib"]\nlevel = "L3"\n', 1)
        self.assertEqual(self.rules(doc), [("structure-missing", "//p:lib")])

    def test_a_binary_counts_and_a_test_does_not(self):
        _, doc = self.run_guards([guarded("//p:bin", [("p/b.c", 1)], kind="c_binary"),
                                  guarded("//p:t", [("p/t.c", 1)], kind="c_test")],
                                 [structure("//p:bin", {"p/b.c": 80}, kind="c_binary")],
                                 '[module."//p:bin"]\nguards = 1\n', 0)
        self.assertEqual([f["module"] for f in doc["findings"]], ["//p:bin"])

    def test_distinct_sites_are_counted_once_over_units(self):
        two = facts("//p:lib", [dict(unit(name="a.c.o"), guards=[{"file": "p/a.c", "line": 1, "function": "f"}]),
                                dict(unit(name="b.c.o"), guards=[{"file": "p/a.c", "line": 1, "function": "f"}])])
        _, doc = self.run_guards([two], [structure("//p:lib", {"p/a.c": 80})], '[module."//p:lib"]\nguards = 2\n', 1)
        self.assertEqual(self.rules(doc), [("guard-budget-over-sites", "//p:lib")])

    def test_bad_policy_values_are_exit_2(self):
        for value in ("-1", '"1"', "true", "1.5"):
            with self.subTest(value=value):
                outcome, _ = self.run_guards([guarded("//p:lib", [])], [structure("//p:lib", {"p/a.c": 40})],
                                             '[module."//p:lib"]\nguards = %s\n' % value)
                self.assertEqual(outcome.code, 2)

    def test_the_facts_judges_accept_the_key(self):
        _, _ = self.run_guards([guarded("//p:lib", [])], [structure("//p:lib", {"p/a.c": 40})],
                               '[global]\ndeny = ["kill"]\n[module."//p:lib"]\nguards = 1\n')
        from rigor_lib import facts_policy
        path = self.tmp / "p.toml"
        path.write_text('[global]\ndeny = ["kill"]\n[module."//p:lib"]\nguards = 3\n', encoding="utf-8")
        self.assertEqual(facts_policy.load_policy(str(path)).modules["//p:lib"].guards, 3)
        path.write_text('[global]\ndeny = ["kill"]\n[module."//p:lib"]\nguards = -3\n', encoding="utf-8")
        from rigor_lib.errors import InternalError
        with self.assertRaises(InternalError):
            facts_policy.load_policy(str(path))

    def test_deterministic(self):
        self.one(2, 3, 120, 0)
        first = (self.tmp / "out.json").read_bytes()
        self.one(2, 3, 120, 0)
        self.assertEqual(first, (self.tmp / "out.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
