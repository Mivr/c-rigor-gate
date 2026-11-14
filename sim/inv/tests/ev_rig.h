/* Test kit of the event-invariant tests: a configuration like the lockers' (type ids of the proposal in the business-apps
 * sim.toml review), a fake world that answers the three callbacks, and helpers that feed hand-built records. */
#ifndef SIM_INV_TESTS_EV_RIG_H
#define SIM_INV_TESTS_EV_RIG_H

#include "ctest/ctest.h"
#include "sim/inv/events.h"

enum {
    T_STAGED = 17,
    T_RESULT = 18,
    T_SHIFT = 19,
    T_BOOT = 14,
    T_ASSIGNED = 52,
    T_DOOR = 53,
    T_RELAY_CLEAR = 70,
    T_FX_OPEN = 26,
    T_DONE = 9, /* the io operation that ends a call */
    HANDOVER_B = 0x7fffffff
};

#define IO_A(durable, outcome) ((uint32_t)T_DONE | ((uint32_t)(outcome) << 8) | ((uint32_t)(durable) << 20))

/* What the fake world answers. */
typedef struct {
    int reserves;      /* book_reserves */
    int digest_rc;     /* book_digest result */
    uint64_t digest;
    int audit_rc;
    const uint8_t *audit;
    uint32_t audit_len;
    uint32_t reserves_calls, digest_calls, audit_calls;
    uint32_t last_open_len;
    uint8_t last_open[EV_PAYLOAD_MAX];
} rig_world_t;

typedef struct {
    ctest_t *t;
    events_t *e;
    rig_world_t *w;
} erig_t;

/* The lockers-like configuration, written into `c` (the struct is big: keep it static). */
void erig_fill(events_cfg_t *c);
/* Start `e` with `cfg` and the callbacks of `w`. `with_world` 0 starts it without callbacks. */
void erig_start(erig_t *r, ctest_t *t, events_t *e, rig_world_t *w, const events_cfg_t *cfg, int with_world);
/* A record of any kind at t_ms; the feed must return 0. */
void erig_rec(erig_t *r, const char *kind, uint64_t t_ms, uint32_t a, uint32_t b, const uint8_t *bytes, uint32_t len);
/* ev with a payload of corr (4 bytes le) and locker (4 bytes le). */
void erig_ev(erig_t *r, uint64_t t_ms, uint32_t type, uint32_t corr, uint32_t locker);
void erig_ev_bare(erig_t *r, uint64_t t_ms, uint32_t type);
/* fx cmd_open effect, hand-over (b = HANDOVER_B), with the same payload layout. */
void erig_effect(erig_t *r, uint64_t t_ms, uint32_t corr, uint32_t locker);
void erig_handover(erig_t *r, uint64_t t_ms, uint32_t corr, uint32_t locker);
/* A request frame FC05 flash-on at channel `ch`, 5 units; and a coil read. */
void erig_flash(erig_t *r, uint64_t t_ms, uint32_t ch);
void erig_read(erig_t *r, uint64_t t_ms);
void erig_io(erig_t *r, uint64_t t_ms, uint32_t a, const char *name);
void erig_vw(erig_t *r, uint64_t t_ms, uint32_t phase);
/* The step the finding `index` is at, and whether it is exactly (inv, rule, record). */
int erig_finding_is(const erig_t *r, uint32_t index, events_inv_t inv, events_rule_t rule, uint32_t record);
/* The standard visit: staged, effect, handover, two flashes, result. Times from t0. Returns nothing; checks nothing. */
void erig_visit(erig_t *r, uint64_t t0, uint32_t corr, uint32_t locker);

#endif
