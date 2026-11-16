/* The canary app of the U06/U07 judges selftest (selftest/ui_judges.sh): one 320x240 screen whose scene is a table of
 * nodes. Variant 0 is the clean state; every other variant puts the scene into a state with exactly one defect that one
 * check of the ui-scene, ui-fit or ui-render judge must find, or (V_MODAL) a correct modal dialog whose dimmed,
 * clickable scrim makes the background inert, which no check may flag (docs/ui-judges.md, docs/ui-judges-render.md,
 * "Canaries"). The model adapter reports the table as the semantic records, in the scene
 * vocabulary of the real lockers kiosk: structural roles, numeric style tokens, flag letters, `-` for importance,
 * input and wrap policy. The LVGL objects are built from the same table.
 * Product rules apply: static memory, no libc allocation, LVGL from the gate. */
#ifndef SELFTEST_UI_CANARY_PRODUCT_CANARY_H
#define SELFTEST_UI_CANARY_PRODUCT_CANARY_H

#include <stdbool.h>
#include <stdint.h>

#include "lvgl.h"

#define CANARY_W 320
#define CANARY_H 240
#define CANARY_NODES 12u
#define CANARY_VARIANTS 39u

typedef enum { CANARY_LABEL, CANARY_BUTTON, CANARY_PANEL, CANARY_GHOST } canary_kind_t;

/* One scene node: what the scene declares (the semantic record) and how it is drawn. */
typedef struct {
    const char *key;
    const char *role;     /* structural: text, button, panel, dialog, ... */
    const char *text;
    int32_t x;
    int32_t y;
    int32_t w;
    int32_t h;
    const char *intent;
    const char *flags;    /* `-` or letters (I inert) */
    unsigned token;       /* the style token (canary.toml [[style]]) */
    canary_kind_t kind;
    bool enabled;
    uint8_t opa;          /* a panel's background opacity (0: none) */
    bool clickable;       /* a panel takes taps */
    bool in_card;         /* built inside the last opaque, clickable panel (a dialog's button) */
    const char *wrap;     /* the wrap_policy field: NULL is `-` (V_WRAP_CONTRA states one the contract does not give) */
} canary_node_t;

/* U24: the scene identity of one node: its element id and msgid (`-` for none) and at most one formatted argument
 * (NULL: none). */
typedef struct {
    const char *element;
    const char *msgid;
    const char *arg;
} canary_identity_t;

/* Cold start: a fresh LVGL and the clean scene drawn. False if LVGL cannot start. */
bool canary_start(void);

/* Rebuild the scene as variant `v` (0 clean, 1..CANARY_VARIANTS-1); false if `v` is out of range. */
bool canary_show(unsigned v);

/* The display of the running app, or NULL when it is not started. */
lv_display_t *canary_display(void);

/* The number of scene nodes of the current variant, and node `i` of it (false if out of range). */
unsigned canary_count(void);
bool canary_node(unsigned i, canary_node_t *out);

/* U24: the state class of the current variant (`main`, or `detail` for the variant that lacks a required element), and
 * the identity of node `i`: false if `i` is out of range or the node has no identity. */
const char *canary_state_class(void);
bool canary_identity(unsigned i, canary_identity_t *out);

/* Move LVGL's tick by `ms` and run its timers once; draw the scene now. */
void canary_step(uint32_t ms);
void canary_draw(void);
#endif
