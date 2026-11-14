#include <string.h>

#include "ctest/ctest.h"
#include "sim/sha256.h"
#include "sim/trace_fmt.h"
#include "sim/workload.h"

/* The workload drives a world only through the interface; this stub records what it was asked. */
struct world {
    unsigned intents;
    unsigned faults;
    unsigned crashes;
    int fail_with;
};

int world_apply(world_t *w, sim_intent_t intent) {
    w->intents++;
    return intent.arg < 10U ? w->fail_with : WORLD_ERROR;
}

int world_fault(world_t *w, sim_fault_t fault) {
    w->faults++;
    return fault.kind < SIM_FAULT_COUNT ? w->fail_with : WORLD_ERROR;
}

int world_crash_restart(world_t *w) {
    w->crashes++;
    return w->fail_with;
}

static void t_sha256_vectors(ctest_t *t) {
    uint8_t out[32];
    sha256_t s;
    sha256_init(&s);
    sha256_update(&s, (const uint8_t *)"abc", 3);
    sha256_final(&s, out);
    static const uint8_t abc[32] = {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40,
                                    0xde, 0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17,
                                    0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
    CHECK_EQ_MEM(t, out, 32, abc, 32);
    sha256_init(&s);
    sha256_final(&s, out);
    CHECK_EQ_U64(t, out[0], 0xe3U);
    CHECK_EQ_U64(t, out[31], 0x55U);
}

static void t_seed_derivation(ctest_t *t) {
    uint8_t zero[32];
    memset(zero, 0, sizeof zero);
    CHECK_EQ_U64(t, sim_seed_of(NULL, 0, zero, 0), 0xe4f07ebe85bb3d31ULL);
    uint8_t world[32];
    for (unsigned i = 0; i < 32; i++) {
        world[i] = (uint8_t)i;
    }
    static const uint8_t salt[2] = {1, 2};
    CHECK_EQ_U64(t, sim_seed_of(salt, 2, world, 7), 0xab809d0094b481acULL);
    CHECK(t, sim_seed_of(salt, 2, world, 8) != sim_seed_of(salt, 2, world, 7));
}

static void t_trace_hash(ctest_t *t) {
    sim_trace_t trace;
    sim_trace_init(&trace);
    CHECK_EQ_U64(t, trace.hash, 0xcbf29ce484222325ULL);
    static const uint8_t ab[2] = {'a', 'b'};
    sim_rec_t rec = {{'e', 'v'}, 5, 1, 2, ab, 2};
    CHECK_EQ_I64(t, sim_trace_add(&trace, &rec), 1);
    CHECK_EQ_U64(t, trace.hash, 0xc2ccd629f9704c25ULL);
    CHECK_EQ_U64(t, trace.records, 1);
    rec.bytes = NULL;
    CHECK_EQ_I64(t, sim_trace_add(&trace, &rec), 0); /* length without bytes: ignored, never read */
    CHECK_EQ_U64(t, trace.records, 1);
}

static void t_rng_is_splitmix64(ctest_t *t) {
    sim_rng_t rng;
    sim_rng_seed(&rng, 0);
    CHECK_EQ_U64(t, sim_rng_next(&rng), 0xe220a8397b1dcdafULL);
    CHECK_EQ_U64(t, sim_rng_next(&rng), 0x6e789e6aa1b965f4ULL);
}

static void t_workload_reaches_every_call(ctest_t *t) {
    world_t w = {0, 0, 0, WORLD_OK};
    sim_rng_t rng;
    sim_rng_seed(&rng, 1);
    for (unsigned i = 0; i < 200000; i++) {
        CHECK_EQ_I64(t, sim_workload_tick(&w, &rng), WORLD_OK);
    }
    CHECK(t, w.intents > 20000 && w.intents < 30000);
    CHECK(t, w.faults > 0 && w.crashes > 0);
}

static void t_workload_passes_a_world_error_on(ctest_t *t) {
    world_t w = {0, 0, 0, WORLD_STEP_LIMIT};
    sim_rng_t rng;
    sim_rng_seed(&rng, 1);
    int rc = WORLD_OK;
    for (unsigned i = 0; i < 1000 && rc == WORLD_OK; i++) {
        rc = sim_workload_tick(&w, &rng);
    }
    CHECK_EQ_I64(t, rc, WORLD_STEP_LIMIT);
}

CTEST_SUITE("sim_unit", {"sha256_vectors", t_sha256_vectors}, {"seed_derivation", t_seed_derivation},
            {"trace_hash", t_trace_hash}, {"rng_is_splitmix64", t_rng_is_splitmix64},
            {"workload_reaches_every_call", t_workload_reaches_every_call},
            {"workload_passes_a_world_error_on", t_workload_passes_a_world_error_on})
