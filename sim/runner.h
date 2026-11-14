/* Command line of the simulation runner (P330 §1.3). Internal to gate//sim:runner. */
#ifndef SIM_RUNNER_H
#define SIM_RUNNER_H

#include <stddef.h>
#include <stdint.h>

#include "sim/seedrun.h"

#define SIM_MAX_COUNT 4096U
#define SIM_MAX_SALT 64U

typedef struct {
    uint64_t first;
    uint64_t count;
    sim_params_t params;
    uint8_t salt[SIM_MAX_SALT];
    size_t salt_len;
    uint8_t world_sha256[32];
    const char *stats_path;
    const char *hashes_path;
    const char *verdict_path;
} sim_args_t;

/* 0 on success, -1 on a usage error (message on stderr). */
int sim_parse_args(int argc, char **argv, sim_args_t *args);

#endif
