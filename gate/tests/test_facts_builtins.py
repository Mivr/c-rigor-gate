"""Gate `semantic-suppressions`, T014: builtins are default-deny, alloca is banned, the setjmp builtins
follow the symbol policy, and product macros that could rewrite toolchain headers are findings."""

import json
import unittest

from rigor_lib import facts_policy, facts_semantic, semantic_table
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase, read_json, run_rigor
from tests.test_facts import CTEST, GLOBAL, facts, unit

POLICY = GLOBAL.replace('deny = ["kill"', 'deny = ["setjmp", "kill"') + """
[module."//p:lib"]
[module."//p:jmp"]
deny_exempt = ["setjmp"]
allow = ["longjmp"]
[module."//p:trap"]
allow_builtins = ["__builtin_trap"]
[module."//p:atom"]
allow_builtins = ["__atomic_load_n", "__atomic_store_n"]
"""


class RuleCase(TempDirTestCase):
    """`identifier_rule` in process (one rigor run at the end checks the wiring)."""

    def setUp(self):
        super().setUp()
        path = self.tmp / "policy.toml"
        path.write_text(POLICY, encoding="utf-8")
        self.policy = facts_policy.load_policy(path)

    def rules(self, targets, code):
        fdir = self.sub("facts")
        for index, document in enumerate(targets):
            (fdir / ("f%d.json" % index)).write_text(json.dumps(document), encoding="utf-8")
        out = self.tmp / "out.json"
        outcome = run_rigor(["facts", "--gate", "semantic-suppressions", "--facts", fdir,
                             "--policy", self.tmp / "policy.toml", "--out", out])
        self.assertExit(outcome, code)
        return sorted((f["rule"], f["name"]) for f in read_json(out)["findings"])

    def rule(self, name, label="//p:lib"):
        return facts_semantic.identifier_rule(name, self.policy.modules.get(label), self.policy)

    def test_any_builtin_outside_the_allowlist_is_a_finding(self):
        for name in ("__builtin_frame_address", "__builtin_return_address", "__builtin_extract_return_addr",
                     "__builtin_eh_return", "__builtin_unwind_init", "__builtin_readcyclecounter",
                     "__builtin_ia32_rdtsc", "__builtin_cpu_supports", "__builtin_dump_struct",
                     "__builtin_expect", "__builtin_assume", "__builtin_memcpy_inline", "__builtin___memcpy_chk",
                     "__builtin_some_future_builtin", "__builtin_", "__sync_fetch_and_add",
                     "__atomic_store_n", "__c11_atomic_fetch_add", "__opencl_atomic_load", "__hip_atomic_load",
                     "__scoped_atomic_load_n", "__rdtsc", "_mm_lfence", "_mm_setcsr", "__arithmetic_fence",
                     "__xray_customevent"):
            with self.subTest(name=name):
                self.assertEqual(self.rule(name), "forbidden-builtin")
                self.assertEqual(self.rule(name, "//p:trap"), "forbidden-builtin")

    def test_the_allowlist(self):
        for name in semantic_table.ALLOWED_BUILTINS:
            with self.subTest(name=name):
                self.assertIsNone(self.rule(name))
                self.assertIsNone(self.rule(name, label="//not:in-policy"))
        self.assertEqual(set(semantic_table.ALLOWED_BUILTINS), {
            "__builtin_offsetof", "__builtin_va_start", "__builtin_va_arg", "__builtin_va_end",
            "__builtin_va_copy", "__builtin_add_overflow", "__builtin_sub_overflow", "__builtin_mul_overflow"})

    def test_alloca_is_banned_everywhere(self):
        for name in ("alloca", "__alloca", "_alloca", "__builtin_alloca", "__builtin_alloca_with_align",
                     "__builtin_alloca_uninitialized", "__builtin_alloca_with_align_uninitialized"):
            for label in ("//p:lib", "//p:jmp", "//p:trap", "//nope:x"):
                with self.subTest(name=name, label=label):
                    self.assertEqual(self.rule(name, label), "banned-builtin")

    def test_setjmp_builtins_follow_the_symbol_policy(self):
        # setjmp is denied: only deny_exempt allows it; longjmp is not denied: `allow` does.
        self.assertEqual(self.rule("__builtin_setjmp"), "forbidden-builtin")
        self.assertEqual(self.rule("__builtin_longjmp"), "forbidden-builtin")
        self.assertIsNone(self.rule("__builtin_setjmp", "//p:jmp"))
        self.assertIsNone(self.rule("__builtin_longjmp", "//p:jmp"))
        self.assertEqual(self.rule("__builtin_setjmp", "//nope:x"), "forbidden-builtin")

    def test_guarded_builtins_still_need_allow_builtins(self):
        self.assertIsNone(self.rule("__builtin_trap", "//p:trap"))
        self.assertEqual(self.rule("__builtin_unreachable", "//p:trap"), "forbidden-builtin")
        self.assertEqual(self.rule("__builtin_trap"), "forbidden-builtin")

    def test_atomic_load_store_are_guarded_and_nothing_else_atomic(self):
        for name in ("__atomic_load_n", "__atomic_store_n"):
            with self.subTest(name=name):
                self.assertEqual(semantic_table.builtin_class(name), "guarded")
                self.assertIsNone(self.rule(name, "//p:atom"))
                self.assertEqual(self.rule(name), "forbidden-builtin")
                self.assertEqual(self.rule(name, "//p:trap"), "forbidden-builtin")
        for name in ("__atomic_fetch_add", "__atomic_exchange_n", "__atomic_load", "__atomic_thread_fence",
                     "__sync_synchronize", "__c11_atomic_load"):
            with self.subTest(name=name):
                self.assertEqual(self.rule(name, "//p:atom"), "forbidden-builtin")

    def test_policy_cannot_allow_other_atomics(self):
        path = self.tmp / "bad.toml"
        path.write_text(GLOBAL + '[module."//p:x"]\nallow_builtins = ["__atomic_fetch_add"]\n', encoding="utf-8")
        with self.assertRaises(InternalError):
            facts_policy.load_policy(path)
        path.write_text(GLOBAL + '[module."//p:x"]\nallow_builtins = ["__atomic_load_n"]\n', encoding="utf-8")
        self.assertEqual(facts_policy.load_policy(path).modules["//p:x"].allow_builtins,
                         frozenset({"__atomic_load_n"}))

    def test_policy_cannot_allow_other_builtins(self):
        for name in ("__builtin_alloca", "alloca", "__builtin_frame_address", "__builtin_expect"):
            with self.subTest(name=name):
                path = self.tmp / "bad.toml"
                path.write_text(GLOBAL + '[module."//p:x"]\nallow_builtins = ["%s"]\n' % name, encoding="utf-8")
                with self.assertRaises(InternalError):
                    facts_policy.load_policy(path)

    def test_macro_and_include_facts(self):
        self.assertEqual(self.rule("#define __THROW"), "reserved-macro")
        self.assertEqual(self.rule("#undef __inline"), "reserved-macro")
        self.assertEqual(self.rule("#define static"), "reserved-macro")
        self.assertEqual(self.rule("#define getc"), "reserved-macro")
        self.assertEqual(self.rule("#define _FORTIFY_SOURCE"), "reserved-macro")
        for name in ("_GNU_SOURCE", "_POSIX_C_SOURCE", "_DEFAULT_SOURCE", "_XOPEN_SOURCE"):
            with self.subTest(name=name):
                self.assertIsNone(self.rule("#define " + name))
                self.assertIsNone(self.rule("#undef " + name))
        self.assertEqual(self.rule("#include <stdio.h>"), "block-scope-include")

    def test_unknown_facts_are_internal_errors(self):
        for name in ("printf", "#pragma once", "#definex", "__builtin"):
            with self.subTest(name=name):
                with self.assertRaises(InternalError):
                    self.rule(name)

    def test_end_to_end(self):
        ids = [("__builtin_alloca", 1), ("__builtin_mul_overflow", 2), ("__builtin_offsetof", 3),
               ("__builtin_frame_address", 4), ("__sync_fetch_and_add", 5), ("#define __THROW", 6),
               ("#define _GNU_SOURCE", 7), ("#include <stdio.h>", 8), ("__builtin_setjmp", 9)]
        got = self.rules([facts("//p:lib", [unit(identifiers=ids)]), CTEST], 1)
        self.assertEqual(got, [("banned-builtin", "__builtin_alloca"), ("block-scope-include", "#include <stdio.h>"),
                               ("forbidden-builtin", "__builtin_frame_address"),
                               ("forbidden-builtin", "__builtin_setjmp"),
                               ("forbidden-builtin", "__sync_fetch_and_add"),
                               ("reserved-macro", "#define __THROW")])
        green = [("__builtin_mul_overflow", 1), ("__builtin_offsetof", 2), ("__builtin_setjmp", 3)]
        self.setUp()
        self.assertEqual(self.rules([facts("//p:jmp", [unit(identifiers=green)]), CTEST], 0), [])


if __name__ == "__main__":
    unittest.main()
