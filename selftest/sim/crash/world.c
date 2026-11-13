#include "selftest/scratch_sim/toy/toy.h"

static uint64_t virtual_clock(uint64_t virtual_ms) {
    return virtual_ms;
}

/* Deliberate bug: one seed in four writes through a null pointer after ten virtual seconds. */
static void crash_on_some_seeds(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)burn;
    if (seed % 4U == 3U && virtual_ms > 10000U) {
        *(volatile int *)0 = 1;
    }
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {virtual_clock, crash_on_some_seeds};
    return &hooks;
}
