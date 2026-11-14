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

typedef struct {
    uint64_t steps; /* steps used so far in this run */
    uint64_t counters[8]; /* the world's own "impossible" counters; the judge reads them (T2G4) */
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
int world_stats(const world_t *w, sim_stats_t *out);
/* A hash of the whole observable state of the app (book, sessions, relay model...), equal for equal runs. */
uint64_t world_state_hash(const world_t *w);

#endif
