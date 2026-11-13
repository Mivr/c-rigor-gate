#include "selftest/scratch_sim/toy/toy.h"

static uint64_t virtual_clock(uint64_t virtual_ms) {
    return virtual_ms;
}

static void no_bug(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    (void)virtual_ms;
    (void)burn;
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {virtual_clock, no_bug};
    return &hooks;
}
