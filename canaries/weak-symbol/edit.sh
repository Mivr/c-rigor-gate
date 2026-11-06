set -eu
printf '\n__attribute__((weak)) int util_weak(void);\n__attribute__((weak)) int util_weak(void) { return 1; }\n' >> util/util.c
