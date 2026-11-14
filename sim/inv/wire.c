#include "sim/inv/wire.h"

#include "sim/inv/frame.h"

static uint32_t rule_bit(wire_rule_t rule) {
    return 1U << (unsigned)rule;
}

static void flag(wire_t *w, wire_inv_t inv, wire_rule_t rule) {
    w->rules_seen |= rule_bit(rule);
    w->inv_seen |= 1U << (unsigned)inv;
    if (w->nfindings < WIRE_MAX_FINDINGS) {
        w->findings[w->nfindings] = (wire_finding_t){inv, rule, w->now, w->records};
        w->nfindings++;
    } else {
        w->dropped++;
    }
}

/* Rules that can repeat on every record of one flight (a stuck coil read again and again) are raised once per flight. */
static void flag_once(wire_t *w, uint8_t *raised, wire_inv_t inv, wire_rule_t rule) {
    if (*raised == 0U) {
        *raised = 1;
        flag(w, inv, rule);
    }
}

/* Definitely on: the device timer has not reached its earliest off time, or a read showed it on past the latest one. */
static int coil_lit(const wire_coil_t *c, uint64_t now) {
    return c->on != 0U && (c->forced != 0U || now < c->off_lo);
}

/* Possibly on: not yet past the latest off time. */
static int coil_maybe(const wire_coil_t *c, uint64_t now) {
    return c->on != 0U && (c->forced != 0U || now <= c->off_hi);
}

static void check_energised(wire_t *w) {
    uint32_t lit = 0;
    const wire_coil_t *first = NULL;
    int mixed = 0;
    for (const wire_coil_t *c = w->coil; c != w->coil + WIRE_COILS; c++) {
        if (coil_lit(c, w->now)) {
            mixed = mixed || (first != NULL && c->flight != first->flight);
            first = first != NULL ? first : c;
            lit++;
        }
    }
    if (lit > WIRE_MAX_ENERGISED_COILS || mixed) {
        flag_once(w, &w->once_two, WIRE_I3, WIRE_R_TWO_ENERGISED);
    }
}

static void check_burn(wire_t *w) {
    for (wire_coil_t *c = w->coil; c != w->coil + WIRE_COILS; c++) {
        if (c->chain != 0U && c->burned == 0U && coil_maybe(c, w->now) && w->now - c->since >= WIRE_BURN_MS) {
            c->burned = 1;
            flag(w, WIRE_I6, WIRE_R_BURN);
        }
    }
}

/* min(units * 100 + 150, 900): the cap applies from the first whole unit count whose deadline passes it. */
static uint64_t watchdog_ms(uint64_t units) {
    if (units > (WIRE_WATCHDOG_CAP_MS - WIRE_WATCHDOG_MARGIN_MS) / WIRE_PULSE_UNIT_MS) {
        return WIRE_WATCHDOG_CAP_MS;
    }
    return units * WIRE_PULSE_UNIT_MS + WIRE_WATCHDOG_MARGIN_MS;
}

/* A read showed a coil on at or past the pulse's deadline: an all-off was due by the first flash + the cap. */
static void check_watchdog(wire_t *w) {
    if (w->wd_due == 0U) {
        return;
    }
    uint64_t cap_at = w->t_first + WIRE_WATCHDOG_CAP_MS;
    int late = w->alloff_valid != 0U ? w->alloff_t > cap_at : w->now > cap_at;
    if (late) {
        flag_once(w, &w->once_watchdog, WIRE_I6, WIRE_R_WATCHDOG);
    }
}

static void check_verify(wire_t *w) {
    if (w->open != 0U && w->now > w->t_first + WIRE_WATCHDOG_CAP_MS + WIRE_VERIFY_SLACK_MS) {
        flag_once(w, &w->once_verify, WIRE_I5, WIRE_R_VERIFY_LATE);
    }
}

static void advance(wire_t *w) {
    check_burn(w);
    check_watchdog(w);
    check_verify(w);
}

/* A new energising of this coil starts a burn chain unless the model already has it on (a chain survives a re-flash of a coil
 * that is still on, and a coil a read showed stuck on). A coil without a chain is never on, so that is the whole test. */
static void start_chain(wire_coil_t *c, uint64_t now) {
    if (!coil_maybe(c, now)) {
        c->chain = 1;
        c->since = now;
        c->burned = 0;
    }
}

static void mark_on(wire_t *w, wire_coil_t *c) {
    start_chain(c, w->now);
    c->on = 1;
    c->forced = 1;
    c->flight = w->flight_no;
}

/* `forced` means something only while `on` is set, and every place that sets `on` sets it too. */
static void coil_off(wire_coil_t *c) {
    c->on = 0;
}

static void begin_flight(wire_t *w, uint64_t units) {
    if (w->open != 0U) {
        flag(w, WIRE_I5, WIRE_R_BEFORE_VERIFY);
    } else if (w->have_verify != 0U && w->now - w->verify_t < WIRE_GAP_MS) {
        flag(w, WIRE_I5, WIRE_R_GAP);
    }
    if (w->pre_ok == 0U) {
        flag(w, WIRE_I5, WIRE_R_NO_PREREAD);
    }
    w->flight_no++;
    w->once_two = 0;
    w->once_verify = 0;
    w->once_watchdog = 0;
    w->open = 1;
    w->nflash = 0;
    w->pre_ok = 0;
    w->t_first = w->now;
    w->units_first = units;
    w->alloff_valid = 0;
    w->wd_due = 0;
}

static void on_flash(wire_t *w, uint32_t channel, uint16_t units) {
    if (w->open == 0U || w->nflash >= 2U) {
        begin_flight(w, units);
    }
    w->nflash++;
    wire_coil_t *c = &w->coil[channel];
    start_chain(c, w->now);
    c->on = 1;
    c->forced = 0;
    c->flight = w->flight_no;
    c->off_lo = w->now + (uint64_t)units * WIRE_PULSE_UNIT_MS - WIRE_FLASH_EARLY_OFF_MS;
    c->off_hi = w->now + (uint64_t)units * WIRE_PULSE_UNIT_MS;
    check_energised(w);
}

static void all_off(wire_t *w) {
    for (wire_coil_t *c = w->coil; c != w->coil + WIRE_COILS; c++) {
        coil_off(c);
    }
    if (w->alloff_valid == 0U) {
        w->alloff_valid = 1;
        w->alloff_t = w->now;
    }
}

/* The coils an FC05 address names: 0x00FF is all, `n` and 0x0200+n are coil n. Returns 0 when it names none. */
static int coil_range(uint16_t addr, uint32_t *first, uint32_t *count) {
    *first = 0;
    *count = 1;
    if (addr == WIRE_ALL_OFF_ADDR) {
        *count = WIRE_COILS;
        return 1;
    }
    if (addr >= WIRE_FLASH_BASE && addr < WIRE_FLASH_BASE + WIRE_COILS) {
        *first = (uint32_t)addr - WIRE_FLASH_BASE;
        return 1;
    }
    *first = addr;
    return addr < WIRE_COILS;
}

static void on_write_coil(wire_t *w, const wire_req_t *r) {
    uint32_t first;
    uint32_t count;
    int named = coil_range(r->addr, &first, &count);
    if (r->arg == WIRE_ON_VALUE || r->arg == WIRE_TOGGLE_VALUE) {
        flag(w, WIRE_I3, WIRE_R_ON_FRAME);
        for (uint32_t i = 0; named && i < count; i++) {
            mark_on(w, &w->coil[first + i]);
        }
        check_energised(w);
    } else if (r->addr >= WIRE_FLASH_BASE && r->addr < WIRE_FLASH_BASE + WIRE_COILS) {
        if (r->arg < 1U || r->arg > WIRE_PULSE_CAP_UNITS) {
            flag(w, WIRE_I4, WIRE_R_UNITS);
        } else {
            on_flash(w, r->addr - WIRE_FLASH_BASE, r->arg);
        }
    } else if (r->addr == WIRE_ALL_OFF_ADDR && r->arg == 0U) {
        all_off(w);
    } else if (r->arg == 0U && named) {
        coil_off(&w->coil[first]);
    }
}

static void on_write_coils(wire_t *w, const wire_req_t *r) {
    if (r->set_bits > 0U) {
        flag(w, WIRE_I3, WIRE_R_ON_FRAME);
    }
    for (uint32_t k = 0; k < r->arg && r->addr + k < WIRE_COILS; k++) {
        if (((r->bits >> k) & 1U) != 0U) {
            mark_on(w, &w->coil[r->addr + k]);
        } else {
            coil_off(&w->coil[r->addr + k]);
        }
    }
    check_energised(w);
}

/* I6b: the gate's own allow-list (P330 section 2.1), written from the hardware-safety rules. */
static int request_allowed(const wire_req_t *r) {
    if (r->slave != WIRE_SLAVE_ID) {
        return 0;
    }
    switch (r->fn) {
    case WIRE_FN_READ_COILS:
        return r->arg >= 1U && r->addr + r->arg <= WIRE_COILS;
    case WIRE_FN_READ_HOLDING:
        return r->arg == 1U && (r->addr == WIRE_VERSION_REG || r->addr == WIRE_CONFIG_REG);
    case WIRE_FN_WRITE_COIL:
        return (r->addr >= WIRE_FLASH_BASE && r->addr < WIRE_FLASH_BASE + WIRE_COILS && r->arg >= 1U &&
                r->arg <= WIRE_PULSE_CAP_UNITS) ||
               (r->addr == WIRE_ALL_OFF_ADDR && r->arg == 0U);
    default:
        return 0;
    }
}

static void on_request(wire_t *w, const uint8_t *bytes, size_t len) {
    wire_req_t r;
    int decoded = wire_decode_request(bytes, len, &r);
    w->pend_fn = (uint8_t)r.fn;
    w->pend_addr = r.addr;
    w->pend_qty = r.arg;
    if (decoded == 0 || !request_allowed(&r)) {
        flag(w, WIRE_I6B, WIRE_R_UNSAFE_FRAME);
    }
    if (r.fn == WIRE_FN_WRITE_COIL) {
        on_write_coil(w, &r);
    } else if (r.fn == WIRE_FN_WRITE_COILS) {
        on_write_coils(w, &r);
    }
}

/* A read showed this coil on: if the model already expects it on, nothing changes; otherwise it is stuck on or unexplained. */
static void seen_on(wire_t *w, wire_coil_t *c) {
    if (c->on == 0U || w->now > c->off_hi) {
        if (c->chain == 0U) {
            c->flight = 0;
            c->since = w->now;
            c->burned = 0;
            c->chain = 1;
        }
        c->on = 1;
        c->forced = 1;
    }
}

static void read_all_clear(wire_t *w, uint32_t bits, int all30) {
    if (all30 == 0) {
        return;
    }
    if (bits != 0U) {
        w->pre_ok = 0;
    } else if (w->open != 0U) {
        w->open = 0;
        w->have_verify = 1;
        w->verify_t = w->now;
        w->pre_ok = 0;
    } else {
        w->pre_ok = 1;
    }
}

static void apply_read(wire_t *w, uint32_t addr, uint32_t qty, uint32_t bits) {
    for (uint32_t k = 0; k < qty; k++) {
        wire_coil_t *c = &w->coil[addr + k];
        if (((bits >> k) & 1U) == 0U) {
            coil_off(c);
            c->chain = 0;
        } else {
            seen_on(w, c);
        }
    }
    if (bits != 0U && w->open != 0U && w->now >= w->t_first + watchdog_ms(w->units_first)) {
        w->wd_due = 1;
    }
    read_all_clear(w, bits, addr == 0U && qty == WIRE_COILS);
    check_energised(w);
    check_burn(w);
    check_watchdog(w);
}

static void on_response(wire_t *w, const uint8_t *bytes, size_t len) {
    wire_resp_t r;
    uint8_t pending = w->pend_fn;
    w->pend_fn = (uint8_t)WIRE_FN_NONE;
    if (wire_decode_response(bytes, len, &r) == 0 || r.fn != WIRE_FN_READ_COILS || pending != (uint8_t)WIRE_FN_READ_COILS) {
        return;
    }
    uint32_t qty = w->pend_qty;
    if (w->pend_addr + qty <= WIRE_COILS && r.nbytes == (qty + 7U) / 8U) {
        apply_read(w, w->pend_addr, qty, r.coils & ((1U << qty) - 1U));
    }
}

void wire_init(wire_t *w) {
    uint8_t *bytes = (uint8_t *)w;
    for (uint8_t *p = bytes; p != bytes + sizeof *w; p++) {
        *p = 0;
    }
}

int wire_feed(wire_t *w, const sim_rec_t *rec) {
    if (w == NULL || rec == NULL) {
        return -1;
    }
    if (rec->kind[0] != 'f' || rec->kind[1] != 'r') {
        return 1;
    }
    if (rec->a > 1U || (rec->len > 0U && rec->bytes == NULL) || rec->t_ms < w->now) {
        return -1;
    }
    w->now = rec->t_ms;
    advance(w);
    if (rec->a == 0U) {
        on_request(w, rec->bytes, rec->len);
    } else {
        on_response(w, rec->bytes, rec->len);
    }
    w->records++;
    return 0;
}

int wire_finish(wire_t *w, uint64_t t_end_ms) {
    if (w == NULL || t_end_ms < w->now) {
        return -1;
    }
    w->now = t_end_ms;
    advance(w);
    return 0;
}

uint32_t wire_flight_count(const wire_t *w) {
    return w->flight_no;
}

uint32_t wire_record_count(const wire_t *w) {
    return w->records;
}

uint32_t wire_finding_count(const wire_t *w) {
    return w->nfindings + w->dropped;
}

const wire_finding_t *wire_finding(const wire_t *w, uint32_t index) {
    return index < w->nfindings ? &w->findings[index] : NULL;
}

int wire_has_inv(const wire_t *w, wire_inv_t inv) {
    return (w->inv_seen & (1U << (unsigned)inv)) != 0U;
}

int wire_has_rule(const wire_t *w, wire_rule_t rule) {
    return (w->rules_seen & rule_bit(rule)) != 0U;
}

uint32_t wire_inv_mask(const wire_t *w) {
    return w->inv_seen;
}

wire_xc_t wire_crosscheck(const wire_t *w, uint32_t board_violations) {
    uint32_t observable = rule_bit(WIRE_R_ON_FRAME) | rule_bit(WIRE_R_TWO_ENERGISED) | rule_bit(WIRE_R_UNITS) |
                          rule_bit(WIRE_R_BURN);
    int engine = (w->rules_seen & observable) != 0U;
    if (board_violations > 0U && !engine) {
        return WIRE_XC_BOARD_ONLY;
    }
    if (board_violations == 0U && engine) {
        return WIRE_XC_ENGINE_ONLY;
    }
    return WIRE_XC_AGREE;
}
