/* Internal interface of the probe's source files (gate-owned; not part of the model interface). */
#ifndef UI_MODEL_PROBE_H
#define UI_MODEL_PROBE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/model/model.h"

/* The lvprobe storage the probe owns statically (probe_frame.c) and the bounds of the seam (docs/ui-model.md,
 * "Frame facts"). Per-frame byte budget: the lines of one `frame` reply are at most UIM_BUF_MAX - 1 bytes (the encoder
 * needs one byte for its NUL). A node takes at most LVPROBE_LINE_FIXED + 4 x (class name + text + full text) bytes, a
 * `life` line at most 64 + 4 x its class name; typical: 60 to 90 bytes per plain node, about 100 more per label plus 4 per
 * UTF-8 byte of its text, so about 512 plain nodes or four Bulgarian screens of 84 objects fit. A frame whose lines do not
 * fit, more than PROBE_LV_NODES objects, PROBE_LV_TEXT bytes of label text or PROBE_LV_LIFE lifecycle events since the
 * previous frame is `err frame too-large`: never a truncation. */
enum {
    PROBE_LV_NODES = LVPROBE_DEFAULT_NODES,     /* objects in one walk */
    PROBE_LV_TEXT = LVPROBE_DEFAULT_TEXT,       /* bytes of all label texts of one walk */
    PROBE_LV_LIFE = LVPROBE_DEFAULT_LIFE,       /* lifecycle events between two frames */
    PROBE_LV_SCREENS = LVPROBE_DEFAULT_SCREENS, /* screens of the display */
    PROBE_LV_SCRATCH_PX = 1280 * 800,           /* ink scratch: the largest display (a 1280x800 panel) */
    PROBE_SETTLE_MAX = 8,                       /* refreshes until a quiet frame, else model-contract */
    PROBE_FRAME_TRIES = 4,                      /* snapshots of one `frame` (stale, unsettled, or product work ran) */
    PROBE_INK_RETRIES = 1                       /* an unstable or unsettled ink: settle and retry once */
};

typedef struct {
    uim_t *model;
    bool opened;
    bool quit;
    bool failed;            /* a protocol error happened (sticky) */
    uint64_t origin;
    uint64_t now;
    const char *cmd;        /* the name of the command being run (set by the dispatcher) */
    lvprobe_t *lv;          /* the lvprobe of the session (static storage); open exactly when `disp` is not NULL */
    struct _lv_display_t *disp;   /* the display lvprobe observes, NULL while it is closed */
    bool framed;            /* a `frame` succeeded and no command changed the model since */
} probe_t;

/* The shape of the records of one call (model.h): field count and which fields are decimal numbers. */
typedef struct {
    unsigned fields;
    unsigned signed_mask;
    unsigned unsigned_mask;
    unsigned flag_mask;     /* fields that are exactly `0` or `1` */
} probe_spec_t;

extern const probe_spec_t PROBE_SPEC_SEMANTIC;
extern const probe_spec_t PROBE_SPEC_PATCHES;
extern const probe_spec_t PROBE_SPEC_TRACE;

/* Strict parsing of command arguments (probe_parse.c). */
bool probe_parse_u64(const char *s, uint64_t *out);
bool probe_parse_i32(const char *s, int32_t *out);
bool probe_parse_text(const char *s, char *out);
void probe_to_hex(const unsigned char *bytes, size_t n, char *out);
int probe_hex_digit(char c);   /* 0..15 for a lowercase hex digit, else -1 */

/* The reply and payload machinery of probe_main.c, for the command files (probe_frame.c). A reply is one header line
 * and, for the framed form, the first `bytes` bytes of the payload buffer after it. */
bool probe_reply_err(const char *name, const char *why);
bool probe_reply_plain(const char *name, bool good);
bool probe_reply_lines(const char *name, size_t lines, size_t bytes);
char *probe_payload(size_t *cap);

/* The lvprobe seam (docs/ui-model.md, "Frame facts"); arguments are NULL-terminated. probe_frame.c: */
bool probe_cmd_frame(probe_t *p, char **arg);
/* probe_records.c: one `life` line of event `e` at out[*at..cap): node and parent are written as -1 unless `indexed`; the class name is
 * escaped by the record grammar, `-` when it is empty. LVPROBE_ERR_TRUNC when it does not fit (`*at` does not move). */
lvprobe_status_t probe_life_line(const lvprobe_life_t *e, bool indexed, char *out, size_t cap, size_t *at);
/* probe_input.c: */
bool probe_cmd_hit_test(probe_t *p, char **arg);
bool probe_cmd_tap(probe_t *p, char **arg);
/* probe_pixels.c: */
bool probe_cmd_ink(probe_t *p, char **arg);
bool probe_cmd_crop(probe_t *p, char **arg);

/* Shared by the seam's files (probe_seam.c). */
const char *probe_why(lvprobe_status_t st);           /* the `err` reason of a status that ends a command */
bool probe_fatal(probe_t *p, const char *reason);     /* `err <cmd> <reason>`, the session poisoned */
bool probe_refuse(probe_t *p, const char *reason);    /* `err <cmd> <reason>` of a read-only call: frame dropped */
bool probe_reply_words(const char *name, const char *a, const char *b);   /* `ok <name> <a>[ <b>]` */
/* lvprobe_settle until a refresh flushes nothing (at most PROBE_SETTLE_MAX); `*flushed` if any refresh flushed. */
lvprobe_status_t probe_lv_settle(probe_t *p, bool *flushed);
typedef enum { PROBE_WORK_OK, PROBE_WORK_FAILED, PROBE_WORK_CONTRACT } probe_work_t;
/* uim_settle, its result checked (UIM_OK; UIM_ERROR fails; anything else breaks the contract). */
probe_work_t probe_model_settle(probe_t *p, bool *worked);
/* `x y`: decimal (`*syntax`), and on a frame inside the display. */
bool probe_point(const probe_t *p, char **arg, int32_t *x, int32_t *y, bool *syntax);
bool probe_point_err(const probe_t *p, bool syntax);
const char *probe_node_word(int32_t node, char *buf, size_t cap);   /* `<index>`, `none`, NULL if it does not fit */

/* The number of lines of a payload that is zero or more valid records, or -1. `spec == NULL`: lines of printable ASCII
 * and TABs only (probe_records.c). */
long probe_check_records(const probe_spec_t *spec, const char *buf, size_t len);

typedef enum { PROBE_ADV_OK, PROBE_ADV_FAILED, PROBE_ADV_CONTRACT } probe_advance_t;

/* Moves the virtual clock to `to` in steps of the frame grid (probe_time.c). */
probe_advance_t probe_advance_to(probe_t *p, uint64_t to);

#endif
