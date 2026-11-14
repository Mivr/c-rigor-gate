#include "sim/workload.h"

void sim_rng_seed(sim_rng_t *rng, uint64_t seed) {
    rng->state = seed;
}

uint64_t sim_rng_next(sim_rng_t *rng) {
    rng->state += 0x9e3779b97f4a7c15ULL;
    uint64_t z = rng->state;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

static int apply_intent(world_t *w, uint64_t r) {
    sim_intent_t intent;
    intent.kind = (sim_intent_kind_t)((r >> 8) % (uint64_t)SIM_INTENT_COUNT);
    intent.arg = (uint32_t)((r >> 16) % 10U);
    return world_apply(w, intent);
}

static int apply_fault(world_t *w, uint64_t r) {
    if (((r >> 48) & 3U) == 0) {
        return world_crash_restart(w);
    }
    sim_fault_t fault;
    fault.kind = (sim_fault_kind_t)((r >> 40) % (uint64_t)SIM_FAULT_COUNT);
    fault.arg = (uint32_t)((r >> 52) & 0xffU);
    fault.duration_ms = (uint32_t)(((r >> 24) % 20U) * 250U);
    return world_fault(w, fault);
}

int sim_workload_tick(world_t *w, sim_rng_t *rng) {
    uint64_t r = sim_rng_next(rng);
    int rc = WORLD_OK;
    if (r % 8U == 0) {
        rc = apply_intent(w, r);
    }
    if (rc == WORLD_OK && ((r >> 32) & 0xffU) == 0) {
        rc = apply_fault(w, r);
    }
    return rc;
}
