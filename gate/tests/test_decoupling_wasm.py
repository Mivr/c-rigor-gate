"""#348: the `decoupling` model reads every BUCK through `buckfiles.MACROS`; a `c_wasm` (#341) is an artifact there.

It is read (not an internal error), it has no sources and no facts, its deps are not judged, it is not a module, and
it counts as one non-test target an edit of its library relinks (G6, a report).
"""

import unittest

from rigor_lib import decoupling_config, decoupling_model, decoupling_rules as rules, facts_data
from rigor_lib.errors import InternalError

LOAD = 'load("@gate//rules:c.bzl", "c_library", "c_test", "c_wasm")\n'
ABI, MODULE, TEST = "//apps/abi:abi", "//apps/abi:abi_wasm", "//apps/abi:abi_test"
CONFIG = '[modules]\ncomponent = ["//apps/**"]\n'


def tree(wasm='c_wasm(name = "abi_wasm", deps = [":abi"], exports = ["sb_call"], stack_bytes = 4096, memory_pages = 2)\n'):
    return {
        "apps/abi/BUCK": LOAD + 'c_library(name = "abi", srcs = ["src/abi.c"], headers = ["abi.h"])\n'
                                'c_test(name = "abi_test", srcs = ["tests/abi_test.c"], deps = [":abi"])\n' + wasm,
        "apps/abi/abi.h": "int sb_call(int n);\n",
        "apps/abi/src/abi.c": '#include "apps/abi/abi.h"\nint sb_call(int n) { return n; }\n',
        "apps/abi/tests/abi_test.c": '#include "apps/abi/abi.h"\n',
    }


def model_of(files):
    return decoupling_model.load(files, lambda path: files[path].encode("utf-8"))


def facts(label, defined=(), undefined=(), kind="c_library", deps=()):
    unit = facts_data.Unit("a.c.o", frozenset(defined), frozenset(), frozenset(undefined), (), (), (), (), data=())
    return facts_data.Facts(label, kind, tuple(deps), (unit,))


class WasmTarget(unittest.TestCase):
    def test_the_module_is_read_without_sources(self):
        target = model_of(tree()).targets[MODULE]
        self.assertEqual((target.kind, target.srcs, target.headers, target.deps, target.exported_deps),
                         ("c_wasm", (), (), (ABI,), ()))

    def test_no_rule_judges_it(self):
        model, config = model_of(tree()), decoupling_config.parse(CONFIG)
        found, levels = rules.violations(model, config, rules.Uses({}))
        self.assertEqual({rule: keys for rule, keys in found.items() if keys}, {})
        self.assertEqual(levels["unit"], 1)

    def test_it_has_no_facts_and_needs_none(self):
        built = {ABI: facts(ABI, defined=["sb_call"]),
                 TEST: facts(TEST, undefined=["sb_call"], kind="c_test", deps=[ABI])}
        uses = rules.uses_from_facts(model_of(tree()), built)
        self.assertNotIn(MODULE, uses.symbols)
        self.assertEqual(uses.symbols[TEST], frozenset([ABI]))

    def test_a_library_without_facts_is_still_an_internal_error(self):
        with self.assertRaises(InternalError):
            rules.uses_from_facts(model_of(tree()), {TEST: facts(TEST, kind="c_test", deps=[ABI])})

    def test_it_counts_as_a_target_its_library_relinks(self):
        self.assertEqual(rules.fan_out(model_of(tree()))[ABI], [1, 1])
        self.assertEqual(rules.fan_out(model_of(tree(wasm="")))[ABI], [0, 1])

    def test_an_unknown_macro_is_still_an_internal_error(self):
        with self.assertRaises(InternalError):
            model_of(tree(wasm='c_wasm32(name = "abi_wasm", deps = [":abi"], exports = ["sb_call"])\n'))


if __name__ == "__main__":
    unittest.main()
