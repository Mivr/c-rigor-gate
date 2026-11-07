"""The exports policy of the `symbols` gate (T033, R003 G7): `exports` and `mutable-global-export`."""

import os
import stat
import sys

from rigor_lib import cscan
from tests.helpers import TempDirTestCase
from tests import test_facts as tf
from tests.test_facts import CTEST, GLOBAL, facts, unit


def module(level=None, exports=None):
    text = '[module."//p:lib"]\n'
    text += 'level = "%s"\n' % level if level else ""
    text += "exports = [%s]\n" % ", ".join('"%s"' % e for e in exports) if exports is not None else ""
    return GLOBAL + text


class ExportsCase(TempDirTestCase):
    run_gate = tf.FactsCase.run_gate    # the helpers, without FactsCase's own tests
    rules = tf.FactsCase.rules

    def exp(self, policy, units, code, kind="c_library"):
        return self.rules("symbols", [facts("//p:lib", units, kind=kind), CTEST], code, policy=policy)

    def test_exact_list_is_green(self):
        self.assertEqual(self.exp(module("L3", ["f", "g"]), [unit(defined=["f"]), unit("b.c.o", defined=["g"])], 0), [])

    def test_the_impl_key_of_the_witness_gates_is_accepted_and_changes_nothing(self):
        policy = module("L3", ["f"]) + 'impl = ["p/lib.c"]\n'
        self.assertEqual(self.exp(policy, [unit(defined=["f"])], 0), [])
        self.assertEqual(self.exp(policy, [unit(defined=["f", "hook"])], 1), [("unexpected-export", "hook")])

    def test_a_list_may_be_wider_than_the_module(self):
        self.assertEqual(self.exp(module("L3", ["f", "g"]), [unit(defined=["f"])], 0), [])

    def test_extra_function(self):
        self.assertEqual(self.exp(module("L3", ["f"]), [unit(defined=["f", "hook"])], 1),
                         [("unexpected-export", "hook")])

    def test_extra_const_table_is_only_unexpected(self):
        self.assertEqual(self.exp(module("L3", ["f"]), [unit(defined=["f", "table"])], 1),
                         [("unexpected-export", "table")])

    def test_extra_mutable_global_is_both(self):
        self.assertEqual(self.exp(module("L3", ["f"]), [unit(defined=["f", "hook"], mutable=["hook"])], 1),
                         [("mutable-global-export", "hook"), ("unexpected-export", "hook")])

    def test_a_listed_mutable_global_is_still_a_finding(self):
        self.assertEqual(self.exp(module("L3", ["f", "hook"]), [unit(defined=["f", "hook"], mutable=["hook"])], 1),
                         [("mutable-global-export", "hook")])

    def test_missing_list_at_l3_fails_closed(self):
        self.assertEqual(self.exp(module("L3"), [unit(defined=["f"])], 1), [("exports-missing", "//p:lib")])

    def test_l2_reports_a_missing_list_and_a_mutable_global_as_info_but_extras_as_errors(self):
        outcome, result = self.run_gate("symbols", [facts("//p:lib", [unit(defined=["f"], mutable=["f"])]), CTEST],
                                        policy=module("L2"), expect_code=0)
        self.assertEqual([(f["rule"], f["severity"]) for f in result["findings"]], [("exports-missing", "info")])
        outcome, result = self.run_gate("symbols", [facts("//p:lib", [unit(defined=["f", "h"], mutable=["h"])]), CTEST],
                                        policy=module("L2", ["f"]), expect_code=1)
        self.assertEqual(sorted((f["rule"], f["severity"]) for f in result["findings"]),
                         [("mutable-global-export", "info"), ("unexpected-export", "error")])

    def test_l1_is_exempt(self):
        self.assertEqual(self.exp(module("L1"), [unit(defined=["f", "h"], mutable=["h"])], 0), [])

    def test_no_level_and_no_list_is_not_checked_but_a_list_arms_it(self):
        self.assertEqual(self.exp(module(), [unit(defined=["f"])], 0), [])
        self.assertEqual(self.exp(module(None, ["f"]), [unit(defined=["f", "h"], mutable=["h"])], 1),
                         [("mutable-global-export", "h"), ("unexpected-export", "h")])

    def test_tests_and_binaries_are_checked_too(self):
        self.assertEqual(self.exp(module("L3", ["main"]), [unit(defined=["main", "x"])], 1, kind="c_test"),
                         [("unexpected-export", "x")])

    def test_trusted_modules_are_not_checked(self):
        self.assertEqual(self.rules("symbols", [facts("//p:lib", [unit()]), CTEST], 0, policy=module("L3", [])), [])

    def test_bad_policy_values_are_exit_2(self):
        for bad in ('level = "L9"', 'exports = "f"', 'exports = ["f", "f"]', 'exports = ["a b"]'):
            self.run_gate("symbols", [facts("//p:lib", [unit()]), CTEST],
                          policy=GLOBAL + '[module."//p:lib"]\n' + bad + "\n", expect_code=2)

    def test_mutable_must_be_defined_and_is_required_for_products(self):
        self.run_gate("symbols", [facts("//p:lib", [unit(defined=["f"], mutable=["g"])]), CTEST],
                      policy=module("L3", ["f"]), expect_code=2)
        document = facts("//p:lib", [unit(defined=["f"])])
        del document["units"][0]["mutable"]
        self.run_gate("symbols", [document, CTEST], policy=module("L3", ["f"]), expect_code=2)


SYSV = """Symbols from x.o:

Name                  Value           Class        Type         Size             Line  Section
a_data              |0000000000000000|   D  |          OBJECT|0000000000000004|     |.data
a_relro             |0000000000000010|   D  |          OBJECT|0000000000000008|     |.data.rel.ro
a_tls               |0000000000000000|   D  |          OBJECT|0000000000000004|     |.tdata
"""
POSIX = "a_relro D 10 8\na_func T 0 4\na_data D 0 4\na_bss B 0 4\na_const R 0 4\na_small G 0 4\na_common C 4 4\na_weak V 0 4\nextern_ref U\n"


class MutableCase(TempDirTestCase):
    def test_writable_classes_are_mutable_and_read_only_ones_are_not(self):
        nm = self.tmp / "nm"
        nm.write_text("#!%s\nimport sys\nsys.stdout.write(%r if '--format=sysv' in sys.argv else %r)\n" % (sys.executable, SYSV, POSIX), encoding="utf-8")
        os.chmod(nm, os.stat(nm).st_mode | stat.S_IXUSR)
        defined, weak, undefined, mutable = cscan.read_symbols(str(nm), "x.o")
        self.assertEqual(mutable, ["a_bss", "a_common", "a_data", "a_small"])    # a_relro is const data
        self.assertEqual((weak, undefined), (["a_weak"], ["extern_ref"]))
        self.assertEqual(defined, ["a_bss", "a_common", "a_const", "a_data", "a_func", "a_relro", "a_small", "a_weak"])

    def test_unparsable_section_listing_reports_more_never_less(self):
        nm = self.tmp / "nm"
        nm.write_text("#!%s\nimport sys\nsys.stdout.write(%r)\n" % (sys.executable, POSIX), encoding="utf-8")
        os.chmod(nm, os.stat(nm).st_mode | stat.S_IXUSR)
        self.assertIn("a_relro", cscan.read_symbols(str(nm), "x.o")[3])
