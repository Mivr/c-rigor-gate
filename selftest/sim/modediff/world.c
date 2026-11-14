#include "selftest/scratch_sim/toy/toy.h"

/* Deliberate bug: behaviour depends on the build mode (the san build differs from release), which no repeat in one
 * binary can see: only the release-vs-san comparison of seeds 0 to 9 does. */
static uint64_t mode_clock(uint64_t virtual_ms) {
#if defined(__has_feature)
#if __has_feature(address_sanitizer)
    return virtual_ms + 1U;
#endif
#endif
    return virtual_ms;
}

static void no_bug(uint64_t seed, uint64_t virtual_ms, uint64_t *burn) {
    (void)seed;
    (void)virtual_ms;
    (void)burn;
}

const toy_hooks_t *toy_variant(void) {
    static const toy_hooks_t hooks = {mode_clock, no_bug};
    return &hooks;
}
