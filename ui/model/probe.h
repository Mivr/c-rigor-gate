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
 * `life` line at most PROBE_LIFE_LINE_MAX; typical: 60 to 90 bytes per plain node, about 100 more per label plus 4 per
 * UTF-8 byte of its text, so about 512 plain nodes or four Bulgarian screens of 84 objects fit. A frame whose lines do not
 * fit, more than PROBE_LV_NODES objects, PROBE_LV_TEXT bytes of label text or PROBE_LV_LIFE lifecycle events since the
 * previous frame is `err frame too-large`: never a truncation. */
enum {
    PROBE_LV_NODES = LVPROBE_DEFAULT_NODES,     /* objects in one walk */
    PROBE_LV_TEXT = LVPROBE_DEFAULT_TEXT,       /* bytes of all label texts of one walk */
    PROBE_LV_LIFE = LVPROBE_DEFAULT_LIFE,       /* lifecycle events between two frames */
    PROBE_LV_SCREENS = LVPROBE_DEFAULT_SCREENS, /* screens of the display */
    PROBE_LV_SCRATCH_PX = 1280 * 800,           /* ink scratch: the largest node box (a 1280x800 panel) */
    PROBE_LIFE_LINE_MAX = 96,                   /* bytes of one `life` line */
    PROBE_SETTLE_MAX = 8,                       /* refreshes until a quiet frame, else model-contract */
    PROBE_FRAME_TRIES = 4,                      /* snapshots of one `frame` that may be stale or unsettled */
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

/* The lvprobe seam (probe_frame.c): runs `frame`, `ink`, `hit-test`, `tap` and `crop`, the command named by `p->cmd`
 * (one entry point for the five, because the probe library's exports are a fixed list). Arguments are NULL-terminated. */
bool probe_cmd_frame(probe_t *p, char **arg);

/* The number of lines of a payload that is zero or more valid records, or -1. `spec == NULL`: lines of printable ASCII
 * and TABs only (probe_records.c). */
long probe_check_records(const probe_spec_t *spec, const char *buf, size_t len);

typedef enum { PROBE_ADV_OK, PROBE_ADV_FAILED, PROBE_ADV_CONTRACT } probe_advance_t;

/* Moves the virtual clock to `to` in steps of the frame grid (probe_time.c). */
probe_advance_t probe_advance_to(probe_t *p, uint64_t to);

#endif
