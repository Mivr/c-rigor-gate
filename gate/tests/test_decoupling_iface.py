"""Gate `decoupling`, rule `interface-changed`: frozen headers at the base against the head."""

import unittest

from rigor_lib import decoupling_config, decoupling_iface as iface
from tests.test_decoupling import CART, CLOCK, CONFIG, FAKE, PAY, model_of, shop

CLOCK_H, CART_H = "shop/contracts/clock/clock.h", "shop/parts/cart/cart.h"
HEADER = ("#ifndef CLOCK_H\n#define CLOCK_H\n#define CLOCK_VERSION 1\n"
          "typedef struct {\n    long (*now)(void *self);\n    void *self;\n} clock_ops_t;\n"
          "enum clock_kind { CLOCK_WALL, CLOCK_STEADY };\nint clock_valid(const clock_ops_t *ops);\n#endif\n")


def judge(head_text, base_text=HEADER, config=CONFIG, head=None):
    base_tree = shop()
    base_tree[CLOCK_H] = base_text
    head_tree = dict(base_tree) if head is None else head
    if head_text is None:
        head_tree.pop(CLOCK_H, None)
    elif head is None:
        head_tree[CLOCK_H] = head_text
    found, judged = iface.findings(model_of(base_tree), model_of(head_tree), decoupling_config.parse(config))
    return sorted((f["rule"], f["severity"], f.get("reason"), f.get("line") or f.get("name") or f.get("declarations"))
                  for f in found), judged


class Frozen(unittest.TestCase):
    def test_which_modules_are_frozen(self):
        config = decoupling_config.parse(CONFIG)
        self.assertEqual(iface.frozen_modules(model_of(shop()), config), [CLOCK])   # the fake is not a contract
        listed = decoupling_config.parse(CONFIG.replace("[contract]", 'frozen = ["//shop/parts/**"]\n[contract]'))
        self.assertEqual(iface.frozen_modules(model_of(shop()), listed), [CLOCK, CART, PAY])

    def test_a_contract_nothing_outside_its_package_depends_on_is_free(self):
        tree = shop()
        for path in ("shop/parts/cart/BUCK", "shop/parts/cart/cart.h", "shop/parts/cart/tests/cart_test.c"):
            tree[path] = tree[path].replace('exported_deps = ["//shop/contracts/clock:clock"]', "")
        self.assertEqual(iface.frozen_modules(model_of(tree), decoupling_config.parse(CONFIG)), [])
        self.assertNotIn(FAKE, iface.frozen_modules(model_of(shop()), decoupling_config.parse(CONFIG)))

    def test_frozen_headers_follow_the_includes_inside_the_module(self):
        tree = shop()
        tree[CART_H] += '#include "src/cart_private.h"\n'
        self.assertEqual(iface.frozen_headers(model_of(tree), CART), [CART_H, "shop/parts/cart/src/cart_private.h"])
        self.assertEqual(iface.frozen_headers(model_of(shop()), CART), [CART_H])


class Compare(unittest.TestCase):
    def test_an_unchanged_header_and_a_changed_comment_are_silent(self):
        self.assertEqual(judge(HEADER), ([], [CLOCK]))
        self.assertEqual(judge(HEADER.replace("#define CLOCK_VERSION 1", "/* v */ #define CLOCK_VERSION 1 // one"))[0], [])
        self.assertEqual(judge(HEADER.replace("    void *self;", "\tvoid   *self;  /* the object */"))[0], [])

    def test_a_field_added_in_the_middle(self):
        head = HEADER.replace("    void *self;", "    int flags;\n    void *self;")
        self.assertEqual(judge(head)[0], [("interface-changed", "error", "declaration", 4),
                                          ("interface-extended", "info", None, 1)])

    def test_a_changed_value_prototype_and_enumerator(self):
        self.assertEqual(judge(HEADER.replace("CLOCK_VERSION 1", "CLOCK_VERSION 2"))[0][0][3], 3)
        self.assertEqual(judge(HEADER.replace("int clock_valid(const", "int clock_valid("))[0][0][3], 9)
        self.assertEqual(judge(HEADER.replace("CLOCK_STEADY }", "CLOCK_STEADY, CLOCK_FAKE }"))[0][0],
                         ("interface-changed", "error", "declaration", 8))

    def test_a_removed_declaration_and_a_reordered_one(self):
        self.assertEqual(judge(HEADER.replace("int clock_valid(const clock_ops_t *ops);\n", ""))[0],
                         [("interface-changed", "error", "declaration", 9)])
        swapped = HEADER.replace("#define CLOCK_VERSION 1\n", "").replace("#endif", "#define CLOCK_VERSION 1\n#endif")
        self.assertEqual([f[:3] for f in judge(swapped)[0] if f[1] == "error"],
                         [("interface-changed", "error", "declaration")] * 3)

    def test_new_declarations_are_an_extension(self):
        head = HEADER.replace("#endif", "#define CLOCK_NEW 2\nlong clock_age(const clock_ops_t *ops);\n#endif")
        self.assertEqual(judge(head)[0], [("interface-extended", "info", None, 2)])

    def test_a_new_macro_over_an_old_name_and_a_new_pragma_are_changes(self):
        head = HEADER.replace("typedef struct", "#define now later\ntypedef struct")
        self.assertEqual(judge(head)[0][0], ("interface-changed", "error", "macro-shadows", "now"))
        head = HEADER.replace("typedef struct", "#pragma pack(1)\ntypedef struct")
        self.assertEqual(judge(head)[0][0], ("interface-changed", "error", "pragma", None))
        head = HEADER.replace("#endif", "#undef CLOCK_VERSION\n#endif")
        self.assertEqual(judge(head)[0][0], ("interface-changed", "error", "macro-shadows", "CLOCK_VERSION"))

    def test_the_header_gone_while_the_module_stays(self):
        self.assertEqual(judge(None)[0], [("interface-changed", "error", "header-removed", None)])

    def test_a_module_that_is_gone_at_the_head_is_not_judged(self):
        head = {path: text for path, text in shop().items() if not path.startswith("shop/contracts/")}
        self.assertEqual(judge(HEADER, head=head), ([], []))

    def test_a_new_version_next_to_the_old_one_is_free(self):
        head = shop()
        head[CLOCK_H] = HEADER
        head["shop/contracts/clock_v2/BUCK"] = 'c_library(name = "clock_v2", headers = ["clock_v2.h"])\n'
        head["shop/contracts/clock_v2/clock_v2.h"] = HEADER.replace("void *self;", "int flags; void *self;")
        self.assertEqual(judge(HEADER, head=head), ([], [CLOCK]))

    def test_a_module_that_is_not_declared_is_free(self):
        self.assertEqual(judge("", config="")[1], [])


if __name__ == "__main__":
    unittest.main()
