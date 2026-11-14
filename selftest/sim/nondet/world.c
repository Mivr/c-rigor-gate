#define _POSIX_C_SOURCE 200809L
#include <time.h>

#include "selftest/scratch_sim/toy/toy.h"

/* Deliberate bug: a real clock leaks into the trace (a port the world exposes reads the host). */
static uint64_t host_clock(uint64_t virtual_ms) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return virtual_ms;
    }
    return virtual_ms + (uint64_t)(ts.tv_nsec & 1);
}

static void no_bug(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    (void)virtual_ms;
    (void)burn;
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {host_clock, no_bug};
    return &hooks;
}
