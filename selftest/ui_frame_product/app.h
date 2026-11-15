/* The frame toy of the U05a selftest (selftest/ui_frame.sh): one screen with a title, a button, a notice in
 * Bulgarian, a label that can be made too small, a hidden label, two colour swatches with known pixels, a label in a
 * font that has its one Cyrillic glyph, a bar that can be animated, and a transparent overlay over everything that can
 * be made clickable (the F3b canary). The app has its own pointer indev and taps through it. Input handlers only QUEUE
 * work (app_take_work); the model runs it in its step and settle. Fixture switches break the model interface on
 * purpose (a second display, an extra pointer, a moving tick). Product rules apply: static memory, LVGL from the gate. */
#ifndef SELFTEST_UI_FRAME_PRODUCT_APP_H
#define SELFTEST_UI_FRAME_PRODUCT_APP_H

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

#define APP_W 160
#define APP_H 120
#define APP_BIG_W 1290   /* the big display of app_start(true): more pixels than the probe's ink scratch */
#define APP_BIG_H 800
#define APP_MANY 400u    /* labels of app_many(): more lines than a frame reply holds */

/* What the input handlers saw, for the trace; APP_POINTER_CLICKED is the pointer indev's own click event (it shows
 * which indev a tap went through). */
typedef enum {
    APP_BUTTON_PRESSED, APP_BUTTON_CLICKED, APP_OVERLAY_PRESSED, APP_OVERLAY_CLICKED, APP_POINTER_CLICKED
} app_event_t;

/* Work queued by a handler or an animation callback. */
typedef enum { APP_WORK_PRESS, APP_WORK_ANIM_DONE } app_work_t;

/* Cold start: a fresh LVGL, the screen, the pointer, one frame drawn (on the big display if `big`). */
bool app_start(bool big);
lv_display_t *app_display(void);
void app_draw(void);
void app_step(uint32_t ms);

void app_press(void);              /* tap the centre of the button through the app's pointer */
void app_show_notice(bool shown);
void app_set_title(const char *text);
void app_cover(bool clickable);    /* the overlay takes taps, or lets them through */
void app_fit(bool room);           /* the fit label at its natural size, or squeezed to 20x8 */
bool app_add(void);                /* one more label (false if there is one); app_drop deletes it */
void app_drop(void);
bool app_many(void);               /* APP_MANY hidden labels */
bool app_animate(uint32_t ms);     /* the bar's width 0 -> 20 in `ms`; its completion queues APP_WORK_ANIM_DONE */

bool app_take_event(app_event_t *out);   /* oldest first; false when there is none */
bool app_take_work(app_work_t *out);

/* Fixture switches (app_fixture.c). */
lv_display_t *app_second_display(void);   /* a second, real display (created once per start) */
bool app_extra_pointer(void);             /* a second pointer indev on the display */
void app_moving_tick(void);               /* LVGL's tick from a callback that moves on every read */
void app_fixture_reset(void);             /* forget the fixtures (at start, after lv_init) */
void app_rare_clock(void);                /* LVGL's tick from a clock that app_clock_moves() moves by 1 ms */
void app_clock_moves(void);

/* Scene nodes the model reports: 0 title, 1 button, 2 notice, 3 fit. */
#define APP_NODES 4u
typedef struct {
    const char *key;
    const char *text;
    int32_t x, y, w, h;
    bool hidden;
} app_node_t;
bool app_node(unsigned i, app_node_t *out);

#endif
