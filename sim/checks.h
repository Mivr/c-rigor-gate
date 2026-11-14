/* The gate's own checks of what a world reports through `world_stats` (P330 §2.4: I11, I12, I13) and the names of the
 * closed fault and screen sets. Pure: the verdict depends on the stats and the virtual time only. */
#ifndef SIM_CHECKS_H
#define SIM_CHECKS_H

#include <stdint.h>

#include "sim/world.h"

/* Bits of `sim_check_t`. */
enum { SIM_CHECK_I11 = 1U, SIM_CHECK_I12 = 2U, SIM_CHECK_I13 = 4U };
#define SIM_CHECKS 3U

typedef struct {
    unsigned checked;  /* the invariants whose antecedent occurred (a check that could have failed) */
    unsigned violated; /* the invariants that do not hold; always a subset of `checked` */
} sim_check_t;

/* I11: while the link has been healthy for 3 sync intervals and the book is ahead of the server's newest snapshot, that
 * snapshot is at most 2 intervals old. Antecedent: an upload happened and the world has a sync interval.
 * I12: every gauge has `free_idle == cap`. Antecedent: the world reports a gauge.
 * I13: every `impossible` counter is 0. Antecedent: the world reports one. `now_ms` is the virtual time of the read. */
sim_check_t sim_check_stats(const sim_stats_t *stats, uint64_t now_ms);

/* The finding name of one bit (`I11`), and the lowercase names of the fault catalogue and the closed screen set; NULL
 * for an index outside them. */
const char *sim_check_name(unsigned bit_index);
const char *sim_fault_name(unsigned kind);
const char *sim_screen_name(unsigned screen);

#endif
