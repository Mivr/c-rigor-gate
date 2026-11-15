"""U03: the `uim_` prefix is reserved by the symbols gate (docs/ui-model.md, "Confinement"), whatever the policy says,
and only the gate's own targets can be exempt (labels compared exactly)."""

from tests import test_facts
from tests.helpers import TempDirTestCase
from tests.test_facts import CTEST, GLOBAL, facts, unit

PROBE_LIB = "gate//ui/model:probe"
HEADERS = "gate//ui/model:model"
MODEL = "//p:model"
BIN = "//p:probe"


def policy(*labels, trusted=()):
    head = GLOBAL.replace('trusted = ["//ctest:ctest"]', 'trusted = ["//ctest:ctest"%s]' % "".join(', "%s"' % t for t in trusted))
    return head + "".join('[module."%s"]\nallow = ["printf"]\n' % label for label in labels)


class UiPrefix(TempDirTestCase):
    run_gate = test_facts.FactsCase.run_gate

    def run_ui(self, targets, *labels, code, trusted=()):
        outcome, result = self.run_gate("symbols", targets + [CTEST], policy=policy(*labels, trusted=trusted),
                                        expect_code=code)
        return result

    def ui(self, targets, *labels, code, trusted=()):
        """Sorted (rule, symbol, use) of the ui findings, for the policy that lists `labels` (no `uim_` entry anywhere)."""
        result = self.run_ui(targets, *labels, code=code, trusted=trusted)
        return sorted((f["rule"], f["symbol"], f["use"]) for f in result["findings"] if f["rule"] == "ui-model-symbol")

    def probe_set(self, probe=PROBE_LIB, headers=HEADERS, bin_deps=None):
        """The adapter, the gate's probe library, the headers and the probe binary of a `c_ui_probe`."""
        adapter = facts(MODEL, [unit(defined=["uim_open", "uim_step"])], deps=[headers])
        main = facts(probe, [unit(defined=["main"], undefined=["uim_open", "uim_step"])], deps=[headers])
        header = facts(headers, [])
        binary = facts(BIN, [], deps=bin_deps or [MODEL, probe], kind="c_binary")
        return [adapter, main, header, binary]

    LABELS = (MODEL, PROBE_LIB, HEADERS, BIN)

    def test_the_adapter_and_the_probe_main_of_a_c_ui_probe_pass(self):
        self.assertEqual(self.ui(self.probe_set(), *self.LABELS, code=0), [])

    def test_a_product_library_that_references_a_model_symbol_is_flagged_without_any_deny_entry(self):
        bad = facts("//p:lib", [unit(defined=["f"], undefined=["uim_open"])], deps=[MODEL])
        self.assertEqual(self.ui(self.probe_set() + [bad], *self.LABELS, "//p:lib", code=1),
                         [("ui-model-symbol", "uim_open", "referenced")])

    def test_a_product_library_that_defines_a_model_symbol_is_flagged_even_without_an_exports_key(self):
        bad = facts("//p:lib", [unit(defined=["uim_frame"])])
        self.assertEqual(self.ui([bad], "//p:lib", code=1), [("ui-model-symbol", "uim_frame", "defined")])

    def test_a_module_that_defines_and_calls_its_own_model_symbol_gets_both_findings(self):
        bad = facts("//p:lib", [unit("a.c.o", defined=["uim_apply"]), unit("b.c.o", undefined=["uim_apply"])])
        self.assertEqual(self.ui([bad], "//p:lib", code=1),
                         [("ui-model-symbol", "uim_apply", "defined"), ("ui-model-symbol", "uim_apply", "referenced")])

    def test_every_symbol_with_the_prefix_counts_not_a_list_of_names(self):
        bad = facts("//p:lib", [unit(undefined=["uim_made_up_name", "uim_", "uimx"])])
        self.assertEqual(self.ui([bad], "//p:lib", code=1),
                         [("ui-model-symbol", "uim_", "referenced"), ("ui-model-symbol", "uim_made_up_name", "referenced")])

    def test_a_dependent_of_the_adapter_is_not_exempt(self):
        bad = facts("//p:user", [unit(undefined=["uim_open"])], deps=[MODEL])
        self.assertEqual(self.ui(self.probe_set() + [bad], *self.LABELS, "//p:user", code=1),
                         [("ui-model-symbol", "uim_open", "referenced")])

    def test_the_same_library_without_a_c_ui_probe_is_not_exempt(self):
        adapter = facts(MODEL, [unit(defined=["uim_open"])])
        plain = facts("//p:bin", [], deps=[MODEL], kind="c_binary")
        self.assertEqual(self.ui([adapter, plain], MODEL, "//p:bin", code=1), [("ui-model-symbol", "uim_open", "defined")])

    def test_the_headers_library_is_not_a_model_adapter(self):
        targets = self.probe_set(bin_deps=[MODEL, PROBE_LIB, HEADERS])   # listed as a dep too
        targets[2] = facts(HEADERS, [unit(defined=["uim_sneaky"])])
        self.assertEqual(self.ui(targets, *self.LABELS, code=1), [("ui-model-symbol", "uim_sneaky", "defined")])

    def test_a_test_module_is_not_exempt(self):
        bad = facts("//p:test", [unit(undefined=["uim_open"])], deps=[MODEL], kind="c_test")
        self.assertEqual(self.ui(self.probe_set() + [bad], *self.LABELS, "//p:test", code=1),
                         [("ui-model-symbol", "uim_open", "referenced")])

    def test_the_exempt_probe_library_still_gets_the_other_checks(self):
        targets = self.probe_set()
        targets[1] = facts(PROBE_LIB, [unit(defined=["main"], undefined=["uim_open", "kill"])], deps=[HEADERS])
        result = self.run_ui(targets, *self.LABELS, code=1)
        self.assertEqual([(f["rule"], f["symbol"]) for f in result["findings"] if f["severity"] == "error"],
                         [("denied-symbol", "kill")])

    # --- only the gate's own targets can match: every spelling of the probe library's label ---

    def impostor(self, label):
        """A product library with this label defines `main` and calls the model: the exemption must not reach it, and a
        product library that the 'probe binary' lists beside it must not be exempt either."""
        core = facts("//app/core:core", [unit(defined=["uim_step"], undefined=["uim_open"])])
        fake = facts(label, [unit(defined=["main"], undefined=["uim_open"])])
        binary = facts(BIN, [], deps=[label, "//app/core:core"], kind="c_binary")
        return [core, fake, binary], ("//app/core:core", label, BIN)

    def test_no_other_spelling_of_the_probe_library_is_the_gates(self):
        for label in ("//ui/model:probe", "root//ui/model:probe", "gate//ui/model:probe2",
                      "gate//ui/model/x:probe"):
            with self.subTest(label=label):
                self.setUp()
                targets, labels = self.impostor(label)
                outcome, result = self.run_gate("symbols", targets + [CTEST], policy=policy(*labels), expect_code=1)
                got = {(f["target"], f["symbol"]) for f in result["findings"] if f["rule"] == "ui-model-symbol"}
                self.assertEqual(got, {("//app/core:core", "uim_step"), ("//app/core:core", "uim_open"),
                                       (label, "uim_open")})

    def test_a_probe_binary_must_have_exactly_one_adapter(self):
        for deps in ([PROBE_LIB], [MODEL, "//app/core:core", PROBE_LIB]):
            with self.subTest(deps=deps):
                self.setUp()
                core = facts("//app/core:core", [unit(defined=["uim_step"])])
                targets = self.probe_set(bin_deps=deps) + [core]
                result = self.run_ui(targets, *self.LABELS, "//app/core:core", code=1)
                shapes = [f for f in result["findings"] if f["rule"] == "ui-probe-shape"]
                self.assertEqual([f["target"] for f in shapes], [BIN])
                self.assertIn(("ui-model-symbol", "uim_step", "defined"),
                              [(f["rule"], f["symbol"], f["use"]) for f in result["findings"] if f["rule"] == "ui-model-symbol"])

    def test_a_trusted_list_cannot_bypass_the_prefix(self):
        bad = facts("//p:lib", [unit(undefined=["uim_open"])])
        self.assertEqual(self.ui([bad], code=1, trusted=["//p:lib"]), [("ui-model-symbol", "uim_open", "referenced")])

    def test_the_at_spelling_is_not_a_label_at_all(self):
        targets, labels = self.impostor("@gate//ui/model:probe")
        self.run_gate("symbols", targets + [CTEST], policy=policy(*labels), expect_code=2)

    # --- U05a: the probe library's dependency on the gate's lvprobe, given without facts, grants nothing ---

    def lvprobe_case(self, dep, user=PROBE_LIB, allow=("printf",), code=1):
        """Error findings (rule, symbol or dep) when `user` (the probe library, or a product library beside it) depends on
        `dep`, of which no facts are given, and references `lvprobe_open`; the policy of `user` allows `allow`."""
        targets = self.probe_set()
        if user == PROBE_LIB:
            targets[1] = facts(PROBE_LIB, [unit(defined=["main"], undefined=["uim_open", "lvprobe_open"])],
                               deps=[HEADERS, dep])
        else:
            targets.append(facts(user, [unit(defined=["f"], undefined=["lvprobe_open"])], deps=[dep]))
        others = [label for label in self.LABELS + (user,) if label != user]
        text = policy(*others) + '[module."%s"]\nallow = [%s]\n' % (user, ", ".join('"%s"' % a for a in allow))
        outcome, result = self.run_gate("symbols", targets + [CTEST], policy=text, expect_code=code)
        return sorted((f["rule"], f.get("symbol", f.get("dep", ""))) for f in result["findings"] if f["severity"] == "error")

    def test_the_probe_librarys_lvprobe_without_facts_is_no_missing_dep_and_grants_nothing(self):
        for dep in ("gate//ui/lvprobe:lvprobe", "//ui/lvprobe:lvprobe"):
            with self.subTest(dep=dep):
                self.setUp()
                self.assertEqual(self.lvprobe_case(dep), [("undeclared-symbol", "lvprobe_open")])
                self.setUp()
                self.assertEqual(self.lvprobe_case(dep, allow=("uim_open", "lvprobe_open"), code=0), [])

    def test_any_other_label_or_module_without_facts_is_still_a_missing_dep(self):
        self.assertEqual(self.lvprobe_case("gate//ui/lvprobe:lvprobe2", allow=("lvprobe_open",)),
                         [("missing-dep-facts", "gate//ui/lvprobe:lvprobe2")])
        self.setUp()
        self.assertEqual(self.lvprobe_case("gate//ui/lvprobe:lvprobe", user="//p:lib", allow=()),
                         [("missing-dep-facts", "gate//ui/lvprobe:lvprobe"), ("undeclared-symbol", "lvprobe_open")])
