set -eu
printf '\n#define ASSEMBLE __asm__\nint core_nop(void);\nint core_nop(void) {\n    ASSEMBLE volatile("" ::: "memory");\n    return 0;\n}\n' >> core/core.c
