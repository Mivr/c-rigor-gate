#include "sim/world.h"

struct world {
    sim_cfg_t cfg;
    uint64_t seed;
    uint64_t now;
    uint64_t steps;
    uint64_t sum;
    sim_tap_fn tap;
    void *ctx;
};

static struct world g_world;

static uint64_t stamp(uint64_t virtual_ms) {
    return virtual_ms;
} /* STAMP */

static void each_step(uint64_t seed, uint64_t virtual_ms) {
    (void)seed;
    (void)virtual_ms;
} /* STEP */

static void emit(const struct world *w, uint32_t a, uint32_t b) {
    if (w->tap != NULL) {
        sim_rec_t rec = {{'e', 'v'}, stamp(w->now), a, b, NULL, 0};
        w->tap(w->ctx, &rec);
    }
}

world_t *world_init(const sim_cfg_t *cfg, uint64_t seed, sim_tap_fn fn, void *tap_ctx) {
    struct world fresh = {*cfg, seed, cfg->start_ms, 0, 0, fn, tap_ctx};
    g_world = fresh;
    emit(&g_world, 0, 0);
    return &g_world;
}

int world_run_until(world_t *w, uint64_t t_ms) {
    while (w->now < t_ms) {
        each_step(w->seed, w->now);
        w->steps++;
        if (w->steps > w->cfg.step_limit) {
            return WORLD_STEP_LIMIT;
        }
        w->now += (t_ms - w->now < 50U) ? (t_ms - w->now) : 50U;
    }
    return WORLD_OK;
}

uint64_t world_now_ms(const world_t *w) {
    return w->now;
}

int world_apply(world_t *w, sim_intent_t intent) {
    emit(w, (uint32_t)intent.kind, intent.arg);
    w->sum += intent.arg + 1U;
    return WORLD_OK;
}

int world_fault(world_t *w, sim_fault_t fault) {
    emit(w, 100U + (uint32_t)fault.kind, fault.duration_ms);
    return WORLD_OK;
}

int world_crash_restart(world_t *w) {
    emit(w, 200, 0);
    return WORLD_OK;
}

int world_stats(const world_t *w, sim_stats_t *out) {
    *out = (sim_stats_t){0};
    out->steps = w->steps;
    return WORLD_OK;
}

uint64_t world_state_hash(const world_t *w) {
    return (w->now * 1099511628211ULL) ^ w->sum;
}
