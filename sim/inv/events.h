/* The event and storage invariants I1, I2, I9, I10 and I15 of P330 section 2.2 (T2G4), over the trace records of
 * sim/trace_fmt.h: `ev` (an event the app took), `fx` (an effect it executed), `fr` (a frame on the wire), `io` (a file
 * operation), `vw` (a view published).
 *
 *   I1  one open per authorisation: every opening effect is paid for by one authorising event (a visitor's `staged`, the shift
 *       reactor's inspection request: the names are the product's, in `sim.toml [inv.I1]`, here `events_cfg_t`); a second effect
 *       without a new authorising event is the double pulse. Also: a unique `corr`, one effect in flight until its result, and on
 *       the wire, no flash-on frame without a hand-over to the driver and no more than `flashes_per_open` of them per hand-over.
 *   I2  durable save before open: at every flash-on frame of an open, the DURABLE image of the book (what a power cut now would
 *       keep) reserves the locker for the visit being opened. The book format is the product's: the world answers through
 *       `book_reserves`, a callback that is itself covered by the product's P1 check against its other implementation.
 *   I9  crash consistency: after a power cut, the book of the durable image equals the book of the last durable save, the audit
 *       file is a prefix-valid chain, and the boot event comes before any opening effect.
 *   I10 audit: the audit file's seq rises by one and stays within its byte bound; a `door_opened` has an earlier `locker_assigned`
 *       and at most one `door_opened` per opening effect of its locker.
 *   I15 liveness: no phase other than idle lasts longer than its limit (screen timer plus slack); after the relay fault clears, the
 *       welcome phase is reached within `recover_ms`; the run ends idle.
 *
 * The engine does not know the product: every record type, payload offset, phase and timer is configuration, and the book and the
 * audit file are read through callbacks the world supplies. It decodes frames with sim/inv/frame.h, shares nothing with the
 * kiosk, and uses static memory (the caller owns an `events_t`; it is big, keep it static). Records must arrive in time order.
 *
 * Step. Every finding carries the virtual time and the index of the record that raised it, counting EVERY record fed to
 * `events_feed` from 0 (the wire engine counts its own `fr` records; the judge reports both by time and index).
 */
#ifndef SIM_INV_EVENTS_H
#define SIM_INV_EVENTS_H

#include <stddef.h>
#include <stdint.h>

#include "sim/trace_fmt.h"

enum {
    EV_MAX_AUTH = 4,
    EV_MAX_PHASES = 8,    /* phase ids are 0 (idle) to 7 */
    EV_MAX_PHASE_ROWS = 8,
    EV_NAME_MAX = 16,     /* file name of the book, with its end */
    EV_PAYLOAD_MAX = 32,  /* the longest opening-effect payload (a longer one is BAD_PAYLOAD); it is kept for the book callback */
    EV_CORRS = 256,       /* corr values remembered for the uniqueness check (the last 256) */
    EV_LOCKERS = 64,      /* lockers tracked by the audit chain rules */
    EV_MAX_FINDINGS = 16
};

/* The `a` field of an `io` record (the gate's layout; the world fills it): bits 0-7 the operation, 8-11 the outcome (0 = ok),
 * 12-19 the errno, bit 20 the "durable" bit (the call ended with the data on the durable image), 24-31 the disk. `bytes` is the file
 * name, `b` the byte count. */
enum {
    EV_IO_KIND_MASK = 0xff,
    EV_IO_OUTCOME_SHIFT = 8,
    EV_IO_OUTCOME_MASK = 0xf,
    EV_IO_DURABLE_SHIFT = 20
};

typedef enum { EV_I1 = 1, EV_I2 = 2, EV_I9 = 9, EV_I10 = 10, EV_I15 = 15 } events_inv_t;

typedef enum {
    EV_R_NO_AUTH = 1,         /* I1: an opening effect with no authorising event left (the double pulse) */
    EV_R_OPEN_OVERLAP,        /* I1: an opening effect while the previous one has no result yet */
    EV_R_CORR_REUSED,         /* I1: a corr seen before (one of the last 256) */
    EV_R_BAD_PAYLOAD,       /* I1: a payload too short for the corr, or an effect payload over 32 bytes */
    EV_R_HANDOVER_NO_EFFECT,  /* I1: a hand-over to the driver with no effect before it */
    EV_R_PULSE_NO_OPEN,       /* I1: a flash-on frame with no hand-over in flight */
    EV_R_EXTRA_PULSE,         /* I1: more flash-on frames than `flashes_per_open` for one hand-over */
    EV_R_NOT_DURABLE,         /* I2: at a flash-on frame the durable book does not reserve the locker */
    EV_R_BOOK_UNDECODABLE,    /* I2: the durable book does not decode */
    EV_R_CRASH_BOOK_CHANGED,  /* I9: the book after the cut is not the last durable save */
    EV_R_CRASH_BOOK_UNREADABLE, /* I9: the book after the cut does not decode */
    EV_R_CRASH_AUDIT_FORMAT,  /* I9: the audit file after the cut is not a prefix-valid chain */
    EV_R_CRASH_AUDIT_GAP,     /* I9: its seq skips */
    EV_R_OPEN_BEFORE_BOOT,    /* I9: an opening effect before the boot event of this boot */
    EV_R_AUDIT_FORMAT,        /* I10: a line that is not a valid audit line, or an unread file */
    EV_R_AUDIT_GAP,           /* I10: seq does not rise by one */
    EV_R_AUDIT_BOUND,         /* I10: the audit file is larger than its bound */
    EV_R_DOOR_NO_ASSIGN,      /* I10: door_opened for a locker never assigned */
    EV_R_DOOR_NO_OPEN,        /* I10: door_opened beyond the opening effects of its locker */
    EV_R_SHORT_LOCKER,        /* I10: a payload too short for the configured locker offset */
    EV_R_TABLE_FULL,          /* I10: more than 64 lockers (fails closed) */
    EV_R_STUCK_PHASE,         /* I15: a phase longer than its limit */
    EV_R_NO_RECOVERY,         /* I15: welcome not reached in time after the relay fault cleared */
    EV_R_NOT_IDLE_AT_END,     /* I15: the run ended outside the idle phase */
    EV_R_COUNT
} events_rule_t;

/* A record selector: kind (two chars) and the record's `a`. */
typedef struct {
    char kind[2];
    uint32_t a;
} events_sel_t;

typedef struct {
    events_sel_t sel;
    uint32_t phase; /* 0 to 7; 0 is idle */
} events_phase_row_t;

/* The product's rules, from `sim.toml`. All of them are plain data: zero means "off" where a `has_` flag exists. */
typedef struct {
    /* I1 */
    uint32_t auth[EV_MAX_AUTH]; /* `ev` types that authorise one opening effect */
    uint32_t n_auth;            /* 1 to 4 */
    uint32_t ev_open_result;    /* `ev` type that ends an opening */
    uint32_t fx_open;           /* `fx` type of the opening effect */
    uint32_t has_handover;      /* 1: an `fx_open` record whose `b` is `handover_b` is the hand-over to the driver, the others are effects */
    uint32_t handover_b;
    uint32_t corr_len;          /* bytes (0 to 8) of the little-endian corr at `corr_off` in the effect payload; 0: no corr checks */
    uint32_t corr_off;
    uint32_t result_corr_off;   /* the same corr in the result's payload; a result with another corr is a stale one and is ignored */
    uint32_t has_corr_shared;   /* 1: this corr (the shift reactor's) is exempt from the uniqueness check */
    uint64_t corr_shared;
    uint32_t flashes_per_open;  /* flash-on frames per hand-over (a row and a column coil: 2); at least 1 */
    /* I2 and I9: the book file */
    char io_book[EV_NAME_MAX]; /* the book's file name in `io` records */
    uint32_t io_done_kind;     /* the `io` operation that ends a call */
    uint32_t has_boot;         /* 1: `ev_boot` marks a completed boot (I9) */
    uint32_t ev_boot;
    uint32_t audit_max_bytes;  /* I10: 0 = unbounded */
    /* I10 */
    uint32_t has_chain;        /* 1: the locker rules run */
    uint32_t ev_assigned, ev_door_opened;
    uint32_t ev_locker_off, ev_locker_len; /* locker id, little endian, in the payload of the two `ev` types (1 to 4 bytes) */
    uint32_t fx_locker_off;                /* and in the payload of the opening effect (same length) */
    /* I15 */
    events_phase_row_t rows[EV_MAX_PHASE_ROWS]; /* a record matching a row sets the phase; the first match wins */
    uint32_t n_rows;
    uint32_t limit_ms[EV_MAX_PHASES]; /* longest stay in the phase; 0: no limit (idle should be 0) */
    uint32_t has_recover;             /* 1: the relay-clear rule */
    events_sel_t relay_clear;
    uint32_t recover_ms;
    uint32_t welcome_phase;
} events_cfg_t;

/* The world's answers about its durable state. Any callback may be NULL: the checks that need it do not run, and the antecedent
 * counters stay at 0, which the judge reports as a vacuous invariant. */
typedef enum { EV_BOOK_NOT_RESERVED = 0, EV_BOOK_RESERVED = 1, EV_BOOK_EXEMPT = 2 } events_book_t;

typedef struct {
    void *ctx;
    /* Does the DURABLE image of the book reserve the locker for the visit that `open` (the payload of the opening effect) names?
     * EV_BOOK_RESERVED, EV_BOOK_NOT_RESERVED, EV_BOOK_EXEMPT (an opening that needs no reservation: an inspection), or < 0: the image does not decode. */
    int (*book_reserves)(void *ctx, const uint8_t *open, uint32_t len);
    /* A digest of the book the durable image decodes to. 0, or < 0 when it does not decode. */
    int (*book_digest)(void *ctx, uint64_t *digest);
    /* The durable audit file. 0 and the bytes, or < 0 when it cannot be read. */
    int (*audit_read)(void *ctx, const uint8_t **bytes, uint32_t *len);
} events_world_t;

typedef struct {
    events_inv_t inv;
    events_rule_t rule;
    uint64_t t_ms;
    uint32_t record;
} events_finding_t;

typedef struct {
    uint32_t opens[EV_LOCKERS], doors[EV_LOCKERS];
} events_lcount_t;

typedef struct {
    uint32_t auth_events, opens, handovers, flashes, i2_checks, durable_saves, power_cuts, audit_lines, doors, phase_changes, records;
} events_counts_t;

typedef struct {
    events_cfg_t cfg;
    events_world_t world;
    uint64_t now;
    uint32_t records;
    uint8_t started;
    /* I1 */
    uint32_t credits, unhanded, flashes;
    uint8_t inflight, window, open_corr_ok;
    uint64_t open_corr;
    uint8_t payload[EV_PAYLOAD_MAX];
    uint32_t payload_len;
    uint64_t corrs[EV_CORRS]; /* newest first */
    uint32_t ncorr;
    /* I9 */
    uint8_t booted, digest_known;
    uint64_t digest;
    /* I10 */
    uint32_t lock_id[EV_LOCKERS];
    uint8_t lock_assigned[EV_LOCKERS];
    events_lcount_t lcount;
    uint32_t nlockers;
    uint8_t table_raised;
    /* I15 */
    uint32_t phase;
    uint64_t phase_since, recover_deadline;
    uint8_t stuck_raised, recovering;
    events_counts_t counts;
    uint32_t rules_seen, inv_seen, nfindings, dropped;
    events_finding_t findings[EV_MAX_FINDINGS];
} events_t;

/* Validate `cfg` and start. Returns 0, or -1 (nothing changed in the meaning of the engine: it refuses every feed) when the
 * configuration is out of range: n_auth not 1..4, an idle limit (`limit_ms[0]`) other than 0, a book name without its end, corr_len over 8, flashes_per_open 0, a locker length not 1..4 when the chain
 * rules are on, a phase row with a phase over 7 or more than 8 rows, a welcome phase over 7. `world` may be NULL (no callbacks). */
int events_init(events_t *e, const events_cfg_t *cfg, const events_world_t *world);

/* Take one record. Returns 0 when it was processed, -1 when it is malformed (NULL, bytes missing, time going backwards) or the
 * engine was not started: nothing changed. */
int events_feed(events_t *e, const sim_rec_t *rec);
/* The power was cut at `t_ms`: drop the volatile state (credits, the opening in flight, the boot flag, the phase). Call it BEFORE
 * world_crash_restart. Returns 0 or -1 (time backwards). */
int events_power_cut(events_t *e, uint64_t t_ms);
/* The world restarted (call it AFTER world_crash_restart returned): the I9 checks of the durable image. Returns 0 or -1. */
int events_restarted(events_t *e, uint64_t t_ms);
/* The run ended at `t_end_ms`, after the drain: raise the timers that passed without a record, require the idle phase and read the
 * audit file once more (no torn tail). Returns 0 or -1. */
int events_finish(events_t *e, uint64_t t_end_ms);

uint32_t events_finding_count(const events_t *e);
const events_finding_t *events_finding(const events_t *e, uint32_t index); /* NULL past the count or past EV_MAX_FINDINGS */
int events_has_rule(const events_t *e, events_rule_t rule);
int events_has_inv(const events_t *e, events_inv_t inv);
uint32_t events_inv_mask(const events_t *e); /* bit `inv` per invariant */
uint32_t events_dropped(const events_t *e);  /* findings past the 16 kept */
events_counts_t events_counts(const events_t *e); /* the antecedents, for the judge's non-vacuity check */

/* Names for the report: "I1" ... and "no-authorisation" ... (a rule's invariant and its kebab-case id). NULL for a value out of range. */
events_inv_t events_rule_inv(events_rule_t rule);
const char *events_inv_name(events_inv_t inv);
const char *events_rule_name(events_rule_t rule);

#endif
