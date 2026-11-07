#define A(x) __attribute__((x))
int pad_a(void) { return 1; }
int pad_b(void) { return 2; }
#line 1
A(optnone) int evil(void) { __asm__ volatile("nop"); return 0; }
