#include "sim/inv/tests/ev_rig.h"

#include <string.h>

#include "sim/inv/frame.h"

static int cb_reserves(void *ctx, const uint8_t *open, uint32_t len) {
    rig_world_t *w = (rig_world_t *)ctx;
    w->reserves_calls++;
    w->last_open_len = len;
    memset(w->last_open, 0, sizeof w->last_open);
    if (len > 0U && len <= sizeof w->last_open) {
        memcpy(w->last_open, open, len);
    }
    return w->reserves;
}

static int cb_digest(void *ctx, uint64_t *digest) {
    rig_world_t *w = (rig_world_t *)ctx;
    w->digest_calls++;
    *digest = w->digest;
    return w->digest_rc;
}

static int cb_audit(void *ctx, const uint8_t **bytes, uint32_t *len) {
    rig_world_t *w = (rig_world_t *)ctx;
    w->audit_calls++;
    *bytes = w->audit;
    *len = w->audit_len;
    return w->audit_rc;
}

void erig_fill(events_cfg_t *cp) {
    events_cfg_t *c = cp;
    memset(c, 0, sizeof *c);
    c->auth[0] = T_STAGED;
    c->auth[1] = T_SHIFT;
    c->n_auth = 2;
    c->ev_open_result = T_RESULT;
    c->fx_open = T_FX_OPEN;
    c->has_handover = 1;
    c->handover_b = HANDOVER_B;
    c->corr_len = 4;
    c->corr_off = 0;
    c->result_corr_off = 0;
    c->has_corr_shared = 1;
    c->corr_shared = 0xfffe;
    c->flashes_per_open = 2;
    memcpy(c->io_book, "book", 5);
    c->io_done_kind = T_DONE;
    c->has_boot = 1;
    c->ev_boot = T_BOOT;
    c->audit_max_bytes = 4096;
    c->has_chain = 1;
    c->ev_assigned = T_ASSIGNED;
    c->ev_door_opened = T_DOOR;
    c->ev_locker_off = 4;
    c->ev_locker_len = 4;
    c->fx_locker_off = 4;
    c->n_rows = 4;
    for (uint32_t i = 0; i < 4U; i++) { /* a view of phase i is `vw` with a = i */
        c->rows[i].sel = (events_sel_t){{'v', 'w'}, i};
        c->rows[i].phase = (uint8_t)i;
    }
    c->limit_ms[1] = 30500;
    c->limit_ms[2] = 3000;
    c->limit_ms[3] = 8500;
    c->has_recover = 1;
    c->relay_clear = (events_sel_t){{'e', 'v'}, T_RELAY_CLEAR};
    c->recover_ms = 7000;
    c->welcome_phase = 0;
}

void erig_start(erig_t *r, ctest_t *t, events_t *e, rig_world_t *w, const events_cfg_t *cfg, int with_world) {
    events_world_t world = {w, cb_reserves, cb_digest, cb_audit};
    memset(w, 0, sizeof *w);
    w->reserves = EV_BOOK_RESERVED;
    r->t = t;
    r->e = e;
    r->w = w;
    CHECK_EQ_I64(t, events_init(e, cfg, with_world != 0 ? &world : NULL), 0);
}

void erig_rec(erig_t *r, const char *kind, uint64_t t_ms, uint32_t a, uint32_t b, const uint8_t *bytes, uint32_t len) {
    sim_rec_t rec = {{kind[0], kind[1]}, t_ms, a, b, bytes, len};
    CHECK_EQ_I64(r->t, events_feed(r->e, &rec), 0);
}

static void put32(uint8_t *p, uint32_t v) {
    for (uint32_t i = 0; i < 4U; i++) {
        p[i] = (uint8_t)(v >> (8U * i));
    }
}

void erig_ev(erig_t *r, uint64_t t_ms, uint32_t type, uint32_t corr, uint32_t locker) {
    uint8_t p[8];
    put32(p, corr);
    put32(p + 4, locker);
    erig_rec(r, "ev", t_ms, type, 0, p, sizeof p);
}

void erig_ev_bare(erig_t *r, uint64_t t_ms, uint32_t type) {
    erig_rec(r, "ev", t_ms, type, 0, NULL, 0);
}

void erig_effect(erig_t *r, uint64_t t_ms, uint32_t corr, uint32_t locker) {
    uint8_t p[8];
    put32(p, corr);
    put32(p + 4, locker);
    erig_rec(r, "fx", t_ms, T_FX_OPEN, 5, p, sizeof p);
}

void erig_handover(erig_t *r, uint64_t t_ms, uint32_t corr, uint32_t locker) {
    uint8_t p[8];
    put32(p, corr);
    put32(p + 4, locker);
    erig_rec(r, "fx", t_ms, T_FX_OPEN, HANDOVER_B, p, sizeof p);
}

void erig_flash(erig_t *r, uint64_t t_ms, uint32_t ch) {
    uint8_t f[8] = {1, 5, (uint8_t)((0x0200U + ch) >> 8), (uint8_t)(0x0200U + ch), 0, 5, 0, 0};
    uint16_t crc = wire_crc16(f, 6);
    f[6] = (uint8_t)(crc & 0xffU);
    f[7] = (uint8_t)(crc >> 8);
    erig_rec(r, "fr", t_ms, 0, 0, f, sizeof f);
}

void erig_read(erig_t *r, uint64_t t_ms) {
    uint8_t f[8] = {1, 1, 0, 0, 0, 30, 0, 0};
    uint16_t crc = wire_crc16(f, 6);
    f[6] = (uint8_t)(crc & 0xffU);
    f[7] = (uint8_t)(crc >> 8);
    erig_rec(r, "fr", t_ms, 0, 0, f, sizeof f);
}

void erig_io(erig_t *r, uint64_t t_ms, uint32_t a, const char *name) {
    erig_rec(r, "io", t_ms, a, 0, (const uint8_t *)name, (uint32_t)strlen(name));
}

void erig_vw(erig_t *r, uint64_t t_ms, uint32_t phase) {
    erig_rec(r, "vw", t_ms, phase, 0, NULL, 0);
}

int erig_finding_is(const erig_t *r, uint32_t index, events_inv_t inv, events_rule_t rule, uint32_t record) {
    const events_finding_t *f = events_finding(r->e, index);
    return f != NULL && f->inv == inv && f->rule == rule && f->record == record;
}

void erig_visit(erig_t *r, uint64_t t0, uint32_t corr, uint32_t locker) {
    erig_ev(r, t0, T_STAGED, corr, locker);
    erig_effect(r, t0 + 10U, corr, locker);
    erig_handover(r, t0 + 20U, corr, locker);
    erig_flash(r, t0 + 30U, locker % 30U);
    erig_flash(r, t0 + 60U, locker % 30U);
    erig_ev(r, t0 + 600U, T_RESULT, corr, locker);
}
