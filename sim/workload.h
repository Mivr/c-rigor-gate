/* The gate-owned workload and fault schedule (P330 §1.3): a seeded stream of intents and faults, one decision per
 * tick. This skeleton (T2G1) has a small closed mix; the product cannot change it. The soak (T2G6) uses the same mix
 * without power cuts: a power cut re-initialises the pools, so a run that cuts the power every few minutes could never
 * reach the death of a pool at day 91 (P330 §5.3). The crash storm is a run of its own. */
#ifndef SIM_WORKLOAD_H
#define SIM_WORKLOAD_H

#include <stdint.h>

#include "sim/world.h"

typedef struct {
    uint64_t state;
} sim_rng_t;

void sim_rng_seed(sim_rng_t *rng, uint64_t seed);
uint64_t sim_rng_next(sim_rng_t *rng); /* splitmix64 */

typedef struct {
    sim_rng_t rng;
    int crashes_allowed;               /* 0: a tick that would cut the power injects a fault instead */
    uint64_t fired[SIM_FAULT_COUNT];   /* faults the world accepted, per kind */
    uint64_t crashes;                  /* power cuts the world accepted */
} sim_workload_t;

void sim_workload_init(sim_workload_t *wl, uint64_t seed, int crashes_allowed);
/* One tick of input: maybe an intent, maybe a fault, maybe a power cut. Returns a WORLD_* code. */
int sim_workload_tick(world_t *w, sim_workload_t *wl);

#endif
