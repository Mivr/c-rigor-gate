/* A fixture product for the event invariants: a model of a locker kiosk that emits the records of one simulated day (`ev`, `fx`,
 * `fr`, `io`, `vw`) from a seed, with a durable book and an audit file behind the callbacks, and three seeded bugs. It is a
 * generator of traces, not a `c_sim` world: the runner does not evaluate invariants until the judge is wired (T2G2, T2G9). It
 * shares nothing with a real product; its type ids are the ones of the lockers-like configuration of the tests. */
#ifndef SIM_INV_TESTS_MODEL_H
#define SIM_INV_TESTS_MODEL_H

#include <stdint.h>

#include "sim/inv/events.h"

typedef enum {
    MODEL_CORRECT = 0,
    MODEL_DOUBLE_PULSE,        /* a stale second cmd_open after the first one's result, with no new authorisation (I1) */
    MODEL_NO_SAVE_BEFORE_OPEN, /* the first visit pulses before its reservation is durable (I2) */
    MODEL_STUCK_PHASE          /* the second visit's opened screen is never left (I15) */
} model_bug_t;

typedef struct {
    uint32_t bug_record; /* the index of the record the bug first shows at (the engine must name exactly this one) */
    uint32_t visits;
    uint32_t cuts;
    uint64_t end_ms;
} model_out_t;

/* The configuration of the model's records (what a product's `sim.toml` would say). */
void model_cfg(events_cfg_t *c);
/* Run one seed through a fresh engine `e`, including `events_init` and `events_finish`. Returns 0 when the engine took every record. */
int model_run(events_t *e, uint64_t seed, model_bug_t bug, model_out_t *out);

#endif
