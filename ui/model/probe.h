/* Internal interface of the probe's source files (gate-owned; not part of the model interface). */
#ifndef UI_MODEL_PROBE_H
#define UI_MODEL_PROBE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/model/model.h"

typedef struct {
    uim_t *model;
    bool opened;
    bool quit;
    bool failed;            /* a protocol error happened (sticky) */
    uint64_t origin;
    uint64_t now;
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
int probe_hex_digit(char c);

/* The reply and payload machinery of probe_main.c, for the command files (probe_frame.c). A reply is one header line
 * and, for the framed form, the first `bytes` bytes of the payload buffer after it. */
bool probe_reply_err(const char *name, const char *why);
bool probe_reply_plain(const char *name, bool good);
bool probe_reply_lines(const char *name, size_t lines, size_t bytes);
char *probe_payload(size_t *cap);

/* The `frame` command (probe_frame.c): the seam where lvprobe joins. */
bool probe_cmd_frame(probe_t *p, char **arg);   /* 0..15 for a lowercase hex digit, else -1 */

/* The number of lines of a payload that is zero or more valid records, or -1. `spec == NULL`: lines of printable ASCII
 * and TABs only (probe_records.c). */
long probe_check_records(const probe_spec_t *spec, const char *buf, size_t len);

typedef enum { PROBE_ADV_OK, PROBE_ADV_FAILED, PROBE_ADV_CONTRACT } probe_advance_t;

/* Moves the virtual clock to `to` in steps of the frame grid (probe_time.c). */
probe_advance_t probe_advance_to(probe_t *p, uint64_t to);

#endif
