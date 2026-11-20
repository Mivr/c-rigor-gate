/* What a shard's seeds showed, summed (P330 §1.6): the invariants checked, the faults fired and observed, the screens
 * reached and the runtime counters. Written into `stats.json` for the judge, which holds the floors. */
#ifndef SIM_COVER_H
#define SIM_COVER_H

#include <stdint.h>
#include <stdio.h>

#include "sim/seedrun.h"

typedef struct {
    char name[SIM_NAME_MAX];
    uint64_t value;
} sim_cover_counter_t;

typedef struct {
    uint64_t checked[SIM_CHECKS];
    uint64_t violated[SIM_CHECKS];
    uint64_t identity_checked;   /* I14: seeds that ran twice and finished both runs */
    uint64_t identity_violated;  /* I14: seeds whose two runs differ */
    uint64_t fired[SIM_FAULT_COUNT];
    uint64_t observed[SIM_FAULT_COUNT];
    uint32_t screens;
    sim_cover_counter_t counters[SIM_COUNTERS];
} sim_cover_total_t;

void sim_cover_init(sim_cover_total_t *total);
/* Folds one finished seed in; a seed that crashed, timed out or never started adds nothing. */
void sim_cover_add(sim_cover_total_t *total, const sim_seed_out_t *out);

/* Each writes one `"key":value` member of the stats object, no separators. */
void sim_cover_write_counters(FILE *f, const sim_cover_total_t *total);
void sim_cover_write_faults(FILE *f, const sim_cover_total_t *total);
void sim_cover_write_invariants(FILE *f, const sim_cover_total_t *total);
void sim_cover_write_screens(FILE *f, const sim_cover_total_t *total);

#endif
