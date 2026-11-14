#include "sim/inv/tests/rig.h"

#include "sim/inv/frame.h"

void rig_init(rig_t *r, ctest_t *t) {
    wire_init(&r->w);
    r->t = t;
}

void rig_raw(rig_t *r, uint64_t t_ms, unsigned dir, const uint8_t *bytes, size_t n) {
    sim_rec_t rec = {{'f', 'r'}, t_ms, dir, 0, bytes, (uint32_t)n};
    CHECK_EQ_I64(r->t, wire_feed(&r->w, &rec), 0);
    /* The guard coil after the last one is never written: an out-of-range coil index would show here. */
    const uint8_t *guard = (const uint8_t *)&r->w.coil[WIRE_COILS];
    uint8_t any = 0;
    for (size_t i = 0; i < sizeof r->w.coil[0]; i++) {
        any = (uint8_t)(any | guard[i]);
    }
    CHECK_EQ_U64(r->t, any, 0);
}

void rig_frame(rig_t *r, uint64_t t_ms, unsigned dir, const uint8_t *body, size_t n) {
    uint8_t buf[40];
    for (size_t i = 0; i < n && i < 38U; i++) {
        buf[i] = body[i];
    }
    uint16_t crc = wire_crc16(body, n);
    buf[n] = (uint8_t)(crc & 0xffU);
    buf[n + 1U] = (uint8_t)(crc >> 8);
    rig_raw(r, t_ms, dir, buf, n + 2U);
}

static void rig_exchange(rig_t *r, uint64_t t_req, uint64_t t_resp, uint16_t addr, uint16_t qty, uint32_t bits) {
    uint8_t req[6] = {1, 1, (uint8_t)(addr >> 8), (uint8_t)addr, (uint8_t)(qty >> 8), (uint8_t)qty};
    uint8_t nbytes = (uint8_t)((qty + 7U) / 8U);
    uint8_t resp[8] = {1, 1, nbytes, (uint8_t)bits, (uint8_t)(bits >> 8), (uint8_t)(bits >> 16), (uint8_t)(bits >> 24), 0};
    rig_frame(r, t_req, 0, req, sizeof req);
    rig_frame(r, t_resp, 1, resp, 3U + nbytes);
}

void rig_read_part(rig_t *r, uint64_t t_ms, uint16_t addr, uint16_t qty, uint32_t bits) {
    rig_exchange(r, t_ms, t_ms + RIG_REPLY_MS, addr, qty, bits);
}

void rig_read_late(rig_t *r, uint64_t t_req, uint64_t t_resp, uint32_t bits) {
    rig_exchange(r, t_req, t_resp, 0, 30, bits);
}

void rig_read(rig_t *r, uint64_t t_ms, uint32_t bits) {
    rig_read_part(r, t_ms, 0, 30, bits);
}

void rig_write(rig_t *r, uint64_t t_ms, uint16_t addr, uint16_t value) {
    uint8_t req[6] = {1, 5, (uint8_t)(addr >> 8), (uint8_t)addr, (uint8_t)(value >> 8), (uint8_t)value};
    rig_frame(r, t_ms, 0, req, sizeof req);
}

void rig_flash(rig_t *r, uint64_t t_ms, uint32_t channel, uint16_t units) {
    rig_write(r, t_ms, (uint16_t)(0x0200U + channel), units);
}

void rig_alloff(rig_t *r, uint64_t t_ms) {
    rig_write(r, t_ms, 0x00ff, 0);
}

uint64_t rig_flight(rig_t *r, uint64_t t0, int first, int second, uint16_t units) {
    uint32_t on = 1U << (unsigned)first;
    rig_read(r, t0, 0);
    rig_flash(r, t0 + 10U, (uint32_t)first, units);
    if (second >= 0) {
        rig_flash(r, t0 + 20U, (uint32_t)second, units);
        on |= 1U << (unsigned)second;
    }
    uint64_t off_at = t0 + 10U + (uint64_t)units * 100U - 15U;
    for (uint64_t at = t0 + 50U; at < t0 + 5000U; at += 50U) {
        if (at + RIG_REPLY_MS >= off_at) {
            rig_read(r, at, 0);
            return at + RIG_REPLY_MS;
        }
        rig_read(r, at, on);
    }
    return 0;
}

int rig_inv_of(const rig_t *r, wire_rule_t rule) {
    for (uint32_t i = 0; i < WIRE_MAX_FINDINGS; i++) {
        const wire_finding_t *f = wire_finding(&r->w, i);
        if (f != NULL && f->rule == rule) {
            return (int)f->inv;
        }
    }
    return 0;
}

int rig_rule(const rig_t *r, wire_rule_t rule) {
    return wire_has_rule(&r->w, rule);
}

uint32_t rig_rule_count(const rig_t *r, wire_rule_t rule) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < WIRE_MAX_FINDINGS; i++) {
        const wire_finding_t *f = wire_finding(&r->w, i);
        n += (f != NULL && f->rule == rule) ? 1U : 0U;
    }
    return n;
}
