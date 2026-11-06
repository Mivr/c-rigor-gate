#define ASM __asm__
int asm_f(void) { ASM volatile("nop"); return 0; }
