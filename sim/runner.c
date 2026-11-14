#include <stdio.h>
#include <string.h>

#include "sim/runner.h"
#include "sim/sha256.h"

typedef struct {
    uint64_t seed;
    uint64_t index;
    sim_seed_out_t out;
} seed_row_t;

static seed_row_t g_rows[SIM_MAX_COUNT];
static sim_args_t g_args;

static void hex_of(const uint8_t *bytes, size_t len, char *out) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < len; i++) {
        out[2 * i] = digits[bytes[i] >> 4];
        out[2 * i + 1] = digits[bytes[i] & 0xfU];
    }
    out[2 * len] = '\0';
}

static uint64_t distinct_traces(uint64_t rows) {
    uint64_t distinct = 0;
    for (uint64_t i = 0; i < rows; i++) {
        int seen = 0;
        for (uint64_t j = 0; j < i && !seen; j++) {
            seen = g_rows[j].out.trace_hash == g_rows[i].out.trace_hash;
        }
        distinct += seen ? 0U : 1U;
    }
    return distinct;
}

static int write_hashes(const sim_args_t *a, uint64_t rows) {
    FILE *f = fopen(a->hashes_path, "w");
    if (f == NULL) {
        return -1;
    }
    for (uint64_t i = 0; i < rows; i++) {
        const seed_row_t *r = &g_rows[i];
        if (r->out.rule == SIM_OK) {
            (void)fprintf(f, "%llu %016llx %016llx %016llx\n", (unsigned long long)r->index,
                          (unsigned long long)r->seed, (unsigned long long)r->out.trace_hash,
                          (unsigned long long)r->out.state_hash);
        }
    }
    return fclose(f);
}

static void write_failures(FILE *f, uint64_t rows) {
    const char *sep = "";
    for (uint64_t i = 0; i < rows; i++) {
        const seed_row_t *r = &g_rows[i];
        if (r->out.rule != SIM_OK) {
            (void)fprintf(f, "%s{\"detail\":%d,\"index\":%llu,\"rule\":\"%s\",\"seed\":\"%016llx\"}", sep,
                          r->out.detail, (unsigned long long)r->index, sim_rule_name(r->out.rule),
                          (unsigned long long)r->seed);
            sep = ",";
        }
    }
}

/* The rule of the verdict: the first failure's, or sim-no-seeds, or sim-vacuous (the seeds do not reach the product). */
static const char *verdict_rule(const sim_args_t *a, uint64_t rows, uint64_t distinct) {
    if (a->count == 0) {
        return "sim-no-seeds";
    }
    for (uint64_t i = 0; i < rows; i++) {
        if (g_rows[i].out.rule != SIM_OK) {
            return sim_rule_name(g_rows[i].out.rule);
        }
    }
    return (rows >= 2 && distinct < rows) ? "sim-vacuous" : NULL;
}

static int write_stats(const sim_args_t *a, uint64_t rows, uint64_t distinct) {
    char world[65];
    char salt_sha[65];
    uint8_t digest[32];
    sha256_t s;
    sha256_init(&s);
    sha256_update(&s, a->salt, a->salt_len);
    sha256_final(&s, digest);
    hex_of(digest, 32, salt_sha);
    hex_of(a->world_sha256, 32, world);
    FILE *f = fopen(a->stats_path, "w");
    if (f == NULL) {
        return -1;
    }
    (void)fprintf(f, "{\"count\":%llu,\"distinct_hashes\":%llu,\"failures\":[", (unsigned long long)a->count,
                  (unsigned long long)distinct);
    write_failures(f, rows);
    (void)fprintf(f, "],\"first\":%llu,\"run_ms\":%llu,\"salt_sha256\":\"%s\",\"schema\":\"sim-stats/1\","
                     "\"seeds_run\":%llu,\"world_sha256\":\"%s\"}\n",
                  (unsigned long long)a->first, (unsigned long long)a->params.run_ms, salt_sha,
                  (unsigned long long)rows, world);
    return fclose(f);
}

static int write_verdict(const sim_args_t *a, const char *rule) {
    FILE *f = fopen(a->verdict_path, "w");
    if (f == NULL) {
        return -1;
    }
    if (rule == NULL) {
        (void)fputs("pass\n", f);
    } else {
        (void)fprintf(f, "fail %s\n", rule);
    }
    return fclose(f);
}

static int run_all(const sim_args_t *a, uint64_t *rows) {
    for (uint64_t i = 0; i < a->count; i++) {
        seed_row_t *r = &g_rows[i];
        r->index = a->first + i;
        r->seed = sim_seed_of(a->salt, a->salt_len, a->world_sha256, r->index);
        if (sim_run_seed(&a->params, r->seed, &r->out) != 0) {
            fprintf(stderr, "sim runner: cannot run a seed (fork/pipe failed)\n");
            return -1;
        }
        *rows = i + 1;
        if (r->out.rule != SIM_OK) {
            printf("seed %016llx (index %llu): %s detail=%d first_diff=%lld\n", (unsigned long long)r->seed,
                   (unsigned long long)r->index, sim_rule_name(r->out.rule), r->out.detail,
                   (long long)r->out.first_diff);
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    const sim_args_t *args = &g_args;
    if (sim_parse_args(argc, argv, &g_args) != 0) {
        return 2;
    }
    uint64_t rows = 0;
    if (run_all(args, &rows) != 0) {
        return 2;
    }
    uint64_t distinct = distinct_traces(rows);
    const char *rule = verdict_rule(args, rows, distinct);
    printf("sim: %llu of %llu seeds run, %llu distinct trace hashes: %s\n", (unsigned long long)rows,
           (unsigned long long)args->count, (unsigned long long)distinct, rule == NULL ? "pass" : rule);
    if (write_stats(args, rows, distinct) != 0 || write_hashes(args, rows) != 0 || write_verdict(args, rule) != 0) {
        fprintf(stderr, "sim runner: cannot write the outputs\n");
        return 2;
    }
    return 0;
}
