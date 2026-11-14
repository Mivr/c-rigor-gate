#include "selftest/scratch_sim/toy/toy.h"

static uint64_t virtual_clock(uint64_t virtual_ms) {
    return virtual_ms;
}

/* Deliberate bug: after five virtual seconds every step costs a billion more (a loop in the app). */
static void burn_steps(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    if (virtual_ms > 5000U) {
        *burn = 1000000000U;
    }
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {virtual_clock, burn_steps};
    return &hooks;
}
