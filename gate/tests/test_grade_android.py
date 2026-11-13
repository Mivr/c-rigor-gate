"""T-G2 wiring: a c_android_so is built, read and judged by the fact gates (it has no Linux build to escape through).

Buck2 is faked at the seam the grader uses (`grade_build.run_buck`, `read_report`, `output_path`, `action_counts`).
"""

import json
import os
from types import SimpleNamespace
from unittest import mock

from rigor_lib import decoupling_model, facts_data, facts_symbols, grade_build, grade_checks, grade_structure, structure_data
from rigor_lib.facts_policy import load_policy
from tests.helpers import TempDirTestCase
from tests.test_facts import CTEST, GLOBAL, LIBC, facts, unit

SO = "root//p:club"
FACTS = "root//p:club_facts"


class FakeBuck:
    def __init__(self, tree, android_labels, shared, fail_android=False):
        self.tree, self.calls = tree, []
        self.android_labels, self.shared, self.fail_android = android_labels, shared, fail_android
        self.reports = {}

    def run(self, tree, args):
        self.calls.append(args)
        if args[0] == "uquery":
            expression = args[1]
            if "c_android_facts" in expression:
                return 0, "".join(l + "\n" for l in self.android_labels), ""
            if "android_so" in expression:
                return 0, "".join(l + "\n" for l in self.shared), ""
            return 0, "root//p:lib_facts\n", ""
        if args[0] == "build":
            built = [a for a in args if a.startswith(("root//", "gate//", "toolchains//"))]
            report = args[args.index("--build-report") + 1]
            android = "toolchains//:android_release" in args
            ok = not (android and self.fail_android)
            results = {}
            for label in built:
                path = os.path.join(self.tree, "buck-out", label.replace("/", "_").replace(":", "_"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                kind = "c_android_so" if label == FACTS else "c_library"
                if label.endswith("libc_symbols") or label.endswith("libc_symbols_android"):
                    body = "kill\nexit\n" if not label.endswith("android") else "ANativeWindow_lock\n"
                else:
                    body = json.dumps(facts("//p:club" if label == FACTS else "//ctest:ctest" if "ctest" in label else "//p:lib",
                                            [unit()], kind=kind if label == FACTS else "c_library"))
                with open(path, "w") as handle:
                    handle.write(body)
                results[label] = {"success": "SUCCESS" if ok else "FAIL", "outputs": {"DEFAULT": [os.path.relpath(path, self.tree)]}}
            with open(report, "w") as handle:
                json.dump({"results": results}, handle)
            return (0 if ok else 1), "", ("" if ok else "compile error")
        return 0, "", ""


class AndroidFacts(TempDirTestCase):
    def build(self, android_labels, shared, fail_android=False):
        tree = self.sub("tree")
        work = self.sub("work")
        fake = FakeBuck(str(tree), android_labels, shared, fail_android)
        g = SimpleNamespace(tree=str(tree), work=str(work), args=SimpleNamespace(uncached=False), facts=None)
        with mock.patch.object(grade_build, "run_buck", fake.run), \
                mock.patch.object(grade_build, "action_counts", lambda *_: (1, 2)), \
                mock.patch.object(grade_checks.facts_third_party, "load", lambda: SimpleNamespace(trusted=[])):
            return grade_checks._build_facts(g), fake

    def test_a_product_without_a_c_android_so_builds_no_android_facts(self):
        built, fake = self.build([], [])
        self.assertIsNone(built.libc_android)
        self.assertFalse(any("toolchains//:android_release" in call for call in fake.calls))

    def test_the_android_facts_are_built_in_the_android_mode_with_the_ndk_libc_list(self):
        built, fake = self.build([FACTS], [SO])
        self.assertTrue(os.path.isfile(built.libc_android))
        with open(built.libc_android) as handle:
            self.assertIn("ANativeWindow_lock", handle.read())
        self.assertEqual(built.metadata["android_facts_targets"], 1)
        android = [call for call in fake.calls if call[0] == "build" and "toolchains//:android_release" in call][0]
        self.assertIn(FACTS, android)
        self.assertIn(SO, android)    # the shared object itself is linked and ELF-checked too
        self.assertIn("toolchains//:libc_symbols_android", android)
        kinds = {f.kind for f in facts_data.load_facts_dir(built.directory).values()}
        self.assertIn("c_android_so", kinds)

    def test_a_c_android_so_without_facts_is_why_the_fact_gates_do_not_run(self):
        built, _ = self.build([], [SO])
        self.assertIsInstance(built, str)
        self.assertIn("c_android_so without facts: " + SO, built)

    def test_an_android_build_failure_is_a_reason_not_a_pass(self):
        built, _ = self.build([FACTS], [SO], fail_android=True)
        self.assertIsInstance(built, str)
        self.assertIn("android build failed", built)


class SymbolsPerKind(TempDirTestCase):
    def run_symbols(self, libc_android):
        so = facts("//p:club", [unit(defined=["ANativeActivity_onCreate", "ANativeWindow_lock"], undefined=["kill"])],
                   kind="c_android_so")
        policy = self.tmp / "policy.toml"
        policy.write_text(GLOBAL + '[module."//p:club"]\nlevel = "L3"\nexports = ["ANativeActivity_onCreate", "ANativeWindow_lock"]\n',
                          encoding="utf-8")
        fdir = self.sub("facts")
        for i, document in enumerate((so, CTEST)):
            (fdir / ("%d.json" % i)).write_text(json.dumps(document), encoding="utf-8")
        loaded = facts_data.load_facts_dir(str(fdir))
        return facts_symbols.run(loaded, load_policy(str(policy)), set(LIBC.split()), libc_android=libc_android)

    def test_an_android_object_is_judged_against_the_ndk_list_and_denied_symbols(self):
        result = self.run_symbols({"ANativeWindow_lock"})
        rules = sorted((f["rule"], f.get("symbol")) for f in result.findings if f["severity"] == "error")
        self.assertEqual(rules, [("denied-symbol", "kill"), ("symbol-collision", "ANativeWindow_lock")])

    def test_the_linux_list_does_not_reserve_the_ndk_names_for_a_linux_kind(self):
        document = facts("//p:lib", [unit(defined=["ANativeWindow_lock"])])
        fdir = self.sub("facts")
        (fdir / "0.json").write_text(json.dumps(document), encoding="utf-8")
        (fdir / "1.json").write_text(json.dumps(CTEST), encoding="utf-8")
        policy = self.tmp / "policy.toml"
        policy.write_text(GLOBAL + '[module."//p:lib"]\n', encoding="utf-8")
        result = facts_symbols.run(facts_data.load_facts_dir(str(fdir)), load_policy(str(policy)), set(LIBC.split()),
                                   libc_android={"ANativeWindow_lock"})
        self.assertEqual([f["rule"] for f in result.findings if f["severity"] == "error"], [])


class Kinds(TempDirTestCase):
    def test_every_gate_that_enumerates_kinds_knows_the_android_one(self):
        self.assertIn("c_android_so", decoupling_model.JUDGED_KINDS)
        self.assertIn("c_android_so", structure_data.KINDS)
        self.assertIn("c_android_so", grade_structure.KINDS)
        self.assertIn("c_android_so", facts_data.KINDS)

    def test_the_structure_target_of_an_android_module_is_the_android_macro_and_loads_it(self):
        module = grade_structure.Module("//p:club", "//p:club__lib", "c_android_so", ["entry.c"], [], [])
        text = grade_structure.call_text(module)
        self.assertTrue(text.startswith("c_android_structure("))
        self.assertNotIn("kind =", text)
        extended = grade_structure.extended_text(b"", [module]).decode()
        self.assertTrue(extended.startswith('load("@gate//rules:structure.bzl", "c_structure")\n'
                                            'load("@gate//rules:structure.bzl", "c_android_structure")\n'))
        plain = grade_structure.Module("//p:a", "//p:a", "c_library", ["a.c"], [], [])
        self.assertNotIn("c_android_structure", grade_structure.extended_text(b"", [plain]).decode())
