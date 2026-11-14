#include "sim/inv/events.h"

#include <string.h>

#include "sim/inv/audit.h"
#include "sim/inv/frame.h"
#include "sim/inv/wire_consts.h"

static void flag(events_t *e, events_rule_t rule) {
    events_inv_t inv = events_rule_inv(rule);
    e->rules_seen |= 1U << (unsigned)rule;
    e->inv_seen |= 1U << (unsigned)inv;
    if (e->nfindings < EV_MAX_FINDINGS) {
        e->findings[e->nfindings] = (events_finding_t){inv, rule, e->now, e->records};
        e->nfindings++;
    } else {
        e->dropped++;
    }
}

/* ---- payload and record helpers ---- */

/* `n` (0 to 8) little-endian bytes at `off`: 1 when they are all there. */
static int le_get(const sim_rec_t *rec, uint32_t off, uint32_t n, uint64_t *out) {
    uint64_t v = 0;
    if (n > rec->len || off > rec->len - n) {
        return 0;
    }
    for (uint32_t i = 0; i < n; i++) {
        v |= (uint64_t)rec->bytes[off + i] << (8U * i);
    }
    *out = v;
    return 1;
}

static int is_kind(const sim_rec_t *rec, char a, char b) {
    return rec->kind[0] == a && rec->kind[1] == b;
}

static int selects(const events_sel_t *s, const sim_rec_t *rec) {
    return rec->kind[0] == s->kind[0] && rec->kind[1] == s->kind[1] && rec->a == s->a;
}

/* ---- I10 locker table ---- */

static events_locker_t *locker_of(events_t *e, uint32_t id) {
    for (uint32_t i = 0; i < e->nlockers; i++) {
        if (e->lockers[i].id == id) {
            return &e->lockers[i];
        }
    }
    if (e->nlockers == EV_LOCKERS) {
        if (e->table_raised == 0U) {
            e->table_raised = 1;
            flag(e, EV_R_TABLE_FULL);
        }
        return NULL;
    }
    e->lockers[e->nlockers] = (events_locker_t){id, 0, 0, 0};
    return &e->lockers[e->nlockers++];
}

/* The locker id of a record at `off`; raises SHORT_LOCKER when the payload is too short. */
static events_locker_t *locker_in(events_t *e, const sim_rec_t *rec, uint32_t off) {
    uint64_t id = 0;
    if (!le_get(rec, off, e->cfg.ev_locker_len, &id)) {
        flag(e, EV_R_SHORT_LOCKER);
        return NULL;
    }
    return locker_of(e, (uint32_t)id);
}

static void on_door(events_t *e, const sim_rec_t *rec) {
    events_locker_t *l = locker_in(e, rec, e->cfg.ev_locker_off);
    e->counts.doors++;
    if (l == NULL) {
        return;
    }
    l->doors++;
    if (l->assigned == 0U) {
        flag(e, EV_R_DOOR_NO_ASSIGN);
    }
    if (l->doors > l->opens) {
        flag(e, EV_R_DOOR_NO_OPEN);
    }
}

static void on_chain_ev(events_t *e, const sim_rec_t *rec) {
    if (rec->a == e->cfg.ev_assigned) {
        events_locker_t *l = locker_in(e, rec, e->cfg.ev_locker_off);
        if (l != NULL) {
            l->assigned = 1;
        }
    }
    if (rec->a == e->cfg.ev_door_opened) {
        on_door(e, rec);
    }
}

/* ---- I1 ---- */

static int corr_seen(const events_t *e, uint64_t corr) {
    uint32_t n = e->ncorr < EV_CORRS ? e->ncorr : EV_CORRS;
    for (uint32_t i = 0; i < n; i++) {
        if (e->corrs[i] == corr) {
            return 1;
        }
    }
    return 0;
}

static void check_corr(events_t *e, const sim_rec_t *rec) {
    uint64_t corr = 0;
    e->open_corr_ok = 0;
    if (e->cfg.corr_len == 0U) {
        return;
    }
    if (!le_get(rec, e->cfg.corr_off, e->cfg.corr_len, &corr)) {
        flag(e, EV_R_SHORT_PAYLOAD);
        return;
    }
    e->open_corr = corr;
    e->open_corr_ok = 1;
    if (e->cfg.has_corr_shared != 0U && corr == e->cfg.corr_shared) {
        return;
    }
    if (corr_seen(e, corr)) {
        flag(e, EV_R_CORR_REUSED);
    }
    e->corrs[e->ncorr % EV_CORRS] = corr;
    e->ncorr++;
}

static void on_open_effect(events_t *e, const sim_rec_t *rec) {
    if (e->cfg.has_boot != 0U && e->booted == 0U) {
        flag(e, EV_R_OPEN_BEFORE_BOOT);
    }
    check_corr(e, rec);
    if (e->inflight != 0U) {
        flag(e, EV_R_OPEN_OVERLAP);
    }
    if (e->credits == 0U) {
        flag(e, EV_R_NO_AUTH);
    } else {
        e->credits--;
    }
    e->payload_len = rec->len < EV_PAYLOAD_MAX ? rec->len : EV_PAYLOAD_MAX;
    if (e->payload_len > 0U) {
        memcpy(e->payload, rec->bytes, e->payload_len);
    }
    e->inflight = 1;
    e->unhanded++;
    e->counts.opens++;
    if (e->cfg.has_handover == 0U) {
        e->window = 1;
        e->flashes = 0;
    }
    if (e->cfg.has_chain != 0U) {
        events_locker_t *l = locker_in(e, rec, e->cfg.fx_locker_off);
        if (l != NULL) {
            l->opens++;
        }
    }
}

static void on_handover(events_t *e) {
    if (e->unhanded == 0U) {
        flag(e, EV_R_HANDOVER_NO_EFFECT);
    } else {
        e->unhanded--;
    }
    e->window = 1;
    e->flashes = 0;
    e->counts.handovers++;
}

static void on_fx(events_t *e, const sim_rec_t *rec) {
    if (rec->a != e->cfg.fx_open) {
        return;
    }
    if (e->cfg.has_handover != 0U && rec->b == e->cfg.handover_b) {
        on_handover(e);
    } else {
        on_open_effect(e, rec);
    }
}

static void on_result(events_t *e, const sim_rec_t *rec) {
    uint64_t corr = 0;
    if (e->inflight == 0U) {
        return; /* a stale result: no opening is waiting for it */
    }
    if (e->cfg.corr_len != 0U) {
        if (!le_get(rec, e->cfg.result_corr_off, e->cfg.corr_len, &corr)) {
            flag(e, EV_R_SHORT_PAYLOAD);
            return;
        }
        if (e->open_corr_ok != 0U && corr != e->open_corr) {
            return; /* the result of an earlier opening */
        }
    }
    e->inflight = 0;
    e->window = 0;
    e->unhanded = 0;
}

static void on_ev(events_t *e, const sim_rec_t *rec) {
    for (uint32_t i = 0; i < e->cfg.n_auth; i++) {
        if (rec->a == e->cfg.auth[i]) {
            e->credits++;
            e->counts.auth_events++;
            break;
        }
    }
    if (rec->a == e->cfg.ev_open_result) {
        on_result(e, rec);
    }
    if (e->cfg.has_boot != 0U && rec->a == e->cfg.ev_boot) {
        e->booted = 1;
    }
    if (e->cfg.has_chain != 0U) {
        on_chain_ev(e, rec);
    }
}

/* ---- I2 on the wire ---- */

static int is_flash(const sim_rec_t *rec) {
    wire_req_t req;
    return rec->a == 0U && wire_decode_request(rec->bytes, rec->len, &req) != 0 && req.fn == WIRE_FN_WRITE_COIL &&
           req.addr >= WIRE_FLASH_BASE && req.addr < WIRE_FLASH_BASE + WIRE_COILS;
}

static void check_durable(events_t *e) {
    int r;
    if (e->world.book_reserves == NULL) {
        return;
    }
    r = e->world.book_reserves(e->world.ctx, e->payload, e->payload_len);
    if (r == EV_BOOK_EXEMPT) {
        return;
    }
    e->counts.i2_checks++;
    if (r < 0) {
        flag(e, EV_R_BOOK_UNDECODABLE);
    } else if (r != EV_BOOK_RESERVED) {
        flag(e, EV_R_NOT_DURABLE);
    }
}

static void on_fr(events_t *e, const sim_rec_t *rec) {
    if (!is_flash(rec)) {
        return;
    }
    e->counts.flashes++;
    if (e->window == 0U) {
        flag(e, EV_R_PULSE_NO_OPEN);
        return;
    }
    e->flashes++;
    if (e->flashes > e->cfg.flashes_per_open) {
        flag(e, EV_R_EXTRA_PULSE);
    }
    check_durable(e);
}

/* ---- I9: the book's durable saves ---- */

static int is_book_done(const events_t *e, const sim_rec_t *rec) {
    return e->cfg.io_book[0] != 0 && strlen(e->cfg.io_book) == rec->len &&
           memcmp(rec->bytes, e->cfg.io_book, rec->len) == 0 && EV_IO_KIND(rec->a) == e->cfg.io_done_kind &&
           EV_IO_OUTCOME(rec->a) == 0U && EV_IO_DURABLE(rec->a) != 0U;
}

static void on_io(events_t *e, const sim_rec_t *rec) {
    uint64_t d = 0;
    if (!is_book_done(e, rec)) {
        return;
    }
    e->counts.durable_saves++;
    if (e->world.book_digest == NULL) {
        return;
    }
    if (e->world.book_digest(e->world.ctx, &d) < 0) {
        flag(e, EV_R_BOOK_UNDECODABLE);
        return;
    }
    e->digest = d;
    e->digest_known = 1;
}

/* ---- I15 ---- */

static void check_timers(events_t *e) {
    if (e->stuck_raised == 0U && e->cfg.limit_ms[e->phase] != 0U &&
        e->now - e->phase_since > e->cfg.limit_ms[e->phase]) {
        e->stuck_raised = 1;
        flag(e, EV_R_STUCK_PHASE);
    }
    if (e->recovering != 0U && e->now > e->recover_deadline) {
        e->recovering = 0;
        flag(e, EV_R_NO_RECOVERY);
    }
}

static void set_phase(events_t *e, uint32_t phase) {
    if (phase == e->phase) {
        return;
    }
    e->phase = phase;
    e->phase_since = e->now;
    e->stuck_raised = 0;
    e->counts.phase_changes++;
    if (phase == e->cfg.welcome_phase) {
        e->recovering = 0;
    }
}

static void on_phase(events_t *e, const sim_rec_t *rec) {
    for (uint32_t i = 0; i < e->cfg.n_rows; i++) {
        if (selects(&e->cfg.rows[i].sel, rec)) {
            set_phase(e, e->cfg.rows[i].phase);
            break;
        }
    }
    if (e->cfg.has_recover != 0U && selects(&e->cfg.relay_clear, rec) && e->phase != e->cfg.welcome_phase) {
        e->recovering = 1;
        e->recover_deadline = e->now + e->cfg.recover_ms;
    }
}

/* ---- the audit file ---- */

static void check_audit(events_t *e, int torn_ok, events_rule_t r_format, events_rule_t r_gap) {
    const uint8_t *bytes = NULL;
    uint32_t len = 0;
    audit_scan_t scan;
    audit_result_t r;
    if (e->world.audit_read == NULL) {
        return;
    }
    if (e->world.audit_read(e->world.ctx, &bytes, &len) < 0) {
        flag(e, r_format);
        return;
    }
    r = audit_scan(bytes, len, torn_ok, &scan);
    e->counts.audit_lines = scan.lines;
    if (r == AUDIT_FORMAT) {
        flag(e, r_format);
    } else if (r == AUDIT_GAP) {
        flag(e, r_gap);
    }
    if (e->cfg.audit_max_bytes != 0U && len > e->cfg.audit_max_bytes) {
        flag(e, EV_R_AUDIT_BOUND);
    }
}

static void check_crash_book(events_t *e) {
    uint64_t d = 0;
    if (e->world.book_digest == NULL) {
        return;
    }
    if (e->world.book_digest(e->world.ctx, &d) < 0) {
        flag(e, EV_R_CRASH_BOOK_UNREADABLE);
    } else if (e->digest_known != 0U && d != e->digest) {
        flag(e, EV_R_CRASH_BOOK_CHANGED);
    } else {
        e->digest = d;
        e->digest_known = 1;
    }
}

/* ---- the public engine ---- */

static int cfg_ok(const events_cfg_t *c) {
    if (c->n_auth < 1U || c->n_auth > EV_MAX_AUTH || c->corr_len > 8U || c->flashes_per_open < 1U ||
        c->n_rows > EV_MAX_PHASE_ROWS || c->welcome_phase >= EV_MAX_PHASES) {
        return 0;
    }
    if (c->limit_ms[0] != 0U || memchr(c->io_book, 0, EV_NAME_MAX) == NULL) {
        return 0;
    }
    if (c->has_chain != 0U && (c->ev_locker_len < 1U || c->ev_locker_len > 4U)) {
        return 0;
    }
    for (uint32_t i = 0; i < c->n_rows; i++) {
        if (c->rows[i].phase >= EV_MAX_PHASES) {
            return 0;
        }
    }
    return 1;
}

int events_init(events_t *e, const events_cfg_t *cfg, const events_world_t *world) {
    if (e == NULL || cfg == NULL || !cfg_ok(cfg)) {
        return -1;
    }
    memset(e, 0, sizeof *e);
    e->cfg = *cfg;
    if (world != NULL) {
        e->world = *world;
    }
    e->started = 1;
    return 0;
}

static int advance(events_t *e, uint64_t t_ms) {
    if (e == NULL || e->started == 0U || t_ms < e->now) {
        return -1;
    }
    e->now = t_ms;
    check_timers(e);
    return 0;
}

int events_feed(events_t *e, const sim_rec_t *rec) {
    if (rec == NULL || (rec->len > 0U && rec->bytes == NULL) || advance(e, rec->t_ms) != 0) {
        return -1;
    }
    if (is_kind(rec, 'e', 'v')) {
        on_ev(e, rec);
    } else if (is_kind(rec, 'f', 'x')) {
        on_fx(e, rec);
    } else if (is_kind(rec, 'f', 'r')) {
        on_fr(e, rec);
    } else if (is_kind(rec, 'i', 'o')) {
        on_io(e, rec);
    }
    on_phase(e, rec);
    e->records++;
    e->counts.records++;
    return 0;
}

int events_power_cut(events_t *e, uint64_t t_ms) {
    if (advance(e, t_ms) != 0) {
        return -1;
    }
    e->credits = 0;
    e->unhanded = 0;
    e->inflight = 0;
    e->window = 0;
    e->booted = 0;
    e->phase = 0;
    e->stuck_raised = 0;
    e->recovering = 0;
    for (uint32_t i = 0; i < e->nlockers; i++) {
        e->lockers[i].opens = 0;
        e->lockers[i].doors = 0;
    }
    e->counts.power_cuts++;
    return 0;
}

int events_restarted(events_t *e, uint64_t t_ms) {
    if (advance(e, t_ms) != 0) {
        return -1;
    }
    check_crash_book(e);
    check_audit(e, 1, EV_R_CRASH_AUDIT_FORMAT, EV_R_CRASH_AUDIT_GAP);
    return 0;
}

int events_finish(events_t *e, uint64_t t_end_ms) {
    if (advance(e, t_end_ms) != 0) {
        return -1;
    }
    if (e->phase != 0U) {
        flag(e, EV_R_NOT_IDLE_AT_END);
    }
    check_audit(e, 0, EV_R_AUDIT_FORMAT, EV_R_AUDIT_GAP);
    return 0;
}

uint32_t events_finding_count(const events_t *e) {
    return e->nfindings + e->dropped;
}

const events_finding_t *events_finding(const events_t *e, uint32_t index) {
    return index < e->nfindings ? &e->findings[index] : NULL;
}

int events_has_rule(const events_t *e, events_rule_t rule) {
    return (unsigned)rule < 32U && (e->rules_seen & (1U << (unsigned)rule)) != 0U;
}

int events_has_inv(const events_t *e, events_inv_t inv) {
    return (unsigned)inv < 32U && (e->inv_seen & (1U << (unsigned)inv)) != 0U;
}

uint32_t events_inv_mask(const events_t *e) {
    return e->inv_seen;
}

uint32_t events_dropped(const events_t *e) {
    return e->dropped;
}

const events_counts_t *events_counts(const events_t *e) {
    return &e->counts;
}
