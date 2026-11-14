/* The soak mode of the runner (P330 §1.7, T2G6): ONE seed, `--soak-days` simulated days, a checkpoint at the end of every
 * day where the gate reads `world_stats` and evaluates I11, I12 and I13 (sim/checks.h). It runs the seeded workload of the
 * seeds without power cuts (a power cut re-initialises every pool, which is the very thing a soak waits for). The run is
 * one sequential action (it cannot be sharded) in a forked child with the real-time limit; whatever happens to it ends
 * in the output file, never in a skip: a crash is the assertion `sim-crash` at day 0.
 *
 * Output (`--soak-out`, canonical JSON, schema `sim-soak/1`): `days` (completed), `failures` (`assertion` I11, I12, I13
 * or the rule of a world that stopped, with the `day` of the first checkpoint at which it failed, or the day it stopped in; day 1 is the end of the
 * first simulated day), `checked` (per invariant, the checkpoints at which its antecedent held, so a soak whose world
 * reports nothing shows it), `uploads`, `seed`, `trace_hash`, `state_hash`, `world_sha256`, `salt_sha256`. */
#ifndef SIM_SOAK_H
#define SIM_SOAK_H

#include <stdint.h>

#include "sim/runner.h"

#define SIM_DAY_MS 86400000ULL
/* The soak's seed is the derivation of index 2^32 (never an index of the seed runs). */
#define SIM_SOAK_INDEX 4294967296ULL

/* Runs the soak and writes the output; the runner's exit status (0 when the file was written, 2 otherwise). */
int sim_soak_main(const sim_args_t *args);

#endif
