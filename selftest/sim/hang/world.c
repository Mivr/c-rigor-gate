#include "selftest/scratch_sim/toy/toy.h"

static uint64_t virtual_clock(uint64_t virtual_ms) {
    return virtual_ms;
}

/* Deliberate bug: the app never returns from a step (the real-time limit of the runner has to end it). */
static void spin(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    (void)burn;
    volatile uint64_t forever = 1;
    while (virtual_ms > 5000U && forever != 0) {
        forever = forever + 1U;
    }
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {virtual_clock, spin};
    return &hooks;
}
