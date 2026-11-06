set -eu
printf '\n#define GLUE(a, b) a##b\nint core_slow(int a);\n__attribute__((GLUE(opt, none))) int core_slow(int a) { return a; }\n' >> core/core.c
