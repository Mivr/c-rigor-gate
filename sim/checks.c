#include "sim/checks.h"

#include <stddef.h>

static int has_name(const char *name) {
    return name[0] != '\0';
}

static int i11_antecedent(const sim_stats_t *s) {
    return s->uploads > 0 && s->sync_interval_ms > 0;
}

static int i11_violated(const sim_stats_t *s, uint64_t now_ms) {
    uint64_t interval = s->sync_interval_ms;
    if (!i11_antecedent(s) || s->snap_pending == 0 || s->link_ok_ms < 3U * interval) {
        return 0;
    }
    return now_ms > s->snap_taken_ms && now_ms - s->snap_taken_ms > 2U * interval;
}

static void i12_scan(const sim_stats_t *s, int *seen, int *lost) {
    for (unsigned i = 0; i < SIM_GAUGES; i++) {
        const sim_gauge_t *g = &s->gauges[i];
        if (has_name(g->name)) {
            *seen = 1;
            *lost |= g->free_idle < g->cap;
        }
    }
}

static void i13_scan(const sim_stats_t *s, int *seen, int *moved) {
    for (unsigned i = 0; i < SIM_COUNTERS; i++) {
        const sim_counter_t *c = &s->counters[i];
        if (has_name(c->name) && c->impossible != 0) {
            *seen = 1;
            *moved |= c->value != 0;
        }
    }
}

sim_check_t sim_check_stats(const sim_stats_t *stats, uint64_t now_ms) {
    sim_check_t out = {0, 0};
    int seen12 = 0, lost12 = 0, seen13 = 0, moved13 = 0;
    i12_scan(stats, &seen12, &lost12);
    i13_scan(stats, &seen13, &moved13);
    if (i11_antecedent(stats)) {
        out.checked |= SIM_CHECK_I11;
    }
    if (seen12) {
        out.checked |= SIM_CHECK_I12;
    }
    if (seen13) {
        out.checked |= SIM_CHECK_I13;
    }
    out.violated |= i11_violated(stats, now_ms) ? SIM_CHECK_I11 : 0U;
    out.violated |= lost12 ? SIM_CHECK_I12 : 0U;
    out.violated |= moved13 ? SIM_CHECK_I13 : 0U;
    return out;
}

const char *sim_check_name(unsigned bit_index) {
    static const char *const names[SIM_CHECKS] = {"I11", "I12", "I13"};
    return bit_index < SIM_CHECKS ? names[bit_index] : NULL;
}

const char *sim_fault_name(unsigned kind) {
    static const char *const names[SIM_FAULT_COUNT] = {"relay_silent", "clock_jump", "disk_full"};
    return kind < (unsigned)SIM_FAULT_COUNT ? names[kind] : NULL;
}

const char *sim_screen_name(unsigned screen) {
    static const char *const names[SIM_SCREEN_COUNT] = {"splash",  "welcome", "choose",        "opened",       "shift",
                                                        "report", "lockout", "fault_storage", "fault_relay"};
    return screen < (unsigned)SIM_SCREEN_COUNT ? names[screen] : NULL;
}
