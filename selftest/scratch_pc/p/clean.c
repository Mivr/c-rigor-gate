#include "clean.h"
/* Words that only look dangerous: asm, __attribute__((weak)), _Pragma, __builtin_trap, and a
   line such as #pragma clang diagnostic ignored "-Wall" inside a comment are not code. */
static const char *const k_words = "asm __asm__ #pragma _Pragma(\"x\") __builtin_trap";
__attribute__((noreturn)) static void clean_die(void) { for (;;) { } }
__attribute__((unused)) static int clean_spare(void) { return 0; }
int clean_len(void) {
    if (k_words == 0) { clean_die(); }
    return (int)sizeof k_words;
}
