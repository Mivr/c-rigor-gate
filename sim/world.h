/* The world interface of a `c_sim` target (P330 §1.2). The product implements these functions in the `srcs` of the
 * `c_sim` target; the gate's runner (`gate//sim:runner`) owns `main`, the seeds, the workload, the faults and the
 * identity check. The world contains no workload, no fault schedule and no invariant.
 *
 * Rules for a world (the other gates apply to its sources like to any `c_library`; the runner only checks what it can see):
 *  - ALL time is virtual. No function reads a real clock, `getenv`, a file or a socket of the host; every port is a simulation.
 *  - Every function is non-blocking and deterministic in (cfg, seed, the calls made so far).
 *  - There is ONE world instance, static (no heap): `world_init` re-initialises it, so two runs in one process are
 *    independent. The tap installed by `world_tap` stays installed across `world_crash_restart`.
 *  - Observation: the world calls the tap for every event, effect, wire frame and file operation it models (see
 *    sim/trace_fmt.h). The product's own code never formats a trace record.
 */
#ifndef SIM_WORLD_H
#define SIM_WORLD_H

#include <stddef.h>
#include <stdint.h>

#include "sim/trace_fmt.h"

typedef struct world world_t;

/* Return codes of world_run_until, world_apply, world_fault and world_crash_restart. */
enum {
    WORLD_OK = 0,
    WORLD_STEP_LIMIT = 1, /* the world used more than cfg.step_limit steps: a runaway; the runner reports sim-timeout */
    WORLD_DEADLOCK = 2,   /* nothing is runnable and virtual time cannot advance: sim-deadlock */
    WORLD_ERROR = 3       /* the call is not understood or failed: sim-world-error */
};

typedef struct {
    uint64_t start_ms;   /* virtual time at boot */
    uint64_t step_limit; /* the most steps one run may use, counted by the world; 0 is refused by the runner */
} sim_cfg_t;

/* Abstract intents on the UI lane (P330 §1.2). `arg` is the digit, size or notice index. */
typedef enum {
    SIM_INTENT_DIGIT = 0,
    SIM_INTENT_BACKSPACE,
    SIM_INTENT_SUBMIT,
    SIM_INTENT_SCAN,
    SIM_INTENT_CHOOSE_SIZE,
    SIM_INTENT_CANCEL,
    SIM_INTENT_DISMISS,
    SIM_INTENT_ACK_OPENED,
    SIM_INTENT_LANG,
    SIM_INTENT_COUNT
} sim_intent_kind_t;

typedef struct {
    sim_intent_kind_t kind;
    uint32_t arg;
} sim_intent_t;

/* The fault catalogue of this skeleton (P330 §1.4 lists the full one; T2G3 and later add kinds, never reorder).
 * A power cut is not a fault of the world: the runner calls world_crash_restart. */
typedef enum {
    SIM_FAULT_RELAY_SILENT = 0,
    SIM_FAULT_CLOCK_JUMP,
    SIM_FAULT_DISK_FULL,
    SIM_FAULT_COUNT
} sim_fault_kind_t;

typedef struct {
    sim_fault_kind_t kind;
    uint32_t arg;
    uint32_t duration_ms;
} sim_fault_t;

/* The closed screen set of the kiosk (P330 §1.6): a bit of `sim_stats_t.screens` per screen the world showed. */
typedef enum {
    SIM_SCREEN_SPLASH = 0,
    SIM_SCREEN_WELCOME,
    SIM_SCREEN_CHOOSE,
    SIM_SCREEN_OPENED,
    SIM_SCREEN_SHIFT,
    SIM_SCREEN_REPORT,
    SIM_SCREEN_LOCKOUT,
    SIM_SCREEN_FAULT_STORAGE,
    SIM_SCREEN_FAULT_RELAY,
    SIM_SCREEN_COUNT
} sim_screen_t;

#define SIM_COUNTERS 8U
#define SIM_GAUGES 4U
#define SIM_NAME_MAX 24U

/* A runtime counter. `name` is empty for an unused slot, else lowercase letters, digits and `_`. An `impossible` counter is
 * one that must stay 0 by design (P330 §2 I13: `rx_push_lost`, `no_free_blob`, ...); the runner reports a violation of I13
 * the first time one is not 0. */
typedef struct {
    char name[SIM_NAME_MAX];
    uint64_t value;
    uint8_t impossible;
} sim_counter_t;

/* A fixed-capacity resource (a pool). `cap` slots exist; `free_idle` of them are usable when the app is idle. Anything
 * below `cap` is capacity lost for good (a retired slot, P330 §5.3): I12. An empty `name` is an unused slot. */
typedef struct {
    char name[SIM_NAME_MAX];
    uint64_t cap;
    uint64_t free_idle;
} sim_gauge_t;

/* What the runner reads from a world (P330 §1.2 `world_stats`), at the end of a run and at every daily checkpoint of a
 * soak. The world only reports what it counted; the verdicts (I11, I12, I13) are the gate's (sim/checks.h). */
typedef struct {
    uint64_t steps; /* steps used so far in this run */
    sim_counter_t counters[SIM_COUNTERS];
    sim_gauge_t gauges[SIM_GAUGES];
    uint64_t uploads;          /* sync uploads the simulated server has received (the antecedent of I11) */
    uint64_t snap_taken_ms;    /* `taken_at` of the newest snapshot the server holds (0: none) */
    uint64_t link_ok_ms;       /* how long the sync link has been healthy up to now */
    uint64_t sync_interval_ms; /* the app's sync interval; 0 when the world has no sync */
    uint32_t snap_pending;     /* 1: the book changed since the newest snapshot the server holds */
    uint32_t screens;          /* bit `sim_screen_t` of every screen shown so far */
    uint64_t fault_observed[SIM_FAULT_COUNT]; /* per fault kind: times its EFFECT was seen (a fault with none is a bug) */
} sim_stats_t;

/* Build the whole app on simulated ports at cfg->start_ms and install the tap `fn` (may be NULL) before anything
 * runs. NULL on failure (the runner reports sim-init-failed). */
world_t *world_init(const sim_cfg_t *cfg, uint64_t seed, sim_tap_fn fn, void *tap_ctx);
/* Run until virtual time is exactly `t_ms`; WORLD_OK only if it got there. */
int world_run_until(world_t *w, uint64_t t_ms);
uint64_t world_now_ms(const world_t *w);
int world_apply(world_t *w, sim_intent_t intent);
int world_fault(world_t *w, sim_fault_t fault);
/* Power cut: drop all volatile state, keep the durable image, boot again through the normal boot path. */
int world_crash_restart(world_t *w);
/* `out` arrives zeroed: the world sets only what it reports (a zeroed field is "nothing to report"), so a world needs no memset. */
int world_stats(const world_t *w, sim_stats_t *out);
/* A hash of the whole observable state of the app (book, sessions, relay model...), equal for equal runs. */
uint64_t world_state_hash(const world_t *w);

#endif
