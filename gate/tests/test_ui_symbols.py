"""U03: the `uim_` prefix is reserved by the symbols gate (docs/ui-model.md, "Confinement"), whatever the policy says."""

from tests import test_facts
from tests.helpers import TempDirTestCase
from tests.test_facts import CTEST, GLOBAL, facts, unit

PROBE_LIB = "//ui/model:probe"
HEADERS = "//ui/model:model"


def policy(*labels):
    return GLOBAL + "".join('[module."%s"]\nallow = ["printf"]\n' % label for label in labels)


class UiPrefix(TempDirTestCase):
    run_gate = test_facts.FactsCase.run_gate

    def ui(self, targets, *labels, code):
        """Sorted (rule, symbol, use) of the ui findings, for the policy that lists `labels` (no `uim_` entry anywhere)."""
        outcome, result = self.run_gate("symbols", targets + [CTEST], policy=policy(*labels), expect_code=code)
        return sorted((f["rule"], f["symbol"], f["use"]) for f in result["findings"] if f["rule"] == "ui-model-symbol")

    def probe_set(self, spelling=lambda label: label):
        """The adapter, the gate's probe library, the headers and the probe binary of a `c_ui_probe`."""
        adapter = facts("//p:model", [unit(defined=["uim_open", "uim_step"])], deps=[spelling(HEADERS)])
        main = facts(spelling(PROBE_LIB), [unit(defined=["main"], undefined=["uim_open", "uim_step"])],
                     deps=[spelling(HEADERS)])
        header = facts(spelling(HEADERS), [])
        binary = facts("//p:probe", [], deps=["//p:model", spelling(PROBE_LIB)], kind="c_binary")
        return [adapter, main, header, binary]

    LABELS = ("//p:model", PROBE_LIB, HEADERS, "//p:probe")

    def test_the_adapter_and_the_probe_main_of_a_c_ui_probe_pass(self):
        self.assertEqual(self.ui(self.probe_set(), *self.LABELS, code=0), [])

    def test_the_gate_spelling_of_the_labels_is_the_same(self):
        gate = lambda label: "gate" + label
        labels = ("//p:model", gate(PROBE_LIB), gate(HEADERS), "//p:probe")
        self.assertEqual(self.ui(self.probe_set(gate), *labels, code=0), [])

    def test_a_product_library_that_references_a_model_symbol_is_flagged_without_any_deny_entry(self):
        bad = facts("//p:lib", [unit(defined=["f"], undefined=["uim_open"])], deps=["//p:model"])
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
        bad = facts("//p:user", [unit(undefined=["uim_open"])], deps=["//p:model"])
        self.assertEqual(self.ui(self.probe_set() + [bad], *self.LABELS, "//p:user", code=1),
                         [("ui-model-symbol", "uim_open", "referenced")])

    def test_the_same_library_without_a_c_ui_probe_is_not_exempt(self):
        adapter = facts("//p:model", [unit(defined=["uim_open"])])
        plain = facts("//p:bin", [], deps=["//p:model"], kind="c_binary")
        self.assertEqual(self.ui([adapter, plain], "//p:model", "//p:bin", code=1),
                         [("ui-model-symbol", "uim_open", "defined")])

    def test_the_headers_library_is_not_a_model_adapter(self):
        targets = self.probe_set()
        targets[2] = facts(HEADERS, [unit(defined=["uim_sneaky"])])
        targets[3] = facts("//p:probe", [], deps=["//p:model", PROBE_LIB, HEADERS], kind="c_binary")   # listed as a dep too
        self.assertEqual(self.ui(targets, *self.LABELS, code=1), [("ui-model-symbol", "uim_sneaky", "defined")])

    def test_a_test_module_is_not_exempt(self):
        bad = facts("//p:test", [unit(undefined=["uim_open"])], deps=["//p:model"], kind="c_test")
        self.assertEqual(self.ui(self.probe_set() + [bad], *self.LABELS, "//p:test", code=1),
                         [("ui-model-symbol", "uim_open", "referenced")])

    def test_the_exempt_probe_library_still_gets_the_other_checks(self):
        targets = self.probe_set()
        targets[1] = facts(PROBE_LIB, [unit(defined=["main"], undefined=["uim_open", "kill"])], deps=[HEADERS])
        outcome, result = self.run_gate("symbols", targets + [CTEST], policy=policy(*self.LABELS), expect_code=1)
        self.assertEqual([(f["rule"], f["symbol"]) for f in result["findings"] if f["severity"] == "error"],
                         [("denied-symbol", "kill")])
