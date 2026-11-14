#include "selftest/scratch_sim/toy/toy.h"
#include "sim/world.h"

#define TICK_MS 50U
#define OPEN_MS 500U
#define SHOW_MS 8000U

enum { PH_IDLE = 0, PH_OPENING, PH_OPENED };

struct pool {
    uint32_t uses[TOY_POOL_SLOTS];
    uint8_t retired[TOY_POOL_SLOTS];
};

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
    uint32_t silenced;           /* the silent relay has been seen delaying an opening */
    struct pool pool;            /* volatile: a power cut builds it again */
    uint64_t next_sync;
    uint64_t uploads;            /* what the simulated server has received (durable on the server) */
    uint64_t snap_taken_ms;      /* the server's newest snapshot */
    uint32_t book_rev;           /* the book changes with every opening */
    uint32_t snap_rev;           /* the book revision of the newest snapshot */
    uint32_t no_free_blob;       /* uploads that went out without a snapshot (the silent degrade) */
    uint32_t screens;
    uint64_t observed[SIM_FAULT_COUNT];
};

static struct world g_world;

static void emit(const struct world *w, char a, char b, uint32_t x, uint32_t y, const uint8_t *bytes, uint32_t len) {
    if (w->tap != NULL) {
        sim_rec_t rec = {{a, b}, w->hooks->clock(w->now), x, y, bytes, len};
        w->tap(w->tap_ctx, &rec);
    }
}

static void show(struct world *w, sim_screen_t screen) {
    w->screens |= 1U << (unsigned)screen;
}

/* The pool of snapshot blobs: take a usable slot (the one with fewest uses), give it back; a slot given back for the
 * `pool_retire_after`-th time is retired for good (lib/ds/pool "Generations"). Returns -1 when no slot is usable. */
static int pool_take(const struct world *w) {
    int best = -1;
    for (unsigned i = 0; i < TOY_POOL_SLOTS; i++) {
        if (!w->pool.retired[i] && (best < 0 || w->pool.uses[i] < w->pool.uses[best])) {
            best = (int)i;
        }
    }
    return best;
}

static void pool_give(struct world *w, int slot) {
    w->pool.uses[slot]++;
    if (w->hooks->pool_retire_after != 0 && w->pool.uses[slot] >= w->hooks->pool_retire_after) {
        w->pool.retired[slot] = 1;
    }
}

static void upload(struct world *w) {
    int slot = pool_take(w);
    w->uploads++;
    if (slot < 0) {
        w->no_free_blob++; /* the events go up without a snapshot and nothing says so */
        return;
    }
    w->snap_taken_ms = w->now;
    w->snap_rev = w->book_rev;
    pool_give(w, slot);
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
    w->book_rev++;
    show(w, SIM_SCREEN_OPENED);
    if (w->disk_full == 0) {
        w->durable_opens = w->opens;
    } else {
        w->save_failed++;
        w->observed[SIM_FAULT_DISK_FULL]++;
    }
    emit(w, 'v', 'w', PH_OPENED, w->opens, NULL, 0);
}

static void tick(struct world *w) {
    while (w->now >= w->next_sync) {
        upload(w);
        w->next_sync += TOY_SYNC_INTERVAL_MS;
    }
    if (w->phase == PH_OPENING && w->now < w->silent_until && w->now - w->phase_since >= OPEN_MS && w->silenced == 0) {
        w->silenced = 1; /* the relay should have answered by now: the fault delays this opening */
        w->observed[SIM_FAULT_RELAY_SILENT]++;
    }
    if (w->phase == PH_OPENING && w->now >= w->silent_until && w->now - w->phase_since >= OPEN_MS) {
        w->silenced = 0;
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
    fresh.next_sync = TOY_SYNC_INTERVAL_MS;
    show(&fresh, SIM_SCREEN_WELCOME);
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
        show(w, SIM_SCREEN_CHOOSE);
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
        w->observed[SIM_FAULT_CLOCK_JUMP] += fault.arg != 0 ? 1U : 0U;
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
    w->silenced = 0;
    w->opens = w->durable_opens;
    w->book_rev = w->opens;
    w->pool = (struct pool){{0}, {0}};
    w->next_sync = w->now + TOY_SYNC_INTERVAL_MS;
    return WORLD_OK;
}

static void name_counter(sim_counter_t *c, const char *name, uint64_t value, uint8_t impossible) {
    unsigned n = 0;
    for (; name[n] != '\0' && n + 1U < SIM_NAME_MAX; n++) {
        c->name[n] = name[n];
    }
    c->value = value;
    c->impossible = impossible;
}

int world_stats(const world_t *w, sim_stats_t *out) {
    out->steps = w->steps; /* `out` arrives zeroed (sim/world.h) */
    name_counter(&out->counters[0], "save_failed", w->save_failed, 0);
    name_counter(&out->counters[1], "no_free_blob", w->no_free_blob, 1);
    const char *pool = "snapshot_pool";
    for (unsigned n = 0; pool[n] != '\0'; n++) {
        out->gauges[0].name[n] = pool[n];
    }
    out->gauges[0].cap = TOY_POOL_SLOTS;
    for (unsigned i = 0; i < TOY_POOL_SLOTS; i++) {
        out->gauges[0].free_idle += w->pool.retired[i] ? 0U : 1U;
    }
    out->uploads = w->uploads;
    out->snap_taken_ms = w->snap_taken_ms;
    out->link_ok_ms = w->now; /* the toy link never drops */
    out->sync_interval_ms = TOY_SYNC_INTERVAL_MS;
    out->snap_pending = w->book_rev != w->snap_rev;
    out->screens = w->screens;
    for (unsigned k = 0; k < (unsigned)SIM_FAULT_COUNT; k++) {
        out->fault_observed[k] = w->observed[k];
    }
    return WORLD_OK;
}

uint64_t world_state_hash(const world_t *w) {
    const uint64_t parts[] = {w->phase, w->digits, w->code, w->now, w->opens, w->durable_opens, w->wall_offset, w->save_failed,
                              w->uploads, w->snap_taken_ms, w->no_free_blob, w->pool.uses[0], w->pool.uses[1], w->book_rev};
    uint64_t h = 14695981039346656037ULL;
    for (unsigned i = 0; i < sizeof parts / sizeof parts[0]; i++) {
        h = (h ^ parts[i]) * 1099511628211ULL;
    }
    return h;
}
