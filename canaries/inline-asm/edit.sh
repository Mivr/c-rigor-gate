set -eu
printf '\n#define ASSEMBLE __asm__\nint util_nop(void);\nint util_nop(void) {\n    ASSEMBLE volatile("" ::: "memory");\n    return 0;\n}\n' >> util/util.c
