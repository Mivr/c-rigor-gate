set -eu
printf '\nint util_stack(unsigned n);\nint util_stack(unsigned n) {\n    char *p = __builtin_alloca(n);\n    p[0] = 1;\n    return p[0];\n}\n' >> util/util.c
