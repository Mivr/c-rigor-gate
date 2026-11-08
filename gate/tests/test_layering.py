"""Gate `layering` (T087): the architecture contract and its findings, on hand-made facts."""

import os
import unittest
from types import SimpleNamespace

from rigor_lib import facts_data, facts_third_party, grade_checks, layering, layering_check
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase

GOOD = GATE_DIR / "tests" / "fixtures" / "layering" / "good.toml"
THIRD = facts_third_party.ThirdParty(frozenset(), ("mbedtls_",))

CORE, FMT, DS, DOM, ROOT = "//lib/base/core:core", "//lib/base/fmt:fmt", "//lib/ds/list:list", \
    "//apps/a/domain:model", "//apps/a/root:root"
KIT, CORE_TEST = "//lib/base/core:testkit", "//lib/base/core:core_test"


def unit(defined=(), undefined=(), name="a.c.o"):
    return facts_data.Unit(name, frozenset(defined), frozenset(), frozenset(undefined), (), (), (), ())


def mod(label, deps=(), defined=(), undefined=(), kind="c_library"):
    return facts_data.Facts(label, kind, tuple(sorted(deps)), (unit(defined, undefined),))


def world(*modules):
    return {m.label: m for m in modules}


def green():
    return world(
        mod(CORE, defined=["core_add"]), mod(FMT, [CORE], ["fmt_int"], ["core_add"]),
        mod(DS, [CORE], ["ds_init", "ds_push"], ["core_add"]),
        mod(DOM, [CORE, DS], ["dom_new"], ["ds_init"]),
        mod(ROOT, [DOM, DS], ["main"], ["dom_new", "ds_push"], "c_binary"),
        mod(KIT, [CORE], ["kit_fake"]), mod(CORE_TEST, [CORE, KIT], [], ["core_add", "kit_fake"], "c_test"))


def judge(facts, arch=None, text=None, trusted=frozenset()):
    arch = layering.load(GOOD) if arch is None else arch
    result = layering_check.run(facts, arch, trusted, THIRD)
    return result, sorted((f["rule"], f.get("target") or f.get("entry"), f.get("dep") or f.get("symbol"))
                          for f in result.findings)


class Green(unittest.TestCase):
    def test_a_conforming_world_is_green(self):
        result, found = judge(green())
        self.assertEqual(found, [])
        self.assertEqual(result.metadata["modules"], 5)

    def test_tests_and_testkits_may_depend_on_anything(self):
        facts = green()
        facts[CORE_TEST] = mod(CORE_TEST, [CORE, KIT, ROOT, DOM], [], [], "c_test")
        facts[KIT] = mod(KIT, [ROOT, DOM])
        self.assertEqual(judge(facts)[1], [])

    def test_a_trusted_module_is_outside_the_contract(self):
        facts = green()
        facts["gate//ctest:ctest"] = mod("gate//ctest:ctest")
        facts[CORE_TEST] = mod(CORE_TEST, [CORE, KIT, "gate//ctest:ctest"], [], [], "c_test")
        facts[DS] = mod(DS, [CORE, "gate//ctest:ctest"], ["ds_init", "ds_push"], ["core_add"])
        self.assertEqual(judge(facts, trusted=frozenset(["gate//ctest:ctest"]))[1], [])

    def test_a_module_edge_works_like_a_layer_edge(self):
        text = GOOD.read_text().replace('from = "lib-ds"\nto = "lib-base"', 'from = "' + DS + '"\nto = "' + CORE + '"')
        facts = green()
        facts[DS] = mod(DS, [CORE], ["ds_init", "ds_push"], ["core_add"])
        self.assertEqual(judge(facts, layering.parse(text))[1], [])
        facts[FMT] = mod(FMT, [CORE], ["fmt_int"])
        self.assertEqual(judge(facts, layering.parse(text))[1], [])


class Findings(unittest.TestCase):
    def test_ungoverned_module(self):
        facts = green()
        facts["//lib/other:x"] = mod("//lib/other:x", [CORE])
        self.assertEqual(judge(facts)[1], [("ungoverned-module", "//lib/other:x", None)])

    def test_an_ungoverned_dep_is_reported_once_and_not_as_an_edge(self):
        facts = green()
        facts["//lib/other:x"] = mod("//lib/other:x")
        facts[FMT] = mod(FMT, [CORE, "//lib/other:x"], ["fmt_int"], ["core_add"])
        self.assertEqual(judge(facts)[1], [("ungoverned-module", "//lib/other:x", None)])

    def test_undeclared_edge_names_both_layers(self):
        facts = green()
        facts[FMT] = mod(FMT, [CORE, DS], ["fmt_int"], ["core_add"])   # lib-base -> lib-ds
        result, found = judge(facts)
        self.assertEqual([(r, t, d) for r, t, d in found], [("undeclared-edge", FMT, DS), ("upward-edge", FMT, DS)])
        edge = next(f for f in result.findings if f["rule"] == "undeclared-edge")
        self.assertEqual((edge["from_layer"], edge["to_layer"]), ("lib-base", "lib-ds"))

    def test_an_exported_dep_is_an_edge_from_the_exporter_only(self):
        # T110: `c_library(exported_deps=)` reaches the facts as an ordinary dep of the exporting library. Its
        # dependent keeps its own edges: no edge to the exported library is gained by inheriting its header.
        facts = green()
        facts[FMT] = mod(FMT, [CORE, DS], ["fmt_int"], ["core_add"])   # FMT exports DS: lib-base -> lib-ds
        # ROOT lists only what its own sources use; every finding is about the exporter, none about its dependents
        self.assertEqual({t for _, t, _ in judge(facts)[1]}, {FMT})

    def test_a_sideways_edge_in_one_layer_must_be_declared(self):
        facts = green()
        facts["//apps/a/domain:two"] = mod("//apps/a/domain:two", [DOM])
        self.assertEqual(judge(facts)[1], [("undeclared-edge", "//apps/a/domain:two", DOM)])

    def test_upward_edge_even_when_declared_by_module(self):
        text = GOOD.read_text() + '\n[[edge]]\nfrom = "%s"\nto = "%s"\nkind = "pure"\n' % (CORE, DS)
        facts = green()
        facts[CORE] = mod(CORE, [DS], ["core_add"], ["ds_init"])
        self.assertEqual(judge(facts, layering.parse(text))[1], [("upward-edge", CORE, DS)])

    def test_a_production_module_depending_on_a_testkit_or_test(self):
        facts = green()
        facts[FMT] = mod(FMT, [CORE, KIT], ["fmt_int"], ["core_add"])
        self.assertEqual(judge(facts)[1], [("undeclared-edge", FMT, KIT)])
        facts[FMT] = mod(FMT, [CORE, CORE_TEST], ["fmt_int"], ["core_add"])
        self.assertEqual(judge(facts)[1], [("undeclared-edge", FMT, CORE_TEST)])

    def test_data_edge_that_calls(self):
        facts = green()
        facts[DOM] = mod(DOM, [CORE, DS], ["dom_new"], ["core_add", "ds_init"])
        result, found = judge(facts)
        self.assertEqual(found, [("edge-kind-violation", DOM, CORE)])
        self.assertEqual((result.findings[0]["symbol"], result.findings[0]["unit"]), ("core_add", "a.c.o"))

    def test_a_symbol_the_module_defines_itself_is_not_a_reference(self):
        facts = green()
        facts[DOM] = mod(DOM, [CORE, DS], ["dom_new", "core_add"], ["core_add", "ds_init"])
        self.assertEqual(judge(facts)[1], [])

    def test_port_edge_beyond_its_symbols(self):
        facts = green()
        facts[DOM] = mod(DOM, [CORE, DS], ["dom_new"], ["ds_init", "ds_push"])
        result, found = judge(facts)
        self.assertEqual(found, [("edge-kind-violation", DOM, DS)])
        self.assertEqual(result.findings[0]["symbol"], "ds_push")

    def test_composition_only_from_listed_modules(self):
        facts = green()
        text = GOOD.read_text().replace('[composition]\nmodules = ["//apps/a/root:root"]',
                                        '[composition]\nmodules = ["//apps/a/domain:*"]')
        result, found = judge(facts, layering.parse(text))
        self.assertEqual(found, [("edge-kind-violation", ROOT, DOM)])
        self.assertEqual(result.findings[0]["reason"], "composition-not-permitted")

    def test_the_most_permissive_allowing_edge_wins(self):
        text = GOOD.read_text() + '\n[[edge]]\nfrom = "app-domain"\nto = "lib-base"\nkind = "pure"\n'
        facts = green()
        facts[DOM] = mod(DOM, [CORE, DS], ["dom_new"], ["core_add", "ds_init"])
        self.assertEqual(judge(facts, layering.parse(text))[1], [])

    def test_stale_entries(self):
        text = GOOD.read_text().replace('"//lib/base/fmt:*"', '"//lib/base/gone:*", "//lib/base/fmt:*"')
        text = text.replace('modules = ["//lib/base/core:testkit"]', 'modules = ["//nowhere/**"]')
        facts = green()
        self.assertEqual(sorted((r, t) for r, t, _ in judge(facts, layering.parse(text))[1]),
                         [("contract-stale", "//lib/base/gone:*"), ("contract-stale", "//nowhere/**"),
                          ("ungoverned-module", KIT)])

    def test_a_stale_edge_endpoint(self):
        text = GOOD.read_text() + '\n[[edge]]\nfrom = "app-root"\nto = "//lib/ds/list:gone"\nkind = "pure"\n'
        self.assertEqual(judge(green(), layering.parse(text))[1], [("contract-stale", "//lib/ds/list:gone", None)])

    def test_two_layers_for_one_module_is_a_contract_defect(self):
        text = GOOD.read_text().replace('"//apps/a/root:root"]\n\n[testkit]', '"//apps/a/root:root", "//lib/ds/**"]\n\n[testkit]')
        with self.assertRaises(InternalError):
            judge(green(), layering.parse(text))


class Contract(unittest.TestCase):
    def bad(self, text):
        with self.assertRaises(InternalError):
            layering.parse(text)

    def test_the_good_contract_loads(self):
        arch = layering.load(GOOD)
        self.assertEqual(arch.order, ("lib-base", "lib-ds", "app-domain", "app-root"))
        self.assertEqual(len(arch.edges), 6)

    def test_matching(self):
        self.assertTrue(layering.matches("//a/b:c", "//a/b:c"))
        self.assertFalse(layering.matches("//a/b:c", "//a/b:d"))
        self.assertTrue(layering.matches("//a/b:*", "//a/b:d"))
        self.assertFalse(layering.matches("//a/b:*", "//a/b/c:d"))
        self.assertTrue(layering.matches("//a/**", "//a:d"))
        self.assertTrue(layering.matches("//a/**", "//a/b/c:d"))
        self.assertFalse(layering.matches("//a/**", "//ab:d"))

    def test_defects(self):
        text = GOOD.read_text()
        self.bad("")
        self.bad("[layers]\norder = []\n")
        self.bad(text + "\n[extra]\n")
        self.bad(text.replace('order = ["lib-base", "lib-ds", "app-domain", "app-root"]', 'order = ["lib-base"]'))
        self.bad(text.replace('"//apps/a/root:root"]\n\n[testkit]', '"apps/**"]\n\n[testkit]'))
        self.bad(text.replace('kind = "pure"', 'kind = "impure"', 1))
        self.bad(text.replace('kind = "data"', 'kind = "data"\nsymbols = ["x"]'))
        self.bad(text.replace('symbols = ["ds_init"]', 'symbols = []'))
        self.bad(text.replace('to = "lib-base"\nkind = "data"', 'to = "nonsense"\nkind = "data"'))
        self.bad(text + '\n[[edge]]\nfrom = "lib-base"\nto = "app-root"\nkind = "pure"\n')   # upward layer edge
        self.bad(text + '\n[[edge]]\nfrom = "lib-ds"\nto = "lib-base"\nkind = "pure"\n')    # duplicate
        self.bad("not toml [")

    def test_a_contract_that_is_not_utf8(self):
        path = os.path.join(os.environ.get("TMPDIR", "/var/tmp"), "layering-bad-%d.toml" % os.getpid())
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe")
        try:
            with self.assertRaises(InternalError):
                layering.load(path)
        finally:
            os.unlink(path)


class Wiring(TempDirTestCase):
    def grading(self, architecture, toolchain="PASS"):
        directory = self.sub("product")
        (directory / "product.toml").write_text('name = "p"\n')
        if architecture is not None:
            (directory / "architecture.toml").write_text(architecture)
        return SimpleNamespace(args=SimpleNamespace(product=str(directory / "product.toml")),
                               status={"toolchain": toolchain, "assemble": "PASS"})

    def test_no_architecture_passes_with_an_info_finding_and_touches_nothing(self):
        result = grade_checks.layering_gate(self.grading(None, toolchain="NOT_RUN"))
        self.assertEqual((result.gate, result.status), ("layering", "PASS"))
        self.assertEqual([(f["rule"], f["severity"]) for f in result.findings], [("no-architecture", "info")])

    def test_with_an_architecture_it_needs_the_toolchain(self):
        self.assertIsNone(grade_checks.layering_gate(self.grading(GOOD.read_text(), toolchain="FAIL")))

    def test_with_an_architecture_it_needs_the_assembled_tree(self):
        g = self.grading(GOOD.read_text())
        g.status["assemble"] = "FAIL"
        self.assertIsNone(grade_checks.layering_gate(g))

    def test_a_broken_architecture_is_an_internal_error_even_without_a_toolchain(self):
        with self.assertRaises(InternalError):
            grade_checks.layering_gate(self.grading("nonsense = 1\n", toolchain="FAIL"))


if __name__ == "__main__":
    unittest.main()
