/* One seed of a simulated club day, run twice on fresh worlds in a forked child (P330 §1.3). The child dies of any
 * crash, sanitizer report or the real-time alarm; the parent turns every way of not finishing into a rule, never
 * into a skip. */
#ifndef SIM_SEEDRUN_H
#define SIM_SEEDRUN_H

#include <stdint.h>

#include "sim/checks.h"
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
    SIM_INVARIANT,
    SIM_RULE_COUNT
} sim_rule_t;

/* What the first pass of a seed showed at its end (after the quiet drain): the stats the world reported, the faults the
 * workload injected, and the verdict of the gate's own checks (sim/checks.h) on them. */
typedef struct {
    sim_stats_t stats;
    uint64_t fired[SIM_FAULT_COUNT];
    unsigned checked;
    unsigned violated;
    uint64_t at_ms;
} sim_cover_t;

typedef struct {
    sim_rule_t rule;
    int detail;             /* signal, exit status, record index of the first difference, or the invariant number (11 to 13); -1 when none */
    uint64_t trace_hash;
    uint64_t state_hash;
    uint64_t records;
    int64_t first_diff;     /* record index where the two runs first differ, -1 when they do not */
    sim_cover_t cover;      /* valid when the child finished both passes (rule SIM_OK, SIM_NONDETERMINISTIC or SIM_INVARIANT) */
} sim_seed_out_t;

const char *sim_rule_name(sim_rule_t rule);
/* The rule of a WORLD_* return code (SIM_OK for WORLD_OK). */
sim_rule_t sim_rule_of_rc(int rc);

/* Runs both passes in a child; always returns with `out` filled (rule SIM_OK only when both passes finished
 * and agree). Returns 0, or -1 when the child could not even be started (the runner then exits 2). */
int sim_run_seed(const sim_params_t *params, uint64_t seed, sim_seed_out_t *out);

#endif
