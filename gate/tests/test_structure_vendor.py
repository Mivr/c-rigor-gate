"""Callbacks into gate-owned vendored libraries (T106): the scanner marks the calls and what they hand over, and
`rigor structure` decides with the library rule instead of the "outside code may call back anything" rule."""

import json
import os
import shutil

from rigor_lib import structure_scan
from tests.helpers import GATE_DIR, TempDirTestCase
from tests.test_structure import StructureCase, func, module, one, unit

FIXTURE = GATE_DIR / "tests" / "fixtures" / "structure" / "vendor"
MARKER = "/art/root/third_party/"


def vcall(to, lib="lib", passes=(), opaque=False, line=1):
    return {"to": to, "fp_args": bool(passes) or opaque, "line": line, "lib": lib, "passes": list(passes),
            "opaque": opaque}


def vfunc(name, calls=(), **kw):
    """A function with direct calls (names) and calls into a library (vcall dicts)."""
    made = func(name, calls=[c for c in calls if isinstance(c, (str, tuple))], **kw)
    made["calls"] += [c for c in calls if isinstance(c, dict)]
    return made


class VendorScanTest(TempDirTestCase):
    def facts(self):
        base = str(self.sub("v"))
        shutil.copytree(FIXTURE / "src", os.path.join(base, "src"))
        # The vendored tree sits where Buck2 puts it (T133: the marker counts only right after `buck-out/<version>`).
        shutil.copytree(FIXTURE / "art", os.path.join(base, "buck-out", "v2", "art"))
        tree = base + "/buck-out/v2/art/"
        ast = json.loads((FIXTURE / "ast.json").read_text().replace("@D@/art/", tree).replace("@D@", base))
        includes = (FIXTURE / "includes.txt").read_text().replace("@D@/art/", tree).replace("@D@", base)
        files = structure_scan.Files([], [MARKER])
        return {f["name"]: f for f in structure_scan.unit_facts(
            "//t:t", os.path.join(base, "src", "v.c"), ast, includes, files)["functions"]}

    def test_a_call_into_a_vendored_library_lists_the_functions_it_hands_over(self):
        funcs = self.facts()
        self.assertEqual([(c["to"], c["lib"], c["passes"], c["opaque"]) for c in funcs["reg"]["calls"]],
                         [("lib_set", "lib", ["cb_a"], False)])

    def test_a_function_inside_a_struct_argument_is_handed_over(self):
        call = self.facts()["reg_struct"]["calls"][0]
        self.assertEqual((call["to"], call["passes"], call["opaque"]), ("lib_use", ["cb_b"], False))

    def test_a_pointer_the_scanner_cannot_name_is_opaque(self):
        call = self.facts()["held"]["calls"][0]
        self.assertEqual((call["passes"], call["opaque"]), ([], True))

    def test_a_call_into_the_library_without_callbacks_is_still_marked(self):
        call = self.facts()["plain"]["calls"][0]
        self.assertEqual((call["to"], call["lib"], call["passes"], call["opaque"]), ("lib_plain", "lib", [], False))

    def test_code_the_product_declares_itself_is_not_a_library(self):
        call = self.facts()["other"]["calls"][0]
        self.assertEqual((call["to"], call["fp_args"]), ("qs", True))
        self.assertNotIn("lib", call)

    def test_a_callee_nested_in_an_argument_is_called_not_handed_over(self):
        calls = {c["to"]: c for c in self.facts()["nested"]["calls"]}
        self.assertEqual(calls["lib_plain"]["passes"], [])
        self.assertEqual(calls["lib_set"]["passes"], ["cb_a"])

    def test_the_library_is_the_directory_after_the_marker(self):
        files = structure_scan.Files([], [MARKER])
        self.assertEqual(files.vendor_lib("buck-out/v2/art/root/third_party/mbedtls/__h__/ssl.h"), "mbedtls")
        self.assertIsNone(files.vendor_lib("core/arena.h"))
        self.assertIsNone(files.vendor_lib("buck-out/v2/art/root/third_party/"))


class LibraryRuleTest(StructureCase):
    """The mbedTLS shape: `configure` registers the callbacks, the callbacks do not call into the library."""

    def product(self, send_calls=(), extra=()):
        funcs = [
            vfunc("port_connect", line=1, calls=["configure"], refs=["port_connect"]),
            vfunc("configure", line=10, calls=[vcall("lib_set_bio", passes=["bio_send"], line=11),
                                               vcall("lib_set_rng", passes=["rng"], line=12)]),
            vfunc("bio_send", line=20, calls=list(send_calls)),
            vfunc("rng", line=30),
        ] + list(extra)
        return [one("//p:a", funcs)]

    def test_registered_callbacks_that_do_not_reach_the_library_are_no_cycle(self):
        found = self.findings(self.product(), 0)
        self.assertEqual(found, [])

    def test_a_callback_that_calls_into_the_library_is_a_cycle(self):
        found = self.findings(self.product(send_calls=[vcall("lib_write", line=21)]), 1)
        self.assertEqual([f["rule"] for f in found], ["indirect-cycle-possible"])
        self.assertEqual((found[0]["function"], found[0]["caller"]), ("bio_send", "bio_send"))
        self.assertEqual(found[0]["sites"], ["p/a.c:21 callback:lib_write (library lib)"])

    def test_a_callback_that_reaches_a_call_into_the_library_is_a_cycle(self):
        extra = [vfunc("helper", line=40, calls=[vcall("lib_write", line=41)])]
        found = self.findings(self.product(send_calls=["helper"], extra=extra), 1)
        self.assertEqual((found[0]["function"], found[0]["caller"], found[0]["path"]),
                         ("bio_send", "helper", ["bio_send", "helper"]))

    def test_a_function_that_registers_and_is_registered_is_a_cycle(self):
        funcs = [vfunc("again", calls=[vcall("lib_set_bio", passes=["again"])])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 1), ["indirect-cycle-possible"])

    def test_the_registration_of_one_function_makes_another_call_into_the_library_reachable(self):
        # configure is not registered, so its own calls into the library are fine
        self.assertEqual(self.rules(self.product(), 0), [])

    def test_a_function_passed_to_any_function_of_the_library_may_be_called_from_any_other(self):
        extra = [vfunc("later", line=50, calls=[vcall("lib_run", line=51)]),
                 vfunc("keeper", line=60, calls=[vcall("lib_keep", passes=["later"], line=61)])]
        found = self.findings(self.product(extra=extra), 1)
        self.assertEqual([(f["function"], f["caller"]) for f in found], [("later", "later")])

    def test_two_libraries_do_not_call_each_other_back(self):
        funcs = [vfunc("cb", calls=[vcall("other_call", lib="other")]),
                 vfunc("reg", line=9, calls=[vcall("lib_set", lib="lib", passes=["cb"])])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 0), [])

    def test_an_opaque_argument_keeps_the_old_rule_and_is_reported(self):
        funcs = [vfunc("cb", calls=["reg"]), vfunc("reg", line=9, calls=[vcall("lib_set", opaque=True)], refs=["cb"])]
        found = self.findings([one("//p:a", funcs)], 1)
        self.assertEqual(sorted((f["rule"], f["severity"]) for f in found),
                         [("indirect-cycle-possible", "error"), ("indirect-untyped-fallback", "info")])
        self.assertEqual(found[0]["sites"] if found[0]["rule"] == "indirect-cycle-possible" else found[1]["sites"],
                         ["p/a.c:9 callback:lib_set"])

    def test_libc_keeps_the_conservative_rule(self):
        funcs = [vfunc("compare", calls=["sorter"]), vfunc("sorter", line=9, calls=[("qsort", True)], refs=["compare"])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 1), ["indirect-cycle-possible"])

    def test_the_old_rule_no_longer_fires_for_a_readable_call_into_a_library(self):
        # `entry` has its address taken and reaches the registering call, but is not what the library gets
        funcs = [vfunc("entry", calls=["reg"], refs=["entry"]), vfunc("cb", line=5),
                 vfunc("reg", line=9, calls=[vcall("lib_set", passes=["cb"])])]
        self.assertEqual(self.rules([one("//p:a", funcs)], 0), [])

    def test_levels_l2_info_l1_nothing(self):
        funcs = [vfunc("again", calls=[vcall("lib_set", passes=["again"])])]
        for level, code, severity in (("L2", 0, "info"), ("L1", 0, None)):
            found = self.findings([one("//p:a", funcs)], code, policy='[module."//p:a"]\nlevel = "%s"\n' % level)
            self.assertEqual([f["severity"] for f in found], [severity] if severity else [])

    def test_a_function_of_another_module_passed_to_the_library_counts(self):
        a = one("//p:a", [vfunc("cb", calls=[vcall("lib_write")])])
        b = module("//p:b", [unit("p/b.c", [vfunc("reg", file="p/b.c", calls=[vcall("lib_set", passes=["cb"])])])],
                   deps=["//p:a"])
        self.assertEqual(self.rules([a, b], 1), ["indirect-cycle-possible"])

    def test_the_library_callbacks_are_listed_in_the_result(self):
        _, result = self.run_gate(self.product(), expect=0)
        self.assertEqual(result["metadata"]["library_callbacks"], {"lib": ["bio_send", "rng"]})


class VendorFactsTest(StructureCase):
    def test_lib_passes_and_opaque_come_together(self):
        bad = vcall("lib_set")
        del bad["opaque"]
        self.run_gate([one("//p:a", [vfunc("f", calls=[bad])])], expect=2)

    def test_a_passed_function_must_be_a_name(self):
        bad = vcall("lib_set")
        bad["passes"] = [3]
        self.run_gate([one("//p:a", [vfunc("f", calls=[bad])])], expect=2)

    def test_facts_without_library_marks_still_read(self):
        self.run_gate([one("//p:a", [func("f", calls=[("lib_set", True)])])], expect=0)
