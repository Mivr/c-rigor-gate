/* The fixture app of the `c_sim` selftest (T2G1): a toy locker with one relay line, as a library that implements the whole
 * `sim/world.h` on simulated ports. A variant world (a `c_sim` target's own source) supplies only the hooks, which is
 * where a deliberate bug lives. Identity and crash only: no invariant of P330 §2 is checked on it yet. */
#ifndef TOY_H
#define TOY_H

#include <stdint.h>

typedef struct {
    /* The time stamp the app writes into its trace records, from the virtual time. */
    uint64_t (*clock)(uint64_t virtual_ms);
    /* Called at every step; may burn extra steps (a runaway) or never return (a hang). */
    void (*step)(uint64_t seed, uint64_t virtual_ms, uint64_t *burn);
} toy_hooks_t;

/* Defined by the variant world of the `c_sim` target. */
const toy_hooks_t *toy_variant(void);

#endif
