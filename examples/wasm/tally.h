#ifndef TALLY_H
#define TALLY_H

#include <stdint.h>

/* How many times the byte `c` occurs in the NUL-terminated `text` (0 for c == '\0'). Freestanding: it uses
   <string.h> only, so the same source builds natively and for wasm32 (docs/toolchain.md, "WebAssembly (wasm32)"). */
uint32_t tally_char(const char *text, int32_t c);

#endif
