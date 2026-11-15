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
    unsigned errors;
    uint64_t origin;
    uint64_t now;
} probe_t;

/* The shape of the records of one call (model.h): field count and which fields are decimal numbers. */
typedef struct {
    unsigned fields;
    unsigned signed_mask;
    unsigned unsigned_mask;
} probe_spec_t;

extern const probe_spec_t PROBE_SPEC_SEMANTIC;
extern const probe_spec_t PROBE_SPEC_PATCHES;
extern const probe_spec_t PROBE_SPEC_TRACE;

/* Strict parsing of command arguments (probe_parse.c). */
bool probe_parse_u64(const char *s, uint64_t *out);
bool probe_parse_i32(const char *s, int32_t *out);
bool probe_parse_text(const char *s, char *out);
void probe_to_hex(const unsigned char *bytes, size_t n, char *out);

/* The number of lines of a payload that is zero or more valid records, or -1. `spec == NULL`: lines of printable ASCII
 * and TABs only (probe_records.c). */
long probe_check_records(const probe_spec_t *spec, const char *buf, size_t len);

typedef enum { PROBE_ADV_OK, PROBE_ADV_FAILED, PROBE_ADV_CONTRACT } probe_advance_t;

/* Moves the virtual clock to `to` in steps of the frame grid (probe_time.c). */
probe_advance_t probe_advance_to(probe_t *p, uint64_t to);

#endif
