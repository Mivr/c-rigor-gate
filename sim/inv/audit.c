#include "sim/inv/audit.h"

#include <stddef.h>

#define SEQ_KEY "\"seq\":"
#define SEQ_KEY_LEN 6U
#define SEQ_MAX_DIGITS 18U

static int key_at(const uint8_t *line, uint32_t n, uint32_t i) {
    static const char key[] = SEQ_KEY;
    if (i + SEQ_KEY_LEN > n) {
        return 0;
    }
    for (uint32_t k = 0; k < SEQ_KEY_LEN; k++) {
        if (line[i + k] != (uint8_t)key[k]) {
            return 0;
        }
    }
    return 1;
}

/* The value after the first `"seq":` of a line: 1 to 18 decimal digits. */
static int parse_seq(const uint8_t *line, uint32_t n, uint64_t *seq) {
    for (uint32_t i = 0; i + SEQ_KEY_LEN <= n; i++) {
        if (!key_at(line, n, i)) {
            continue;
        }
        uint32_t p = i + SEQ_KEY_LEN;
        uint64_t v = 0;
        uint32_t digits = 0;
        while (p < n && line[p] >= '0' && line[p] <= '9' && digits <= SEQ_MAX_DIGITS) {
            v = v * 10U + (uint64_t)(line[p] - '0');
            digits++;
            p++;
        }
        *seq = v;
        return digits >= 1U && digits <= SEQ_MAX_DIGITS;
    }
    return 0;
}

/* One complete line, without its newline: accept it and take its seq. */
static audit_result_t take_line(const uint8_t *line, uint32_t n, audit_scan_t *out) {
    uint64_t seq = 0;
    if (n < 2U || line[0] != (uint8_t)'{' || line[n - 1U] != (uint8_t)'}' || !parse_seq(line, n, &seq)) {
        return AUDIT_FORMAT;
    }
    if (out->lines == 0U) {
        out->first_seq = seq;
    } else if (seq != out->last_seq + 1U) {
        return AUDIT_GAP;
    }
    out->last_seq = seq;
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
