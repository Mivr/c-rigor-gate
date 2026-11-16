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

    def test_the_probe_may_name_a_model_of_another_package(self):
        self.assertEqual(self.check({"BUCK": C_LOAD + UI_LOAD + 'c_ui_probe(name = "p", model = "//m:model")\n'}, 0), [])

    def test_the_probe_has_no_deps_and_no_visibility(self):
        """Only the adapter is exempt from the `uim_` reservation: other code cannot ride along through `deps`."""
        for extra in ('deps = [":x"]', 'deps = []', 'visibility = ["PUBLIC"]'):
            with self.subTest(extra=extra):
                self.setUp()
                self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = ":m", %s)\n' % extra, "bad-argument")

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
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = "root//m:model")\n', "bad-argument")

    def test_the_gates_probe_library_cannot_be_named_by_a_product(self):
        self.bad(C_LOAD + 'c_library(name = "a", deps = ["gate//ui/model:probe"])\n', "bad-argument")
        self.setUp()
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = "gate//ui/model:probe")\n', "bad-argument")

    def test_the_model_header_library_is_for_libraries_binaries_and_tests_only(self):
        self.bad(UI_LOAD + 'c_ui_probe(name = "p", model = "gate//ui/model:model")\n', "bad-argument")
        self.setUp()
        self.assertEqual(self.check({"BUCK": 'load("@gate//rules:c.bzl", "c_test")\nc_test(name = "t", deps = ["gate//ui/model:model"])\n'}, 0), [])

    def test_nothing_may_depend_on_a_probe_or_what_it_derives(self):
        self.bad(C_LOAD + UI_LOAD + PROBE + 'c_library(name = "x", deps = [":probe"])\n', "bad-argument")
        self.setUp()
        self.bad(C_LOAD + UI_LOAD + PROBE + 'c_library(name = "x", deps = [":probe_facts"])\n', "bad-argument")

    def test_no_spelling_of_the_gates_probe_library_is_a_dep(self):
        for label in ("//ui/model:probe", "root//ui/model:probe", "@gate//ui/model:probe", "gate//ui/model:probe",
                      "//ui/model:model", "//ui/model/x:y"):
            with self.subTest(label=label):
                self.setUp()
                self.bad(C_LOAD + 'c_library(name = "a", deps = ["%s"])\n' % label, "bad-argument")

    def test_a_product_has_no_ui_model_package(self):
        """`:probe` inside a product `ui/model` package would print as `//ui/model:probe`: the package is refused."""
        for name in ("BUCK", "probe.c", "sub/x.h"):
            with self.subTest(name=name):
                self.setUp()
                self.assertEqual(self.check({"ui/model/" + name: C_LOAD + 'c_library(name = "probe")\n'}, 1), ["reserved-package"])
        self.setUp()
        self.assertEqual(self.check({"ui/modelx/BUCK": C_LOAD + 'c_library(name = "probe")\n', "ui/BUCK": C_LOAD}, 0), [])


SESSION_LOAD = 'load("@gate//rules:ui.bzl", "c_ui_probe", "c_ui_probe_session")\n'
SESSION = 'c_ui_probe_session(name = "s", probe = ":probe", session = "session.in", expected = "session.out")\n'


class UiSessionBuckFiles(test_buckfiles.BuckFilesCase):
    """U05c: `c_ui_probe_session(name, probe, session, expected)`, exactly these keywords, a probe of the same file."""

    def bad(self, source, *rules):
        self.assertEqual(self.check({"BUCK": source}, 1), sorted(rules))

    def why(self, source):
        """The `why` of each finding, all of them `bad-argument`."""
        rules = self.check({"BUCK": source}, 1)
        self.assertEqual(set(rules), {"bad-argument"})
        return sorted(f["why"] for f in test_buckfiles.read_json(self.tmp / "out.json")["findings"])

    def test_a_session_of_a_probe_of_the_same_file_is_clean(self):
        self.assertEqual(self.check({"BUCK": C_LOAD + SESSION_LOAD + MODEL + PROBE + SESSION}, 0), [])
        self.setUp()
        files = SESSION.replace('"session.in"', '"tests/a-1.in"').replace('"session.out"', '"tests/sub/a_1.out"')
        self.assertEqual(self.check({"BUCK": C_LOAD + SESSION_LOAD + MODEL + PROBE + files}, 0), [])

    def test_the_session_macro_is_loaded_only_from_the_ui_file(self):
        self.bad('load("@gate//rules:c.bzl", "c_ui_probe_session")\n' + SESSION, "bad-load", "bad-argument")
        self.setUp()
        self.bad('load("@gate//rules:ui.bzl", "c_ui_probe_sessions")\n', "bad-load")
        self.setUp()   # the rule kind behind the macro is the gate's: neither loadable nor callable
        self.bad('load("@gate//rules:ui.bzl", "ui_probe_session_run")\n', "bad-load")
        self.setUp()
        self.bad(C_LOAD + SESSION_LOAD + MODEL + PROBE + SESSION.replace("c_ui_probe_session(", "ui_probe_session_run("),
                 "bad-call")

    def test_the_probe_must_be_a_c_ui_probe_of_the_same_build_file(self):
        head = C_LOAD + SESSION_LOAD + MODEL
        for probe, why in ((":model", "probe"), (":nope", "probe"), (":probe_facts", "probe"), (":probe__ui_probe", "value"),
                           ("//x:probe", "value"), ("probe", "value"), (":", "value"), ("root//x:probe", "value")):
            with self.subTest(probe=probe):
                self.setUp()
                self.assertEqual(self.why(head + PROBE + SESSION.replace('":probe"', '"%s"' % probe)), [why])
        self.setUp()   # a probe of another BUCK file is refused, even of the same name
        files = {"a/BUCK": C_LOAD + SESSION_LOAD + MODEL + PROBE, "BUCK": SESSION_LOAD + SESSION}
        self.assertEqual(self.check(files, 1), ["bad-argument"])

    def test_the_files_are_plain_relative_files_of_the_package_and_two_of_them(self):
        head = C_LOAD + SESSION_LOAD + MODEL + PROBE
        for value in ("", "/abs.in", "../x.in", "a/../x.in", "./x.in", "a//x.in", "x.in/", ":x", "//p:x", "@c//p:x",
                      "*.in", "a\\\\x.in", ".hidden", "a/.", "a/..", "x y.in"):
            with self.subTest(value=value):
                self.setUp()
                self.assertEqual(self.why(head + SESSION.replace('"session.in"', '"%s"' % value)), ["value"])
                self.setUp()
                self.assertEqual(self.why(head + SESSION.replace('"session.out"', '"%s"' % value)), ["value"])
        self.setUp()
        self.assertEqual(self.why(head + SESSION.replace('"session.out"', '"session.in"')), ["file"])
        for value in ('["session.in"]', "glob([\"*.in\"])", '"a" + "b"', "1", "None"):
            with self.subTest(value=value):
                self.setUp()
                self.assertEqual(self.why(head + SESSION.replace('"session.in"', value)), ["value"])

    def test_exactly_its_keywords(self):
        head = C_LOAD + SESSION_LOAD + MODEL + PROBE
        for extra in ('deps = [":model"]', 'visibility = ["PUBLIC"]', 'srcs = ["a.c"]', 'model = ":model"', 'timeout = 1',
                      'env = {"A": "1"}', 'args = ["-x"]', 'runner = "r.py"'):
            with self.subTest(extra=extra):
                self.setUp()
                self.assertEqual(self.why(head + SESSION.replace(")\n", ", %s)\n" % extra)), ["keyword"])
        for gone in ('probe = ":probe", ', 'session = "session.in", ', ', expected = "session.out"', 'name = "s", '):
            with self.subTest(gone=gone):
                self.setUp()
                self.assertEqual(self.why(head + SESSION.replace(gone, "")), ["missing"])
        self.setUp()
        self.assertEqual(self.why(head + 'c_ui_probe_session("s", ":probe", "session.in", "session.out")\n'),
                         ["missing", "positional"])
        self.setUp()
        self.assertEqual(self.why(head + 'c_ui_probe_session(**{"name": "s"})\n'), ["keyword", "missing"])

    def test_nothing_may_depend_on_a_session_or_the_probe_mark(self):
        head = C_LOAD + SESSION_LOAD + MODEL + PROBE + SESSION
        for dep in (":s", ":s_results", ":probe__ui_probe"):
            with self.subTest(dep=dep):
                self.setUp()
                self.assertEqual(self.why(head + 'c_library(name = "x", deps = ["%s"])\n' % dep), ["test-target"])
