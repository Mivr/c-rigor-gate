/* Shared setup of the gate//ui/lvprobe tests: LVGL with a 320x240 memory display, an open probe, a test font. */
#ifndef UI_LVPROBE_TESTS_TESTKIT_H
#define UI_LVPROBE_TESTS_TESTKIT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ctest/ctest.h"
#include "lvgl.h"
#include "ui/lvprobe/lvprobe.h"

enum { TK_W = 320, TK_H = 240, TK_LINE_H = 16 };

extern lvprobe_t tk_probe;
extern uint32_t tk_scratch[TK_W * TK_H];

/* Monospace test font, line height 16, baseline 2 px above the bottom, solid 1 bpp glyphs, each box 1 px right of the
 * pen: ' ' (advance 10, no box), '.' (advance 10, 2x2 at line rows 12..13), 'A' (advance 10, 8x12 at rows 2..13),
 * U+0419 (Cyrillic Й: advance 10, 8x14 at rows 0..13), U+0401 (Cyrillic Ё: advance 10, 8x18 at rows -4..13, so it
 * rises 4 px above the line). Everything else is missing (LVGL draws a placeholder). */
extern const lv_font_t tk_mono;

lv_display_t *tk_start(ctest_t *t);           /* pool, lv_init, display, white screen, probe open, settled */
void tk_stop(lv_display_t *disp);
bool tk_walk(ctest_t *t);                     /* settle until quiet (at most 4 refreshes), then walk: OK */
const lvprobe_node_t *tk_node(ctest_t *t, const lv_obj_t *obj);
uint16_t tk_index(const lv_obj_t *obj);       /* 0xFFFF when not walked */
lv_obj_t *tk_label(lv_obj_t *parent, const char *text, int32_t x, int32_t y); /* tk_mono, black */
lv_obj_t *tk_box(lv_obj_t *parent, int32_t x, int32_t y, int32_t w, int32_t h, uint32_t rgb); /* no theme style */
uint32_t tk_pixel(int32_t x, int32_t y);      /* the display buffer, read without the probe */
uint32_t tk_count_not(const lv_area_t *box, uint32_t rgb); /* pixels of `box` that are not `rgb` */
bool tk_contains(const char *hay, size_t len, const char *needle);
bool tk_box_is(const lv_area_t *a, int32_t x1, int32_t y1, int32_t x2, int32_t y2);

#endif /* UI_LVPROBE_TESTS_TESTKIT_H */
