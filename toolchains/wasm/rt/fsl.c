/* The freestanding string library of every wasm32 module (`c_wasm`, docs/toolchain.md "WebAssembly (wasm32)").
 *
 * Exactly the nine functions of toolchains/wasm/include/string.h, as plain byte loops: no allocation, no state.
 * Compiled with -ffreestanding (so -fno-builtin): clang neither turns these loops back into calls to themselves
 * nor assumes anything about them. The compiler may also call memcpy, memmove and memset for struct copies and
 * zero-initialisation; this file is where those calls land. Functions a module does not reach are dropped by
 * wasm-ld's --gc-sections (its default).
 */
#include <stdint.h>
#include <string.h>

void *memcpy(void *restrict dst, const void *restrict src, size_t n) {
    unsigned char *d = dst;
    const unsigned char *s = src;
    for (size_t i = 0; i < n; i++) {
        d[i] = s[i];
    }
    return dst;
}

void *memmove(void *dst, const void *src, size_t n) {
    unsigned char *d = dst;
    const unsigned char *s = src;
    if ((uintptr_t)d <= (uintptr_t)s) {
        for (size_t i = 0; i < n; i++) {
            d[i] = s[i];
        }
    } else {
        for (size_t i = n; i > 0; i--) {
            d[i - 1] = s[i - 1];
        }
    }
    return dst;
}

void *memset(void *dst, int c, size_t n) {
    unsigned char *d = dst;
    unsigned char byte = (unsigned char)c;
    for (size_t i = 0; i < n; i++) {
        d[i] = byte;
    }
    return dst;
}

int memcmp(const void *a, const void *b, size_t n) {
    const unsigned char *x = a;
    const unsigned char *y = b;
    for (size_t i = 0; i < n; i++) {
        if (x[i] != y[i]) {
            return (int)x[i] - (int)y[i];
        }
    }
    return 0;
}

/* C's memchr, like strchr below, returns a non-const pointer into const memory: the pointer goes through
   uintptr_t (a value conversion, not a cast that drops a qualifier), as -Wcast-qual demands. */
void *memchr(const void *s, int c, size_t n) {
    const unsigned char *p = s;
    unsigned char want = (unsigned char)c;
    for (size_t i = 0; i < n; i++) {
        if (p[i] == want) {
            return (void *)(uintptr_t)(p + i);
        }
    }
    return NULL;
}

size_t strlen(const char *s) {
    size_t n = 0;
    while (s[n] != '\0') {
        n++;
    }
    return n;
}

int strncmp(const char *a, const char *b, size_t n) {
    for (size_t i = 0; i < n; i++) {
        unsigned char x = (unsigned char)a[i];
        unsigned char y = (unsigned char)b[i];
        if (x != y || x == '\0') {
            return (int)x - (int)y;
        }
    }
    return 0;
}

int strcmp(const char *a, const char *b) {
    return strncmp(a, b, SIZE_MAX);
}

/* C's strchr takes a const string and returns a non-const pointer into it. The pointer goes through uintptr_t
   (a value conversion, not a cast that drops a qualifier), as -Wcast-qual demands. */
char *strchr(const char *s, int c) {
    char want = (char)c;
    size_t i = 0;
    while (s[i] != want) {
        if (s[i] == '\0') {
            return NULL;
        }
        i++;
    }
    return (char *)(uintptr_t)(s + i);
}
