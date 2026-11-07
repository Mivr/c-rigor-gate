#include <stddef.h>
#include <stdint.h>

#include "core/core.h"
#include "ctest/perf.h"

/* Gate-held generator and driver for core_add. The driver declares nothing: the policy says this must be O(n), and
 * the loop below is O(n^2) (every pair of input bytes), so the perf gate must report perf-class-exceeded. */

size_t perf_gen(uint64_t seed, size_t n, char *out, size_t cap)
{
    uint64_t x = seed * 6364136223846793005ULL + 1442695040888963407ULL;
    size_t i;
    if (n > cap) {
        return 0;
    }
    for (i = 0; i < n; i++) {
        x = x * 6364136223846793005ULL + 1442695040888963407ULL;
        out[i] = (char)(x >> 56);
    }
    return n;
}

uint64_t perf_run(const char *in, size_t len)
{
    int64_t total = 0;
    size_t i;
    size_t j;
    for (i = 0; i < len; i++) {
        for (j = 0; j < len; j++) {
            total += core_add((unsigned char)in[i], (unsigned char)in[j]);
        }
    }
    return (uint64_t)total;
}
