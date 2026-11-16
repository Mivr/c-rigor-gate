/* Shared core of the two broken model adapters of the explorer selftest (U05): model_nondet.c and model_starve.c.
 * It defines no `uim_` symbol (only a `c_ui_probe` model may); each adapter wraps it in the interface of model.h.
 * The core: the toy app; intent 1 (a press) shows the notice for TOY_NOTICE_MS and emits a trace event whose type the
 * adapter chooses; with `spin`, the press also arms a timer that re-arms itself 1 ms after every firing; with `tick_ms`
 * above 0, a perpetual periodic tick fires every `tick_ms` from boot and changes nothing visible (a clock tick). */
#ifndef SELFTEST_UI_PRODUCT_FIXTURE_H
#define SELFTEST_UI_PRODUCT_FIXTURE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FIX_LOG_MAX 2048u
#define FIX_NO_DEADLINE UINT64_MAX

typedef struct {
    bool open;
    bool spin;
    uint64_t now;
    uint64_t seq;
    uint64_t spin_due;
    uint64_t tick_ms;
    uint64_t tick_due;
    char trace[FIX_LOG_MAX];
    size_t trace_len;
} fix_t;

typedef enum { FIX_ERROR = 0, FIX_OK = 1, FIX_REFUSED = 2 } fix_result_t;

/* Cold start at `origin_ms`; `spin` selects the re-arming timer, `tick_ms` (0: none) the periodic tick. */
bool fix_open(fix_t *f, uint64_t origin_ms, bool spin, uint64_t tick_ms);

/* Intent 1 (kind 3) when no notice is shown: the press, with trace type `press_type`. Anything else is refused. */
fix_result_t fix_apply(fix_t *f, uint16_t kind, uint32_t id, const char *press_type);

uint64_t fix_next_due(const fix_t *f);

/* One step of `ms` (1..16): LVGL tick, then the due timers. */
bool fix_step(fix_t *f, uint32_t ms);

/* The 14-field semantic records of the toy's three nodes into data[0..cap); `*len` the bytes written. */
bool fix_semantic(const fix_t *f, char *data, size_t cap, size_t *len);

/* The trace records since the last call; the log is then cleared. */
bool fix_take_trace(fix_t *f, char *data, size_t cap, size_t *len);

#endif
