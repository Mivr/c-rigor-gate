/* The toy LVGL app of the UI gate selftest (U03): one screen with a title, one button and one timed notice.
 * Product rules apply: static memory, no libc allocation, LVGL from the gate. */
#ifndef SELFTEST_UI_PRODUCT_TOY_H
#define SELFTEST_UI_PRODUCT_TOY_H

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

#define TOY_W 160
#define TOY_H 120
#define TOY_NOTICE_MS 3000u

/* Cold start: a fresh LVGL, the screen with the notice hidden, and one frame drawn. False if LVGL cannot start. */
bool toy_start(void);

/* The display of the running app, or NULL when it is not started. */
lv_display_t *toy_display(void);

/* Click the button (the same event a tap sends). */
void toy_press(void);

/* True once per click since the last call (the button's handler records it). */
bool toy_take_press(void);

/* Show the notice with `text` for TOY_NOTICE_MS from virtual time `now_ms`. */
void toy_show_notice(const char *text, uint64_t now_ms);

/* Hide the notice now. */
void toy_hide_notice(void);

/* The virtual time the shown notice times out at, or UINT64_MAX if none is shown. */
uint64_t toy_notice_due(void);

/* Move LVGL's tick by `ms` and run its timers once. */
void toy_step(uint32_t ms);

/* One node of the scene as the model reports it. */
typedef struct {
    const char *key;
    const char *role;
    const char *text;
    int32_t x;
    int32_t y;
    int32_t w;
    int32_t h;
    bool hidden;
} toy_node_t;

#define TOY_NODES 3u

/* The node `i` (0 title, 1 button, 2 notice) with its geometry from LVGL; false if `i` is out of range. */
bool toy_node(unsigned i, toy_node_t *out);

bool toy_notice_shown(void);

/* Draw the scene now (what a frame does). */
void toy_draw(void);
#endif
