/* The canary app of the U06 judges selftest (selftest/ui_judges.sh): one 320x240 screen whose scene is a table of nodes.
 * Variant 0 is the clean state; every other variant puts the scene into a state with exactly one defect that one check
 * of the ui-scene or ui-fit judge must find (docs/ui-judges.md, "Canaries"). The model adapter reports the table as
 * the semantic records; the LVGL objects are built from the same table.
 * Product rules apply: static memory, no libc allocation, LVGL from the gate. */
#ifndef SELFTEST_UI_CANARY_PRODUCT_CANARY_H
#define SELFTEST_UI_CANARY_PRODUCT_CANARY_H

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

#define CANARY_W 320
#define CANARY_H 240
#define CANARY_NODES 8u
#define CANARY_VARIANTS 17u

typedef enum { CANARY_LABEL, CANARY_BUTTON, CANARY_PANEL, CANARY_LAYER, CANARY_GHOST } canary_kind_t;

/* One scene node: what the scene declares (the semantic record) and how it is drawn. */
typedef struct {
    const char *key;
    const char *role;
    const char *text;
    int32_t x;
    int32_t y;
    int32_t w;
    int32_t h;
    const char *intent;
    const char *style;
    const char *importance;
    const char *policy;
    const char *wrap;
    canary_kind_t kind;
} canary_node_t;

/* Cold start: a fresh LVGL and the clean scene drawn. False if LVGL cannot start. */
bool canary_start(void);

/* Rebuild the scene as variant `v` (0 clean, 1..CANARY_VARIANTS-1 one defect each); false if `v` is out of range. */
bool canary_show(unsigned v);

/* The display of the running app, or NULL when it is not started. */
lv_display_t *canary_display(void);

/* The number of scene nodes of the current variant, and node `i` of it (false if out of range). */
unsigned canary_count(void);
bool canary_node(unsigned i, canary_node_t *out);

/* Move LVGL's tick by `ms` and run its timers once; draw the scene now. */
void canary_step(uint32_t ms);
void canary_draw(void);
#endif
