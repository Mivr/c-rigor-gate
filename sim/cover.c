#include "sim/cover.h"

#include <string.h>

void sim_cover_init(sim_cover_total_t *total) {
    memset(total, 0, sizeof *total);
}

static int finished_both_runs(const sim_seed_out_t *out) {
    return out->rule == SIM_OK || out->rule == SIM_NONDETERMINISTIC || out->rule == SIM_INVARIANT;
}

static sim_cover_counter_t *counter_slot(sim_cover_total_t *total, const char *name) {
    sim_cover_counter_t *free_slot = NULL;
    for (unsigned i = 0; i < SIM_COUNTERS; i++) {
        sim_cover_counter_t *c = &total->counters[i];
        if (c->name[0] == '\0') {
            free_slot = free_slot == NULL ? c : free_slot;
        } else if (strncmp(c->name, name, SIM_NAME_MAX) == 0) {
            return c;
        }
    }
    if (free_slot != NULL) {
        memcpy(free_slot->name, name, SIM_NAME_MAX);
        free_slot->name[SIM_NAME_MAX - 1U] = '\0';
    }
    return free_slot;
}

static void add_counters(sim_cover_total_t *total, const sim_stats_t *stats) {
    for (unsigned i = 0; i < SIM_COUNTERS; i++) {
        const sim_counter_t *c = &stats->counters[i];
        sim_cover_counter_t *slot = c->name[0] == '\0' ? NULL : counter_slot(total, c->name);
        if (slot != NULL) {
            slot->value += c->value;
        }
    }
}

void sim_cover_add(sim_cover_total_t *total, const sim_seed_out_t *out) {
    if (!finished_both_runs(out)) {
        return;
    }
    total->identity_checked++;
    total->identity_violated += out->rule == SIM_NONDETERMINISTIC ? 1U : 0U;
    const sim_cover_t *c = &out->cover;
    for (unsigned i = 0; i < SIM_CHECKS; i++) {
        total->checked[i] += (c->checked >> i) & 1U;
        total->violated[i] += (c->violated >> i) & 1U;
    }
    for (unsigned k = 0; k < (unsigned)SIM_FAULT_COUNT; k++) {
        total->fired[k] += c->fired[k];
        total->observed[k] += c->stats.fault_observed[k];
    }
    total->screens |= c->stats.screens;
    add_counters(total, &c->stats);
}

/* A name in the stats is a JSON key: anything but lowercase letters, digits and `_` becomes `_`. */
static void put_key(FILE *f, const char *name) {
    (void)fputc('"', f);
    for (unsigned i = 0; i < SIM_NAME_MAX && name[i] != '\0'; i++) {
        char ch = name[i];
        int ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_';
        (void)fputc(ok ? ch : '_', f);
    }
    (void)fputs("\":", f);
}

void sim_cover_write_counters(FILE *f, const sim_cover_total_t *total) {
    const char *sep = "";
    (void)fputs("\"counters\":{", f);
    for (unsigned i = 0; i < SIM_COUNTERS; i++) {
        if (total->counters[i].name[0] != '\0') {
            (void)fputs(sep, f);
            put_key(f, total->counters[i].name);
            (void)fprintf(f, "%llu", (unsigned long long)total->counters[i].value);
            sep = ",";
        }
    }
    (void)fputc('}', f);
}

void sim_cover_write_faults(FILE *f, const sim_cover_total_t *total) {
    const char *sep = "";
    (void)fputs("\"faults\":{", f);
    for (unsigned k = 0; k < (unsigned)SIM_FAULT_COUNT; k++) {
        (void)fprintf(f, "%s\"%s\":{\"fired\":%llu,\"observed\":%llu}", sep, sim_fault_name(k),
                      (unsigned long long)total->fired[k], (unsigned long long)total->observed[k]);
        sep = ",";
    }
    (void)fputc('}', f);
}

void sim_cover_write_invariants(FILE *f, const sim_cover_total_t *total) {
    (void)fputs("\"invariants\":{", f);
    for (unsigned i = 0; i < SIM_CHECKS; i++) {
        (void)fprintf(f, "\"%s\":{\"checked\":%llu,\"violated\":%llu},", sim_check_name(i),
                      (unsigned long long)total->checked[i], (unsigned long long)total->violated[i]);
    }
    (void)fprintf(f, "\"I14\":{\"checked\":%llu,\"violated\":%llu}}", (unsigned long long)total->identity_checked,
                  (unsigned long long)total->identity_violated);
}

void sim_cover_write_screens(FILE *f, const sim_cover_total_t *total) {
    const char *sep = "";
    (void)fputs("\"screens\":[", f);
    for (unsigned s = 0; s < (unsigned)SIM_SCREEN_COUNT; s++) {
        if (((total->screens >> s) & 1U) != 0) {
            (void)fprintf(f, "%s\"%s\"", sep, sim_screen_name(s));
            sep = ",";
        }
    }
    (void)fputc(']', f);
}
