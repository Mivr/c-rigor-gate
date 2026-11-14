#include "selftest/scratch_sim/toy/toy.h"
#include "sim/world.h"

#define TICK_MS 50U
#define OPEN_MS 500U
#define SHOW_MS 8000U

enum { PH_IDLE = 0, PH_OPENING, PH_OPENED };

struct world {
    sim_cfg_t cfg;
    uint64_t seed;
    uint64_t now;
    uint64_t steps;
    sim_tap_fn tap;
    void *tap_ctx;
    const toy_hooks_t *hooks;
    uint32_t phase;
    uint32_t digits;
    uint32_t code;
    uint64_t phase_since;
    uint64_t silent_until;
    uint64_t wall_offset;
    uint32_t opens;
    uint32_t durable_opens;
    uint32_t save_failed;
    uint32_t disk_full;
};

static struct world g_world;

static void emit(const struct world *w, char a, char b, uint32_t x, uint32_t y, const uint8_t *bytes, uint32_t len) {
    if (w->tap != NULL) {
        sim_rec_t rec = {{a, b}, w->hooks->clock(w->now), x, y, bytes, len};
        w->tap(w->tap_ctx, &rec);
    }
}

static void start_open(struct world *w) {
    static const uint8_t frame[8] = {1, 5, 2, 0, 0xff, 0, 0, 0}; /* a flash-on frame of the toy board */
    w->phase = PH_OPENING;
    w->phase_since = w->now;
    emit(w, 'f', 'x', w->code, 0, NULL, 0);
    emit(w, 'f', 'r', 1, 0, frame, sizeof frame);
}

static void finish_open(struct world *w) {
    w->phase = PH_OPENED;
    w->phase_since = w->now;
    w->opens++;
    if (w->disk_full == 0) {
        w->durable_opens = w->opens;
    } else {
        w->save_failed++;
    }
    emit(w, 'v', 'w', PH_OPENED, w->opens, NULL, 0);
}

static void tick(struct world *w) {
    if (w->phase == PH_OPENING && w->now >= w->silent_until && w->now - w->phase_since >= OPEN_MS) {
        finish_open(w);
    } else if (w->phase == PH_OPENED && w->now - w->phase_since >= SHOW_MS) {
        w->phase = PH_IDLE;
        w->digits = 0;
        w->code = 0;
        emit(w, 'v', 'w', PH_IDLE, 0, NULL, 0);
    }
}

world_t *world_init(const sim_cfg_t *cfg, uint64_t seed, sim_tap_fn fn, void *tap_ctx) {
    struct world fresh = {0};
    fresh.cfg = *cfg;
    fresh.seed = seed;
    fresh.now = cfg->start_ms;
    fresh.tap = fn;
    fresh.tap_ctx = tap_ctx;
    fresh.hooks = toy_variant();
    g_world = fresh;
    emit(&g_world, 'e', 'v', 0, 0, NULL, 0);
    return &g_world;
}

int world_run_until(world_t *w, uint64_t t_ms) {
    while (w->now < t_ms) {
        uint64_t burn = 0;
        w->hooks->step(w->seed, w->now, &burn);
        w->steps += 1U + burn;
        if (w->steps > w->cfg.step_limit) {
            return WORLD_STEP_LIMIT;
        }
        uint64_t left = t_ms - w->now;
        w->now += left < TICK_MS ? left : TICK_MS;
        tick(w);
    }
    return WORLD_OK;
}

uint64_t world_now_ms(const world_t *w) {
    return w->now;
}

int world_apply(world_t *w, sim_intent_t intent) {
    emit(w, 'e', 'v', (uint32_t)intent.kind, intent.arg, NULL, 0);
    if (intent.kind == SIM_INTENT_DIGIT && w->phase == PH_IDLE && w->digits < 6) {
        w->code = w->code * 10U + intent.arg % 10U;
        w->digits++;
    } else if (intent.kind == SIM_INTENT_SUBMIT && w->phase == PH_IDLE && w->digits >= 4) {
        start_open(w);
    } else if (intent.kind == SIM_INTENT_CANCEL && w->phase == PH_IDLE) {
        w->digits = 0;
        w->code = 0;
    }
    return WORLD_OK;
}

int world_fault(world_t *w, sim_fault_t fault) {
    emit(w, 'e', 'v', 100U + (uint32_t)fault.kind, fault.duration_ms, NULL, 0);
    if (fault.kind == SIM_FAULT_RELAY_SILENT) {
        w->silent_until = w->now + fault.duration_ms;
    } else if (fault.kind == SIM_FAULT_CLOCK_JUMP) {
        w->wall_offset += fault.arg;
    } else if (fault.kind == SIM_FAULT_DISK_FULL) {
        w->disk_full = fault.arg & 1U;
    }
    return WORLD_OK;
}

int world_crash_restart(world_t *w) {
    emit(w, 'e', 'v', 200, w->durable_opens, NULL, 0);
    w->phase = PH_IDLE; /* volatile state is gone; the durable count and the virtual time stay */
    w->digits = 0;
    w->code = 0;
    w->silent_until = 0;
    w->opens = w->durable_opens;
    return WORLD_OK;
}

int world_stats(const world_t *w, sim_stats_t *out) {
    *out = (sim_stats_t){0};
    out->steps = w->steps;
    out->counters[0] = w->save_failed;
    return WORLD_OK;
}

uint64_t world_state_hash(const world_t *w) {
    const uint64_t parts[] = {w->phase, w->digits, w->code, w->now, w->opens, w->durable_opens, w->wall_offset, w->save_failed};
    uint64_t h = 14695981039346656037ULL;
    for (unsigned i = 0; i < sizeof parts / sizeof parts[0]; i++) {
        h = (h ^ parts[i]) * 1099511628211ULL;
    }
    return h;
}
