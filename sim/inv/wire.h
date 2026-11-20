/* The wire invariants I3 to I6b of P330 section 2.1, over `fr` records (sim/trace_fmt.h).
 *
 *   I3  one coil pair: at most one energised locker; no ON, all-ON or toggle frame, ever
 *   I4  pulse cap: every flash-on frame carries 1..8 units
 *   I5  read-off, pulse, verify-off, gap: a fresh all-off read before each flight, a verified-off read after it, 300 ms
 *       before the next flight
 *   I6  watchdog: an all-off by first flash + 900 ms when a read showed a coil on past min(pulse + 150, 900) ms; and no
 *       coil on for 1000 ms in the engine's own model
 *   I6b safe frames: every frame the kiosk sends is in the gate's allow-list, with a valid CRC
 *
 * The engine decodes the raw bytes itself (sim/inv/frame.h) and models the coils itself; it calls nothing of the kiosk's
 * frame code and nothing of the board simulator. A record is kind "fr", `a` = 0 for a frame sent to the board (request)
 * or 1 for a frame sent by the board (response), `t_ms` = the virtual time of the frame at the tap, bytes = one whole frame.
 * Records must arrive in non-decreasing time. A response is matched to the request before it.
 *
 * The model: a flash-on of N units turns the coil on at the frame and off between N*100-30 and N*100 ms later (the board's
 * early-off window). A coil read is authoritative about the coils it covers (a read showing off turns the model off, a
 * read showing on after the latest off time is a coil stuck on). An all-off frame turns every coil off in the model but
 * not in the burn chain: only a read that shows the coil off ends it. Flights: the first flash-on starts one, a second
 * flash-on before the verified-off read joins it (row, then column), a third or a later one after verification starts a
 * new one. Constants: sim/inv/wire_consts.h = policy/sim_constants.toml, each with its source line.
 */
#ifndef SIM_INV_WIRE_H
#define SIM_INV_WIRE_H

#include <stddef.h>
#include <stdint.h>

#include "sim/inv/wire_consts.h"
#include "sim/trace_fmt.h"

typedef enum { WIRE_I3 = 1, WIRE_I4, WIRE_I5, WIRE_I6, WIRE_I6B } wire_inv_t;

typedef enum {
    WIRE_R_ON_FRAME = 1,    /* I3: FC05 ON/toggle, all-ON, or FC0F with a set bit */
    WIRE_R_TWO_ENERGISED,   /* I3: more than two coils on, or two coils of different flights */
    WIRE_R_UNITS,           /* I4: flash-on with 0 or more than 8 units */
    WIRE_R_NO_PREREAD,      /* I5: a flight without a fresh all-off read before its flash */
    WIRE_R_BEFORE_VERIFY,   /* I5: a flash-on while the previous flight has no verified-off read */
    WIRE_R_GAP,             /* I5: a flash-on less than 300 ms after the verified-off read */
    WIRE_R_VERIFY_LATE,     /* I5: no verified-off read by first flash + 900 + 150 ms */
    WIRE_R_WATCHDOG,        /* I6: no all-off by first flash + 900 ms after a read showed a coil on past its deadline */
    WIRE_R_BURN,            /* I6: a coil on for 1000 ms or more in the model */
    WIRE_R_UNSAFE_FRAME     /* I6b: a request outside the allow-list, or with a bad CRC */
} wire_rule_t;

typedef struct {
    wire_inv_t inv;
    wire_rule_t rule;
    uint64_t t_ms;
    uint32_t record; /* index of the `fr` record that raised it, from 0 */
} wire_finding_t;

#define WIRE_MAX_FINDINGS 16U

typedef struct {
    uint8_t on, forced, chain, burned;
    uint32_t flight;
    uint64_t since, off_lo, off_hi;
} wire_coil_t;

/* The engine's state. The caller owns the memory; `wire_init` sets every field. */
typedef struct {
    uint64_t now;
    uint32_t records;
    wire_coil_t coil[WIRE_COILS + 1U]; /* the last is a guard: nothing ever writes it, the tests check that */
    uint8_t pend_fn;
    uint16_t pend_addr, pend_qty;
    uint8_t open, nflash, pre_ok, have_verify, wd_due, alloff_valid;
    uint8_t once_two, once_verify, once_watchdog; /* raised already in this flight */
    uint32_t flight_no;
    uint64_t t_first, units_first, alloff_t, verify_t;
    uint32_t rules_seen, inv_seen, nfindings, dropped;
    wire_finding_t findings[WIRE_MAX_FINDINGS];
} wire_t;

void wire_init(wire_t *w);

/* Take one trace record. Returns 0 when it was an `fr` record and was processed, 1 when it is another kind (ignored), -1 when
 * it is malformed (NULL, `a` not 0 or 1, a frame with bytes missing, or time going backwards): nothing changed. */
int wire_feed(wire_t *w, const sim_rec_t *rec);
/* The run ended at `t_end_ms`: raise the deadlines that passed without an event. Returns 0, or -1 if time goes backwards. */
int wire_finish(wire_t *w, uint64_t t_end_ms);

/* How many flights (a first flash-on, or a flash-on after a verified one) and `fr` records were taken: the antecedents of the
 * invariants, for the judge's non-vacuity check. */
uint32_t wire_flight_count(const wire_t *w);
uint32_t wire_record_count(const wire_t *w);

/* Violations raised so far, and what they were. */
uint32_t wire_finding_count(const wire_t *w);
const wire_finding_t *wire_finding(const wire_t *w, uint32_t index); /* NULL past the count or past WIRE_MAX_FINDINGS */
int wire_has_inv(const wire_t *w, wire_inv_t inv);
int wire_has_rule(const wire_t *w, wire_rule_t rule);
/* The invariants as a bit set (bit `inv`), for tests and the judge. */
uint32_t wire_inv_mask(const wire_t *w);

typedef enum {
    WIRE_XC_AGREE = 0,
    WIRE_XC_BOARD_ONLY,  /* the board simulator saw a violation the engine's model did not: sim-model-divergence */
    WIRE_XC_ENGINE_ONLY  /* the engine saw a board-observable violation the board did not: sim-model-divergence */
} wire_xc_t;

/* The board cross-check (P330 section 1.5): `board_violations` is the length of the board simulator's own violation list.
 * Board-observable rules are the ones a coil model can see: ON frame, two energised, units, and burn. The others (read-off,
 * gap, watchdog, allow-list) are the engine's alone. A non-empty board list is a failure of the run whatever this returns. */
wire_xc_t wire_crosscheck(const wire_t *w, uint32_t board_violations);

#endif
