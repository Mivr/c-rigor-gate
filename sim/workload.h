/* The gate-owned workload and fault schedule (P330 §1.3): a seeded stream of intents and faults, one decision per
 * tick. This skeleton (T2G1) has a small closed mix; the product cannot change it. */
#ifndef SIM_WORKLOAD_H
#define SIM_WORKLOAD_H

#include <stdint.h>

#include "sim/world.h"

typedef struct {
    uint64_t state;
} sim_rng_t;

void sim_rng_seed(sim_rng_t *rng, uint64_t seed);
uint64_t sim_rng_next(sim_rng_t *rng); /* splitmix64 */

/* One tick of input: maybe an intent, maybe a fault, maybe a power cut. Returns a WORLD_* code. */
int sim_workload_tick(world_t *w, sim_rng_t *rng);

#endif
