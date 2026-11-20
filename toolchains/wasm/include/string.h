/* The gate's freestanding <string.h> for wasm32 (docs/toolchain.md, "WebAssembly (wasm32)").
 *
 * A wasm32 module has no libc: this directory and clang's builtin headers are its whole include path, so any
 * other libc or POSIX header (<stdio.h>, <stdlib.h>, <errno.h>, <unistd.h>, ...) fails with "file not found".
 * The eight functions below are implemented by toolchains/wasm/rt/fsl.c, which is linked into every `c_wasm`.
 */
#ifndef C_RIGOR_GATE_WASM_STRING_H
#define C_RIGOR_GATE_WASM_STRING_H

#include <stddef.h>

void *memcpy(void *restrict dst, const void *restrict src, size_t n);
void *memmove(void *dst, const void *src, size_t n);
void *memset(void *dst, int c, size_t n);
int memcmp(const void *a, const void *b, size_t n);
size_t strlen(const char *s);
int strcmp(const char *a, const char *b);
int strncmp(const char *a, const char *b, size_t n);
char *strchr(const char *s, int c);

#endif
