#include "sim/inv/audit.h"

#include <stddef.h>

#define SEQ_MAX_DIGITS 18U

/* What one pass over a line finds: the digits after the first `"seq":`. */
typedef struct {
    uint32_t matched; /* bytes of the key matched so far (6 = the key was seen) */
    uint32_t digits;
    uint64_t value;
    int ended; /* the digits (or their absence) are over */
} line_t;

static void line_byte(line_t *l, uint8_t c) {
    static const char key[] = "\"seq\":";
    if (l->ended != 0) {
        return;
    }
    if (l->matched < sizeof key - 1U) {
        /* The key has one `"`, at its start: a mismatch can only restart on another `"`. */
        l->matched = c == (uint8_t)key[l->matched] ? l->matched + 1U : (c == (uint8_t)key[0] ? 1U : 0U);
    } else if (c >= (uint8_t)'0' && c <= (uint8_t)'9') {
        l->value = l->value * 10U + (uint64_t)(c - (uint8_t)'0');
        l->digits++;
    } else {
        l->ended = 1;
    }
}

/* One complete line of `n` >= 1 bytes, without its newline: accept it and take its seq. */
static audit_result_t take_line(const uint8_t *line, uint32_t n, audit_scan_t *out) {
    line_t l = {0, 0, 0, 0};
    for (uint32_t i = 0; i < n; i++) {
        line_byte(&l, line[i]);
    }
    if (line[0] != (uint8_t)'{' || line[n - 1U] != (uint8_t)'}' || l.digits < 1U || l.digits > SEQ_MAX_DIGITS) {
        return AUDIT_FORMAT;
    }
    if (out->lines == 0U) {
        out->first_seq = l.value;
    } else if (l.value != out->last_seq + 1U) {
        return AUDIT_GAP;
    }
    out->last_seq = l.value;
    out->lines++;
    return AUDIT_OK;
}

audit_result_t audit_scan(const uint8_t *bytes, uint32_t len, int allow_torn, audit_scan_t *out) {
    if (out == NULL) {
        return AUDIT_FORMAT;
    }
    *out = (audit_scan_t){0, 0, 0, 0};
    if (bytes == NULL && len > 0U) {
        return AUDIT_FORMAT;
    }
    uint32_t start = 0;
    for (uint32_t i = 0; i < len; i++) {
        if (bytes[i] == (uint8_t)'\n') {
            if (i == start) {
                return AUDIT_FORMAT; /* an empty line */
            }
            audit_result_t r = take_line(bytes + start, i - start, out);
            if (r != AUDIT_OK) {
                return r;
            }
            start = i + 1U;
        }
    }
    if (start < len) {
        if (!allow_torn) {
            return AUDIT_FORMAT;
        }
        out->torn = 1;
    }
    return AUDIT_OK;
}
