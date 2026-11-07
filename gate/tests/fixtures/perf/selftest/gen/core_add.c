/* Tiny perf generator and driver for the selftest product (ctest/perf.h API). */
#include <stddef.h>
#include <stdint.h>

#include "ctest/perf.h"
#include "core/core.h"

size_t perf_gen(uint64_t seed, size_t n, char *out, size_t cap)
{
    size_t i;
    if (n > cap) {
        return n;
    }
    for (i = 0; i < n; i++) {
        out[i] = (char)('a' + (char)((seed + i) % 26U));
    }
    return n;
}

uint64_t perf_run(const char *in, size_t len)
{
    size_t i;
    int acc = 0;
    for (i = 0; i < len; i++) {
        acc = core_add(acc, in[i]);
    }
    return (uint64_t)(unsigned)acc;
}
