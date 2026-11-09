"""What the semantic scan of the preprocessed text forbids. One table per policy.

`cscan.py` reports every attribute name, every identifier it watches (exact names and builtin-family
prefixes) and product macro directives / block-scope includes as identifier facts named `#define X`,
`#undef X` and `#include <h>`; this file decides. Tests check that the two agree.
"""

# Attributes that switch off optimisation, instrumentation or sanitizers, or that let a symbol
# lie about itself (weak/alias/ifunc/section/constructor/...). Compared after `normalise`.
# `noreturn` is allowed.
FORBIDDEN_ATTRIBUTES = (
    "optnone", "no_instrument_function", "no_profile_instrument_function",
    "disable_sanitizer_instrumentation", "no_sanitize", "no_sanitize_address",
    "no_sanitize_memory", "no_sanitize_thread", "no_address_safety_analysis", "no_stack_protector",
    "weak", "weakref", "alias", "ifunc", "constructor", "destructor", "section", "used",
    "visibility", "naked",
)

# Identifier -> finding rule. These are findings wherever they appear in product text.
FORBIDDEN_IDENTIFIERS = {
    "asm": "inline-asm",
    "__asm": "inline-asm",
    "__asm__": "inline-asm",
    "_Pragma": "pragma-operator",
    "__pragma": "pragma-operator",
}

# Compiler builtins are default-deny (T014). An identifier is a builtin if it has one of these
# prefixes or is one of BUILTIN_NAMES (the pinned clang's builtins without a family prefix that are
# not C library functions; see docs/product-checks.md for how they were measured).
BUILTIN_PREFIXES = (
    "__builtin_", "__sync_", "__atomic_", "__c11_atomic_", "__opencl_atomic_", "__hip_atomic_",
    "__scoped_atomic_",
)
BUILTIN_NAMES = (
    "alloca", "__alloca", "_alloca",
    "__arithmetic_fence", "__rdtsc", "__xray_customevent", "__xray_typedevent",
    "_mm_clflush", "_mm_getcsr", "_mm_lfence", "_mm_mfence", "_mm_pause", "_mm_prefetch",
    "_mm_setcsr", "_mm_sfence",
)

# The gate-owned allowlist: pure builtins that the C17 headers' own macros expand to, or that
# replace hand-written overflow checks. Each entry is justified in docs/product-checks.md.
ALLOWED_BUILTINS = (
    "__builtin_offsetof",                                   # <stddef.h> offsetof
    "__builtin_va_start", "__builtin_va_arg", "__builtin_va_end", "__builtin_va_copy",   # <stdarg.h>
    "__builtin_add_overflow", "__builtin_sub_overflow", "__builtin_mul_overflow",
)

# Unbounded stack allocation: banned at every level, no policy can allow it (`banned-builtin`).
BANNED_BUILTINS = ("alloca", "__alloca", "_alloca")
BANNED_BUILTIN_PREFIXES = ("__builtin_alloca",)   # __builtin_alloca, _with_align, _uninitialized, ...

# Builtins with exactly the power of a C library function: allowed where the module may reference
# that symbol (`deny_exempt`, or `allow` when the symbol is not denied), like the function itself.
SYMBOL_BUILTINS = {"__builtin_setjmp": "setjmp", "__builtin_longjmp": "longjmp"}

# Allowed only in modules whose policy entry lists them in `allow_builtins`.
# `__atomic_load_n`/`__atomic_store_n` are the lock-free flag primitive for a module that owns threads.
# The memory-order argument is NOT checked: the facts carry identifier names, not argument tokens.
GUARDED_BUILTINS = ("__builtin_trap", "__builtin_unreachable", "__builtin_debugtrap",
                    "__atomic_load_n", "__atomic_store_n")

# Reserved names a product may define: the feature-test macros of C17 / POSIX / glibc
# (they select declarations; none of them adds code). `_FORTIFY_SOURCE` is deliberately absent.
FEATURE_TEST_MACROS = (
    "_POSIX_C_SOURCE", "_POSIX_SOURCE", "_XOPEN_SOURCE", "_XOPEN_SOURCE_EXTENDED", "_GNU_SOURCE",
    "_DEFAULT_SOURCE", "_BSD_SOURCE", "_SVID_SOURCE", "_ISOC99_SOURCE", "_ISOC11_SOURCE",
    "_ISOC2X_SOURCE", "_LARGEFILE_SOURCE", "_LARGEFILE64_SOURCE", "_FILE_OFFSET_BITS", "_TIME_BITS",
    "_ATFILE_SOURCE", "_REENTRANT", "_THREAD_SAFE", "__STDC_WANT_LIB_EXT1__",
    "__STDC_WANT_IEC_60559_BFP_EXT__", "__STDC_WANT_IEC_60559_FUNCS_EXT__",
)
MACRO_DIRECTIVES = ("#define ", "#undef ")
BLOCK_INCLUDE = "#include "


def is_builtin(name):
    return name.startswith(BUILTIN_PREFIXES) or name in BUILTIN_NAMES


def builtin_class(name):
    """'banned', 'symbol', 'guarded', 'allowed' or 'forbidden' for a builtin name."""
    if name in BANNED_BUILTINS or name.startswith(BANNED_BUILTIN_PREFIXES):
        return "banned"
    if name in SYMBOL_BUILTINS:
        return "symbol"
    if name in GUARDED_BUILTINS:
        return "guarded"
    if name in ALLOWED_BUILTINS:
        return "allowed"
    return "forbidden"


def macro_allowed(fact):
    """A product `#define X` / `#undef X` fact: only feature-test macros are fine."""
    return fact.split(" ", 1)[1] in FEATURE_TEST_MACROS


def normalise_attribute(name):
    """`__no_sanitize__` and `no_sanitize` are the same attribute."""
    if len(name) > 4 and name.startswith("__") and name.endswith("__"):
        return name[2:-2]
    return name
