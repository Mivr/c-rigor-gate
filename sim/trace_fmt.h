/* The trace of a simulated run (P330 §1.3, §1.5): the records the gate's tap sees and the rolling hash over them.
 *
 * A record is what the world (or the gate's own wire/file taps, later) observed, never what the product chose to
 * report. Kinds: "ev" (event taken by the app), "fx" (effect executed), "fr" (frame on the wire), "io" (file
 * operation), "vw" (view published), "st" (stats). The hash is FNV-1a 64 over the canonical byte form of every
 * record in order: kind (2 bytes), t_ms (8, little endian), a (4, le), b (4, le), len (4, le), then `len` bytes.
 * Gate-owned: the product never writes a trace file and never computes the trace hash.
 */
#ifndef SIM_TRACE_FMT_H
#define SIM_TRACE_FMT_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    char kind[2];
    uint64_t t_ms;
    uint32_t a;
    uint32_t b;
    const uint8_t *bytes; /* NULL only when len is 0 */
    uint32_t len;
} sim_rec_t;

/* The observer the runner installs with world_tap. `ctx` is the runner's. */
typedef void (*sim_tap_fn)(void *ctx, const sim_rec_t *rec);

typedef struct {
    uint64_t hash;
    uint64_t records;
} sim_trace_t;

void sim_trace_init(sim_trace_t *trace);
/* Fold one record into the trace; a record with `len > 0` and no bytes is ignored and returns 0. */
int sim_trace_add(sim_trace_t *trace, const sim_rec_t *rec);

#endif
