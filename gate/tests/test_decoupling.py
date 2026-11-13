"""Gate `decoupling`: the text scans, the static model, the rules and the baseline ratchet, on a hand-made tree."""

import unittest

from rigor_lib import decoupling_baseline as baseline
from rigor_lib import decoupling_config, decoupling_model, decoupling_rules as rules, decoupling_scan, facts_data
from rigor_lib import layering
from rigor_lib.errors import InternalError

LOAD = 'load("@gate//rules:c.bzl", "c_library", "c_test")\n'
TEXT, CLOCK, FAKE, CART, PAY, MAIN = ("//lib/text:text", "//shop/contracts/clock:clock", "//shop/contracts/clock:fake",
                                      "//shop/parts/cart:cart", "//shop/parts/pay:pay", "//shop/main:main")
CART_TEST, PAY_TEST, FLOW_TEST = "//shop/parts/cart:cart_test", "//shop/parts/pay:pay_test", "//shop/itest/flow:flow_test"
CONFIG = """
[modules]
contract = ["//shop/contracts/**"]
component = ["//shop/parts/**"]
composition = ["//shop/main:*"]
fake = ["//shop/contracts/clock:fake"]
[contract]
may_use = ["//lib/**"]
[tests]
integration = ["//shop/itest/**"]
"""


def shop():
    """Two components (cart, pay), one contract (clock) with its fake, a composition module, one unit test per
    component and one integration test. Nothing in it violates a rule."""
    return {
        "lib/text/BUCK": LOAD + 'c_library(name = "text", srcs = ["text.c"], headers = ["text.h"])\n',
        "lib/text/text.h": "int text_len(const char *s);\n",
        "lib/text/text.c": '#include "text.h"\nint text_len(const char *s) { return s[0]; }\n',
        "shop/contracts/clock/BUCK": LOAD + 'c_library(name = "clock", headers = ["clock.h"])\n'
                                            'c_library(name = "fake", srcs = ["fake.c"], headers = ["fake.h"],\n'
                                            '          exported_deps = [":clock"])\n',
        "shop/contracts/clock/clock.h": "typedef struct { long (*now)(void *self); void *self; } clock_ops_t;\n",
        "shop/contracts/clock/fake.h": '#include "shop/contracts/clock/clock.h"\nclock_ops_t fake_clock(long *at);\n',
        "shop/contracts/clock/fake.c": '#include "fake.h"\n',
        "shop/parts/cart/BUCK": LOAD + 'c_library(name = "cart", srcs = glob(["src/*.c"]),\n'
                                       '          headers = ["cart.h"] + glob(["src/*.h"]),\n'
                                       '          deps = ["//lib/text:text"], exported_deps = ["//shop/contracts/clock:clock"])\n'
                                       'c_test(name = "cart_test", srcs = ["tests/cart_test.c"],\n'
                                       '       deps = [":cart", "//shop/contracts/clock:fake"])\n',
        "shop/parts/cart/cart.h": '#include "shop/contracts/clock/clock.h"\nint cart_total(const clock_ops_t *clock);\n',
        "shop/parts/cart/src/cart.c": '#include "shop/parts/cart/cart.h"\n#include "cart_private.h"\n#include "lib/text/text.h"\n',
        "shop/parts/cart/src/cart_private.h": "#define CART_MAX 4\n",
        "shop/parts/cart/tests/cart_test.c": '#include "shop/parts/cart/cart.h"\n#include "shop/contracts/clock/fake.h"\n',
        "shop/parts/pay/BUCK": LOAD + 'c_library(name = "pay", srcs = ["pay.c"], headers = ["pay.h"])\n'
                                      'c_test(name = "pay_test", srcs = ["pay_test.c"], deps = [":pay"])\n',
        "shop/parts/pay/pay.h": "int pay_take(int cents);\n",
        "shop/parts/pay/pay.c": '#include "pay.h"\n',
        "shop/parts/pay/pay_test.c": '#include "pay.h"\n',
        "shop/main/BUCK": LOAD + 'c_library(name = "main", srcs = ["main.c"], headers = ["main.h"],\n'
                                 '          deps = ["//shop/parts/cart:cart", "//shop/parts/pay:pay"])\n'
                                 'c_test(name = "main_test", srcs = ["main_test.c"], deps = [":main"])\n',
        "shop/main/main.h": "int shop_run(void);\n",
        "shop/main/main.c": '#include "main.h"\n#include "shop/parts/cart/cart.h"\n#include "shop/parts/pay/pay.h"\n',
        "shop/main/main_test.c": '#include "main.h"\n',
        "shop/itest/flow/BUCK": LOAD + 'c_test(name = "flow_test", srcs = ["flow_test.c"],\n'
                                       '       deps = ["//shop/parts/cart:cart", "//shop/parts/pay:pay"])\n',
        "shop/itest/flow/flow_test.c": '#include "shop/parts/cart/cart.h"\n#include "shop/parts/pay/pay.h"\n',
    }


def model_of(tree):
    return decoupling_model.load(tree, lambda path: tree[path].encode("utf-8"))


def judge(tree, uses=None, config=CONFIG):
    """({rule: sorted keys} for the rules that have violations, the test counts)."""
    found, levels = rules.violations(model_of(tree), decoupling_config.parse(config), uses or rules.Uses({}))
    return {rule: sorted(keys) for rule, keys in found.items() if keys}, levels


def edited(path, old, new):
    tree = shop()
    assert old in tree[path]
    tree[path] = tree[path].replace(old, new)
    return tree


def facts(label, defined=(), undefined=(), deps=(), data=(), kind="c_library"):
    unit = facts_data.Unit("a.c.o", frozenset(defined), frozenset(), frozenset(undefined), (), (), (), (), data=data)
    return facts_data.Facts(label, kind, tuple(sorted(deps)), (unit,))


class Scan(unittest.TestCase):
    def test_includes_skip_comments_and_keep_both_forms(self):
        text = '/* #include "no.h" */\n# include "a/b.h" // x\n#include <c.h>\n// #include "no.h"\nchar *s = "#include";\n'
        self.assertEqual(decoupling_scan.includes(text), ["a/b.h", "c.h"])

    def test_identifiers_skip_comments_and_literals(self):
        self.assertEqual(decoupling_scan.identifiers('int a = f("g()"); /* h */ char c = \'i\'; // j\n'),
                         frozenset(["int", "a", "f", "char", "c"]))

    def test_strip_keeps_the_line_numbers(self):
        text = "a /* x\n y */ b \\\n c\nd // e\n"
        self.assertEqual(decoupling_scan.strip(text).split("\n"), ["a  ", " b  c", "", "d  ", ""])

    def test_an_unterminated_comment_or_literal_ends_the_text_or_the_line(self):
        self.assertEqual(decoupling_scan.includes('/* open\n#include "a.h"\n'), [])
        self.assertEqual(decoupling_scan.includes('char *s = "open\n#include "a.h"\n'), ["a.h"])

    def test_declarations(self):
        text = ("#ifndef X_H\n#define M(a) \\\n  (a)\ntypedef struct { int a; int b; } x_t;\n"
                "static inline int f(int a) { return a; }\nenum e { A, B };\nint g(void);\n#endif\n")
        self.assertEqual(decoupling_scan.declarations(text), [
            (1, "# ifndef X_H"), (2, "# define M(a) (a)"), (4, "typedef struct { int a ; int b ; } x_t ;"),
            (5, "static inline int f ( int a ) { return a ; }"), (6, "enum e { A , B } ;"),
            (7, "int g ( void ) ;"), (8, "# endif")])

    def test_blanks_in_a_directive_are_folded_not_dropped(self):
        one, two = decoupling_scan.declarations("#define M(a) 1\n# define  M (a) 1\n")
        self.assertEqual((one[1], two[1]), ("# define M(a) 1", "# define M (a) 1"))
        self.assertEqual(decoupling_scan.defined_name(one[1]), "M")
        self.assertIsNone(decoupling_scan.defined_name("# include <a.h>"))


class StaticModel(unittest.TestCase):
    def test_targets_files_and_labels(self):
        model = model_of(shop())
        cart = model.targets[CART]
        self.assertEqual(cart.srcs, ("shop/parts/cart/src/cart.c",))
        self.assertEqual(cart.headers, ("shop/parts/cart/cart.h", "shop/parts/cart/src/cart_private.h"))
        self.assertEqual(cart.public_headers, ("shop/parts/cart/cart.h",))
        self.assertEqual((cart.deps, cart.exported_deps), ((TEXT,), (CLOCK,)))
        self.assertEqual(model.targets[CART_TEST].deps, (CART, FAKE))
        self.assertEqual(model.targets[CART_TEST].kind, "c_test")

    def test_includes_resolve_next_to_the_includer_then_from_the_root(self):
        model = model_of(shop())
        self.assertEqual(model.included(model.targets[CART].srcs), {CART, TEXT})
        self.assertEqual(model.included(("shop/contracts/clock/fake.c",)), {FAKE})
        self.assertEqual(model.resolve("shop/parts/cart/src/cart.c", "../../../../etc/passwd"), None)

    def test_closure_is_what_a_target_links(self):
        model = model_of(shop())
        self.assertEqual(model.closure(CART_TEST), {CART, FAKE, CLOCK, TEXT})
        self.assertEqual(model.closure(TEXT), frozenset())

    def test_generated_libraries_provide_their_header(self):
        tree = shop()
        tree["shop/msgs/BUCK"] = ('c_catalog(name = "msgs", pots = ["m.pot"], po = {}, langs = ["en"], source_lang = "en",\n'
                                  '          symbol = "MSGS", runtime = "//lib/text:text", deps = [])\n'
                                  'c_embed(name = "blob", src = "b.bin", symbol = "blob", max_bytes = 4, nul = True)\n')
        model = model_of(tree)
        self.assertEqual(model.targets["//shop/msgs:msgs"].deps, (TEXT,))
        self.assertEqual(model.targets["//shop/msgs:msgs"].provided, ("shop/msgs/msgs.h",))
        self.assertEqual(model.owners["shop/msgs/blob.h"], ["//shop/msgs:blob"])

    def test_a_glob_stays_inside_its_package(self):
        tree = shop()
        tree["shop/parts/cart/src/deep/BUCK"] = LOAD
        tree["shop/parts/cart/src/deep/x.c"] = ""
        tree["shop/parts/cart/src/sub/y.c"] = ""
        self.assertEqual(model_of(tree).targets[CART].srcs, ("shop/parts/cart/src/cart.c",))

    def test_a_build_file_the_gate_cannot_read_is_an_internal_error(self):
        for text in ("c_library(name = ", "x = 1\n", "other_rule(name = 'a')\n", 'c_library("a")\n',
                     'c_library(name = "a", srcs = SRCS)\n', 'c_library(name = "a", **more)\n',
                     LOAD + 'c_library(name = "text")\nc_library(name = "text")\n'):
            tree = shop()
            tree["lib/text/BUCK"] = text
            with self.assertRaises(InternalError, msg=text):
                model_of(tree)


class Dependencies(unittest.TestCase):
    def test_the_clean_tree_has_no_violation(self):
        self.assertEqual(judge(shop()), ({}, {"unit": 3, "integration": 1, "simulation": 0, "unleveled": 0}))

    def test_a_dep_nothing_includes_is_unused(self):
        tree = edited("shop/parts/pay/BUCK", 'headers = ["pay.h"])', 'headers = ["pay.h"], deps = ["//lib/text:text"])')
        self.assertEqual(judge(tree)[0], {"unused-dep": [PAY + " -> " + TEXT]})

    def test_a_dep_whose_symbol_the_objects_reference_is_used(self):
        tree = edited("shop/parts/pay/BUCK", 'headers = ["pay.h"])', 'headers = ["pay.h"], deps = ["//lib/text:text"])')
        model = model_of(tree)
        world = {PAY: facts(PAY, ["pay_take"], ["text_len"], [TEXT]), TEXT: facts(TEXT, ["text_len"])}
        uses = rules.uses_from_facts(model, {**{l: facts(l) for l in model.targets}, **world})
        self.assertEqual(uses.symbols[PAY], frozenset([TEXT]))
        self.assertEqual(judge(tree, uses)[0], {})

    def test_a_header_only_include_through_another_header_is_not_a_use(self):
        tree = edited("shop/parts/cart/tests/cart_test.c", '#include "shop/contracts/clock/fake.h"\n', "")
        self.assertEqual(judge(tree)[0], {"unused-dep": [CART_TEST + " -> " + FAKE]})

    def test_exports_are_what_the_public_headers_include(self):
        tree = edited("shop/parts/cart/BUCK", 'deps = ["//lib/text:text"], exported_deps = ["//shop/contracts/clock:clock"]',
                      'deps = ["//shop/contracts/clock:clock"], exported_deps = ["//lib/text:text"]')
        self.assertEqual(judge(tree)[0], {"missing-export": [CART + " -> " + CLOCK],
                                          "needless-export": [CART + " -> " + TEXT]})

    def test_a_private_header_does_not_export(self):
        tree = edited("shop/parts/cart/src/cart_private.h", "#define", '#include "lib/text/text.h"\n#define')
        self.assertEqual(judge(tree)[0], {})

    def test_a_dep_of_another_cell_is_not_judged(self):
        tree = edited("shop/parts/pay/BUCK", 'deps = [":pay"]', 'deps = [":pay", "gate//third_party/x:x"]')
        self.assertEqual(judge(tree)[0], {})

    def test_the_text_approximation_reads_names_of_the_exports(self):
        tree = edited("shop/parts/pay/BUCK", 'headers = ["pay.h"])', 'headers = ["pay.h"], deps = ["//lib/text:text"])')
        tree["shop/parts/pay/pay.c"] += "int pay_take(int c) { return text_len(\"\") + c; } /* other_name */\n"
        uses = rules.uses_from_text(model_of(tree), {TEXT: frozenset(["text_len"]), PAY: frozenset(["other_name"])})
        self.assertEqual((uses.symbols[PAY], uses.exact), (frozenset([TEXT]), False))

    def test_a_target_with_sources_and_no_facts_is_an_internal_error(self):
        model = model_of(shop())
        with self.assertRaises(InternalError):
            rules.uses_from_facts(model, {l: facts(l) for l in model.targets if l != PAY})
        rules.uses_from_facts(model, {l: facts(l) for l in model.targets if l != CLOCK})   # header-only: nothing to read


class Tests(unittest.TestCase):
    def test_a_unit_test_that_links_another_component(self):
        tree = edited("shop/parts/pay/BUCK", 'deps = [":pay"]', 'deps = [":pay", "//shop/parts/cart:cart"]')
        tree["shop/parts/pay/pay_test.c"] += '#include "shop/parts/cart/cart.h"\n'
        self.assertEqual(judge(tree)[0], {"unit-test-links-component": [PAY_TEST + " -> " + CART]})

    def test_a_component_reached_through_the_module_under_test_counts(self):
        tree = edited("shop/parts/pay/BUCK", 'headers = ["pay.h"])', 'headers = ["pay.h"], deps = ["//shop/parts/cart:cart"])')
        tree["shop/parts/pay/pay.c"] += '#include "shop/parts/cart/cart.h"\n'
        self.assertEqual(judge(tree)[0], {"unit-test-links-component": [PAY_TEST + " -> " + CART]})

    def test_fakes_contracts_and_libraries_are_free(self):
        self.assertNotIn("unit-test-links-component", judge(shop())[0])

    def test_a_composition_test_may_link_what_its_module_binds_and_nothing_more(self):
        self.assertEqual(judge(shop())[0], {})   # main_test links cart and pay through :main
        tree = shop()
        tree["shop/parts/gift/BUCK"] = LOAD + 'c_library(name = "gift", headers = ["gift.h"])\n'
        tree["shop/parts/gift/gift.h"] = "\n"
        tree["shop/main/BUCK"] = tree["shop/main/BUCK"].replace('deps = [":main"]', 'deps = [":main", "//shop/parts/gift:gift"]')
        tree["shop/main/main_test.c"] += '#include "shop/parts/gift/gift.h"\n'
        self.assertEqual(judge(tree)[0], {"unit-test-links-component": ["//shop/main:main_test -> //shop/parts/gift:gift"]})

    def test_integration_tests_link_what_they_like(self):
        self.assertEqual(judge(shop())[1]["integration"], 1)

    def test_a_test_in_a_package_without_a_module_needs_a_declared_level(self):
        config = CONFIG.replace('integration = ["//shop/itest/**"]', 'simulation = ["//shop/sim/**"]')
        found, levels = judge(shop(), config=config)
        self.assertEqual((found, levels["unleveled"]), ({"unleveled-test": [FLOW_TEST]}, 1))

    def test_a_library_in_a_test_package(self):
        tree = shop()
        tree["shop/itest/flow/BUCK"] += 'c_library(name = "helper", headers = ["helper.h"])\n'
        tree["shop/itest/flow/helper.h"] = "\n"
        self.assertEqual(judge(tree)[0], {"library-in-test-package": ["//shop/itest/flow:helper"]})
        fake = CONFIG.replace('fake = [', 'fake = ["//shop/itest/flow:helper", ')
        self.assertEqual(judge(tree, config=fake)[0], {})


class Contracts(unittest.TestCase):
    def test_a_contract_that_depends_on_a_component(self):
        tree = edited("shop/contracts/clock/BUCK", 'c_library(name = "clock", headers = ["clock.h"])',
                      'c_library(name = "clock", headers = ["clock.h"], exported_deps = ["//shop/parts/pay:pay", "//lib/text:text"])')
        tree["shop/contracts/clock/clock.h"] += '#include "shop/parts/pay/pay.h"\n#include "lib/text/text.h"\n'
        self.assertEqual(judge(tree)[0]["contract-has-behaviour"], [CLOCK + " -> " + PAY])

    def test_a_contract_whose_objects_call_out_or_hold_state(self):
        model = model_of(shop())
        world = {l: facts(l) for l in model.targets}
        world[CLOCK] = facts(CLOCK, ["clock_ok"], ["memcpy", "printf"], data=(("clock_count", 8, "bss", True),))
        found = judge(shop(), rules.uses_from_facts(model, world))[0]
        self.assertEqual(found, {"contract-has-behaviour": [CLOCK + " : printf", CLOCK + " : static-data"]})

    def test_a_fake_in_a_contract_package_is_not_a_contract(self):
        model = model_of(shop())
        world = {l: facts(l) for l in model.targets}
        world[FAKE] = facts(FAKE, ["fake_clock"], ["printf"], data=(("calls", 8, "bss", True),))
        self.assertEqual(judge(shop(), rules.uses_from_facts(model, world))[0], {})


class FanOut(unittest.TestCase):
    def test_counts_per_library(self):
        counts = rules.fan_out(model_of(shop()))
        self.assertEqual(counts[TEXT], [2, 3])     # cart and main; cart_test, main_test, flow_test
        self.assertEqual(counts[CLOCK], [3, 3])    # fake, cart and main; the same three tests
        self.assertEqual(counts[MAIN], [0, 1])


class Config(unittest.TestCase):
    ARCH = '[layers]\norder = ["low", "high"]\n[layer.low]\nmodules = ["//lib/**"]\n[layer.high]\nmodules = []\n' \
           '[testkit]\nmodules = ["//lib/text:testkit"]\n'

    def test_patterns_and_defaults(self):
        config = decoupling_config.parse(CONFIG)
        self.assertTrue(config.is_in("component", CART) and config.is_in("contract", CLOCK))
        self.assertFalse(config.is_in("component", CLOCK) or config.is_in("frozen", CART))
        self.assertEqual(config.allow, frozenset(["memcpy", "memset", "memcmp"]))
        self.assertEqual(decoupling_config.parse(""), decoupling_config.Config())

    def test_a_layer_name_stands_for_its_patterns_and_testkits_are_fakes(self):
        arch = layering.parse(self.ARCH)
        config = decoupling_config.parse('[modules]\ncomponent = ["low"]\ncontract = ["high"]\n', arch)
        self.assertEqual((config.component, config.contract, config.fake), (("//lib/**",), (), ("//lib/text:testkit",)))

    def test_defects_are_internal_errors(self):
        for text in ("not toml [", "[other]\n", '[modules]\nother = []\n', '[modules]\ncontract = "//a:b"\n',
                     '[modules]\ncontract = ["a/b"]\n', '[modules]\ncontract = ["low"]\n',
                     '[modules]\ncontract = ["//a:b", "//a:b"]\n', '[contract]\nallow = ["a b"]\n',
                     '[tests]\nintegration = [1]\n', 'modules = 1\n'):
            with self.assertRaises(InternalError, msg=text):
                decoupling_config.parse(text)


class Ratchet(unittest.TestCase):
    PRESENT = {"unused-dep": {"//a:a -> //b:b": {"target": "//a:a", "dep": "//b:b", "list": "deps"},
                              "//a:a -> //c:c": {"target": "//a:a", "dep": "//c:c", "list": "deps"}}}

    def judge(self, text, present=None):
        found, counts = baseline.judge(self.PRESENT if present is None else present, baseline.parse(text))
        return sorted((f["rule"], f["severity"], f["entry"]) for f in found), counts

    def test_a_baselined_violation_is_tolerated(self):
        found, counts = self.judge('unused-dep = ["//a:a -> //b:b", "//a:a -> //c:c"]\n')
        self.assertEqual(found, [])
        self.assertEqual(counts["unused-dep"], {"violations": 2, "new": 0, "stale": 0})

    def test_a_new_violation_is_an_error_named_after_its_rule(self):
        found, counts = baseline.judge(self.PRESENT, baseline.parse('unused-dep = ["//a:a -> //b:b"]\n'))
        self.assertEqual(found, [{"rule": "unused-dep", "severity": "error", "entry": "//a:a -> //c:c",
                                  "target": "//a:a", "dep": "//c:c", "list": "deps"}])
        self.assertEqual(counts["unused-dep"], {"violations": 2, "new": 1, "stale": 0})

    def test_without_a_baseline_every_violation_is_new(self):
        self.assertEqual(len(self.judge("")[0]), 2)

    def test_an_entry_that_is_no_longer_a_violation_is_stale(self):
        text = 'unused-dep = ["//a:a -> //b:b", "//a:a -> //c:c", "//a:a -> //d:d"]\nunleveled-test = ["//t:t"]\n'
        found, counts = self.judge(text)
        self.assertEqual(found, [("stale-baseline", "error", "//a:a -> //d:d"), ("stale-baseline", "error", "//t:t")])
        self.assertEqual((counts["unused-dep"]["stale"], counts["unleveled-test"]["stale"]), (1, 1))

    def test_render_and_parse_are_inverse_and_deterministic(self):
        keys = {rule: set(entries) for rule, entries in self.PRESENT.items()}
        text = baseline.render(keys)
        self.assertEqual(text, baseline.render({"unused-dep": ["//a:a -> //c:c", "//a:a -> //b:b"]}))
        self.assertEqual(baseline.parse(text)["unused-dep"], frozenset(keys["unused-dep"]))
        self.assertEqual(self.judge(text)[0], [])
        self.assertIn('unused-dep = [\n    "//a:a -> //b:b",\n    "//a:a -> //c:c",\n]\n', text)
        self.assertIn("\nmissing-export = []\n", text)

    def test_a_malformed_baseline_is_an_internal_error(self):
        for text in ("not toml [", 'other-rule = []\n', 'unused-dep = "//a:a -> //b:b"\n', "unused-dep = [1]\n",
                     'unused-dep = ["//a:a -> //c:c", "//a:a -> //b:b"]\n', 'unused-dep = ["//a:a", "//a:a"]\n',
                     'unused-dep = ["two  spaces"]\n', 'unused-dep = ["//a:a => //b:b"]\n', 'unused-dep = [""]\n',
                     '[unused-dep]\nentries = []\n'):
            with self.assertRaises(InternalError, msg=text):
                baseline.parse(text)
        with self.assertRaises(InternalError):
            baseline.render({"unused-dep": ['a "quoted" key']})


if __name__ == "__main__":
    unittest.main()
