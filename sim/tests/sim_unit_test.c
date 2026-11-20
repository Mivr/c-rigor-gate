#include <string.h>

#include "ctest/ctest.h"
#include "sim/checks.h"
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
    sim_workload_t wl;
    sim_workload_init(&wl, 1, 1);
    for (unsigned i = 0; i < 200000; i++) {
        CHECK_EQ_I64(t, sim_workload_tick(&w, &wl), WORLD_OK);
    }
    CHECK(t, w.intents > 20000 && w.intents < 30000);
    CHECK(t, w.faults > 0 && w.crashes > 0);
    CHECK_EQ_U64(t, wl.crashes, w.crashes);
    CHECK_EQ_U64(t, wl.fired[0] + wl.fired[1] + wl.fired[2], w.faults);
    CHECK(t, wl.fired[0] > 0 && wl.fired[1] > 0 && wl.fired[2] > 0);
}

static void t_workload_without_power_cuts_injects_a_fault_instead(ctest_t *t) {
    world_t cuts = {0, 0, 0, WORLD_OK};
    world_t none = {0, 0, 0, WORLD_OK};
    sim_workload_t with, without;
    sim_workload_init(&with, 1, 1);
    sim_workload_init(&without, 1, 0);
    for (unsigned i = 0; i < 200000; i++) {
        CHECK_EQ_I64(t, sim_workload_tick(&cuts, &with), WORLD_OK);
        CHECK_EQ_I64(t, sim_workload_tick(&none, &without), WORLD_OK);
    }
    CHECK_EQ_U64(t, none.crashes, 0);
    CHECK_EQ_U64(t, without.crashes, 0);
    CHECK_EQ_U64(t, none.faults, cuts.faults + cuts.crashes); /* the same decisions, the cut is a fault */
    CHECK_EQ_U64(t, none.intents, cuts.intents);
}

static void t_workload_passes_a_world_error_on(ctest_t *t) {
    world_t w = {0, 0, 0, WORLD_STEP_LIMIT};
    sim_workload_t wl;
    sim_workload_init(&wl, 1, 1);
    int rc = WORLD_OK;
    for (unsigned i = 0; i < 1000 && rc == WORLD_OK; i++) {
        rc = sim_workload_tick(&w, &wl);
    }
    CHECK_EQ_I64(t, rc, WORLD_STEP_LIMIT);
    CHECK_EQ_U64(t, wl.fired[0] + wl.fired[1] + wl.fired[2] + wl.crashes, 0); /* a refused call is not counted */
}

/* ---- sim/checks: I11, I12, I13 over what a world reports ---- */

#define HOUR 3600000ULL

static sim_stats_t g_stats; /* static: a sim_stats_t is larger than the frame limit of a test */

static sim_stats_t *blank(void) {
    memset(&g_stats, 0, sizeof g_stats);
    return &g_stats;
}

static sim_stats_t *synced(void) {
    sim_stats_t *s = blank();
    s->uploads = 5;
    s->sync_interval_ms = 12U * HOUR;
    s->snap_pending = 1;
    s->link_ok_ms = 100U * HOUR;
    s->snap_taken_ms = 100U * HOUR;
    return s;
}

static void t_nothing_reported_checks_nothing(ctest_t *t) {
    sim_check_t c = sim_check_stats(blank(), 1000U * HOUR);
    CHECK_EQ_U64(t, c.checked, 0);
    CHECK_EQ_U64(t, c.violated, 0);
}

static void t_i11_boundary_is_two_intervals(ctest_t *t) {
    sim_stats_t *s = synced();
    sim_check_t ok = sim_check_stats(s, s->snap_taken_ms + 24U * HOUR); /* exactly 2 intervals: still fine */
    CHECK_EQ_U64(t, ok.checked, SIM_CHECK_I11);
    CHECK_EQ_U64(t, ok.violated, 0);
    sim_check_t late = sim_check_stats(s, s->snap_taken_ms + 24U * HOUR + 1U);
    CHECK_EQ_U64(t, late.violated, SIM_CHECK_I11);
}

static void t_i11_needs_every_part_of_its_antecedent(ctest_t *t) {
    uint64_t now = 1000U * HOUR;
    sim_stats_t *s = synced();
    s->uploads = 0;
    CHECK_EQ_U64(t, sim_check_stats(s, now).checked, 0); /* no upload yet: nothing to check */
    s = synced();
    s->sync_interval_ms = 0;
    CHECK_EQ_U64(t, sim_check_stats(s, now).checked, 0); /* no sync in this app */
    s = synced();
    s->snap_pending = 0;
    CHECK_EQ_U64(t, sim_check_stats(s, now).violated, 0); /* the book did not change: an old snapshot is current */
    s = synced();
    s->link_ok_ms = 36U * HOUR - 1U;
    CHECK_EQ_U64(t, sim_check_stats(s, now).violated, 0); /* the link was not healthy for 3 intervals */
    s->link_ok_ms = 36U * HOUR;
    CHECK_EQ_U64(t, sim_check_stats(s, now).violated, SIM_CHECK_I11);
    s = synced();
    s->snap_taken_ms = now + 1U; /* a snapshot from the future is not stale, and nothing underflows */
    CHECK_EQ_U64(t, sim_check_stats(s, now).violated, 0);
}

static void t_i12_a_lost_slot_is_a_violation(ctest_t *t) {
    sim_stats_t *s = blank();
    strcpy(s->gauges[1].name, "pool");
    s->gauges[1].cap = 2;
    s->gauges[1].free_idle = 2;
    sim_check_t c = sim_check_stats(s, 0);
    CHECK_EQ_U64(t, c.checked, SIM_CHECK_I12);
    CHECK_EQ_U64(t, c.violated, 0);
    s->gauges[1].free_idle = 1;
    CHECK_EQ_U64(t, sim_check_stats(s, 0).violated, SIM_CHECK_I12);
    s->gauges[1].free_idle = 2;
    strcpy(s->gauges[3].name, "other"); /* any gauge counts, not the first */
    s->gauges[3].cap = 4;
    s->gauges[3].free_idle = 0;
    CHECK_EQ_U64(t, sim_check_stats(s, 0).violated, SIM_CHECK_I12);
}

static void t_i13_only_impossible_counters_count(ctest_t *t) {
    sim_stats_t *s = blank();
    strcpy(s->counters[0].name, "save_failed");
    s->counters[0].value = 7; /* a counter that may move */
    CHECK_EQ_U64(t, sim_check_stats(s, 0).checked, 0);
    strcpy(s->counters[5].name, "no_free_blob");
    s->counters[5].impossible = 1;
    sim_check_t c = sim_check_stats(s, 0);
    CHECK_EQ_U64(t, c.checked, SIM_CHECK_I13);
    CHECK_EQ_U64(t, c.violated, 0);
    s->counters[5].value = 1;
    CHECK_EQ_U64(t, sim_check_stats(s, 0).violated, SIM_CHECK_I13);
    s->counters[5].name[0] = '\0'; /* an unused slot is not read */
    CHECK_EQ_U64(t, sim_check_stats(s, 0).checked, 0);
}

static void t_checks_are_independent(ctest_t *t) {
    sim_stats_t *s = synced();
    strcpy(s->gauges[0].name, "pool");
    s->gauges[0].cap = 2;
    s->gauges[0].free_idle = 0;
    strcpy(s->counters[0].name, "no_free_blob");
    s->counters[0].impossible = 1;
    sim_check_t c = sim_check_stats(s, s->snap_taken_ms + 25U * HOUR);
    CHECK_EQ_U64(t, c.checked, SIM_CHECK_I11 | SIM_CHECK_I12 | SIM_CHECK_I13);
    CHECK_EQ_U64(t, c.violated, SIM_CHECK_I11 | SIM_CHECK_I12);
}

static void t_names_are_closed_sets(ctest_t *t) {
    CHECK(t, strcmp(sim_check_name(0), "I11") == 0 && strcmp(sim_check_name(2), "I13") == 0);
    CHECK(t, sim_check_name(3) == NULL);
    CHECK(t, strcmp(sim_fault_name(SIM_FAULT_RELAY_SILENT), "relay_silent") == 0);
    CHECK(t, strcmp(sim_fault_name(SIM_FAULT_DISK_FULL), "disk_full") == 0);
    CHECK(t, sim_fault_name(SIM_FAULT_COUNT) == NULL);
    CHECK(t, strcmp(sim_screen_name(SIM_SCREEN_SPLASH), "splash") == 0);
    CHECK(t, strcmp(sim_screen_name(SIM_SCREEN_FAULT_RELAY), "fault_relay") == 0);
    CHECK(t, sim_screen_name(SIM_SCREEN_COUNT) == NULL);
}

CTEST_SUITE("sim_unit", {"sha256_vectors", t_sha256_vectors}, {"seed_derivation", t_seed_derivation},
            {"trace_hash", t_trace_hash}, {"rng_is_splitmix64", t_rng_is_splitmix64},
            {"workload_reaches_every_call", t_workload_reaches_every_call},
            {"workload_without_power_cuts", t_workload_without_power_cuts_injects_a_fault_instead},
            {"workload_passes_a_world_error_on", t_workload_passes_a_world_error_on},
            {"nothing_reported_checks_nothing", t_nothing_reported_checks_nothing},
            {"i11_boundary_is_two_intervals", t_i11_boundary_is_two_intervals},
            {"i11_needs_every_part_of_its_antecedent", t_i11_needs_every_part_of_its_antecedent},
            {"i12_a_lost_slot_is_a_violation", t_i12_a_lost_slot_is_a_violation},
            {"i13_only_impossible_counters_count", t_i13_only_impossible_counters_count},
            {"checks_are_independent", t_checks_are_independent}, {"names_are_closed_sets", t_names_are_closed_sets})
