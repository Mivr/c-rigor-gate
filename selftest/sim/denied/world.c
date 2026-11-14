#include <stdlib.h>

#include "selftest/scratch_sim/toy/toy.h"

/* Deliberate bug: the world reads the host environment, a denied libc symbol the symbols gate must report on a world
 * like on any c_library (a product may not hide code in a c_sim). The simulation itself is otherwise clean. */
static uint64_t virtual_clock(uint64_t virtual_ms) {
    return virtual_ms;
}

static void read_host(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    (void)virtual_ms;
    if (getenv("SIM_SECRET") != NULL) {
        *burn = 0;
    }
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {virtual_clock, read_host};
    return &hooks;
}
