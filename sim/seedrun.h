/* One seed of a simulated club day, run twice on fresh worlds in a forked child (P330 §1.3). The child dies of any
 * crash, sanitizer report or the real-time alarm; the parent turns every way of not finishing into a rule, never
 * into a skip. */
#ifndef SIM_SEEDRUN_H
#define SIM_SEEDRUN_H

#include <stdint.h>

#include "sim/world.h"

#define SIM_TICK_MS 250U
#define SIM_DRAIN_MS 120000U

typedef struct {
    uint64_t run_ms;        /* virtual length of the workload part of a run */
    uint64_t step_limit;    /* handed to the world through sim_cfg_t */
    unsigned real_limit_s;  /* alarm of the child; 0 is refused by the runner */
} sim_params_t;

typedef enum {
    SIM_OK = 0,
    SIM_CRASH,
    SIM_TIMEOUT,
    SIM_NONDETERMINISTIC,
    SIM_DEADLOCK,
    SIM_INIT_FAILED,
    SIM_WORLD_ERROR,
    SIM_RULE_COUNT
} sim_rule_t;

typedef struct {
    sim_rule_t rule;
    int detail;             /* signal, exit status, or record index of the first difference; -1 when none */
    uint64_t trace_hash;
    uint64_t state_hash;
    uint64_t records;
    int64_t first_diff;     /* record index where the two runs first differ, -1 when they do not */
} sim_seed_out_t;

const char *sim_rule_name(sim_rule_t rule);

/* Runs both passes in a child; always returns with `out` filled (rule SIM_OK only when both passes finished
 * and agree). Returns 0, or -1 when the child could not even be started (the runner then exits 2). */
int sim_run_seed(const sim_params_t *params, uint64_t seed, sim_seed_out_t *out);

#endif
