/* A fixture product for the view invariants: a model of a kiosk that publishes the views of one simulated day (`ev` and `vw` records
 * of the fixture schema) from a seed, answers the engine's phrase and replay callbacks by re-running itself, and has seeded bugs. It is
 * a generator of traces, not a `c_sim` world; it shares nothing with a real product. */
#ifndef SIM_INV_TESTS_UI_MODEL_H
#define SIM_INV_TESTS_UI_MODEL_H

#include <stdint.h>

#include "sim/inv/ui.h"

typedef enum {
    UMODEL_CORRECT = 0,
    UMODEL_FULL_SCREEN_MESSAGE,    /* the third visit's rejection is published as a screen of its own (I7) */
    UMODEL_NOTICE_WITHOUT_DISMISS, /* the third visit's rejection is published with no dismiss intent (I7) */
    UMODEL_COUNTDOWN_NULL,         /* the third visit's rejection clears by itself and never showed a countdown (I7) */
    UMODEL_LANG_NOT_RESET,         /* the language a visitor chose is still there after the idle time (I7) */
    UMODEL_DISMISS_IGNORED         /* a dismiss intent does not clear the notice (I8) */
} umodel_bug_t;

typedef struct {
    uint32_t bug_record; /* the index of the record the bug first shows at (the engine must name exactly this one) */
    uint32_t visits, notices, dismissed, expired;
    uint64_t end_ms;
} umodel_out_t;

/* Run one seed through `u` (started here, with the fixture schema, the usual configuration and the model's callbacks), including ui_finish.
 * Returns 0 when the engine took every record. */
int umodel_run(ui_t *u, uint64_t seed, umodel_bug_t bug, umodel_out_t *out);

#endif
