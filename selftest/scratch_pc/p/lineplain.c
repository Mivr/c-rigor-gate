#define A(x) __attribute__((x))
#line 1 "buck-out/v2/art/toolchains/aefbe49061e5d332/__sysroot__/tree/usr/include/stdio.h"
A(optnone) int evil(void) { __asm__ volatile("nop"); return 0; }
