/* The timed canary of the ui-time judge (U09, selftest/ui_time.sh, docs/ui-judges-time.md): one 320x240 screen with
 * a title; intent v puts one timed defect on it (or, TV_CLEAN, a correct dialog of 4 s whose countdown counts 4, 3, 2,
 * 1). The scene is a pure function of (variant, the instant it was asked for, now); the model adapter (timed_model.c)
 * publishes it, diffs it into scene patches and rebuilds the LVGL objects when it changes.
 * Product rules apply: static memory, no libc allocation, LVGL from the gate. */
#ifndef SELFTEST_UI_CANARY_PRODUCT_TIMED_H
#define SELFTEST_UI_CANARY_PRODUCT_TIMED_H

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

#define TIMED_W 320
#define TIMED_H 240
#define TIMED_NODES 5u
#define TIMED_TEXT 112u
#define TIMED_NONE UINT64_MAX

/* The variants, by intent id (timed.events.toml). */
typedef enum {
    TV_NONE,    /* the title only */
    TV_CLEAN,   /* a dialog for 4 s, countdown 4 3 2 1 */
    TV_EARLY,   /* the dialog leaves after 1 s: notice-lifetime-short */
    TV_NEVER,   /* the dialog never leaves (its countdown stops at 1): notice-lifetime-long */
    TV_FLASH,   /* an object created and deleted within the input: flash in one step */
    TV_BLINK,   /* a panel shown for 200 ms: flash */
    TV_SKIP,    /* the countdown counts 4 2 (every 2 s): countdown-wrong */
    TV_ZERO,    /* the countdown counts 3 2 1 0: countdown-wrong */
    TV_START,   /* the countdown starts at 9: countdown-wrong */
    TV_SILENT,  /* the state class turns `detail` 1 s later, nothing visible changes: invisible-auto-transition */
    TV_CLOCK,   /* the expiry kept modulo 2^32: the dialog never shows from an origin of 2^32 or more */
    TV_WORDY,   /* a 4 s dialog whose text takes longer to read: dwell-below-reading-time, notice-lifetime-short */
    TV_COUNT
} timed_variant_t;

/* One scene node: its key, scene role, label and rect (display pixels). */
typedef struct {
    const char *key;
    const char *role;
    char text[TIMED_TEXT];
    int32_t x;
    int32_t y;
    int32_t w;
    int32_t h;
} timed_node_t;

/* A published scene: its nodes in tree order and the state class of its identity. */
typedef struct {
    timed_node_t nodes[TIMED_NODES];
    unsigned count;
    const char *cls;
} timed_scene_t;

/* Cold start: a fresh LVGL and an empty screen. False if LVGL cannot start. */
bool timed_start(void);

/* The display of the running app, or NULL when it is not started. */
lv_display_t *timed_display(void);

/* The scene of variant `v` asked for at `since`, at instant `now` (pure). */
void timed_scene_at(timed_variant_t v, uint64_t since, uint64_t now, timed_scene_t *out);

/* The first instant after `now` at which that scene may change, or TIMED_NONE (pure). */
uint64_t timed_next_change(timed_variant_t v, uint64_t since, uint64_t now);

/* Rebuild the LVGL objects of `scene`; false if an object cannot be made. */
bool timed_build(const timed_scene_t *scene);

/* Create one LVGL object and delete it at once (TV_FLASH); false if it cannot be made. */
bool timed_flash_object(void);

/* Move LVGL's tick by `ms` and run its timers once; draw the scene now. */
void timed_step(uint32_t ms);
void timed_draw(void);
#endif
