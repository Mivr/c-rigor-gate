#include "sim/inv/tests/model.h"

#include <string.h>

#include "sim/inv/frame.h"
#include "sim/inv/tests/ev_rig.h"

typedef struct {
    events_t *e;
    uint64_t rng;
    model_bug_t bug;
    uint64_t now;
    int rc;
    uint32_t durable_locker; /* the locker the durable book reserves (0 = none) */
    uint64_t saves;
    uint32_t seq;
    uint32_t audit_len;
    char audit[512];
    uint32_t bug_record;
    int bug_set;
} model_t;

static model_t M;

/* splitmix64: the model's own seeded stream. */
static uint64_t rng_next(model_t *m) {
    uint64_t z = (m->rng += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

static int cb_reserves(void *ctx, const uint8_t *open, uint32_t len) {
    const model_t *m = (const model_t *)ctx;
    uint32_t locker = (uint32_t)open[4] | ((uint32_t)open[5] << 8);
    return len >= 8U && m->durable_locker == locker ? EV_BOOK_RESERVED : EV_BOOK_NOT_RESERVED;
}

static int cb_digest(void *ctx, uint64_t *digest) {
    const model_t *m = (const model_t *)ctx;
    *digest = m->saves * 1000U + m->durable_locker;
    return 0;
}

static int cb_audit(void *ctx, const uint8_t **bytes, uint32_t *len) {
    const model_t *m = (const model_t *)ctx;
    *bytes = (const uint8_t *)m->audit;
    *len = m->audit_len;
    return 0;
}

void model_cfg(events_cfg_t *c) {
    erig_fill(c);
}

static void emit(model_t *m, const char *kind, uint64_t t_ms, uint32_t a, uint32_t b, const uint8_t *bytes, uint32_t len) {
    sim_rec_t rec = {{kind[0], kind[1]}, t_ms, a, b, bytes, len};
    if (events_feed(m->e, &rec) != 0) {
        m->rc = -1;
    }
}

static uint32_t next_index(const model_t *m) {
    return events_counts(m->e)->records;
}

static void mark_bug(model_t *m) {
    if (m->bug_set == 0) {
        m->bug_set = 1;
        m->bug_record = next_index(m);
    }
}

static void put32(uint8_t *p, uint32_t v) {
    for (uint32_t i = 0; i < 4U; i++) {
        p[i] = (uint8_t)(v >> (8U * i));
    }
}

static void emit_open_ev(model_t *m, uint64_t t_ms, uint32_t type, uint32_t corr, uint32_t locker) {
    uint8_t p[8];
    put32(p, corr);
    put32(p + 4, locker);
    emit(m, "ev", t_ms, type, 0, p, sizeof p);
}

static void emit_fx(model_t *m, uint64_t t_ms, uint32_t b, uint32_t corr, uint32_t locker) {
    uint8_t p[8];
    put32(p, corr);
    put32(p + 4, locker);
    emit(m, "fx", t_ms, T_FX_OPEN, b, p, sizeof p);
}

static void emit_flash(model_t *m, uint64_t t_ms, uint32_t ch) {
    uint8_t f[8] = {1, 5, (uint8_t)((0x0200U + ch) >> 8), (uint8_t)(0x0200U + ch), 0, 5, 0, 0};
    uint16_t crc = wire_crc16(f, 6);
    f[6] = (uint8_t)(crc & 0xffU);
    f[7] = (uint8_t)(crc >> 8);
    emit(m, "fr", t_ms, 0, 0, f, sizeof f);
}

static void emit_vw(model_t *m, uint64_t t_ms, uint32_t phase) {
    emit(m, "vw", t_ms, phase, 0, NULL, 0);
}

static void audit_door(model_t *m, uint32_t locker) {
    int n = 0;
    char line[40];
    static const char head[] = "{\"seq\":";
    memcpy(line, head, sizeof head - 1U);
    n = (int)sizeof head - 1;
    uint32_t v = m->seq++;
    char digits[10];
    int d = 0;
    do {
        digits[d++] = (char)('0' + v % 10U);
        v /= 10U;
    } while (v != 0U);
    while (d > 0) {
        line[n++] = digits[--d];
    }
    memcpy(line + n, ",\"e\":\"door\"}\n", 13);
    n += 13;
    (void)locker;
    memcpy(m->audit + m->audit_len, line, (size_t)n);
    m->audit_len += (uint32_t)n;
}

/* The durable save of the reservation, then the effect and the hand-over. */
static void open_door(model_t *m, uint64_t t0, uint32_t k, uint32_t locker) {
    int skip_save = m->bug == MODEL_NO_SAVE_BEFORE_OPEN && k == 1U;
    emit_open_ev(m, t0, T_STAGED, k, locker);
    emit_open_ev(m, t0 + 10U, T_ASSIGNED, 0, locker);
    if (!skip_save) {
        m->durable_locker = locker;
        m->saves++;
        emit(m, "io", t0 + 50U, IO_A(1, 0), 0, (const uint8_t *)"book", 4);
    }
    emit_fx(m, t0 + 100U, 5, k, locker);
    emit_vw(m, t0 + 110U, 2);
    emit_fx(m, t0 + 120U, HANDOVER_B, k, locker);
    if (skip_save) {
        mark_bug(m);
    }
    emit_flash(m, t0 + 130U, locker % 30U);
    emit_flash(m, t0 + 190U, (locker + 1U) % 30U);
    emit_open_ev(m, t0 + 700U, T_RESULT, k, locker);
    emit_open_ev(m, t0 + 710U, T_DOOR, 0, locker);
    audit_door(m, locker);
    emit_vw(m, t0 + 720U, 3);
}

/* The bug of GAP-V2: a stale second opening after the result, paid for by nothing. */
static void stale_open(model_t *m, uint64_t t0, uint32_t k, uint32_t locker) {
    mark_bug(m);
    emit_fx(m, t0 + 800U, 5, 900U + k, locker);
    emit_fx(m, t0 + 810U, HANDOVER_B, 900U + k, locker);
    emit_flash(m, t0 + 820U, locker % 30U);
    emit_flash(m, t0 + 880U, (locker + 1U) % 30U);
    emit_open_ev(m, t0 + 1400U, T_RESULT, 900U + k, locker);
}

static void power_cut(model_t *m, uint64_t t_ms) {
    if (events_power_cut(m->e, t_ms) != 0) {
        m->rc = -1;
    }
    emit(m, "ev", t_ms + 1U, T_BOOT, 0, NULL, 0);
    if (events_restarted(m->e, t_ms + 1U) != 0) {
        m->rc = -1;
    }
}

/* One visit from t0; returns the time it is idle again (or the time it stopped, stuck). */
static uint64_t visit(model_t *m, uint64_t t0, uint32_t k, int *stuck) {
    uint32_t locker = 80U + (uint32_t)(rng_next(m) % 9U);
    emit_vw(m, t0, 1);
    open_door(m, t0 + 3000U, k, locker);
    if (m->bug == MODEL_DOUBLE_PULSE && k == 2U) {
        stale_open(m, t0 + 3000U, k, locker);
    }
    if (m->bug == MODEL_STUCK_PHASE && k == 2U) {
        mark_bug(m);
        emit_vw(m, t0 + 3720U + 8501U, 3); /* the screen is republished, never left */
        *stuck = 1;
        return t0 + 3720U + 8501U;
    }
    emit_vw(m, t0 + 3720U + 5000U, 0);
    return t0 + 3720U + 5000U;
}

int model_run(events_t *e, uint64_t seed, model_bug_t bug, model_out_t *out) {
    events_cfg_t cfg;
    events_world_t world = {&M, cb_reserves, cb_digest, cb_audit};
    uint64_t t = 0;
    int stuck = 0;
    memset(&M, 0, sizeof M);
    M.e = e;
    M.bug = bug;
    M.rng = seed;
    model_cfg(&cfg);
    if (events_init(e, &cfg, &world) != 0) {
        return -1;
    }
    emit(&M, "ev", 1, T_BOOT, 0, NULL, 0);
    uint32_t n = 3U + (uint32_t)(rng_next(&M) % 5U);
    for (uint32_t k = 1; k <= n && !stuck; k++) {
        t += 1000U + rng_next(&M) % 5000U;
        t = visit(&M, t, k, &stuck);
        if (seed % 3U == 0U && k == 2U && !stuck) {
            power_cut(&M, t + 100U);
            t += 200U;
            if (out != NULL) {
                out->cuts++;
            }
        }
        if (out != NULL) {
            out->visits = k;
        }
    }
    t += 120000U;
    if (events_finish(e, t) != 0) {
        M.rc = -1;
    }
    if (out != NULL) {
        out->bug_record = M.bug_record;
        out->end_ms = t;
    }
    return M.rc;
}
