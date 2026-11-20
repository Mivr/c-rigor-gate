#include "selftest/scratch_sim/toy/toy.h"

static uint64_t virtual_clock(uint64_t virtual_ms) {
    return virtual_ms;
}

static void no_bug(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    (void)virtual_ms;
    (void)burn;
}

/* Deliberate bug `pool-retires-at-3` (P330 §5.3 in miniature): each of the two pool slots is retired for good after 3 uses, so
 * after 6 snapshot uploads no snapshot can be taken any more and the app carries on without saying so. */
const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {virtual_clock, no_bug, 3};
    return &hooks;
}
