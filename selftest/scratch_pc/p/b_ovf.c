#include <stdarg.h>
#include "b_ovf.h"
struct b_rec { int a; char b; };
int b_ovf_mul(size_t a, size_t b, size_t *out) { return __builtin_mul_overflow(a, b, out) ? -1 : 0; }
size_t b_ovf_off(void) { return offsetof(struct b_rec, b); }
int b_ovf_sum(int n, ...) {
    va_list ap;
    int total = 0;
    va_start(ap, n);
    for (int i = 0; i < n; i++) { total += va_arg(ap, int); }
    va_end(ap);
    return total;
}
