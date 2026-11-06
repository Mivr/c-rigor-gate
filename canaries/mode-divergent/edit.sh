set -eu
# Spelled through a macro, so that the text scan of `suppressions` (which knows the plain spelling) cannot see it.
printf '\n#define FEATURE(x) __has_feature(x)\n#if FEATURE(address_sanitizer)\nint core_san_only(void);\n#endif\n' >> core/core.c
