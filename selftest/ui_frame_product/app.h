/* The frame toy of the U05a selftest (selftest/ui_frame.sh): one 160x120 screen with a title, a button, a notice in
 * Bulgarian, a label that can be made too small, a hidden label, two colour swatches with known pixels and a
 * transparent overlay over everything that can be made clickable (the F3b canary). The app has its own pointer indev
 * and taps through it. Product rules apply: static memory, LVGL from the gate. */
#ifndef SELFTEST_UI_FRAME_PRODUCT_APP_H
#define SELFTEST_UI_FRAME_PRODUCT_APP_H

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

#define APP_W 160
#define APP_H 120
#define APP_MANY 400u   /* labels of app_many(): more lines than a frame reply holds */

typedef enum { APP_BUTTON_PRESSED, APP_BUTTON_CLICKED, APP_OVERLAY_PRESSED, APP_OVERLAY_CLICKED } app_event_t;

/* Cold start: a fresh LVGL, the screen, the pointer, one frame drawn. False if LVGL cannot start. */
bool app_start(void);
lv_display_t *app_display(void);
void app_draw(void);
void app_step(uint32_t ms);

/* Tap the centre of the button through the app's pointer; true if the button got the click. */
bool app_press(void);
void app_show_notice(void);
void app_cover(bool clickable);    /* the overlay takes taps, or lets them through */
void app_fit(bool room);           /* the fit label at its natural size, or squeezed to 20x8 */
bool app_add(void);                /* one more label (false if there is one); app_drop deletes it */
void app_drop(void);
bool app_many(void);               /* APP_MANY hidden labels */

/* The input handlers' events since the last call, oldest first; false when there is none. */
bool app_take_event(app_event_t *out);

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
