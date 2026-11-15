"""U03: `rigor buckfiles` accepts `c_ui_probe` from `@gate//rules:ui.bzl` and the gate's model header, nothing more."""

from tests import test_buckfiles

C_LOAD = 'load("@gate//rules:c.bzl", "c_library")\n'
UI_LOAD = 'load("@gate//rules:ui.bzl", "c_ui_probe")\n'
MODEL = 'c_library(name = "model", srcs = ["m.c"], deps = ["gate//ui/model:model"])\n'
PROBE = 'c_ui_probe(name = "probe", model = ":model")\n'


class UiBuckFiles(test_buckfiles.BuckFilesCase):
    def bad(self, source, *rules):
        self.assertEqual(self.check({"BUCK": source}, 1), sorted(rules))

    def test_the_two_loads_a_probe_and_its_adapter_use_are_clean_in_either_order(self):
        self.assertEqual(self.check({"BUCK": C_LOAD + UI_LOAD + MODEL + PROBE}, 0), [])
        self.setUp()
        self.assertEqual(self.check({"BUCK": UI_LOAD + C_LOAD + MODEL + PROBE}, 0), [])

    def test_the_probe_may_name_a_model_of_another_package_and_extra_deps(self):
        source = C_LOAD + UI_LOAD + 'c_ui_probe(name = "p", model = "//m:model", deps = [":x"], visibility = ["PUBLIC"])\n'
        self.assertEqual(self.check({"BUCK": source}, 0), [])

    def test_a_second_load_of_the_same_file_is_still_extra(self):
        self.bad(C_LOAD + C_LOAD + MODEL, "extra-load")
        self.setUp()
        self.bad(UI_LOAD + UI_LOAD + PROBE, "extra-load")

    def test_a_third_load_is_extra(self):
        self.bad(C_LOAD + UI_LOAD + 'load("//x:y.bzl", "z")\n' + MODEL, "bad-load", "extra-load")

    def test_the_macro_is_loaded_only_from_its_own_file(self):
        self.bad('load("@gate//rules:c.bzl", "c_ui_probe")\n' + PROBE, "bad-load")
        self.setUp()
        self.bad('load("@gate//rules:ui.bzl", "c_library")\n' + MODEL, "bad-load")
        self.setUp()
        self.bad('load("@gate//rules:ui.bzl", "c_ui_probe")\nload("@gate//rules:ui.bzl", "c_ui_probe")\n' + PROBE,
                 "extra-load")

    def test_other_gate_rule_files_cannot_be_loaded(self):
        self.bad(C_LOAD + 'load("@gate//rules:sim.bzl", "sim_run")\n' + MODEL, "bad-load", "extra-load")

    def test_the_probe_takes_no_sources_flags_or_positional_arguments(self):
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = ":m", srcs = ["a.c"])\n', "bad-argument")
        self.setUp()
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = ":m", compiler_flags = ["-w"])\n', "bad-argument")
        self.setUp()
        self.bad(UI_LOAD + 'c_ui_probe("p", ":m")\n', "bad-argument")
        self.setUp()
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = [":m"])\n', "bad-argument")

    def test_the_probe_model_and_deps_are_checked_like_any_dep(self):
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = "prelude//cxx:cxx")\n', "bad-argument")
        self.setUp()
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = ":m", deps = ["gate//ctest:ctest"])\n', "bad-argument")

    def test_the_gates_probe_library_cannot_be_named_by_a_product(self):
        self.bad(C_LOAD + 'c_library(name = "a", deps = ["gate//ui/model:probe"])\n', "bad-argument")
        self.setUp()
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = ":m", deps = ["gate//ui/model:probe"])\n', "bad-argument")

    def test_the_model_header_library_is_for_libraries_binaries_and_tests_only(self):
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = ":m", deps = ["gate//ui/model:model"])\n', "bad-argument")
        self.setUp()
        self.assertEqual(self.check({"BUCK": 'load("@gate//rules:c.bzl", "c_test")\nc_test(name = "t", deps = ["gate//ui/model:model"])\n'}, 0), [])

    def test_nothing_may_depend_on_a_probe_or_what_it_derives(self):
        self.bad(C_LOAD + UI_LOAD + PROBE + 'c_library(name = "x", deps = [":probe"])\n', "bad-argument")
        self.setUp()
        self.bad(C_LOAD + UI_LOAD + PROBE + 'c_library(name = "x", deps = [":probe_facts"])\n', "bad-argument")
