"""Static data facts (T089): `cscan.read_data`, the `mutable-data` rule, `allow_mutable_data`, the RAM budget."""

import json
import os
import stat
import sys

from rigor_lib import cscan, facts_data, facts_policy, ram_budget
from rigor_lib.errors import InternalError
from tests import test_facts as tf
from tests.helpers import TempDirTestCase
from tests.test_facts import CTEST, GLOBAL, facts, unit

SYSV = """Symbols from x.o:

Name                  Value           Class        Type         Size             Line  Section
counter             |0000000000000000|   b  |          OBJECT|0000000000000004|     |.bss
f.calls             |0000000000000004|   b  |          OBJECT|0000000000000008|     |.bss.f.calls
g_init              |0000000000000000|   D  |          OBJECT|0000000000000010|     |.data
table               |0000000000000010|   d  |          OBJECT|0000000000000018|     |.data.rel.ro
konst               |0000000000000000|   r  |          OBJECT|0000000000000020|     |.rodata
tl                  |0000000000000000|   b  |             TLS|0000000000000008|     |.tbss
tl_init             |0000000000000008|   D  |             TLS|0000000000000008|     |.tdata
ctor                |0000000000000000|   d  |          OBJECT|0000000000000008|     |.init_array
code                |0000000000000000|   T  |            FUNC|0000000000000004|     |.text
.rodata.str1.1      |0000000000000000|   r  |         NOTYPE |0000000000000000|     |.rodata.str1.1
"""


def fake_nm(directory, text):
    nm = directory / "nm"
    nm.write_text("#!%s\nimport sys\nsys.stdout.write(%r)\n" % (sys.executable, text), encoding="utf-8")
    os.chmod(nm, os.stat(nm).st_mode | stat.S_IXUSR)
    return str(nm)


class ReadDataCase(TempDirTestCase):
    def test_every_data_object_with_its_size_and_section_class(self):
        got = {d["name"]: (d["size"], d["section"], d["local"]) for d in cscan.read_data(fake_nm(self.tmp, SYSV), "x.o")}
        self.assertEqual(got, {
            "counter": (4, "bss", True), "f.calls": (8, "bss", True), "g_init": (16, "data", False),
            "table": (24, "ro", True), "konst": (32, "ro", True), "tl": (8, "tls", True),
            "tl_init": (8, "tls", False)})

    def test_output_is_sorted_and_keeps_duplicate_names(self):
        text = SYSV + "counter             |0000000000000040|   b  |          OBJECT|0000000000000002|     |.bss\n"
        names = [(d["name"], d["size"]) for d in cscan.read_data(fake_nm(self.tmp, text), "x.o")]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names.count(("counter", 4)) + names.count(("counter", 2)), 2)

    def test_section_classes(self):
        for section, kind, want in [(".data", "OBJECT", "data"), (".data.foo", "OBJECT", "data"),
                                    (".data.rel.ro.local", "OBJECT", "ro"), (".rodata.cst8", "OBJECT", "ro"),
                                    (".bss.x", "OBJECT", "bss"), (".sbss", "OBJECT", "bss"), (".sdata", "OBJECT", "data"),
                                    ("*COM*", "OBJECT", "bss"), (".tdata", "TLS", "tls"), (".tbss", "TLS", "tls"),
                                    (".text", "OBJECT", None), (".init_array", "OBJECT", None), (".weird", "TLS", "tls")]:
            self.assertEqual(cscan.section_class(section, kind), want, section)

    def test_unreadable_size_stops_the_scan(self):
        text = "x |0|   b  |          OBJECT|zz|     |.bss\n"
        with self.assertRaises(SystemExit):
            cscan.read_data(fake_nm(self.tmp, text), "x.o")

    def test_nm_failure_stops_the_scan(self):
        nm = self.tmp / "bad"
        nm.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        nm.chmod(nm.stat().st_mode | stat.S_IXUSR)
        with self.assertRaises(SystemExit):
            cscan.read_data(str(nm), "x.o")


class ParseCase(TempDirTestCase):
    def parse(self, document):
        return facts_data.parse_facts("f.json", json.dumps(document).encode())

    def test_data_round_trips(self):
        doc = facts("//p:lib", [unit(data=[("c", 4, "bss", True)])])
        self.assertEqual(self.parse(doc).units[0].data, (("c", 4, "bss", True),))

    def test_product_facts_without_data_are_exit_2(self):
        doc = facts("//p:lib", [unit()])
        del doc["units"][0]["data"]
        with self.assertRaises(InternalError):
            self.parse(doc)

    def test_third_party_facts_may_omit_data(self):
        doc = facts("gate//third_party/x:x", [unit()], kind="c_third_party")
        for key in ("data", "mutable"):
            del doc["units"][0][key]
        self.assertEqual(self.parse(doc).units[0].data, ())

    def test_malformed_data_is_exit_2(self):
        good = {"name": "c", "size": 4, "section": "bss", "local": True}
        for bad in [{"name": "c", "size": 4, "section": "bss"}, dict(good, section="text"), dict(good, size=-1),
                    dict(good, size=True), dict(good, local=1), dict(good, name="a b"), dict(good, extra=1)]:
            doc = facts("//p:lib", [unit()])
            doc["units"][0]["data"] = [bad]
            with self.assertRaises(InternalError, msg=str(bad)):
                self.parse(doc)
        doc = facts("//p:lib", [unit()])
        doc["units"][0]["data"] = {}
        with self.assertRaises(InternalError):
            self.parse(doc)


LIB = GLOBAL + '[module."//p:lib"]\n'


class MutableDataCase(TempDirTestCase):
    run_gate = tf.FactsCase.run_gate
    rules = tf.FactsCase.rules

    def check(self, targets, policy=LIB, code=None):
        outcome, result = self.run_gate("symbols", targets + [CTEST], policy=policy, expect_code=code)
        return result["findings"]

    def test_static_local_in_a_library_is_red_with_unit_symbol_size_and_section(self):
        found = self.check([facts("//p:lib", [unit(data=[("f.counter", 4, "bss", True)])])], code=1)
        self.assertEqual([(f["rule"], f["target"], f["unit"], f["symbol"], f["size"], f["section"], f["local"])
                          for f in found], [("mutable-data", "//p:lib", "a.c.o", "f.counter", 4, "bss", True)])

    def test_each_writable_class_is_red_and_read_only_is_green(self):
        data = [("a", 1, "data", False), ("b", 2, "bss", True), ("c", 3, "tls", True), ("d", 4, "ro", True)]
        found = self.check([facts("//p:lib", [unit(data=data)])], code=1)
        self.assertEqual(sorted(f["symbol"] for f in found), ["a", "b", "c"])

    def test_green_without_data(self):
        self.assertEqual(self.check([facts("//p:lib", [unit(data=[("k", 8, "ro", False)])])], code=0), [])

    def test_allow_mutable_data_makes_the_module_green(self):
        policy = LIB + "allow_mutable_data = true\n"
        self.assertEqual(self.check([facts("//p:lib", [unit(data=[("m", 8, "bss", True)])])], policy, 0), [])

    def test_allowing_one_module_does_not_allow_another(self):
        policy = LIB + "allow_mutable_data = true\n" + '[module."//p:other"]\n'
        found = self.check([facts("//p:lib", [unit(data=[("m", 8, "bss", True)])]),
                            facts("//p:other", [unit(data=[("n", 8, "bss", True)])])], policy, 1)
        self.assertEqual([(f["target"], f["symbol"]) for f in found], [("//p:other", "n")])

    def test_tests_and_fuzzers_are_exempt_but_binaries_and_testkits_are_not(self):
        data = [unit(data=[("m", 8, "bss", True)])]
        policy = GLOBAL + "".join('[module."//p:%s"]\n' % n for n in ("t", "z", "b", "kit"))
        found = self.check([facts("//p:t", data, kind="c_test"), facts("//p:z", data, kind="c_fuzz"),
                            facts("//p:b", data, kind="c_binary"), facts("//p:kit", data)], policy, 1)
        self.assertEqual(sorted(f["target"] for f in found), ["//p:b", "//p:kit"])

    def test_the_external_mutable_global_is_reported_by_both_rules(self):
        policy = LIB + 'level = "L3"\nexports = ["g"]\n'
        found = self.check([facts("//p:lib", [unit(defined=["g"], mutable=["g"], data=[("g", 4, "data", False)])])],
                           policy, 1)
        self.assertEqual(sorted(f["rule"] for f in found), ["mutable-data", "mutable-global-export"])

    def test_allow_mutable_data_must_be_a_boolean(self):
        self.run_gate("symbols", [facts("//p:lib", [unit()]), CTEST], policy=LIB + 'allow_mutable_data = "yes"\n',
                      expect_code=2)


BIN = GLOBAL + "".join('[module."//p:%s"]\nallow_mutable_data = true\n' % n for n in ("lib", "bin", "other"))


def three():
    lib = facts("//p:lib", [unit(data=[("a", 100, "bss", True), ("r", 999, "ro", False)])])
    other = facts("//p:other", [unit(data=[("z", 1000, "data", True)])])
    binary = facts("//p:bin", [unit(data=[("m", 50, "data", False), ("t", 6, "tls", True)])],
                   deps=["//p:lib"], kind="c_binary")
    return lib, other, binary


class RamCase(TempDirTestCase):
    run_gate = tf.FactsCase.run_gate

    def ram(self, budget, targets=None, code=None):
        if budget is not None:
            (self.tmp / "ram-budget.toml").write_text(budget, encoding="utf-8")
        outcome, result = self.run_gate("symbols", (targets or list(three())) + [CTEST], policy=BIN, expect_code=code)
        return result

    def test_total_is_the_writable_bytes_of_everything_the_binary_reaches(self):
        result = self.ram(None, code=0)
        self.assertEqual(result["metadata"]["ram"], {"//p:bin": {"product": 156, "third_party": 0, "total": 156,
                                                                  "unmeasured": []}})

    def test_no_file_means_no_check(self):
        self.assertEqual(self.ram(None, code=0)["findings"], [])

    def test_exactly_at_the_budget_is_green_and_one_byte_over_is_red(self):
        self.assertEqual(self.ram('[binary."//p:bin"]\nmax_bytes = 156\n', code=0)["findings"], [])
        found = self.ram('[binary."//p:bin"]\nmax_bytes = 155\n', code=1)["findings"]
        self.assertEqual([(f["rule"], f["bytes"], f["max_bytes"]) for f in found], [("ram-over-budget", 156, 155)])

    def test_binary_missing_from_an_existing_file_is_unbudgeted(self):
        found = self.ram('[binary."//p:elsewhere"]\nmax_bytes = 1\n', code=1)["findings"]
        self.assertEqual([(f["rule"], f["target"], f["bytes"]) for f in found], [("ram-unbudgeted", "//p:bin", 156)])

    def test_libraries_tests_and_fuzzers_have_no_budget(self):
        lib, other, binary = three()
        data = [unit(data=[("m", 9, "bss", True)])]
        extra = [facts("//p:t", data, kind="c_test"), facts("//p:z", data, kind="c_fuzz")]
        policy_ok = self.ram('[binary."//p:bin"]\nmax_bytes = 156\n', [lib, other, binary] + extra)
        self.assertEqual(set(policy_ok["metadata"]["ram"]), {"//p:bin"})

    def test_third_party_is_reported_separately(self):
        third = facts("gate//third_party/mbedtls:mbedtls", [unit(data=[("tp", 7, "bss", True)])], kind="c_third_party")
        lib, other, binary = three()
        binary["deps"] = ["//p:lib", "gate//third_party/mbedtls:mbedtls"]
        pol = BIN.replace('[module."//p:bin"]\n', '[module."//p:bin"]\nthird_party = ["gate//third_party/mbedtls:mbedtls"]\n')
        (self.tmp / "ram-budget.toml").write_text('[binary."//p:bin"]\nmax_bytes = 163\n', encoding="utf-8")
        outcome, result = self.run_gate("symbols", [lib, other, binary, third, CTEST], policy=pol, expect_code=0,
                                        extra=["--third-party", str(self.third_dir())])
        self.assertEqual(result["metadata"]["ram"]["//p:bin"],
                         {"product": 156, "third_party": 7, "total": 163, "unmeasured": []})

    def third_dir(self):
        directory = self.sub("tp")
        (directory / "ALLOWED_LABELS").write_text("gate//third_party/mbedtls:mbedtls\n", encoding="utf-8")
        (directory / "ALLOWED_TEST_LABELS").write_text("", encoding="utf-8")
        (directory / "RESERVED_PREFIXES").write_text("mbedtls_\n", encoding="utf-8")
        return directory

    def test_third_party_without_data_is_listed_as_unmeasured(self):
        third = facts("gate//third_party/mbedtls:mbedtls", [unit()], kind="c_third_party")
        for key in ("data", "mutable"):
            del third["units"][0][key]
        lib, other, binary = three()
        binary["deps"] = ["//p:lib", "gate//third_party/mbedtls:mbedtls"]
        pol = BIN.replace('[module."//p:bin"]\n', '[module."//p:bin"]\nthird_party = ["gate//third_party/mbedtls:mbedtls"]\n')
        outcome, result = self.run_gate("symbols", [lib, other, binary, third, CTEST], policy=pol, expect_code=0,
                                        extra=["--third-party", str(self.third_dir())])
        self.assertEqual(result["metadata"]["ram"]["//p:bin"]["unmeasured"], ["gate//third_party/mbedtls:mbedtls"])


class BudgetFileCase(TempDirTestCase):
    def test_parse(self):
        self.assertEqual(ram_budget.parse('[binary."//a:b"]\nmax_bytes = 0\n'), {"//a:b": 0})
        self.assertEqual(ram_budget.parse(""), {})

    def test_every_defect_is_exit_2(self):
        for text in ['x = 1\n', 'binary = 1\n', '[binary."nolabel"]\nmax_bytes = 1\n', '[binary."//a:b"]\n',
                     '[binary."//a:b"]\nmax_bytes = -1\n', '[binary."//a:b"]\nmax_bytes = true\n',
                     '[binary."//a:b"]\nmax_bytes = 1.5\n', '[binary."//a:b"]\nmax_bytes = 1\nother = 2\n',
                     '[binary."//a:b"\n', 'binary."//a:b" = 3\n']:
            with self.assertRaises(InternalError, msg=text):
                ram_budget.parse(text)

    def test_sibling_of_the_policy_file(self):
        policy = self.tmp / "policy.toml"
        policy.write_text(GLOBAL, encoding="utf-8")
        self.assertIsNone(facts_policy.load_policy(str(policy)).ram_budget)
        (self.tmp / "ram-budget.toml").write_text('[binary."//a:b"]\nmax_bytes = 3\n', encoding="utf-8")
        self.assertEqual(facts_policy.load_policy(str(policy)).ram_budget, {"//a:b": 3})

    def test_a_symlinked_or_non_file_budget_is_exit_2(self):
        policy = self.tmp / "policy.toml"
        policy.write_text(GLOBAL, encoding="utf-8")
        (self.tmp / "real.toml").write_text("", encoding="utf-8")
        os.symlink(self.tmp / "real.toml", self.tmp / "ram-budget.toml")
        with self.assertRaises(InternalError):
            facts_policy.load_policy(str(policy))
