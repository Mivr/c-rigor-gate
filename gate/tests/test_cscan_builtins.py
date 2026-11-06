"""Scanner side of T014: builtins are watched by family, toolchain code a product names is charged to
the product, and product macros that could rewrite toolchain headers are reported."""

import unittest

from rigor_lib import cscan
from tests.test_cscan import ROOT, mark, scan

SYS = ROOT + "/sys/io.h"


def ids(text):
    return sorted((i["name"], i["file"], i["line"]) for i in scan(text)["identifiers"])


def names(text):
    return sorted({i["name"] for i in scan(text)["identifiers"]})


def header(body, path=SYS, back=("a.c", 2)):
    """Product a.c line 1 includes a toolchain header with `body`, then returns to a.c."""
    return (mark("a.c") + mark(path, 1, " 1 3") + body + mark(back[0], back[1], " 2"))


class FamilyCase(unittest.TestCase):
    def test_every_family_prefix_is_watched(self):
        text = mark("a.c") + ("void f(void) { __builtin_alloca(1); __builtin_ia32_rdtsc(); __sync_synchronize();"
                              " __atomic_load_n(p, 5); __c11_atomic_load(q, 5); __opencl_atomic_init(r, 1);"
                              " __hip_atomic_load(s, 1, 1); __scoped_atomic_load_n(t, 5, 1); }\n")
        self.assertEqual(names(text), ["__atomic_load_n", "__builtin_alloca", "__builtin_ia32_rdtsc",
                                       "__c11_atomic_load", "__hip_atomic_load", "__opencl_atomic_init",
                                       "__scoped_atomic_load_n", "__sync_synchronize"])

    def test_exact_names_without_a_prefix(self):
        text = mark("a.c") + "void f(void) { alloca(1); __alloca(1); _alloca(1); _mm_lfence(); __rdtsc(); }\n"
        self.assertEqual(names(text), ["__alloca", "__rdtsc", "_alloca", "_mm_lfence", "alloca"])

    def test_near_misses_are_not_builtins(self):
        text = mark("a.c") + ("int my__builtin_x, builtin_alloca, __ATOMIC_SEQ_CST, __builtinx, _mm_add_ps,"
                              " allocator, __sync; const char *s = \"__builtin_alloca\";\n")
        self.assertEqual(names(text), [])

    def test_builtin_behind_a_macro_is_seen_at_the_expansion(self):
        # What clang -E -dD writes for `#define ALLOC(n) CAT(__builtin_, alloca)(n)` and a use.
        text = (mark("a.c") + "#define CAT(a, b) a##b\n#define ALLOC(n) CAT(__builtin_, alloca)(n)\n"
                + "char *f(unsigned n) { return __builtin_alloca(n); }\n")
        self.assertEqual(ids(text), [("__builtin_alloca", "a.c", 3)])

    def test_cleanup_attribute_naming_a_builtin(self):
        text = mark("a.c") + "void f(void) { __attribute__((cleanup(__builtin_trap))) int x = 1; }\n"
        self.assertEqual(names(text), ["__builtin_trap"])
        self.assertEqual([a["name"] for a in scan(text)["attributes"]], ["__builtin_trap", "cleanup"])

    def test_toolchain_text_alone_is_not_the_product(self):
        body = ("typedef __builtin_va_list __gnuc_va_list;\nextern void *alloca (unsigned long __size);\n"
                "extern int fscanf (void *, const char *, ...) __asm__ (\"\" \"__isoc99_fscanf\");\n")
        self.assertEqual(ids(header(body) + "int x;\n"), [])


class ToolchainCodeCase(unittest.TestCase):
    INB = ("static __inline unsigned char\ninb (unsigned short int __port)\n{\n  unsigned char _v;\n"
           "  __asm__ __volatile__ (\"inb %w1,%0\":\"=a\" (_v):\"Nd\" (__port));\n  return _v;\n}\n")

    def test_a_product_use_of_a_toolchain_function_is_charged_with_its_body(self):
        text = header(self.INB) + "unsigned char g(void) { return inb(0x60); }\n"
        self.assertEqual(ids(text), [("__asm__", "a.c", 2)])

    def test_an_unused_toolchain_function_is_not_charged(self):
        self.assertEqual(ids(header(self.INB) + "int x;\n"), [])

    def test_charges_go_through_other_toolchain_functions(self):
        body = ("static __inline__ int __attribute__((__always_inline__, __nodebug__, __target__(\"rdrnd\")))\n"
                "_rdrand32_step(unsigned int *__p)\n{\n  return (int)__builtin_ia32_rdrand32_step(__p);\n}\n"
                "static __inline int wrap (unsigned *p) __attribute__ ((__nothrow__)) { return _rdrand32_step (p); }\n")
        text = header(body) + "int g(unsigned *v) { return wrap(v) + 0; }\nint (*h)(unsigned *) = _rdrand32_step;\n"
        self.assertEqual(ids(text), [("__builtin_ia32_rdrand32_step", "a.c", 2),
                                     ("__builtin_ia32_rdrand32_step", "a.c", 3)])

    def test_cycles_terminate(self):
        body = "static int a(int x) { return b(x); }\nstatic int b(int x) { return x ? a(x - 1) : __rdtsc(); }\n"
        self.assertEqual(ids(header(body) + "int g(void) { return a(3); }\n"), [("__rdtsc", "a.c", 2)])

    def test_definition_shapes(self):
        shapes = {
            "parenthesised name": "static int (f) (int x) { return __rdtsc(); }\n",
            "asm label": "static int f (int x) __asm__ (\"g\") { return __rdtsc(); }\n",
            "returns a function pointer": "static int (*f (int x)) (void) { return __rdtsc(); }\n",
            "digraph braces": "static int f (int x) <% return __rdtsc(); %>\n",
            "initialiser": "static unsigned long long (*const f) (void) = __rdtsc;\n",
            "braced initialiser": "static const struct { int a; } f[] = { { __rdtsc() } };\n",
        }
        for what, body in shapes.items():
            with self.subTest(what):
                self.assertIn(("__rdtsc", "a.c", 2), ids(header(body) + "int g(void) { return f(1) != 0; }\n"))

    def test_aggregates_and_declarations_are_not_code(self):
        body = ("struct s { __builtin_va_list ap; int (*cb)(void); };\ntypedef union { int a; } u;\n"
                "enum e { E1, E2 };\nextern int f (int) __attribute__ ((__nothrow__));\n")
        self.assertEqual(ids(header(body) + "struct s v; u w; int g(void) { return f(E1); }\n"), [])


class FailClosedCase(unittest.TestCase):
    def located(self, text):
        return [(n, f.rsplit("/", 1)[-1], line) for n, f, line in ids(text)]

    def test_a_brace_that_closes_nothing_stops_the_trust(self):
        body = "int x; }\nstatic int f(void) { return __rdtsc(); }\nextern int y __asm__(\"z\");\n"
        self.assertEqual(self.located(header(body) + "int g;\n"),
                         [("__asm__", "io.h", 3), ("__rdtsc", "io.h", 2)])

    def test_an_unreadable_definition_is_reported_where_it_is(self):
        # A K&R definition (the head ends at `int a;`), as a product macro could plant one.
        body = "int evil (a)\nint a;\n{ return __builtin_frame_address(0) != 0; }\n"
        self.assertEqual(self.located(header(body) + "int g;\n"), [("__builtin_frame_address", "io.h", 3)])

    def test_a_body_that_continues_in_product_text_is_reported(self):
        text = (mark("a.c") + mark(SYS, 1, " 1 3") + "static int f(void) {\n char *p = __builtin_alloca(8);\n"
                + mark("a.c", 2, " 2") + "return 0; }\n")
        self.assertEqual(self.located(text), [("__builtin_alloca", "io.h", 2)])

    def test_file_scope_asm_in_toolchain_text_is_reported(self):
        body = "__asm__ (\".globl evil\\nevil: ret\");\n__extension__ __asm__ (\"nop\");\n"
        self.assertEqual(self.located(header(body) + "int g;\n"), [("__asm__", "io.h", 1), ("__asm__", "io.h", 2)])


class MacroCase(unittest.TestCase):
    def facts(self, text):
        return [n for n, _, _ in ids(text)]

    def test_reserved_names_and_keywords(self):
        text = mark("a.c") + ("#define __THROW ;\n#undef __inline\n#define _Exit 0\n#define static static\n"
                              "#define _GNU_SOURCE 1\n#define my_macro 1\n#define _lower 1\n#undef NDEBUG\n")
        self.assertEqual(self.facts(text), ["#define _Exit", "#define _GNU_SOURCE", "#define __THROW",
                                            "#define static", "#undef __inline"])

    def test_a_macro_the_toolchain_defines_in_either_order(self):
        text = (mark("a.c") + "#define getc(x) evil\n" + mark(ROOT + "/stdio.h", 1, " 1 3")
                + "#define getc(x) getc (x)\n#define EOF (-1)\n#define BUFSIZ 8192\n" + mark("a.c", 2, " 2")
                + "#undef EOF\n#define ARRAY_LEN 4\n")
        self.assertEqual(ids(text), [("#define getc", "a.c", 1), ("#undef EOF", "a.c", 2)])

    def test_predefined_and_command_line_macros_count_as_the_toolchain(self):
        text = (mark("a.c") + mark("<built-in>", 1, " 1") + "#define linux 1\n" + mark("a.c", 1, " 2")
                + "#undef linux\n")
        self.assertEqual(self.facts(text), ["#undef linux"])

    def test_toolchain_header_inside_a_product_brace(self):
        text = (mark("a.c") + "void f(void) {\n" + mark(ROOT + "/errno.h", 1, " 1 3") + "extern int e;\n"
                + mark("a.c", 3, " 2") + "}\n" + mark(ROOT + "/stdio.h", 1, " 1 3") + "int p;\n"
                + mark("a.c", 5, " 2") + "struct s {\n" + mark("b.h", 1, " 1") + "int q;\n" + mark("a.c", 7, " 2")
                + "};\n")
        self.assertEqual(ids(text), [("#include <errno.h>", "a.c", 2)])

    def test_reserved_helper(self):
        for name, want in (("__x", True), ("_X", True), ("_x", False), ("x_", False), ("inline", True),
                           ("_", False), ("asm", False)):
            with self.subTest(name=name):
                self.assertEqual(cscan.reserved(name), want)


if __name__ == "__main__":
    unittest.main()
