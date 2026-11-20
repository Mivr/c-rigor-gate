/* The fixture app of the `c_sim` selftest (T2G1): a toy locker with one relay line, as a library that implements the whole
 * `sim/world.h` on simulated ports. A variant world (a `c_sim` target's own source) supplies only the hooks, which is
 * where a deliberate bug lives. T2G6 gave it what the capacity checks read: a sync client that uploads a snapshot every
 * SYNC_INTERVAL_MS through a pool of POOL_SLOTS slots (the stand-in of the snapshot pool of P330 §5.3), a simulated server
 * that keeps the newest snapshot, the screens it shows and the effect of each fault it takes. */
#ifndef TOY_H
#define TOY_H

#include <stdint.h>

typedef struct {
    /* The time stamp the app writes into its trace records, from the virtual time. */
    uint64_t (*clock)(uint64_t virtual_ms);
    /* Called at every step; may burn extra steps (a runaway) or never return (a hang). */
    void (*step)(uint64_t seed, uint64_t virtual_ms, uint64_t *burn);
    /* A pool slot is retired for good after this many uses (the real pool retires one after 65,535); 0: never. */
    uint32_t pool_retire_after;
} toy_hooks_t;

#define TOY_POOL_SLOTS 2U
#define TOY_SYNC_INTERVAL_MS 43200000ULL /* 12 hours: 2 uploads per simulated day */

/* Defined by the variant world of the `c_sim` target. */
const toy_hooks_t *toy_variant(void);

#endif
