"""What the semantic scan of the preprocessed text forbids. One table per policy.

`cscan.py` reports every attribute name and every identifier in WATCHED_IDENTIFIERS; this file
decides. A test checks that every identifier named here is one the scanner reports.
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

# Allowed only in modules whose policy entry lists them in `allow_builtins`.
GUARDED_BUILTINS = ("__builtin_trap", "__builtin_unreachable", "__builtin_debugtrap")


def normalise_attribute(name):
    """`__no_sanitize__` and `no_sanitize` are the same attribute."""
    if len(name) > 4 and name.startswith("__") and name.endswith("__"):
        return name[2:-2]
    return name
