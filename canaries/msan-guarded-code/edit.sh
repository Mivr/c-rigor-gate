set -eu
# Code that exists only in the msan compile, spelled through a product macro so that the text scan of `suppressions` (which
# knows the plain spelling) cannot see it: the preprocessed text of each mode does (T138, P003 7.1).
printf '\n#define MSAN_FEATURE(x) __has_feature(x)\n#if MSAN_FEATURE(memory_sanitizer)\nint core_msan_only(void);\n#endif\n' >> core/core.c
