#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sim/runner.h"

static int hex_value(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    return -1;
}

/* Lowercase hex of exactly `want` bytes (want 0: any even length up to `cap`); returns the byte count or -1. */
static long parse_hex(const char *text, uint8_t *out, size_t cap, size_t want) {
    size_t len = strlen(text);
    if (len % 2 != 0 || len / 2 > cap || (want != 0 && len / 2 != want)) {
        return -1;
    }
    for (size_t i = 0; i < len / 2; i++) {
        int hi = hex_value(text[2 * i]);
        int lo = hex_value(text[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            return -1;
        }
        out[i] = (uint8_t)(hi * 16 + lo);
    }
    return (long)(len / 2);
}

static int parse_u64(const char *text, uint64_t *out) {
    char *end = NULL;
    errno = 0;
    unsigned long long v = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || text[0] == '-') {
        return -1;
    }
    *out = v;
    return 0;
}

static int set_option(sim_args_t *a, const char *name, const char *value, int *seen_world) {
    uint64_t n = 0;
    if (strcmp(name, "--stats") == 0) {
        a->stats_path = value;
    } else if (strcmp(name, "--hashes") == 0) {
        a->hashes_path = value;
    } else if (strcmp(name, "--verdict") == 0) {
        a->verdict_path = value;
    } else if (strcmp(name, "--salt") == 0) {
        long len = parse_hex(value, a->salt, SIM_MAX_SALT, 0);
        if (len < 0) {
            return -1;
        }
        a->salt_len = (size_t)len;
    } else if (strcmp(name, "--world-sha256") == 0) {
        *seen_world = parse_hex(value, a->world_sha256, 32, 32) == 32;
        return *seen_world ? 0 : -1;
    } else if (parse_u64(value, &n) != 0) {
        return -1;
    } else if (strcmp(name, "--first") == 0) {
        a->first = n;
    } else if (strcmp(name, "--count") == 0) {
        a->count = n;
    } else if (strcmp(name, "--run-ms") == 0) {
        a->params.run_ms = n;
    } else if (strcmp(name, "--step-limit") == 0) {
        a->params.step_limit = n;
    } else if (strcmp(name, "--real-limit-s") == 0) {
        a->params.real_limit_s = (unsigned)(n > 3600U ? 0U : n);
    } else {
        return -1;
    }
    return 0;
}

int sim_parse_args(int argc, char **argv, sim_args_t *args) {
    memset(args, 0, sizeof *args);
    int seen_world = 0;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (set_option(args, argv[i], argv[i + 1], &seen_world) != 0) {
            fprintf(stderr, "sim runner: bad option %s\n", argv[i]);
            return -1;
        }
    }
    int ok = argc % 2 == 1 && seen_world && args->stats_path != NULL && args->hashes_path != NULL &&
             args->verdict_path != NULL && args->count <= SIM_MAX_COUNT && args->params.run_ms >= SIM_TICK_MS &&
             args->params.step_limit > 0 && args->params.real_limit_s > 0;
    if (!ok) {
        fprintf(stderr, "usage: runner --world-sha256 HEX64 [--salt HEX] --first N --count N --run-ms N --step-limit N "
                        "--real-limit-s N --stats F --hashes F --verdict F\n");
        return -1;
    }
    return 0;
}
