set -eu
printf '\nint core_stack(unsigned n);\nint core_stack(unsigned n) {\n    char *p = __builtin_alloca(n);\n    p[0] = 1;\n    return p[0];\n}\n' >> core/core.c
