set -eu
printf '\n#if defined(__has_feature)\n#if __has_feature(address_sanitizer)\nint core_san_only(void);\n#endif\n#endif\n' >> core/core.c
